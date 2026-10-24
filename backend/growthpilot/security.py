"""Password hashing, token helpers, and at-rest encryption for credentials."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password.lower() == password or password.upper() == password or not re.search(r"\d", password):
        return "Password must mix upper and lower case letters and include a number."
    return None


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Tokens (sessions, invites, OAuth state) are stored only as SHA-256 hashes."""
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _fernet() -> Fernet:
    return Fernet(get_settings().encryption_key.encode())


def encrypt_json(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as exc:
        raise ValueError("Stored credentials could not be decrypted (wrong ENCRYPTION_KEY?)") from exc


def encrypt_str(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_str(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-~+/]+=*"),
    re.compile(r"(?i)(\"?(?:access_token|refresh_token|client_secret|secret|password|api_key)\"?\s*[:=]\s*\"?)[^\s\",}]+"),
]


def redact(text: str | None) -> str:
    """Strip anything that looks like a credential before storing or displaying errors."""
    if not text:
        return ""
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", out)
    return out[:2000]
