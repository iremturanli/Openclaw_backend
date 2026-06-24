"""FastAPI dependency providers.

Repositories are now **DB-backed** and constructed per request from the
``AsyncSession`` provided by :func:`app.db.session.get_session`. Services are
likewise built per request from those repositories. The transaction boundary
lives in ``get_session`` (commit on success, rollback on error), so an order or
booking and its loyalty-ledger row commit atomically.

The TTS service is stateless and unrelated to the DB, so it keeps its own
provider (overridden in tests).
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import Settings, get_settings
from app.db.models.user import UserORM
from app.db.session import get_session
from app.repositories.user_repo import UserRepository
from app.services.auth_service import AuthService
from app.services.preferences_service import PreferencesService
from app.services.flight_service import FlightService
from app.services.hotel_search_service import HotelSearchService
from app.services.restaurant_service import RestaurantService
from app.services.car_service import CarService
from app.services.transfer_service import TransferService
from app.services.trip_planner_service import TripPlannerService
from app.services.ai_itinerary_service import AiItineraryService
from app.services.wallet_service import WalletService
from app.services.spend_service import SpendService
from app.repositories.base import (
    CheckInRepository,
    ConnectionRepository,
    LoyaltyRepository,
    MenuRepository,
    OrchestratorRepository,
    OrderRepository,
    StayRepository,
    TravelRepository,
)
from app.repositories.db import (
    DbCheckInRepository,
    DbConnectionRepository,
    DbLoyaltyRepository,
    DbMenuRepository,
    DbOrchestratorRepository,
    DbOrderRepository,
    DbStayRepository,
    DbTravelRepository,
)
from app.services.check_in_service import CheckInService
from app.services.connection_service import ConnectionService
from app.services.key_service import KeyService
from app.services.loyalty_service import LoyaltyService
from app.services.orchestrator_service import OrchestratorService
from app.services.order_service import OrderService
from app.services.travel_service import TravelService
from app.services.tts_service import TtsService


# --------------------------------------------------------------------------- #
# Repositories (per request, bound to the request's AsyncSession)
# --------------------------------------------------------------------------- #
def get_stay_repository(
    session: AsyncSession = Depends(get_session),
) -> StayRepository:
    """Return a DB-backed stay repository for this request."""

    return DbStayRepository(session)


def get_check_in_repository(
    session: AsyncSession = Depends(get_session),
) -> CheckInRepository:
    """Return a DB-backed check-in repository for this request."""

    return DbCheckInRepository(session)


def get_menu_repository(
    session: AsyncSession = Depends(get_session),
) -> MenuRepository:
    """Return a DB-backed menu repository for this request."""

    return DbMenuRepository(session)


def get_order_repository(
    session: AsyncSession = Depends(get_session),
) -> OrderRepository:
    """Return a DB-backed order repository for this request."""

    return DbOrderRepository(session)


def get_travel_repository(
    session: AsyncSession = Depends(get_session),
) -> TravelRepository:
    """Return a DB-backed travel repository for this request."""

    return DbTravelRepository(session)


def get_loyalty_repository(
    session: AsyncSession = Depends(get_session),
) -> LoyaltyRepository:
    """Return a DB-backed loyalty-ledger repository for this request."""

    return DbLoyaltyRepository(session)


def get_connection_repository(
    session: AsyncSession = Depends(get_session),
) -> ConnectionRepository:
    """Return a DB-backed provider-connection repository for this request."""

    return DbConnectionRepository(session)


def get_orchestrator_repository(
    session: AsyncSession = Depends(get_session),
) -> OrchestratorRepository:
    """Return a DB-backed loyalty-orchestrator repository for this request."""

    return DbOrchestratorRepository(session)


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #
def get_key_service() -> KeyService:
    """Return a key service."""

    return KeyService()


def get_loyalty_service(
    loyalty_repo: LoyaltyRepository = Depends(get_loyalty_repository),
) -> LoyaltyService:
    """Return a wired :class:`LoyaltyService`."""

    return LoyaltyService(loyalty_repo)


def get_check_in_service(
    stay_repo: StayRepository = Depends(get_stay_repository),
    check_in_repo: CheckInRepository = Depends(get_check_in_repository),
    key_service: KeyService = Depends(get_key_service),
) -> CheckInService:
    """Return a wired :class:`CheckInService`."""

    return CheckInService(stay_repo, check_in_repo, key_service)


def get_order_service(
    stay_repo: StayRepository = Depends(get_stay_repository),
    menu_repo: MenuRepository = Depends(get_menu_repository),
    order_repo: OrderRepository = Depends(get_order_repository),
    loyalty_service: LoyaltyService = Depends(get_loyalty_service),
) -> OrderService:
    """Return a wired :class:`OrderService`."""

    return OrderService(stay_repo, menu_repo, order_repo, loyalty_service)


def get_travel_service(
    travel_repo: TravelRepository = Depends(get_travel_repository),
    loyalty_repo: LoyaltyRepository = Depends(get_loyalty_repository),
    loyalty_service: LoyaltyService = Depends(get_loyalty_service),
) -> TravelService:
    """Return a wired :class:`TravelService`."""

    return TravelService(travel_repo, loyalty_repo, loyalty_service)


def get_connection_service(
    connection_repo: ConnectionRepository = Depends(get_connection_repository),
    loyalty_repo: LoyaltyRepository = Depends(get_loyalty_repository),
) -> ConnectionService:
    """Return a wired :class:`ConnectionService`."""

    return ConnectionService(connection_repo, loyalty_repo)


def get_orchestrator_service(
    orchestrator_repo: OrchestratorRepository = Depends(
        get_orchestrator_repository
    ),
    connection_repo: ConnectionRepository = Depends(get_connection_repository),
    loyalty_repo: LoyaltyRepository = Depends(get_loyalty_repository),
) -> OrchestratorService:
    """Return a wired :class:`OrchestratorService`."""

    return OrchestratorService(orchestrator_repo, connection_repo, loyalty_repo)


def get_tts_service() -> TtsService:
    """Return a text-to-speech service backed by current settings.

    Reads ``elevenlabs_*`` settings and creates its own httpx client per call.
    Tests override this provider to inject a stubbed client.
    """

    return TtsService()


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
def get_user_repository(
    session: AsyncSession = Depends(get_session),
) -> UserRepository:
    """Return a DB-backed user repository for this request."""

    return UserRepository(session)


def get_auth_service(
    users: UserRepository = Depends(get_user_repository),
) -> AuthService:
    """Return a wired :class:`AuthService`."""

    return AuthService(users)


def get_preferences_service(
    users: UserRepository = Depends(get_user_repository),
) -> PreferencesService:
    """Return a wired :class:`PreferencesService`."""

    return PreferencesService(users)


def get_flight_service(
    settings: Settings = Depends(get_settings),
) -> FlightService:
    """Return a SerpApi-backed flight search service."""

    return FlightService(settings)


def get_hotel_search_service(
    settings: Settings = Depends(get_settings),
) -> HotelSearchService:
    """Return a SerpApi-backed hotel search service."""

    return HotelSearchService(settings)


def get_restaurant_service(
    settings: Settings = Depends(get_settings),
) -> RestaurantService:
    """Return a SerpApi-backed restaurant search service."""

    return RestaurantService(settings)


def get_car_service(
    settings: Settings = Depends(get_settings),
) -> CarService:
    """Return the car-rental search service (sandbox unless Sixt is configured)."""

    return CarService(settings)


def get_transfer_service(
    settings: Settings = Depends(get_settings),
) -> TransferService:
    """Return the transfers/scooters service (sandbox unless Uber is configured)."""

    return TransferService(settings)


def get_trip_planner_service(
    settings: Settings = Depends(get_settings),
    flights: FlightService = Depends(get_flight_service),
    hotels: HotelSearchService = Depends(get_hotel_search_service),
    restaurants: RestaurantService = Depends(get_restaurant_service),
) -> TripPlannerService:
    """Return the trip planner wired to the live SerpApi search services."""

    return TripPlannerService(settings, flights, hotels, restaurants)


def get_ai_itinerary_service(
    settings: Settings = Depends(get_settings),
    flights: FlightService = Depends(get_flight_service),
    hotels: HotelSearchService = Depends(get_hotel_search_service),
    restaurants: RestaurantService = Depends(get_restaurant_service),
) -> AiItineraryService:
    """Return the OpenAI-designed, live-priced day-by-day itinerary planner."""

    return AiItineraryService(
        settings=settings,
        flights=flights,
        hotels=hotels,
        restaurants=restaurants,
    )


def get_wallet_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> WalletService:
    """Return a demo-budget wallet service bound to this request's session."""

    return WalletService(session, settings)


def get_spend_service(
    wallet: WalletService = Depends(get_wallet_service),
) -> SpendService:
    """Return a spend-intelligence service over the guest's real purchases."""

    return SpendService(wallet)


_bearer = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    users: UserRepository = Depends(get_user_repository),
) -> UserORM:
    """Resolve the signed-in user from the ``Authorization: Bearer`` token.

    Raises 401 for a missing/invalid/expired token or unknown user. Only access
    tokens are accepted here (refresh tokens are exchanged at ``/auth/refresh``).
    """

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = security.decode_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise invalid from exc

    if payload.get("type") != "access":
        raise invalid
    user_id = payload.get("sub")
    if not isinstance(user_id, str):
        raise invalid

    user = await users.get_by_id(user_id)
    if user is None:
        raise invalid
    return user
