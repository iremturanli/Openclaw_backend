"""Payment endpoints: Stripe hosted checkout + smart payment-routing.

The app creates a Checkout Session, opens the returned Stripe URL, then polls
the session until ``payment_status == 'paid'`` before recording the booking.
Real money never moves in sandbox; this exercises the live Stripe test rail.

``POST /payments/webhook`` is the server-authoritative payment confirmation:
Stripe calls it, we verify the signature, and a paid ``checkout.session.completed``
is recorded in :class:`PaymentVerificationStore`. Polling reports this via
``webhook_verified`` so fulfilment can trust a server-verified signal instead of
a client claim.

``GET /payments/recommend`` is an unauthenticated, location-aware
recommendation layer (best card network per country with acceptance/fee
intelligence). It is advisory only — it never moves money; settlement still
runs through the Stripe sandbox above.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_current_user, get_settings
from app.core.config import Settings
from app.db.models.user import UserORM
from app.services.payment_verification import (
    PaymentVerificationStore,
    get_payment_store,
)
from app.services.payments_directory import recommend_provider
from app.services.stripe_service import (
    StripeError,
    StripeNotConfiguredError,
    StripeService,
    StripeSignatureError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

# The hosted page redirects here after pay/cancel. The app polls session status
# rather than relying on the redirect, so these only need to be valid URLs.
_SUCCESS_URL = "https://staywallet.app/pay/success?session_id={CHECKOUT_SESSION_ID}"
_CANCEL_URL = "https://staywallet.app/pay/cancel"


class CheckoutSessionRequest(BaseModel):
    # The app sends camelCase (``amountCents``); accept both that and snake_case.
    amount_cents: int = Field(gt=0, alias="amountCents")
    currency: str = "USD"
    title: str = "Booking"

    model_config = ConfigDict(populate_by_name=True)


class CheckoutSessionResponse(BaseModel):
    id: str
    url: str


class SessionStatusResponse(BaseModel):
    status: str  # open | complete | expired
    payment_status: str  # paid | unpaid | no_payment_required
    # True only when a signature-verified webhook has confirmed this session
    # paid server-side — the authoritative signal fulfilment should trust.
    webhook_verified: bool = False


def get_stripe_service(
    settings: Settings = Depends(get_settings),
) -> StripeService:
    return StripeService(settings)


@router.get(
    "/recommend",
    summary="Payment-provider auto-switch recommendation (country-aware)",
)
async def recommend_payment_provider(
    country: str | None = Query(None, description="ISO country code, e.g. TR"),
    currency: str | None = Query(None, description="ISO currency code, e.g. TRY"),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Best card network for ``country`` plus ranked alternatives.

    Honest intelligence layer: demo acceptance/fee figures (``isDemo: true``);
    real settlement still runs through the Stripe sandbox. No auth -- this is
    non-sensitive reference data, matching ``/partners/mobility``.
    """

    return recommend_provider(country, currency, settings)


@router.post(
    "/checkout-session",
    response_model=CheckoutSessionResponse,
    summary="Create a Stripe hosted Checkout Session",
)
async def create_checkout_session(
    request: CheckoutSessionRequest,
    user: UserORM = Depends(get_current_user),
    stripe: StripeService = Depends(get_stripe_service),
) -> CheckoutSessionResponse:
    try:
        session = await stripe.create_checkout_session(
            amount_cents=request.amount_cents,
            currency=request.currency,
            title=request.title,
            success_url=_SUCCESS_URL,
            cancel_url=_CANCEL_URL,
        )
    except StripeNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured on the server.",
        ) from exc
    except StripeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {exc}",
        ) from exc
    return CheckoutSessionResponse(id=session["id"], url=session["url"])


@router.get(
    "/checkout-session/{session_id}",
    response_model=SessionStatusResponse,
    summary="Poll a Checkout Session's payment status",
)
async def get_checkout_session(
    session_id: str,
    user: UserORM = Depends(get_current_user),
    stripe: StripeService = Depends(get_stripe_service),
    payments: PaymentVerificationStore = Depends(get_payment_store),
) -> SessionStatusResponse:
    try:
        session = await stripe.get_session(session_id)
    except StripeNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured on the server.",
        ) from exc
    except StripeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {exc}",
        ) from exc
    return SessionStatusResponse(
        status=session.get("status", "open"),
        payment_status=session.get("payment_status", "unpaid"),
        webhook_verified=payments.is_paid(session_id),
    )


@router.post(
    "/webhook",
    summary="Stripe webhook (signature-verified) — confirms payment server-side",
    status_code=status.HTTP_200_OK,
)
async def stripe_webhook(
    request: Request,
    stripe: StripeService = Depends(get_stripe_service),
    payments: PaymentVerificationStore = Depends(get_payment_store),
) -> dict[str, bool]:
    """Receive and verify a Stripe webhook event.

    Authenticated by the Stripe signature (NOT a user token) — this endpoint is
    called by Stripe, not the app. We read the RAW body (signature is computed
    over the exact bytes), verify it, and on ``checkout.session.completed`` with
    ``payment_status == 'paid'`` record the session as paid in the
    server-authoritative store. A bad signature is rejected with 400 so Stripe
    surfaces it; an unconfigured secret returns 503.
    """

    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    try:
        event = stripe.verify_webhook(payload, signature)
    except StripeNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook secret is not configured.",
        ) from exc
    except StripeSignatureError as exc:
        # Do not leak detail to an unauthenticated caller; log server-side.
        logger.warning("Rejected Stripe webhook: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature.",
        ) from exc

    event_type = event.get("type")
    if event_type == "checkout.session.completed":
        session = (event.get("data") or {}).get("object") or {}
        session_id = session.get("id")
        if session_id and session.get("payment_status") == "paid":
            payments.mark_paid(
                session_id,
                {
                    "amount_total": session.get("amount_total"),
                    "currency": session.get("currency"),
                    "event_id": event.get("id"),
                },
            )
            logger.info("Stripe session %s confirmed paid via webhook", session_id)

    # Always 200 for a validly-signed event so Stripe stops retrying.
    return {"received": True}
