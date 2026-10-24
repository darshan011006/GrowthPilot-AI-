from __future__ import annotations

from sqlalchemy.orm import Session

from ..adapters.base import ConnectionContext
from ..models import ChannelConnection
from ..security import decrypt_json, encrypt_json


def context(db: Session, conn: ChannelConnection) -> ConnectionContext:
    def save(creds: dict) -> None:
        conn.credentials_enc = encrypt_json(creds)
        db.flush()

    return ConnectionContext(connection_id=conn.id, account_id=conn.account_id, config=dict(conn.config or {}),
                             credentials=decrypt_json(conn.credentials_enc), save_credentials=save)
