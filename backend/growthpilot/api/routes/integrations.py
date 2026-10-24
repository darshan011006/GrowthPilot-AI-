from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ... import audit
from ...adapters import AdapterError, all_adapters, available_adapters, get_adapter
from ...adapters.instagram import InstagramAdapter
from ...adapters.webhook import validate_url
from ...config import get_settings
from ...models import ChannelConnection, ConnectionStatus, ContentItem, ContentStatus, OAuthState, utcnow
from ...research import search as search_mod
from ...security import encrypt_json, encrypt_str, hash_token, new_token, redact
from ...services.connections import context
from .. import serializers as S
from ..deps import ApiError, Ctx, get_ctx, rate_limit

router = APIRouter(prefix="/api", tags=["integrations"])


def _adapter_info(key: str) -> dict:
    a = all_adapters()[key]
    caps = a.capabilities
    return {"key": a.key, "label": a.label, "platform": a.platform, "external": a.external, "maturity": a.maturity,
            "capabilities": {"oauth": caps.oauth, "identity": caps.identity, "validation": caps.validation,
                             "publish": caps.publish, "scheduling": caps.scheduling,
                             "status_verification": caps.status_verification, "analytics": caps.analytics,
                             "content_types": list(caps.content_types)}}


def _conns(ctx: Ctx) -> list[ChannelConnection]:
    return list(ctx.db.execute(select(ChannelConnection).where(ChannelConnection.workspace_id == ctx.workspace.id)
                               .order_by(ChannelConnection.id)).scalars())


@router.get("/integrations")
def integrations(ctx: Ctx = Depends(get_ctx)):
    s = get_settings()
    conns = _conns(ctx)
    allowed = available_adapters()

    def status_of(configured: bool, partial: bool = False) -> str:
        if s.is_demo:
            return ConnectionStatus.DEMO
        if configured:
            return "configured"
        return ConnectionStatus.CONFIG_INCOMPLETE if partial else ConnectionStatus.NOT_CONFIGURED

    ig_conns = [c for c in conns if c.adapter in ("instagram", "demo_instagram") and c.adapter in allowed]
    if s.is_demo:
        ig_status = ConnectionStatus.DEMO
    elif not (s.meta_app_id or s.meta_app_secret):
        ig_status = ConnectionStatus.NOT_CONFIGURED
    elif not s.instagram_configured:
        ig_status = ConnectionStatus.CONFIG_INCOMPLETE
    elif not ig_conns:
        ig_status = ConnectionStatus.AWAITING_AUTHORIZATION
    else:
        ig_status = ig_conns[0].status
    items = [
        {"key": "llm", "name": "LLM (Anthropic Claude)", "status": status_of(s.llm_configured),
         "detail": "Demo planner and generator (no LLM calls)" if s.is_demo else
         (f"Model {s.llm_model}, effort {s.llm_effort}. Use “Test” to verify the key." if s.llm_configured
          else "Set LLM_API_KEY in .env."), "env": ["LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL"], "testable": s.is_live},
        {"key": "search", "name": "Web research (Brave Search)", "status": status_of(s.search_configured),
         "detail": "Demo mode uses labelled fixture notes" if s.is_demo else
         ("Configured. “Test” runs one search (counts toward your quota)." if s.search_configured
          else "Set SEARCH_API_KEY in .env. Without it, research uses only the built-in seasonal calendar."),
         "env": ["SEARCH_PROVIDER", "SEARCH_API_KEY"], "testable": s.is_live},
        {"key": "instagram", "name": "Instagram (API with Instagram Login)", "status": ig_status,
         "detail": "Demo adapter simulates publishing; nothing is posted." if s.is_demo else
         ("Needs META_APP_ID and META_APP_SECRET." if ig_status in (ConnectionStatus.NOT_CONFIGURED,
                                                                    ConnectionStatus.CONFIG_INCOMPLETE)
          else f"Redirect URI to register with Meta: {s.instagram_redirect_uri}"),
         "env": ["META_APP_ID", "META_APP_SECRET", "META_REDIRECT_URI"], "adapter": _adapter_info(
             "demo_instagram" if s.is_demo else "instagram")},
        {"key": "webhook", "name": "Signed webhook (Zapier / Make / n8n)", "status": ConnectionStatus.DEMO if s.is_demo
         else ("connected" if any(c.adapter == "webhook" and c.status == "connected" for c in conns) else "not_configured"),
         "detail": "Live mode only." if s.is_demo else "Add a webhook URL below.", "env": [],
         "adapter": _adapter_info("webhook")},
        {"key": "image", "name": "Image generation", "status": ConnectionStatus.NOT_CONFIGURED,
         "detail": "No provider implemented. The agent writes image briefs and attaches labelled placeholders; "
                   "upload real product photos in Brand Brain.", "env": ["IMAGE_GENERATION_API_KEY"]},
    ]
    return {"mode": s.app_mode.value, "live_publishing_enabled": s.live_publishing_enabled, "integrations": items,
            "connections": [S.connection(c, _adapter_info(c.adapter) if c.adapter in all_adapters() else None)
                            | {"available_in_mode": c.adapter in allowed} for c in conns],
            "config_problems": s.problems()}


@router.post("/integrations/{key}/test")
def test_integration(key: str, ctx: Ctx = Depends(get_ctx)):
    ctx.require_owner()
    s = get_settings()
    if s.is_demo:
        raise ApiError(400, "Demo mode makes no external calls.", "demo")
    rate_limit(f"test:{ctx.workspace.id}:{key}", 10, 3600)
    if key == "llm":
        import anthropic

        try:
            anthropic.Anthropic(api_key=s.llm_key, timeout=20).models.retrieve(s.llm_model)
        except anthropic.AuthenticationError:
            return {"ok": False, "message": "Anthropic rejected the API key."}
        except anthropic.NotFoundError:
            return {"ok": False, "message": f"Model {s.llm_model} not available to this key."}
        except anthropic.APIError as exc:
            return {"ok": False, "message": f"Anthropic error: {redact(str(exc))[:200]}"}
        return {"ok": True, "message": f"Key works and {s.llm_model} is available."}
    if key == "search":
        try:
            results = search_mod.search("furniture design trends", count=1)
        except (search_mod.SearchUnavailable, search_mod.SearchError) as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": f"Search works ({len(results)} result returned)."}
    raise ApiError(404, "Unknown integration.", "not_found")


@router.post("/integrations/instagram/start")
def instagram_start(ctx: Ctx = Depends(get_ctx)):
    ctx.require_owner()
    s = get_settings()
    if s.is_demo:
        raise ApiError(400, "Demo mode uses the demo Instagram adapter; switch to live mode to connect an account.",
                       "demo")
    if not s.instagram_configured:
        raise ApiError(400, "Set META_APP_ID and META_APP_SECRET in .env first.", "not_configured")
    state = new_token(24)
    ctx.db.add(OAuthState(state_hash=hash_token(state), provider="instagram", workspace_id=ctx.workspace.id,
                          user_id=ctx.user.id, code_verifier_enc=encrypt_str("-"),
                          expires_at=utcnow() + timedelta(minutes=10)))
    ctx.db.commit()
    return {"authorize_url": InstagramAdapter().authorize_url(state)}


def _back(status: str, message: str = "") -> RedirectResponse:
    return RedirectResponse(f"/integrations?instagram={status}&message={quote(message[:300])}", status_code=303)


@router.get("/integrations/instagram/callback")
def instagram_callback(state: str = "", code: str = "", error: str = "", error_description: str = "",
                       ctx: Ctx = Depends(get_ctx)):
    row = ctx.db.execute(select(OAuthState).where(OAuthState.state_hash == hash_token(state or "-"))).scalar_one_or_none()
    valid = (row is not None and row.provider == "instagram" and row.user_id == ctx.user.id
             and row.workspace_id == ctx.workspace.id and row.expires_at > utcnow())
    if row is not None:
        ctx.db.delete(row)  # single use
        ctx.db.commit()
    if not valid:
        return _back("error", "Authorisation link expired or invalid. Start again.")
    if error or not code:
        return _back("error", f"Authorisation cancelled: {redact(error_description or error)}")
    adapter = InstagramAdapter()
    try:
        creds = adapter.exchange_code(code)
    except AdapterError as exc:
        return _back("error", f"Token exchange failed: {redact(str(exc))}")
    conn = ChannelConnection(workspace_id=ctx.workspace.id, adapter="instagram", platform="instagram",
                             name="Instagram", account_id=creds.get("user_id", ""), credentials_enc=encrypt_json(creds),
                             token_expires_at=datetime.fromtimestamp(creds["expires_at"], UTC).replace(tzinfo=None) if creds.get("expires_at") else None,
                             status=ConnectionStatus.AWAITING_AUTHORIZATION, created_by=ctx.user.id)
    ctx.db.add(conn)
    ctx.db.flush()
    try:
        info = adapter.verify_connection(context(ctx.db, conn))
        conn.account_id, conn.account_label = info.account_id, info.label
        conn.status, conn.last_verified_at = ConnectionStatus.CONNECTED, utcnow()
        msg = f"Connected {info.label}."
    except AdapterError as exc:
        conn.status, conn.last_error = ConnectionStatus.FAILED, redact(str(exc))
        msg = f"Authorised, but verification failed: {conn.last_error}"
    audit.record(ctx.db, "connection.created", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="connection", target_id=conn.id, ip=ctx.ip, adapter="instagram", status=conn.status)
    ctx.db.commit()
    return _back("connected" if conn.status == ConnectionStatus.CONNECTED else "error", msg)


class WebhookIn(BaseModel):
    name: str = Field(default="Webhook", max_length=120)
    url: str = Field(max_length=1000)


@router.post("/connections/webhook")
def add_webhook(body: WebhookIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_owner()
    try:
        get_adapter("webhook")
        validate_url(body.url)
    except AdapterError as exc:
        raise ApiError(400, str(exc), "validation") from exc
    secret = new_token(32)
    conn = ChannelConnection(workspace_id=ctx.workspace.id, adapter="webhook", platform="any", name=body.name.strip()
                             or "Webhook", config={"url": body.url}, credentials_enc=encrypt_json({"signing_secret": secret}),
                             status=ConnectionStatus.AWAITING_AUTHORIZATION, created_by=ctx.user.id)
    ctx.db.add(conn)
    ctx.db.flush()
    audit.record(ctx.db, "connection.created", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="connection", target_id=conn.id, ip=ctx.ip, adapter="webhook")
    ctx.db.commit()
    return {"connection": S.connection(conn), "signing_secret": secret,
            "note": "Copy the signing secret now; it won't be shown again."}


@router.post("/connections/{conn_id}/verify")
def verify_connection(conn_id: int, ctx: Ctx = Depends(get_ctx)):
    ctx.require_owner()
    conn = ctx.get(ChannelConnection, conn_id)
    try:
        adapter = get_adapter(conn.adapter)
        info = adapter.verify_connection(context(ctx.db, conn))
    except AdapterError as exc:
        conn.status = ConnectionStatus.EXPIRED if exc.reauth else ConnectionStatus.FAILED
        conn.last_error = redact(str(exc))
        ctx.db.commit()
        return S.connection(conn)
    conn.account_id = info.account_id or conn.account_id
    conn.account_label = info.label
    conn.status = ConnectionStatus.DEMO if not adapter.external else ConnectionStatus.CONNECTED
    conn.last_verified_at, conn.last_error = utcnow(), None
    audit.record(ctx.db, "connection.verified", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="connection", target_id=conn.id, ip=ctx.ip)
    ctx.db.commit()
    return S.connection(conn)


@router.delete("/connections/{conn_id}")
def delete_connection(conn_id: int, ctx: Ctx = Depends(get_ctx)):
    ctx.require_owner()
    conn = ctx.get(ChannelConnection, conn_id)
    scheduled = ctx.db.execute(select(ContentItem).where(ContentItem.connection_id == conn.id,
                                                         ContentItem.status == ContentStatus.SCHEDULED)).scalars().all()
    for i in scheduled:
        i.status, i.scheduled_at = ContentStatus.APPROVED, None
    audit.record(ctx.db, "connection.deleted", workspace_id=ctx.workspace.id, user_id=ctx.user.id,
                 target_type="connection", target_id=conn.id, ip=ctx.ip, unscheduled=len(scheduled))
    ctx.db.delete(conn)
    ctx.db.commit()
    return {"ok": True, "unscheduled": len(scheduled)}
