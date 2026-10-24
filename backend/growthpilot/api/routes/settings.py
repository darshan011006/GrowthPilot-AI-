from __future__ import annotations

from datetime import timedelta
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from ... import audit
from ...config import get_settings
from ...demo import fixtures
from ...models import AgentRun, AuditLog, Invite, Membership, Role, RunStatus, User, UserSession, utcnow
from ...security import hash_token, new_token
from .. import serializers as S
from ..deps import ApiError, Ctx, get_ctx
from .auth import EMAIL_RE

router = APIRouter(prefix="/api", tags=["settings"])
_TZ = available_timezones()


@router.get("/settings")
def get_workspace(ctx: Ctx = Depends(get_ctx)):
    ws = ctx.workspace
    members = ctx.db.execute(select(Membership).where(Membership.workspace_id == ws.id).order_by(Membership.id)).scalars()
    invites = ctx.db.execute(select(Invite).where(Invite.workspace_id == ws.id, Invite.accepted_at.is_(None),
                                                  Invite.expires_at > utcnow())).scalars()
    return {"workspace": {"id": ws.id, "name": ws.name, "timezone": ws.timezone, "agent_max_steps": ws.agent_max_steps,
                          "agent_token_budget": ws.agent_token_budget, "agent_timeout_minutes": ws.agent_timeout_minutes,
                          "run_budget_usd": ws.run_budget_usd, "monthly_budget_usd": ws.monthly_budget_usd,
                          "approval_threshold_usd": ws.approval_threshold_usd,
                          "search_requests_per_run": ws.search_requests_per_run,
                          "search_requests_per_day": ws.search_requests_per_day},
            "members": [{"id": m.id, "user_id": m.user_id, "name": m.user.name, "email": m.user.email, "role": m.role}
                        for m in members],
            "invites": [{"id": i.id, "email": i.email, "role": i.role, "expires_at": S.dt(i.expires_at)} for i in invites],
            "role": ctx.role, "timezones": sorted(_TZ)}


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str
    agent_max_steps: int = Field(ge=5, le=200)
    agent_token_budget: int = Field(ge=10_000, le=5_000_000)
    agent_timeout_minutes: int = Field(ge=1, le=120)
    run_budget_usd: float = Field(default=0.5, ge=0, le=100)
    monthly_budget_usd: float = Field(default=10.0, ge=0, le=10_000)
    approval_threshold_usd: float = Field(default=0.25, ge=0, le=100)
    search_requests_per_run: int = Field(default=8, ge=0, le=100)
    search_requests_per_day: int = Field(default=40, ge=0, le=2000)


@router.put("/settings")
def save_workspace(body: WorkspaceIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_owner()
    if body.timezone not in _TZ:
        raise ApiError(400, "Unknown time zone.", "validation")
    for k, v in body.model_dump().items():
        setattr(ctx.workspace, k, v.strip() if isinstance(v, str) else v)
    audit.record(ctx.db, "workspace.updated", workspace_id=ctx.workspace.id, user_id=ctx.user.id, ip=ctx.ip,
                 **body.model_dump())
    ctx.db.commit()
    return {"ok": True}


class InviteIn(BaseModel):
    email: str = Field(max_length=255)
    role: str = "editor"


@router.post("/settings/invites")
def invite(body: InviteIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_owner()
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email) or body.role not in Role._value2member_map_:
        raise ApiError(400, "Enter a valid email and role.", "validation")
    token = new_token(24)
    ctx.db.add(Invite(workspace_id=ctx.workspace.id, token_hash=hash_token(token), email=email, role=body.role,
                      created_by=ctx.user.id, expires_at=utcnow() + timedelta(days=7)))
    audit.record(ctx.db, "member.invited", workspace_id=ctx.workspace.id, user_id=ctx.user.id, ip=ctx.ip,
                 email=email, role=body.role)
    ctx.db.commit()
    return {"link": f"{get_settings().base_url.rstrip('/')}/register?invite={token}",
            "note": "Share this link with the person directly. It's shown once and expires in 7 days."}


@router.delete("/settings/invites/{iid}")
def revoke_invite(iid: int, ctx: Ctx = Depends(get_ctx)):
    ctx.require_owner()
    ctx.db.delete(ctx.get(Invite, iid))
    ctx.db.commit()
    return {"ok": True}


def _owners(ctx: Ctx) -> int:
    return ctx.db.execute(select(func.count(Membership.id)).where(Membership.workspace_id == ctx.workspace.id,
                                                                  Membership.role == Role.OWNER)).scalar_one()


class RoleIn(BaseModel):
    role: str


@router.put("/settings/members/{mid}")
def change_role(mid: int, body: RoleIn, ctx: Ctx = Depends(get_ctx)):
    ctx.require_owner()
    m = ctx.get(Membership, mid)
    if body.role not in Role._value2member_map_:
        raise ApiError(400, "Unknown role.", "validation")
    if m.role == Role.OWNER and body.role != Role.OWNER and _owners(ctx) <= 1:
        raise ApiError(400, "A workspace needs at least one owner.", "validation")
    m.role = body.role
    audit.record(ctx.db, "member.role_changed", workspace_id=ctx.workspace.id, user_id=ctx.user.id, ip=ctx.ip,
                 member_user_id=m.user_id, role=body.role)
    ctx.db.commit()
    return {"ok": True}


@router.delete("/settings/members/{mid}")
def remove_member(mid: int, ctx: Ctx = Depends(get_ctx)):
    ctx.require_owner()
    m = ctx.get(Membership, mid)
    if m.role == Role.OWNER and _owners(ctx) <= 1:
        raise ApiError(400, "A workspace needs at least one owner.", "validation")
    for s in ctx.db.execute(select(UserSession).where(UserSession.user_id == m.user_id,
                                                      UserSession.workspace_id == ctx.workspace.id)).scalars():
        ctx.db.delete(s)
    audit.record(ctx.db, "member.removed", workspace_id=ctx.workspace.id, user_id=ctx.user.id, ip=ctx.ip,
                 member_user_id=m.user_id)
    ctx.db.delete(m)
    ctx.db.commit()
    return {"ok": True}


@router.get("/settings/audit")
def audit_log(page: int = 1, action: str = "", ctx: Ctx = Depends(get_ctx)):
    ctx.require_owner()
    page = max(1, page)
    q = select(AuditLog).where(AuditLog.workspace_id == ctx.workspace.id)
    if action:
        q = q.where(AuditLog.action.like(f"{action[:40]}%"))
    rows = ctx.db.execute(q.order_by(AuditLog.created_at.desc()).offset((page - 1) * 100).limit(101)).scalars().all()
    users = {u.id: u.name for u in ctx.db.execute(select(User)).scalars()}
    return {"rows": [{"id": r.id, "action": r.action, "target_type": r.target_type, "target_id": r.target_id,
                      "details": r.details, "user": users.get(r.user_id, "system/agent") if r.user_id else "system/agent",
                      "ip": r.ip, "created_at": S.dt(r.created_at)} for r in rows[:100]], "more": len(rows) > 100}


class ResetIn(BaseModel):
    confirm: str
    brand: str = "poojaloka"


@router.post("/demo/reset")
def demo_reset(body: ResetIn, ctx: Ctx = Depends(get_ctx)):
    """Delete this workspace's marketing data and reload a demo brand. Demo mode only."""
    ctx.require_owner()
    if not get_settings().is_demo:
        raise ApiError(400, "Demo reset is only available in demo mode.", "demo_only")
    if body.confirm != "RESET":
        raise ApiError(400, "Type RESET to confirm.", "confirm_required")
    busy = ctx.db.execute(select(AgentRun).where(AgentRun.workspace_id == ctx.workspace.id,
                                                 AgentRun.status == RunStatus.RUNNING)).first()
    if busy:
        raise ApiError(409, "An agent run is in progress; cancel it first.", "busy")
    if body.brand not in fixtures.BRANDS:
        raise ApiError(400, "Unknown demo brand.", "validation")
    result = fixtures.seed(ctx.db, ctx.workspace.id, ctx.user.id, body.brand)
    ctx.db.commit()
    return {"ok": True, **result}


@router.get("/system")
def system(ctx: Ctx = Depends(get_ctx)):
    s = get_settings()
    try:
        ctx.db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    last_run = ctx.db.execute(select(AgentRun).where(AgentRun.workspace_id == ctx.workspace.id)
                              .order_by(AgentRun.created_at.desc()).limit(1)).scalar_one_or_none()
    return {"mode": s.app_mode.value, "env": s.app_env.value, "database": "ok" if db_ok else "error",
            "database_kind": s.database_url.split(":", 1)[0], "worker": "in-process" if s.run_worker_in_process
            else "separate process", "live_publishing_enabled": s.live_publishing_enabled,
            "config_problems": s.problems(), "last_run": S.run(last_run) if last_run else None,
            "secure_cookies": s.secure_cookies}
