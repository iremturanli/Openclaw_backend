"""Stripe (sandbox/test) hosted-checkout integration.

Talks to the Stripe REST API with httpx (no extra SDK dependency). We create a
hosted **Checkout Session** and let the app open Stripe's payment page; the
client then polls :meth:`get_session` until the payment is ``paid``. Only the
secret key lives here — it never reaches the client.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from app.core.config import Settings

_STRIPE_BASE = "https://api.stripe.com/v1"
# Reject webhook events whose signature timestamp is older/newer than this many
# seconds — defends against replay of a captured (validly signed) payload.
_WEBHOOK_TOLERANCE_SECONDS = 300


class StripeNotConfiguredError(Exception):
    """Raised when no Stripe secret key is configured."""


class StripeError(Exception):
    """Raised when Stripe returns an error response."""


class StripeSignatureError(StripeError):
    """Raised when a webhook signature fails verification."""


class StripeService:
    def __init__(self, settings: Settings) -> None:
        self._key = settings.stripe_secret_key
        self._webhook_secret = settings.stripe_webhook_secret

    @property
    def is_configured(self) -> bool:
        return bool(self._key)

    async def create_checkout_session(
        self,
        *,
        amount_cents: int,
        currency: str,
        title: str,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        """Create a hosted Checkout Session; returns the raw Stripe session
        (includes ``id`` and ``url``)."""

        if not self._key:
            raise StripeNotConfiguredError

        # Stripe expects form-encoded, bracketed nested keys.
        form = {
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][unit_amount]": str(amount_cents),
            "line_items[0][price_data][product_data][name]": title[:250] or "Booking",
        }
        return await self._post("/checkout/sessions", form)

    async def get_session(self, session_id: str) -> dict[str, Any]:
        if not self._key:
            raise StripeNotConfiguredError
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{_STRIPE_BASE}/checkout/sessions/{session_id}",
                headers={"Authorization": f"Bearer {self._key}"},
            )
        return self._unwrap(resp)

    def verify_webhook(
        self,
        payload: bytes,
        signature_header: str | None,
        *,
        tolerance: int = _WEBHOOK_TOLERANCE_SECONDS,
    ) -> dict[str, Any]:
        """Verify a Stripe webhook signature and return the parsed event.

        Implements Stripe's ``Stripe-Signature`` scheme without the SDK: the
        signed payload is ``"{t}.{raw_body}"`` HMAC-SHA256'd with the webhook
        secret; we constant-time compare against every ``v1`` signature in the
        header and enforce a timestamp tolerance to block replays.

        Raises:
            StripeNotConfiguredError: if no webhook secret is configured.
            StripeSignatureError: if the header is malformed, the timestamp is
                outside ``tolerance``, or no signature matches.
        """

        if not self._webhook_secret:
            raise StripeNotConfiguredError
        if not signature_header:
            raise StripeSignatureError("Missing Stripe-Signature header.")

        timestamp: str | None = None
        v1_signatures: list[str] = []
        for part in signature_header.split(","):
            key, _, value = part.strip().partition("=")
            if key == "t":
                timestamp = value
            elif key == "v1":
                v1_signatures.append(value)
        if not timestamp or not v1_signatures:
            raise StripeSignatureError("Malformed Stripe-Signature header.")

        try:
            event_ts = int(timestamp)
        except ValueError as exc:
            raise StripeSignatureError("Invalid signature timestamp.") from exc
        if tolerance and abs(time.time() - event_ts) > tolerance:
            raise StripeSignatureError("Signature timestamp outside tolerance.")

        signed_payload = f"{timestamp}.".encode() + payload
        expected = hmac.new(
            self._webhook_secret.encode(), signed_payload, hashlib.sha256
        ).hexdigest()
        if not any(hmac.compare_digest(expected, sig) for sig in v1_signatures):
            raise StripeSignatureError("Signature verification failed.")

        try:
            event = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise StripeSignatureError("Webhook payload is not valid JSON.") from exc
        if not isinstance(event, dict):
            raise StripeSignatureError("Webhook payload is not a JSON object.")
        return event

    async def _post(self, path: str, form: dict[str, str]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{_STRIPE_BASE}{path}",
                headers={"Authorization": f"Bearer {self._key}"},
                data=form,
            )
        return self._unwrap(resp)

    @staticmethod
    def _unwrap(resp: httpx.Response) -> dict[str, Any]:
        data = resp.json()
        if resp.status_code >= 400:
            message = (
                data.get("error", {}).get("message")
                if isinstance(data, dict)
                else "Stripe request failed"
            )
            raise StripeError(message or "Stripe request failed")
        return data
