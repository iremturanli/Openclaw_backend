"""Travel Services business logic.

Reads seeded categories/deals and creates bookings. Booking is a real
cross-feature transaction: it persists a ``bookings`` row **and** writes a
loyalty earn row (travel multiplier, 3x) through the shared
:class:`LoyaltyService`, both inside the request's unit of work so they commit
or roll back together.
"""

from __future__ import annotations

import secrets

from app.core.config import Settings, get_settings
from app.models.travel import (
    BookingConfirmation,
    BookingRequest,
    FeaturedDeal,
    ServiceCategory,
)
from app.repositories.base import LoyaltyRepository, TravelRepository
from app.services.exceptions import GuestNotFoundError, TravelTargetNotFoundError
from app.services.loyalty_service import LoyaltyService


class TravelService:
    """Orchestrates travel catalogue reads and loyalty-earning bookings."""

    def __init__(
        self,
        travel_repository: TravelRepository,
        loyalty_repository: LoyaltyRepository,
        loyalty_service: LoyaltyService,
        settings: Settings | None = None,
    ) -> None:
        self._travel = travel_repository
        self._guests = loyalty_repository
        self._loyalty = loyalty_service
        self._settings = settings or get_settings()

    async def list_categories(self) -> list[ServiceCategory]:
        """Return all seeded travel-service categories."""

        return await self._travel.list_categories()

    async def list_deals(self) -> list[FeaturedDeal]:
        """Return all seeded featured deals."""

        return await self._travel.list_deals()

    async def create_booking(self, request: BookingRequest) -> BookingConfirmation:
        """Create a booking, award travel loyalty points, return confirmation.

        Raises:
            GuestNotFoundError: If ``request.guest_id`` is unknown.
            TravelTargetNotFoundError: If the referenced category/deal is unknown.

        ``request`` is guaranteed (by the Pydantic model validator) to carry at
        least one of ``category_id`` / ``deal_id``; supplying neither surfaces as
        HTTP 422 before reaching this method.
        """

        if not await self._guests.guest_exists(request.guest_id):
            raise GuestNotFoundError(request.guest_id)

        # Resolve the booking target (deal takes precedence if both are given).
        title: str
        total_cents: int
        category_id: str | None = None
        deal_id: str | None = None

        if request.deal_id:
            deal = await self._travel.get_deal(request.deal_id)
            if deal is None:
                raise TravelTargetNotFoundError(request.deal_id)
            deal_id = deal.id
            title = deal.title
            total_cents = await self._travel.deal_base_price_cents(deal.id) or 0
        else:
            assert request.category_id is not None  # guaranteed by validator
            category = await self._travel.get_category(request.category_id)
            if category is None:
                raise TravelTargetNotFoundError(request.category_id)
            category_id = category.id
            title = category.name
            total_cents = (
                await self._travel.category_base_price_cents(category.id) or 0
            )

        booking_id = f"bk_{secrets.token_hex(6)}"

        # Award travel points (3x) on the indicative total, atomically with the
        # booking row.
        points_earned = await self._loyalty.earn(
            guest_id=request.guest_id,
            total_cents=total_cents,
            source="booking",
            reference_id=booking_id,
            description=f"Travel booking: {title}",
            multiplier=self._settings.loyalty_travel_multiplier,
        )

        await self._travel.create_booking(
            booking_id=booking_id,
            guest_id=request.guest_id,
            category_id=category_id,
            deal_id=deal_id,
            title=title,
            total_cents=total_cents,
            points_earned=points_earned,
        )

        new_balance = await self._guests.balance(request.guest_id)
        return BookingConfirmation(
            booking_id=booking_id,
            title=title,
            points_earned=points_earned,
            new_balance=new_balance,
        )
