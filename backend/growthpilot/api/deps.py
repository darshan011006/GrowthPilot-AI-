"""Authentication, CSRF and request context for the JSON API."""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import AppEnv, get_settings
from ..db import get_db
from ..models import Membership, Role, User, UserSession, Workspace, utcnow
from ..security import constant_time_equals, hash_token, new_token

SESSION_COOKIE = "gp_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class ApiError(HTTPException):
    def __init__(self, status: int, message: str, code: str = "error"):
        super().__init__(status_code=status, detail={"error": code, "message": message})


@dataclass
class Ctx:
    db: Session
    user: User
    workspace: Workspace
    role: str
    session: UserSession
    request: Request

    @property
    def ip(self) -> str | None:
        return self.request.client.host if self.request.client else None

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.workspace.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    def require_owner(self) -> None:
        if self.role != Role.OWNER:
            raise ApiError(403, "Only a workspace owner can do this.", "forbidden")

    def require_editor(self) -> None:
        if self.role not in (Role.OWNER, Role.EDITOR):
            raise ApiError(403, "Your role is read-only.", "forbidden")

    def get(self, model, obj_id):
        """Workspace-scoped fetch. All tenant data access goes through this."""
        obj = self.db.get(model, obj_id)
        if obj is None or getattr(obj, "workspace_id", None) != self.workspace.id:
            raise ApiError(404, f"{model.__name__} not found.", "not_found")
        return obj


def start_session(db: Session, request: Request, user: User, workspace_id: int) -> str:
    token = new_token()
    db.add(UserSession(token_hash=hash_token(token), user_id=user.id, workspace_id=workspace_id,
                       csrf_token=new_token(24), expires_at=utcnow() + timedelta(hours=get_settings().session_ttl_hours),
                       ip=request.client.host if request.client else None,
                       user_agent=(request.headers.get("user-agent") or "")[:255]))
    user.last_login_at = utcnow()
    return token


def set_cookie(response, token: str) -> None:
    s = get_settings()
    response.set_cookie(SESSION_COOKIE, token, max_age=s.session_ttl_hours * 3600, httponly=True, samesite="lax",
                        secure=s.secure_cookies, path="/")


def load_session(request: Request, db: Session) -> UserSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    sess = db.execute(select(UserSession).where(UserSession.token_hash == hash_token(token))).scalar_one_or_none()
    if sess is None or sess.expires_at < utcnow() or not sess.user.is_active:
        return None
    return sess


def require_json_origin(request: Request) -> None:
    """For unauthenticated POSTs (login/register): only same-origin JS can send JSON with this header without a
    CORS preflight, and the API grants no CORS."""
    if request.method in SAFE_METHODS:
        return
    if "application/json" not in request.headers.get("content-type", "") or \
            request.headers.get("x-requested-with") != "GrowthPilot":
        raise ApiError(403, "Request blocked by CSRF protection.", "csrf")
    origin = request.headers.get("origin")
    if origin:
        from urllib.parse import urlsplit

        settings = get_settings()

        def normalized(value: str) -> str | None:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                return None
            authority = parsed.hostname.casefold()
            try:
                if parsed.port:
                    authority += f":{parsed.port}"
            except ValueError:
                return None
            return f"{parsed.scheme.casefold()}://{authority}"

        allowed = {normalized(settings.base_url)}
        if settings.app_env == AppEnv.DEVELOPMENT:
            allowed.update({"http://localhost:3000", "http://127.0.0.1:3000"})
            tunnel_host = os.environ.get("GROWTHPILOT_TUNNEL_HOST", "").strip()
            if tunnel_host and "://" not in tunnel_host and "/" not in tunnel_host:
                tunnel_origin = normalized(f"https://{tunnel_host}")
                if tunnel_origin:
                    allowed.add(tunnel_origin)
        if normalized(origin) not in allowed:
            raise ApiError(403, "Request blocked by CSRF protection.", "csrf")


def get_ctx(request: Request, db: Session = Depends(get_db)) -> Ctx:
    sess = load_session(request, db)
    if sess is None:
        raise ApiError(401, "Please sign in.", "unauthenticated")
    m = db.execute(select(Membership).where(Membership.user_id == sess.user_id,
                                            Membership.workspace_id == sess.workspace_id)).scalar_one_or_none()
    if m is None:
        raise ApiError(401, "Your workspace access was removed.", "unauthenticated")
    if request.method not in SAFE_METHODS:
        sent = request.headers.get("x-csrf-token") or ""
        if not sent or not constant_time_equals(sent, sess.csrf_token):
            raise ApiError(403, "Security check failed (CSRF). Reload the page.", "csrf")
    return Ctx(db=db, user=sess.user, workspace=m.workspace, role=m.role, session=sess, request=request)


# ── simple in-process rate limiting ──────────────────────────────────────

_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window_seconds:
        q.popleft()
    if len(q) >= limit:
        raise ApiError(429, "Too many requests. Wait a little and try again.", "rate_limited")
    q.append(now)


def reset_rate_limits() -> None:
    _hits.clear()
