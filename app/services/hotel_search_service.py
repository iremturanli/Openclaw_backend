"""Hotel search via SerpApi's Google Hotels engine.

Returns normalized hotel options (real prices) for the agent and the UI. With no
SerpApi key it returns an empty list. Price is the total for the stay when
SerpApi reports it, else per-night × nights.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from app.core.config import Settings

_TIMEOUT = httpx.Timeout(30.0)


class HotelSearchError(Exception):
    """Upstream hotel-search failure."""


class HotelSearchService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def search(
        self,
        *,
        location: str,
        check_in: str,
        check_out: str,
        adults: int = 2,
        currency: str | None = None,
    ) -> list[dict[str, Any]]:
        settings = self._settings
        if not settings.serpapi_api_key:
            return []

        cur = currency or settings.demo_budget_currency
        params = {
            "engine": "google_hotels",
            "q": f"hotels in {location}",
            "check_in_date": check_in,
            "check_out_date": check_out,
            "adults": str(adults),
            "currency": cur,
            "hl": "en",
            "api_key": settings.serpapi_api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(settings.serpapi_base_url, params=params)
        except httpx.HTTPError as exc:
            raise HotelSearchError(str(exc)) from exc
        if resp.status_code != 200:
            raise HotelSearchError(f"SerpApi {resp.status_code}")
        data = resp.json()
        if data.get("error"):
            raise HotelSearchError(str(data["error"]))

        nights = _nights(check_in, check_out)
        props = data.get("properties") or []
        out: list[dict[str, Any]] = []
        for i, p in enumerate(props):
            opt = self._normalize(p, index=i, currency=cur, nights=nights)
            if opt is not None:
                out.append(opt)
        return out

    @staticmethod
    def _normalize(
        p: dict, *, index: int, currency: str, nights: int
    ) -> dict[str, Any] | None:
        name = p.get("name")
        if not name:
            return None
        total = _num((p.get("total_rate") or {}).get("extracted_lowest"))
        per_night = _num((p.get("rate_per_night") or {}).get("extracted_lowest"))
        price = total if total is not None else (
            per_night * nights if per_night is not None else None
        )
        images = p.get("images") or []
        image = None
        if images and isinstance(images[0], dict):
            image = images[0].get("thumbnail") or images[0].get("original_image")
        return {
            "id": f"ho_{index}",
            "name": name,
            "price": round(price) if price is not None else None,
            "currency": currency,
            "perNight": round(per_night) if per_night is not None else None,
            "nights": nights,
            "rating": _num(p.get("overall_rating")),
            "stars": _extract_stars(p),
            "image": image,
            "bookingLink": p.get("link") or p.get("serpapi_property_details_link"),
            "amenities": (p.get("amenities") or [])[:3],
        }


def _nights(check_in: str, check_out: str) -> int:
    try:
        a = date.fromisoformat(check_in)
        b = date.fromisoformat(check_out)
        return max((b - a).days, 1)
    except ValueError:
        return 1


def _num(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _extract_stars(p: dict) -> int | None:
    ex = p.get("extracted_hotel_class")
    if isinstance(ex, (int, float)) and ex > 0:
        return int(ex)
    return None
