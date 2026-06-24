"""Live flight search (SerpApi Google Flights), authenticated."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user, get_flight_service
from app.db.models.user import UserORM
from app.models.travel_wallet import FlightSearchResponse
from app.services.flight_service import FlightSearchError, FlightService

router = APIRouter(prefix="/flights", tags=["flights"])


@router.get(
    "/search",
    response_model=FlightSearchResponse,
    summary="Search live flights (real prices via SerpApi)",
)
async def search_flights(
    origin: str = Query(..., min_length=3, max_length=3, examples=["IST"]),
    destination: str = Query(..., min_length=3, max_length=3, examples=["FCO"]),
    outbound_date: str = Query(..., alias="outboundDate", examples=["2026-06-20"]),
    return_date: str | None = Query(default=None, alias="returnDate"),
    adults: int = Query(default=1, ge=1, le=9),
    currency: str | None = None,
    user: UserORM = Depends(get_current_user),
    service: FlightService = Depends(get_flight_service),
) -> FlightSearchResponse:
    try:
        options = await service.search(
            origin=origin,
            destination=destination,
            outbound_date=outbound_date,
            return_date=return_date,
            adults=adults,
            currency=currency,
        )
    except FlightSearchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Flight search failed upstream.",
        ) from exc
    return FlightSearchResponse(options=options)
