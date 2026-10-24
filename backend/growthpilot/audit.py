from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog


def record(
    db: Session,
    action: str,
    *,
    workspace_id: int | None,
    user_id: int | None = None,
    target_type: str = "",
    target_id: int | str | None = None,
    ip: str | None = None,
    **details: Any,
) -> AuditLog:
    """Append an audit entry. Callers must never pass secrets in ``details``."""
    entry = AuditLog(
        workspace_id=workspace_id,
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=details,
        ip=ip,
    )
    db.add(entry)
    return entry
