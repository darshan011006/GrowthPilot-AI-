"""Instagram API with Instagram Login (Meta) — live adapter.

Implemented from Meta's documentation (checked 2026-10-24):
  * OAuth:        https://www.instagram.com/oauth/authorize  (response_type=code, comma-separated scope)
  * Short token:  POST https://api.instagram.com/oauth/access_token
  * Long token:   GET  https://graph.instagram.com/access_token?grant_type=ig_exchange_token   (60 days)
  * Refresh:      GET  https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token
  * Publish:      POST /<IG_ID>/media (image_url, caption) → container; GET /<container>?fields=status_code
                  until FINISHED; POST /<IG_ID>/media_publish (creation_id) → media id
  * Limits:       GET  /<IG_ID>/content_publishing_limit (100 API posts / 24h)
  * Insights:     GET  /<MEDIA_ID>/insights?metric=reach,likes,comments,shares,saved,views
                  (needs instagram_business_manage_insights; `impressions` is deprecated for new media)

Requirements: an Instagram *professional* (Business or Creator) account; images must be JPEG and
reachable at a public HTTPS URL when publishing. Status: implemented but not yet verified with real
credentials — the UI shows it as such until a connection verifies successfully.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

from ..config import get_settings
from ..models import Platform
from ..research.net import client
from .base import (
    AccountInfo,
    AdapterError,
    Capabilities,
    ConnectionContext,
    Metrics,
    PublishPayload,
    PublishResult,
    StatusResult,
)

SCOPES = ["instagram_business_basic", "instagram_business_content_publish", "instagram_business_manage_insights"]
GRAPH = "https://graph.instagram.com"
INSIGHT_METRICS = ["reach", "likes", "comments", "shares", "saved", "views"]

# Polling for container readiness (docs suggest checking about once a minute for up to 5 minutes; image
# containers are usually ready within seconds). The worker re-queues anything still in progress.
POLL_ATTEMPTS = 6
POLL_SECONDS = 5.0
_sleep = time.sleep


def set_sleep(fn) -> None:
    global _sleep
    _sleep = fn


def _raise(resp, what: str) -> None:
    if resp.is_success:
        return
    msg, code = "", None
    try:
        err = resp.json().get("error", {})
        msg = str(err.get("message", ""))[:300]
        code = err.get("code")
    except Exception:  # noqa: BLE001
        msg = resp.text[:200]
    reauth = resp.status_code in (401,) or code in (190,)  # 190 = invalid/expired OAuth token
    retryable = resp.status_code == 429 or resp.status_code >= 500 or code in (1, 2, 4, 17, 341)
    hint = " Reconnect Instagram." if reauth else ""
    raise AdapterError(f"Instagram {what} failed (HTTP {resp.status_code}): {msg}.{hint}", retryable=retryable,
                       reauth=reauth)


class InstagramAdapter:
    key = "instagram"
    platform = Platform.INSTAGRAM.value
    label = "Instagram (professional account)"
    external = True
    maturity = "implemented-unverified"
    capabilities = Capabilities(oauth=True, identity=True, publish=True, scheduling="app-managed",
                                status_verification=True, analytics=True, content_types=("post", "carousel"))

    @property
    def version(self) -> str:
        return get_settings().instagram_api_version

    # ── OAuth ────────────────────────────────────────────────────────────
    def authorize_url(self, state: str) -> str:
        s = get_settings()
        return "https://www.instagram.com/oauth/authorize?" + urlencode(
            {"client_id": s.meta_app_id, "redirect_uri": s.instagram_redirect_uri, "response_type": "code",
             "scope": ",".join(SCOPES), "state": state, "enable_fb_login": "false"}
        )

    def exchange_code(self, code: str) -> dict[str, Any]:
        s = get_settings()
        with client() as c:
            resp = c.post("https://api.instagram.com/oauth/access_token", data={
                "client_id": s.meta_app_id, "client_secret": s.meta_app_secret, "grant_type": "authorization_code",
                "redirect_uri": s.instagram_redirect_uri, "code": code,
            })
            _raise(resp, "token exchange")
            data = resp.json()
            short = (data.get("data") or [data])[0]
            resp = c.get(f"{GRAPH}/access_token", params={
                "grant_type": "ig_exchange_token", "client_secret": s.meta_app_secret,
                "access_token": short["access_token"],
            })
            _raise(resp, "long-lived token exchange")
            long = resp.json()
        perms = short.get("permissions", "")
        granted = perms.split(",") if isinstance(perms, str) else list(perms or [])
        return {
            "access_token": long["access_token"],
            "issued_at": int(time.time()),
            "expires_at": int(time.time()) + int(long.get("expires_in", 0)),
            "user_id": str(short.get("user_id", "")),
            "permissions": [p.strip() for p in granted if p.strip()],
        }

    def _token(self, ctx: ConnectionContext) -> str:
        creds = ctx.credentials
        token = creds.get("access_token")
        if not token:
            raise AdapterError("Instagram is not authorised. Connect the account.", reauth=True)
        now = time.time()
        if creds.get("expires_at", 0) <= now:
            raise AdapterError("Instagram authorisation expired. Reconnect the account.", reauth=True)
        # Refresh when inside the last 7 days and the token is at least 24h old (docs requirement).
        if creds["expires_at"] - now < 7 * 86400 and now - creds.get("issued_at", 0) > 86400:
            with client() as c:
                resp = c.get(f"{GRAPH}/refresh_access_token",
                             params={"grant_type": "ig_refresh_token", "access_token": token})
            _raise(resp, "token refresh")
            data = resp.json()
            new = dict(creds, access_token=data["access_token"], issued_at=int(now),
                       expires_at=int(now) + int(data.get("expires_in", 0)))
            ctx.credentials = new
            ctx.save_credentials(new)
            token = new["access_token"]
        return token

    def _get(self, ctx: ConnectionContext, path: str, what: str, **params) -> dict:
        with client() as c:
            resp = c.get(f"{GRAPH}/{self.version}/{path}", params=params,
                         headers={"Authorization": f"Bearer {self._token(ctx)}"})
        _raise(resp, what)
        return resp.json()

    def _post(self, ctx: ConnectionContext, path: str, what: str, **data) -> dict:
        with client() as c:
            resp = c.post(f"{GRAPH}/{self.version}/{path}", data=data,
                          headers={"Authorization": f"Bearer {self._token(ctx)}"})
        _raise(resp, what)
        return resp.json()

    # ── adapter interface ────────────────────────────────────────────────
    def verify_connection(self, ctx: ConnectionContext) -> AccountInfo:
        me = self._get(ctx, "me", "account lookup", fields="user_id,username,account_type,media_count")
        acct_type = (me.get("account_type") or "").upper()
        if acct_type and acct_type not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR"):
            raise AdapterError(f"@{me.get('username')} is a {acct_type.lower()} account. Publishing needs an "
                               "Instagram professional (Business or Creator) account.")
        missing = [p for p in ("instagram_business_basic", "instagram_business_content_publish")
                   if ctx.credentials.get("permissions") and p not in ctx.credentials["permissions"]]
        if missing:
            raise AdapterError("Missing permission(s): " + ", ".join(missing) + ". Reconnect and grant them.")
        return AccountInfo(account_id=str(me.get("user_id") or me.get("id") or ctx.account_id),
                           label="@" + str(me.get("username", "")), detail={"account_type": acct_type})

    def _wait_ready(self, ctx: ConnectionContext, container_id: str) -> None:
        for _ in range(POLL_ATTEMPTS):
            status = self._get(ctx, container_id, "container status", fields="status_code").get("status_code")
            if status in ("FINISHED", "PUBLISHED"):
                return
            if status in ("ERROR", "EXPIRED"):
                raise AdapterError(f"Instagram couldn't process the media (container status {status}). "
                                   "Check the image is a JPEG reachable at a public HTTPS URL.")
            _sleep(POLL_SECONDS)
        raise AdapterError("Instagram is still processing the media; will retry.", retryable=True)

    def publish(self, ctx: ConnectionContext, payload: PublishPayload) -> PublishResult:
        ig = ctx.account_id
        if not payload.image_urls:
            raise AdapterError("Instagram posts need at least one image.")
        for u in payload.image_urls:
            if not u.startswith("https://"):
                raise AdapterError("Instagram must fetch images from a public HTTPS URL. Set BASE_URL to a public "
                                   "HTTPS address (see docs/API_INTEGRATIONS.md).")
        limit = self._get(ctx, f"{ig}/content_publishing_limit", "publishing limit check", fields="quota_usage,config")
        rows = limit.get("data") or [{}]
        usage, total = rows[0].get("quota_usage"), (rows[0].get("config") or {}).get("quota_total")
        if usage is not None and total is not None and usage >= total:
            raise AdapterError(f"Instagram's 24-hour publishing limit is used up ({usage}/{total}).", retryable=True)

        if payload.content_type == "carousel" and len(payload.image_urls) > 1:
            children = []
            for u in payload.image_urls[:10]:
                child = self._post(ctx, f"{ig}/media", "carousel item creation", image_url=u, is_carousel_item="true")
                children.append(child["id"])
            for cid in children:
                self._wait_ready(ctx, cid)
            container = self._post(ctx, f"{ig}/media", "carousel container creation", media_type="CAROUSEL",
                                   children=",".join(children), caption=payload.caption)
        else:
            fields = {"image_url": payload.image_urls[0], "caption": payload.caption}
            if payload.alt_text:
                fields["alt_text"] = payload.alt_text[:1000]
            container = self._post(ctx, f"{ig}/media", "media container creation", **fields)
        self._wait_ready(ctx, container["id"])
        published = self._post(ctx, f"{ig}/media_publish", "publish", creation_id=container["id"])
        media_id = str(published["id"])
        return PublishResult(external_id=media_id, url=None, provider_status="PUBLISH_ACCEPTED",
                             summary=f"Instagram accepted media_publish (media id {media_id}).")

    def publication_status(self, ctx: ConnectionContext, external_id: str) -> StatusResult:
        try:
            media = self._get(ctx, external_id, "media lookup", fields="id,permalink,timestamp,media_type")
        except AdapterError as exc:
            if "HTTP 400" in str(exc) or "HTTP 404" in str(exc):
                return StatusResult(state="not_found", detail=str(exc))
            raise
        if media.get("id"):
            return StatusResult(state="published", url=media.get("permalink"),
                                detail=f"Instagram reports media {media['id']} at {media.get('timestamp', '?')}.")
        return StatusResult(state="unknown", detail="Instagram returned no media id.")

    def fetch_metrics(self, ctx: ConnectionContext, external_id: str, *, hours_since: float, hints: dict) -> Metrics | None:
        perms = ctx.credentials.get("permissions") or []
        if perms and "instagram_business_manage_insights" not in perms:
            return None
        data = self._get(ctx, f"{external_id}/insights", "insights", metric=",".join(INSIGHT_METRICS))
        values: dict[str, int] = {}
        for row in data.get("data", []):
            vals = row.get("values") or []
            if vals and isinstance(vals[0].get("value"), int):
                values[row["name"]] = vals[0]["value"]
            elif isinstance((row.get("total_value") or {}).get("value"), int):
                values[row["name"]] = row["total_value"]["value"]
        return Metrics(reach=values.get("reach"), views=values.get("views"), likes=values.get("likes"),
                       comments=values.get("comments"), shares=values.get("shares"), saves=values.get("saved"),
                       raw={"insights": values})
