"""Restaurant search via SerpApi's Google Local engine.

Returns normalized restaurant options for the agent and the UI. Reservations are
free in the demo (recorded with a $0 amount). With no SerpApi key it returns an
empty list.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings

_TIMEOUT = httpx.Timeout(20.0)


class RestaurantSearchError(Exception):
    """Upstream restaurant-search failure."""


class RestaurantService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def search(
        self, *, query: str, location: str | None = None
    ) -> list[dict[str, Any]]:
        settings = self._settings
        if not settings.serpapi_api_key:
            return []

        q = query if location is None else f"{query} in {location}"
        params = {
            "engine": "google_local",
            "q": q,
            "hl": "en",
            "google_domain": "google.com",
            "api_key": settings.serpapi_api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(settings.serpapi_base_url, params=params)
        except httpx.HTTPError as exc:
            raise RestaurantSearchError(str(exc)) from exc
        if resp.status_code != 200:
            raise RestaurantSearchError(f"SerpApi {resp.status_code}")
        data = resp.json()
        if data.get("error"):
            raise RestaurantSearchError(str(data["error"]))

        local = data.get("local_results")
        places = (
            local
            if isinstance(local, list)
            else (local.get("places", []) if isinstance(local, dict) else [])
        )
        out: list[dict[str, Any]] = []
        for i, p in enumerate(places):
            if not isinstance(p, dict) or not p.get("title"):
                continue
            out.append(
                {
                    "id": f"re_{i}",
                    "name": p.get("title"),
                    "rating": _num(p.get("rating")),
                    "reviews": p.get("reviews"),
                    "priceLevel": p.get("price"),
                    "type": p.get("type"),
                    "address": p.get("address"),
                    "image": p.get("thumbnail"),
                }
            )
        return out


def _num(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None
