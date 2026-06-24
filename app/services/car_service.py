"""Car-rental search: mock Sixt-branded fleet + Booking.com Demand API adapter.

Providers (``STAYWALLET_CAR_PROVIDER``):

- ``mock`` (default): deterministic, realistic fleet flagged ``sandbox=True``.
- ``booking``: LIVE adapter for the Booking.com Demand API v3.1
  (``POST {base}/cars/search`` per
  https://developers.booking.com/demand/docs/open-api/demand-api/cars).
  Requires ``STAYWALLET_BOOKING_DEMAND_TOKEN`` (Bearer) and
  ``STAYWALLET_BOOKING_AFFILIATE_ID`` (``X-Affiliate-Id`` header); point
  ``STAYWALLET_BOOKING_DEMAND_BASE_URL`` at the sandbox host to test.
- ``sixt``: reserved for a direct Sixt partner integration (credentials only;
  raises a clear "missing credentials" error until they exist).

The wire shape (:class:`app.models.market.CarOffer`) is identical across
providers, so the Flutter app never changes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import Settings
from app.models.market import CarOffer

_TIMEOUT = httpx.Timeout(20.0)


class CarSearchError(Exception):
    """Upstream car-search failure."""


class CarProviderNotConfiguredError(Exception):
    """A live car provider is selected but its credentials are missing."""

    def __init__(self, missing: str) -> None:
        self.missing = missing
        super().__init__(f"Missing {missing}")


_FLEET: list[CarOffer] = [
    CarOffer(
        id="car_bmw5",
        name="BMW 5 Series",
        category="Premium",
        seats=5,
        bags=3,
        fuel="Hybrid",
        price_per_day_cents=12900,
        rating=4.9,
        badge="MOST BOOKED",
        image="https://images.unsplash.com/photo-1555215695-3004980ad54e?w=800",
    ),
    CarOffer(
        id="car_audia6",
        name="Audi A6",
        category="Premium",
        seats=5,
        bags=3,
        price_per_day_cents=11900,
        rating=4.8,
        image="https://images.unsplash.com/photo-1606220838315-056192d5e927?w=800",
    ),
    CarOffer(
        id="car_golf",
        name="VW Golf",
        category="Compact",
        seats=5,
        bags=2,
        price_per_day_cents=5400,
        rating=4.7,
        badge="BEST VALUE",
        image="https://images.unsplash.com/photo-1471444928139-48c5bf5173f8?w=800",
    ),
    CarOffer(
        id="car_tesla3",
        name="Tesla Model 3",
        category="Electric",
        seats=5,
        bags=2,
        fuel="Electric",
        price_per_day_cents=9800,
        rating=4.9,
        badge="ZERO EMISSION",
        image="https://images.unsplash.com/photo-1560958089-b8a1929cea89?w=800",
    ),
    CarOffer(
        id="car_911",
        name="Porsche 911 Carrera S",
        category="Sports",
        seats=2,
        bags=1,
        price_per_day_cents=34900,
        rating=5.0,
        badge="FEATURED DEAL",
        image="https://images.unsplash.com/photo-1503376780353-7e6692767b70?w=800",
    ),
    CarOffer(
        id="car_xc90",
        name="Volvo XC90",
        category="SUV",
        seats=7,
        bags=4,
        fuel="Hybrid",
        price_per_day_cents=13900,
        rating=4.8,
        image="https://images.unsplash.com/photo-1519641471654-76ce0107ad1b?w=800",
    ),
]


class CarService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def provider(self) -> str:
        return self._settings.car_provider

    @property
    def sandbox(self) -> bool:
        return self._settings.car_provider == "mock"

    async def search(
        self, *, pickup: str, category: str | None = None
    ) -> list[CarOffer]:
        provider = self._settings.car_provider
        if provider == "booking":
            return await self._search_booking_demand(pickup=pickup)
        if provider == "sixt":
            # Direct Sixt partner API needs commercial credentials.
            raise CarProviderNotConfiguredError("SIXT_CLIENT_ID / SIXT_CLIENT_SECRET")
        location = pickup.strip() or "Dubai International Airport"
        offers = [
            o.model_copy(update={"pickup_location": location}) for o in _FLEET
        ]
        if category:
            wanted = category.strip().lower()
            offers = [o for o in offers if o.category.lower() == wanted] or offers
        return offers

    async def get(self, offer_id: str) -> CarOffer | None:
        for offer in _FLEET:
            if offer.id == offer_id:
                return offer
        return None

    # ── Booking.com Demand API v3.1 (live) ────────────────────────────────
    async def _search_booking_demand(self, *, pickup: str) -> list[CarOffer]:
        """``POST /cars/search`` against the Demand API.

        Request/response shapes follow the public docs: bearer auth +
        ``X-Affiliate-Id``, a ``route`` with pickup/dropoff location+datetime,
        mandatory ``driver.age``/``booker.country``/``currency``; the response
        carries a ``data`` array of vehicle products.
        """

        settings = self._settings
        if not settings.booking_demand_token or not settings.booking_affiliate_id:
            raise CarProviderNotConfiguredError(
                "BOOKING_DEMAND_TOKEN / BOOKING_AFFILIATE_ID"
            )

        pickup_dt = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        dropoff_dt = pickup_dt + timedelta(days=3)
        location: dict[str, Any] = (
            {"airport": pickup.strip().upper()}
            if len(pickup.strip()) == 3 and pickup.strip().isalpha()
            else {"city": pickup.strip() or "Dubai"}
        )
        body = {
            "booker": {"country": "nl"},
            "currency": "USD",
            "driver": {"age": 30},
            "route": {
                "pickup": {
                    "location": location,
                    "datetime": pickup_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                "dropoff": {
                    "location": location,
                    "datetime": dropoff_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                },
            },
            "maximum_results": 20,
        }
        headers = {
            "Authorization": f"Bearer {settings.booking_demand_token}",
            "X-Affiliate-Id": str(settings.booking_affiliate_id),
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{settings.booking_demand_base_url}/cars/search",
                    json=body,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise CarSearchError(str(exc)) from exc
        if resp.status_code != 200:
            raise CarSearchError(f"Booking.com Demand API {resp.status_code}")

        rental_days = max(1, (dropoff_dt - pickup_dt).days)
        offers: list[CarOffer] = []
        for i, item in enumerate(resp.json().get("data") or []):
            if not isinstance(item, dict):
                continue
            vehicle = item.get("vehicle") or item.get("vehicle_info") or item
            price = item.get("price") or item.get("pricing") or {}
            total = _first_number(
                price.get("total"),
                price.get("amount"),
                (price.get("base") or {}).get("amount")
                if isinstance(price.get("base"), dict)
                else None,
            )
            name = (
                vehicle.get("name")
                or vehicle.get("label")
                or vehicle.get("group")
                or f"Rental car {i + 1}"
            )
            offers.append(
                CarOffer(
                    id=str(item.get("id") or f"bdc_{i}"),
                    partner="Booking.com",
                    name=str(name),
                    category=str(vehicle.get("category") or vehicle.get("group") or "Standard"),
                    seats=int(_first_number(vehicle.get("seats"), 5) or 5),
                    bags=int(_first_number(vehicle.get("suitcases"), vehicle.get("bags"), 2) or 2),
                    transmission=str(vehicle.get("transmission") or "Automatic"),
                    fuel=str(vehicle.get("fuel_type") or vehicle.get("fuel") or "Petrol"),
                    price_per_day_cents=int(round((total or 0) * 100 / rental_days)),
                    currency=str(price.get("currency") or "USD"),
                    rating=4.7,
                    image=vehicle.get("image") or vehicle.get("image_url"),
                    pickup_location=pickup.strip() or "Airport",
                )
            )
        return offers


def _first_number(*candidates: Any) -> float | None:
    for value in candidates:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None
