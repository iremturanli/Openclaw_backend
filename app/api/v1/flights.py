"""Live flight search (SerpApi Google Flights), authenticated."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user, get_flight_service
from app.db.models.user import UserORM
from app.models.travel_wallet import FlightSearchResponse
from app.services.flight_service import FlightSearchError, FlightService

router = APIRouter(prefix="/flights", tags=["flights"])


def _coerce_outbound(value: str) -> str:
    """Clamp a missing/malformed/past outbound date to today.

    SerpApi rejects a past ``outbound_date`` outright, which the endpoint then
    surfaced as a 502. Clamping keeps the search valid (and closest to intent)
    instead of failing the request.
    """
    today = date.today()
    try:
        parsed = date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return today.isoformat()
    return (parsed if parsed >= today else today).isoformat()


def _coerce_return(value: str | None, outbound_iso: str) -> str | None:
    """Keep the return date only if it lands after the (coerced) outbound date;
    otherwise push it a few days out so the round trip stays valid."""
    if not value:
        return None
    outbound = date.fromisoformat(outbound_iso)
    try:
        parsed = date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return (outbound + timedelta(days=3)).isoformat()
    return (parsed if parsed > outbound else outbound + timedelta(days=3)).isoformat()


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
    # Defend against stale/past dates (e.g. a default that aged past "today"):
    # SerpApi errors on a past outbound_date and that became a 502.
    outbound_date = _coerce_outbound(outbound_date)
    return_date = _coerce_return(return_date, outbound_date)
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
