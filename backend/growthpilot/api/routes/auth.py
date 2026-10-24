from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import audit
from ...config import get_settings
from ...db import get_db
from ...models import Invite, Membership, Role, User, UserSession, Workspace, utcnow
from ...security import hash_password, hash_token, password_problem, verify_password
from ..deps import (
    SESSION_COOKIE,
    ApiError,
    Ctx,
    get_ctx,
    load_session,
    rate_limit,
    require_json_origin,
    set_cookie,
    start_session,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _no_users(db: Session) -> bool:
    return db.execute(select(func.count(User.id))).scalar_one() == 0


def _invite(db: Session, token: str | None) -> Invite | None:
    if not token:
        return None
    inv = db.execute(select(Invite).where(Invite.token_hash == hash_token(token))).scalar_one_or_none()
    if inv is None or inv.accepted_at is not None or inv.expires_at < utcnow():
        return None
    return inv


@router.get("/state")
def state(request: Request, invite: str | None = None, db: Session = Depends(get_db)):
    s = get_settings()
    base = {"mode": s.app_mode.value, "live_publishing_enabled": s.live_publishing_enabled,
            "needs_setup": _no_users(db)}
    inv = _invite(db, invite)
    if inv:
        base["invite"] = {"email": inv.email, "role": inv.role}
    sess = load_session(request, db)
    if sess is None:
        return base | {"authenticated": False}
    m = db.execute(select(Membership).where(Membership.user_id == sess.user_id,
                                            Membership.workspace_id == sess.workspace_id)).scalar_one_or_none()
    if m is None:
        return base | {"authenticated": False}
    return base | {"authenticated": True, "csrf": sess.csrf_token,
                   "user": {"id": sess.user.id, "name": sess.user.name, "email": sess.user.email},
                   "workspace": {"id": m.workspace.id, "name": m.workspace.name, "timezone": m.workspace.timezone},
                   "role": m.role}


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=500)


@router.post("/login", dependencies=[Depends(require_json_origin)])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    ip = request.client.host if request.client else "?"
    rate_limit(f"login:{ip}:{email}", 10, 900)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        audit.record(db, "auth.login_failed", workspace_id=None, ip=ip, email=email)
        db.commit()
        raise ApiError(400, "Email or password is incorrect.", "bad_credentials")
    m = db.execute(select(Membership).where(Membership.user_id == user.id).order_by(Membership.id)).scalars().first()
    if m is None:
        raise ApiError(400, "Your account has no workspace.", "no_workspace")
    token = start_session(db, request, user, m.workspace_id)
    audit.record(db, "auth.login", workspace_id=m.workspace_id, user_id=user.id, ip=ip)
    db.commit()
    set_cookie(response, token)
    return {"ok": True}


class RegisterIn(BaseModel):
    name: str = Field(max_length=120)
    email: str = Field(max_length=255)
    password: str = Field(max_length=500)
    workspace_name: str = Field(default="", max_length=120)
    invite: str = Field(default="", max_length=200)


@router.post("/register", dependencies=[Depends(require_json_origin)])
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "?"
    rate_limit(f"register:{ip}", 10, 3600)
    first = _no_users(db)
    inv = _invite(db, body.invite)
    if not first and inv is None:
        raise ApiError(403, "Registration is invite-only. Ask a workspace owner for an invite link.", "invite_only")
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise ApiError(400, "Enter a valid email address.", "validation")
    if inv and inv.email.lower() != email:
        raise ApiError(400, "Use the email address the invite was sent to.", "validation")
    if not body.name.strip():
        raise ApiError(400, "Enter your name.", "validation")
    if problem := password_problem(body.password):
        raise ApiError(400, problem, "validation")
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise ApiError(400, "An account with this email already exists.", "exists")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    if inv:
        ws_id = inv.workspace_id
        db.add(Membership(user_id=user.id, workspace_id=ws_id, role=inv.role))
        inv.accepted_at = utcnow()
    else:
        ws = Workspace(name=(body.workspace_name.strip() or f"{body.name.strip()}'s workspace")[:120])
        db.add(ws)
        db.flush()
        ws_id = ws.id
        db.add(Membership(user_id=user.id, workspace_id=ws_id, role=Role.OWNER))
    audit.record(db, "auth.registered", workspace_id=ws_id, user_id=user.id, ip=ip, via_invite=bool(inv))
    token = start_session(db, request, user, ws_id)
    db.commit()
    set_cookie(response, token)
    return {"ok": True}


@router.post("/logout")
def logout(response: Response, ctx: Ctx = Depends(get_ctx)):
    audit.record(ctx.db, "auth.logout", workspace_id=ctx.workspace.id, user_id=ctx.user.id, ip=ctx.ip)
    ctx.db.delete(ctx.session)
    ctx.db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=500)
    new_password: str = Field(max_length=500)


@router.post("/password")
def change_password(body: PasswordIn, ctx: Ctx = Depends(get_ctx)):
    rate_limit(f"pw:{ctx.user.id}", 10, 900)
    if not verify_password(ctx.user.password_hash, body.current_password):
        raise ApiError(400, "Current password is incorrect.", "validation")
    if problem := password_problem(body.new_password):
        raise ApiError(400, problem, "validation")
    ctx.user.password_hash = hash_password(body.new_password)
    for s in ctx.db.execute(select(UserSession).where(UserSession.user_id == ctx.user.id)).scalars():
        if s.id != ctx.session.id:
            ctx.db.delete(s)
    audit.record(ctx.db, "auth.password_changed", workspace_id=ctx.workspace.id, user_id=ctx.user.id, ip=ctx.ip)
    ctx.db.commit()
    return {"ok": True}
