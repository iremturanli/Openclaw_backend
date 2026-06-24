"""AI travel assistant chat endpoint (authenticated).

Drives the OpenAI function-calling [AgentService] against the same flight +
wallet services the manual UI uses — so voice, chat and buttons share one
backend, one budget and one list.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_current_user,
    get_flight_service,
    get_hotel_search_service,
    get_restaurant_service,
    get_settings,
    get_wallet_service,
)
from app.core.config import Settings
from app.db.models.user import UserORM
from app.models.assistant import (
    ChatRequest,
    ChatResponse,
    TranslateRequest,
    TranslateResponse,
)
from app.models.market import TripPlanRequest
from app.services.agent_service import AgentNotConfiguredError, AgentService
from app.services.trip_planner_service import TripPlannerService
from app.services.flight_service import FlightService
from app.services.hotel_search_service import HotelSearchService
from app.services.restaurant_service import RestaurantService
from app.services.translation_service import TranslationService
from app.services.wallet_service import WalletService

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Chat with the AI travel concierge (tool-calling agent)",
)
async def chat(
    request: ChatRequest,
    user: UserORM = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    flights: FlightService = Depends(get_flight_service),
    hotels: HotelSearchService = Depends(get_hotel_search_service),
    restaurants: RestaurantService = Depends(get_restaurant_service),
    wallet: WalletService = Depends(get_wallet_service),
) -> ChatResponse:
    agent = AgentService(
        settings=settings,
        flights=flights,
        hotels=hotels,
        restaurants=restaurants,
        wallet=wallet,
        guest_id=user.guest_id,
        preferences=user.preferences,
    )
    history = [{"role": m.role, "content": m.content} for m in request.messages]
    try:
        reply = await agent.run(history)
    except AgentNotConfiguredError:
        # No OpenAI key: degrade to the rule-based planner so chat still works.
        planner = TripPlannerService(settings, flights, hotels, restaurants)
        last_user = next(
            (m.content for m in reversed(request.messages) if m.role == "user"), ""
        )
        planned = await planner.plan(TripPlanRequest(prompt=last_user or "help"))
        budget = await wallet.ensure_budget(user.guest_id)
        return ChatResponse(
            reply=planned.message
            + (
                "\n\n(Demo mode — set OPENAI_API_KEY for the live concierge. "
                "Use the trip planner card to confirm this plan.)"
                if planned.trip_plan
                else "\n\n(Demo mode — set OPENAI_API_KEY for the live concierge.)"
            ),
            balance_cents=budget.balance_cents,
            currency=budget.currency,
        )

    budget = await wallet.ensure_budget(user.guest_id)
    return ChatResponse(
        reply=reply,
        flight_options=agent.flight_options,
        hotel_options=agent.hotel_options,
        restaurant_options=agent.restaurant_options,
        booked=agent.booked,
        balance_cents=budget.balance_cents,
        currency=budget.currency,
    )


@router.post(
    "/translate",
    response_model=TranslateResponse,
    summary="Live Translation — translate traveller text between languages",
)
async def translate(
    request: TranslateRequest,
    user: UserORM = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> TranslateResponse:
    """Translate text into ``targetLang`` via OpenAI, auto-detecting the source.

    Honest about availability: with no OpenAI key (or on an upstream failure)
    the service returns ``isDemo: true`` with the original text echoed back and
    a ``note``, so this endpoint never 500s on a missing key.
    """

    service = TranslationService(settings)
    result = await service.translate(
        text=request.text,
        target_lang=request.target_lang,
        source_lang=request.source_lang,
    )
    return TranslateResponse(**result)
