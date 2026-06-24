"""Digital-key issuance.

Generates an opaque, signed access token whose validity window is bound to the
stay's check-in/check-out dates. The token is JWT-like: a base64url payload of
claims plus an HMAC-SHA256 signature. It is intentionally opaque to clients.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets

from app.core.config import Settings, get_settings
from app.models.check_in import DigitalKey
from app.models.stay import StayInfo


def _b64url(data: bytes) -> str:
    """Base64url-encode ``data`` without padding."""

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class KeyService:
    """Issues :class:`DigitalKey` instances bound to a stay's date window."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _sign(self, payload: bytes) -> str:
        """Return the HMAC-SHA256 signature for ``payload`` as base64url."""

        signature = hmac.new(
            self._settings.key_signing_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).digest()
        return _b64url(signature)

    def _build_access_token(self, key_id: str, stay: StayInfo) -> str:
        """Build the opaque, signed access token string."""

        claims = {
            "kid": key_id,
            "sid": stay.id,
            "room": stay.room_number,
            "nbf": stay.check_in_date.isoformat(),
            "exp": stay.check_out_date.isoformat(),
            # Random nonce so two keys for the same stay differ.
            "jti": secrets.token_urlsafe(8),
        }
        payload = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
        encoded_payload = _b64url(payload)
        signature = self._sign(payload)
        return f"{encoded_payload}.{signature}"

    def issue_key(self, stay: StayInfo) -> DigitalKey:
        """Issue a digital key valid for the duration of ``stay``."""

        key_id = f"key_{secrets.token_hex(6)}"
        access_token = self._build_access_token(key_id, stay)
        return DigitalKey(
            key_id=key_id,
            access_token=access_token,
            valid_from=stay.check_in_date,
            valid_until=stay.check_out_date,
        )
