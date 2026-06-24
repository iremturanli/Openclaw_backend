"""Travel Services endpoints (categories, deals, bookings)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_travel_service
from app.models.travel import (
    BookingConfirmation,
    BookingRequest,
    FeaturedDeal,
    ServiceCategory,
)
from app.services.exceptions import GuestNotFoundError, TravelTargetNotFoundError
from app.services.travel_service import TravelService

router = APIRouter(prefix="/travel", tags=["travel"])


@router.get(
    "/categories",
    response_model=list[ServiceCategory],
    response_model_by_alias=True,
    summary="List bookable travel-service categories",
)
async def list_categories(
    service: TravelService = Depends(get_travel_service),
) -> list[ServiceCategory]:
    """Return all seeded travel-service categories."""

    return await service.list_categories()


@router.get(
    "/deals",
    response_model=list[FeaturedDeal],
    response_model_by_alias=True,
    summary="List featured partner deals",
)
async def list_deals(
    service: TravelService = Depends(get_travel_service),
) -> list[FeaturedDeal]:
    """Return all seeded featured deals."""

    return await service.list_deals()


@router.post(
    "/bookings",
    response_model=BookingConfirmation,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Book a travel service and earn loyalty points",
)
async def create_booking(
    request: BookingRequest,
    service: TravelService = Depends(get_travel_service),
) -> BookingConfirmation:
    """Create a booking.

    Awards loyalty points (3x travel multiplier) via the shared ledger and
    returns the new balance. Returns 404 for an unknown category/deal or guest,
    and 422 (via Pydantic) when neither ``categoryId`` nor ``dealId`` is given.
    """

    try:
        return await service.create_booking(request)
    except GuestNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guest not found",
        ) from exc
    except TravelTargetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Travel category or deal not found",
        ) from exc
