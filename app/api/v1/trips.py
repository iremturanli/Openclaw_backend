"""Trip planning + one-tap confirmation.

``POST /trips/plan`` parses a free-text request into a priced plan (rule-based,
no keys needed -- the conversational path stays on ``/assistant/chat``).
``POST /trips/confirm`` books every item in the plan as wallet purchases in one
transaction, so the balance, bookings and itinerary all update together.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_ai_itinerary_service,
    get_current_user,
    get_trip_planner_service,
    get_wallet_service,
)
from app.core.config import Settings, get_settings
from app.db.models.user import UserORM
from app.models.market import (
    TripConfirmRequest,
    TripConfirmResponse,
    TripPlanRequest,
    TripPlanResponse,
)
from app.services.ai_itinerary_service import (
    AiItineraryNotConfiguredError,
    AiItineraryService,
)
from app.services.trip_planner_service import TripPlannerService
from app.services.wallet_service import (
    InsufficientBudgetError,
    InvalidPurchaseError,
    WalletService,
)

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("/plan", response_model=TripPlanResponse, summary="Plan a trip from text")
async def plan_trip(
    request: TripPlanRequest,
    user: UserORM = Depends(get_current_user),
    planner: TripPlannerService = Depends(get_trip_planner_service),
) -> TripPlanResponse:
    return await planner.plan(request)


@router.post(
    "/ai-plan",
    response_model=TripPlanResponse,
    summary="AI-compose a day-by-day, live-priced trip itinerary",
)
async def ai_plan_trip(
    request: TripPlanRequest,
    user: UserORM = Depends(get_current_user),
    itinerary: AiItineraryService = Depends(get_ai_itinerary_service),
    planner: TripPlannerService = Depends(get_trip_planner_service),
    settings: Settings = Depends(get_settings),
) -> TripPlanResponse:
    """Compose ONE bookable day-by-day itinerary from a free-text prompt.

    The OpenAI-backed planner designs the day structure and the live SerpApi
    services fill in real pricing; each item carries a 1-based ``day`` (per-day
    items) or ``None`` (trip-wide flight/hotel). When OpenAI is not configured —
    or any OpenAI call fails — this degrades to the rule-based
    :class:`TripPlannerService` so the endpoint always answers with the same
    response shape (``day`` is simply ``None`` on those items).

    Every plan returned here is denominated in the wallet currency
    (``demo_budget_currency``): the AI path already prices in it, and the
    rule-based fallback is normalised below so the endpoint is always
    wallet-consistent.
    """

    try:
        return await itinerary.plan(request)
    except AiItineraryNotConfiguredError:
        return _wallet_consistent(await planner.plan(request), settings)
    except Exception:  # noqa: BLE001 — any OpenAI/upstream failure degrades safely
        return _wallet_consistent(await planner.plan(request), settings)


def _wallet_consistent(
    response: TripPlanResponse, settings: Settings
) -> TripPlanResponse:
    """Force a fallback plan's currency to the wallet currency for ai-plan.

    The wallet has no FX, so amounts are treated as already being in the wallet
    currency (``demo_budget_currency``); the rule-based planner may have labelled
    them ``EUR`` (or a prompt-parsed currency). Relabelling — not converting —
    keeps the AI endpoint money-consistent with the wallet that books it, without
    changing :func:`plan_trip`'s behaviour for its other callers.
    """

    plan = response.trip_plan
    if plan is not None and plan.currency != settings.demo_budget_currency:
        plan.currency = settings.demo_budget_currency
    return response


@router.post(
    "/confirm",
    response_model=TripConfirmResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Book every item of a plan (charges the travel wallet)",
)
async def confirm_trip(
    request: TripConfirmRequest,
    user: UserORM = Depends(get_current_user),
    wallet: WalletService = Depends(get_wallet_service),
) -> TripConfirmResponse:
    plan = request.trip_plan
    if not plan.items:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty plan.")
    booking_ids: list[str] = []
    balance = 0
    try:
        for item in plan.items:
            purchase, budget = await wallet.purchase(
                guest_id=user.guest_id,
                kind=item.kind,
                title=item.title,
                subtitle=item.subtitle,
                amount_cents=item.amount_cents,
                currency=plan.currency,
                details={
                    **item.details,
                    "trip": f"{plan.origin} → {plan.destination}",
                },
            )
            booking_ids.append(purchase.id)
            balance = budget.balance_cents
    except InvalidPurchaseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid plan item.") from exc
    except InsufficientBudgetError as exc:
        # The request-scoped session rolls back, so no partial bookings remain.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This trip would exceed your remaining budget.",
        ) from exc
    return TripConfirmResponse(
        booking_ids=booking_ids,
        total_cents=plan.total_cents,
        currency=plan.currency,
        balance_cents=balance,
    )
