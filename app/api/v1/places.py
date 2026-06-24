"""Places / hotels directory proxy.

The mobile app's Directory and Digital-Key screens render live venue & hotel
data from SerpApi (Google Local / Google Hotels engines). Rather than ship the
SerpApi key in the app, the client calls these endpoints and the backend
forwards the request server-side, returning SerpApi's JSON unchanged.

When no key is configured the endpoints return an empty result set (HTTP 200)
so the app gracefully falls back to its seed/placeholder content instead of
erroring.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import Settings, get_settings

router = APIRouter(prefix="/places", tags=["places"])

_TIMEOUT = httpx.Timeout(20.0)


async def _serp_get(params: dict[str, str], settings: Settings) -> dict[str, Any]:
    """Forward a query to SerpApi and return the parsed JSON."""
    query = {**params, "api_key": settings.serpapi_api_key, "google_domain": "google.com"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(settings.serpapi_base_url, params=query)
    except httpx.HTTPError as exc:  # network / timeout
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Places provider request failed",
        ) from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Places provider error {resp.status_code}",
        )
    return resp.json()


@router.get(
    "/local",
    summary="Proxy SerpApi Google Local search for the directory",
)
async def local_places(
    q: str = Query(..., min_length=1, description="Search query, e.g. 'spa in Dubai'"),
    hl: str = Query("en"),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Return the SerpApi google_local JSON (``local_results``)."""
    if not settings.serpapi_api_key:
        return {"local_results": []}
    return await _serp_get({"engine": "google_local", "q": q, "hl": hl}, settings)


@router.get(
    "/hotels",
    summary="Proxy SerpApi Google Hotels search for the digital-key card",
)
async def hotels(
    q: str = Query(..., min_length=1),
    check_in_date: str = Query(..., alias="checkInDate"),
    check_out_date: str = Query(..., alias="checkOutDate"),
    adults: int = Query(2, ge=1),
    currency: str = Query("USD"),
    hl: str = Query("en"),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Return the SerpApi google_hotels JSON (``properties``)."""
    if not settings.serpapi_api_key:
        return {"properties": []}
    return await _serp_get(
        {
            "engine": "google_hotels",
            "q": q,
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "adults": str(adults),
            "currency": currency,
            "hl": hl,
        },
        settings,
    )


@router.get(
    "/geocode/reverse",
    summary="Reverse-geocode coordinates to a city (OSM Nominatim, keyless)",
)
async def reverse_geocode(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
) -> dict[str, Any]:
    """Return ``{"city": ..., "country": ...}`` for the coordinates.

    Uses OpenStreetMap's free Nominatim service (no key; requires a proper
    User-Agent per their usage policy). Fails honestly when unreachable.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "lat": str(lat),
                    "lon": str(lng),
                    "format": "jsonv2",
                    "zoom": "10",
                    "accept-language": "en",
                },
                headers={"User-Agent": "StayWallet/1.0 (demo travel app)"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Reverse geocoding unavailable",
        ) from exc
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Reverse geocoding error {resp.status_code}",
        )
    data = resp.json()
    address = data.get("address") or {}
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("county")
        or address.get("state")
    )
    if not city:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No city found for these coordinates",
        )
    return {"city": city, "country": address.get("country", "")}


@router.get(
    "/hotels/details",
    summary="Proxy SerpApi Google Hotels property details (real rooms & rates)",
)
async def hotel_details(
    property_token: str = Query(..., alias="propertyToken", min_length=1),
    q: str = Query(..., min_length=1),
    check_in_date: str = Query(..., alias="checkInDate"),
    check_out_date: str = Query(..., alias="checkOutDate"),
    adults: int = Query(2, ge=1),
    currency: str = Query("USD"),
    hl: str = Query("en"),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Return the SerpApi google_hotels property-details JSON.

    Carries real room offers (``featured_prices`` with per-room names and
    rates) and per-OTA ``prices`` for the selected dates — the app renders the
    "Select Your Room" list from this, never from invented room types.
    """
    if not settings.serpapi_api_key:
        return {"featured_prices": [], "prices": []}
    return await _serp_get(
        {
            "engine": "google_hotels",
            "q": q,
            "property_token": property_token,
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "adults": str(adults),
            "currency": currency,
            "hl": hl,
        },
        settings,
    )
