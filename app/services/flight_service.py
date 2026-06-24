"""Flight search via SerpApi's Google Flights engine.

Returns normalized [FlightOption]-shaped dicts the app and the AI agent both
consume. Prices are whatever SerpApi reports (in the requested currency) — never
fabricated. With no SerpApi key the search returns an empty list.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings

_TIMEOUT = httpx.Timeout(30.0)


class FlightSearchError(Exception):
    """Upstream flight-search failure."""


class FlightService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def search(
        self,
        *,
        origin: str,
        destination: str,
        outbound_date: str,
        return_date: str | None = None,
        adults: int = 1,
        currency: str | None = None,
    ) -> list[dict[str, Any]]:
        settings = self._settings
        if not settings.serpapi_api_key:
            return []

        cur = currency or settings.demo_budget_currency
        params: dict[str, str] = {
            "engine": "google_flights",
            "departure_id": origin.upper(),
            "arrival_id": destination.upper(),
            "outbound_date": outbound_date,
            "adults": str(adults),
            "currency": cur,
            "hl": "en",
            "api_key": settings.serpapi_api_key,
        }
        # type: 1 = round trip (needs return_date), 2 = one way.
        if return_date:
            params["return_date"] = return_date
            params["type"] = "1"
        else:
            params["type"] = "2"

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(settings.serpapi_base_url, params=params)
        except httpx.HTTPError as exc:
            raise FlightSearchError(str(exc)) from exc
        if resp.status_code != 200:
            raise FlightSearchError(f"SerpApi {resp.status_code}")

        data = resp.json()
        if data.get("error"):
            raise FlightSearchError(str(data["error"]))

        raw = (data.get("best_flights") or []) + (data.get("other_flights") or [])
        options: list[dict[str, Any]] = []
        for i, item in enumerate(raw):
            opt = self._normalize(item, index=i, currency=cur)
            if opt is not None:
                options.append(opt)
        return options

    @staticmethod
    def _normalize(item: dict, *, index: int, currency: str) -> dict[str, Any] | None:
        legs = item.get("flights") or []
        if not legs:
            return None
        first, last = legs[0], legs[-1]
        dep = first.get("departure_airport", {}) or {}
        arr = last.get("arrival_airport", {}) or {}
        airlines = sorted({leg.get("airline") for leg in legs if leg.get("airline")})
        price = item.get("price")
        return {
            "id": f"fl_{index}",
            "price": price if isinstance(price, (int, float)) else None,
            "currency": currency,
            "airline": ", ".join(airlines) if airlines else "Multiple airlines",
            "airlineLogo": item.get("airline_logo") or first.get("airline_logo"),
            "departureAirport": dep.get("id"),
            "departureName": dep.get("name"),
            "departureTime": dep.get("time"),
            "arrivalAirport": arr.get("id"),
            "arrivalName": arr.get("name"),
            "arrivalTime": arr.get("time"),
            "durationMinutes": item.get("total_duration"),
            "stops": max(len(legs) - 1, 0),
        }
