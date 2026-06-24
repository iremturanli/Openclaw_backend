"""Password hashing and JWT helpers.

Passwords are hashed with bcrypt; tokens are signed JWTs (HS256) carrying the
user id (``sub``), the loyalty ``guest_id``, a ``type`` (access | refresh) and an
expiry. Secrets and lifetimes come from settings.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import get_settings

TokenType = Literal["access", "refresh"]


def hash_password(plain: str) -> str:
    """Return a bcrypt hash for [plain]."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if [plain] matches the stored bcrypt [hashed]."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(
    *, user_id: str, guest_id: str, token_type: TokenType
) -> str:
    """Create a signed JWT of [token_type] for the given user."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if token_type == "access":
        expires = now + timedelta(minutes=settings.access_token_minutes)
    else:
        expires = now + timedelta(days=settings.refresh_token_days)
    payload: dict[str, Any] = {
        "sub": user_id,
        "guest_id": guest_id,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(payload, settings.auth_secret, algorithm=settings.auth_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT, raising ``jwt.PyJWTError`` on failure."""
    settings = get_settings()
    return jwt.decode(
        token, settings.auth_secret, algorithms=[settings.auth_algorithm]
    )
