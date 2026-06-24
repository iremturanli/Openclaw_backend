"""Stripe webhook signature verification + paid-session recording.

The webhook is the server-authoritative payment confirmation: it must accept a
correctly-signed ``checkout.session.completed`` and record the session as paid,
and must reject anything whose signature does not verify.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from app.api.v1.payments import get_stripe_service
from app.core.config import Settings
from app.main import app
from app.services.payment_verification import get_payment_store
from app.services.stripe_service import StripeService

_WEBHOOK_SECRET = "whsec_test_secret_value"


def _signed(body: bytes, secret: str = _WEBHOOK_SECRET, *, ts: int | None = None) -> str:
    ts = ts if ts is not None else int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _event(session_id: str, payment_status: str = "paid") -> bytes:
    return json.dumps(
        {
            "id": "evt_test_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": session_id,
                    "payment_status": payment_status,
                    "amount_total": 2450,
                    "currency": "usd",
                }
            },
        }
    ).encode()


def _override_stripe(secret: str | None = _WEBHOOK_SECRET) -> None:
    settings = Settings(stripe_secret_key="sk_test_x", stripe_webhook_secret=secret)
    app.dependency_overrides[get_stripe_service] = lambda: StripeService(settings)


@pytest.mark.asyncio
async def test_webhook_valid_signature_marks_paid(client) -> None:
    _override_stripe()
    try:
        body = _event("cs_test_paid_1")
        resp = await client.post(
            "/api/v1/payments/webhook",
            content=body,
            headers={"stripe-signature": _signed(body)},
        )
        assert resp.status_code == 200
        assert resp.json() == {"received": True}
        assert get_payment_store().is_paid("cs_test_paid_1") is True
    finally:
        app.dependency_overrides.pop(get_stripe_service, None)


@pytest.mark.asyncio
async def test_webhook_bad_signature_rejected(client) -> None:
    _override_stripe()
    try:
        body = _event("cs_test_bad_1")
        resp = await client.post(
            "/api/v1/payments/webhook",
            content=body,
            headers={"stripe-signature": "t=123,v1=deadbeef"},
        )
        assert resp.status_code == 400
        assert get_payment_store().is_paid("cs_test_bad_1") is False
    finally:
        app.dependency_overrides.pop(get_stripe_service, None)


@pytest.mark.asyncio
async def test_webhook_tampered_body_rejected(client) -> None:
    _override_stripe()
    try:
        body = _event("cs_test_tamper_1")
        header = _signed(body)
        resp = await client.post(
            "/api/v1/payments/webhook",
            content=body + b"tampered",
            headers={"stripe-signature": header},
        )
        assert resp.status_code == 400
        assert get_payment_store().is_paid("cs_test_tamper_1") is False
    finally:
        app.dependency_overrides.pop(get_stripe_service, None)


@pytest.mark.asyncio
async def test_webhook_unconfigured_secret_503(client) -> None:
    _override_stripe(secret=None)
    try:
        body = _event("cs_test_noconf_1")
        resp = await client.post(
            "/api/v1/payments/webhook",
            content=body,
            headers={"stripe-signature": _signed(body)},
        )
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.pop(get_stripe_service, None)


@pytest.mark.asyncio
async def test_webhook_unpaid_session_not_recorded(client) -> None:
    _override_stripe()
    try:
        body = _event("cs_test_unpaid_1", payment_status="unpaid")
        resp = await client.post(
            "/api/v1/payments/webhook",
            content=body,
            headers={"stripe-signature": _signed(body)},
        )
        assert resp.status_code == 200
        assert get_payment_store().is_paid("cs_test_unpaid_1") is False
    finally:
        app.dependency_overrides.pop(get_stripe_service, None)
