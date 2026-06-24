"""Rule-based trip planner with **live SerpApi pricing**.

Parses free text like ``"Istanbul to Rome weekend trip with hotel, restaurant
and airport transfer under 1000 EUR"`` into a structured, priced
:class:`app.models.market.TripPlan`. Flight and hotel prices come from the
live SerpApi services (Google Flights / Google Hotels); restaurants come from
Google Local with a price-level based dinner estimate. Each leg independently
falls back to deterministic demo pricing (``details.live == False``) when
SerpApi is unset or the call fails, so the planner always answers.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import date, timedelta
from typing import Any

from app.core.config import Settings
from app.models.market import TripPlan, TripPlanItem, TripPlanRequest, TripPlanResponse
from app.services.flight_service import FlightService
from app.services.hotel_search_service import HotelSearchService
from app.services.restaurant_service import RestaurantService

# "from X to Y" is matched first so leading verbiage ("plan a trip from …")
# never leaks into the origin; the bare "X to Y" form is the fallback.
_CITY = r"[A-Za-zÀ-ž][A-Za-zÀ-ž .'-]*?"
_TAIL = r"(?=$|[,.;]|\s+(?:weekend|week|trip|for|with|under|in|on|next|this)\b)"
_FROM_ROUTE_RE = re.compile(
    rf"from\s+({_CITY})\s+to\s+({_CITY}){_TAIL}", re.IGNORECASE
)
_ROUTE_RE = re.compile(rf"({_CITY})\s+to\s+({_CITY}){_TAIL}", re.IGNORECASE)
_BUDGET_RE = re.compile(
    r"(?:under|below|max|budget(?:\s+of)?)\s*[€$£]?\s*([\d.,]+)\s*(eur|usd|aed|gbp|try|€|\$|£)?",
    re.IGNORECASE,
)
_NIGHTS_RE = re.compile(r"(\d+)\s*(?:night|day)s?", re.IGNORECASE)

_CURRENCY_MAP = {"€": "EUR", "$": "USD", "£": "GBP"}

# How far ahead the demo trip departs; gives SerpApi a realistic search window.
_DEPARTURE_OFFSET_DAYS = 14
# Per-leg upstream budget so the whole plan stays well under ~25s.
_LEG_TIMEOUT_SECONDS = 20.0

# Major cities → primary international airport (IATA). Lowercase keys.
CITY_TO_IATA: dict[str, str] = {
    "istanbul": "IST",
    "ankara": "ESB",
    "izmir": "ADB",
    "antalya": "AYT",
    "bodrum": "BJV",
    "rome": "FCO",
    "milan": "MXP",
    "venice": "VCE",
    "naples": "NAP",
    "florence": "FLR",
    "paris": "CDG",
    "nice": "NCE",
    "lyon": "LYS",
    "london": "LHR",
    "manchester": "MAN",
    "edinburgh": "EDI",
    "dublin": "DUB",
    "new york": "JFK",
    "los angeles": "LAX",
    "san francisco": "SFO",
    "chicago": "ORD",
    "miami": "MIA",
    "boston": "BOS",
    "washington": "IAD",
    "seattle": "SEA",
    "las vegas": "LAS",
    "toronto": "YYZ",
    "vancouver": "YVR",
    "montreal": "YUL",
    "mexico city": "MEX",
    "sao paulo": "GRU",
    "rio de janeiro": "GIG",
    "buenos aires": "EZE",
    "tokyo": "HND",
    "osaka": "KIX",
    "seoul": "ICN",
    "beijing": "PEK",
    "shanghai": "PVG",
    "hong kong": "HKG",
    "singapore": "SIN",
    "bangkok": "BKK",
    "kuala lumpur": "KUL",
    "jakarta": "CGK",
    "delhi": "DEL",
    "mumbai": "BOM",
    "dubai": "DXB",
    "abu dhabi": "AUH",
    "doha": "DOH",
    "riyadh": "RUH",
    "tel aviv": "TLV",
    "cairo": "CAI",
    "casablanca": "CMN",
    "johannesburg": "JNB",
    "cape town": "CPT",
    "nairobi": "NBO",
    "amsterdam": "AMS",
    "brussels": "BRU",
    "frankfurt": "FRA",
    "berlin": "BER",
    "munich": "MUC",
    "hamburg": "HAM",
    "zurich": "ZRH",
    "geneva": "GVA",
    "vienna": "VIE",
    "prague": "PRG",
    "budapest": "BUD",
    "warsaw": "WAW",
    "barcelona": "BCN",
    "madrid": "MAD",
    "lisbon": "LIS",
    "porto": "OPO",
    "athens": "ATH",
    "copenhagen": "CPH",
    "stockholm": "ARN",
    "oslo": "OSL",
    "helsinki": "HEL",
    "moscow": "SVO",
    "sydney": "SYD",
    "melbourne": "MEL",
    "auckland": "AKL",
}


def parse_budget_cents(text: str) -> int | None:
    """Parse a budget *amount* (in minor units) from free-text ``text``.

    Reuses the shared :data:`_BUDGET_RE` so the rule-based and AI planners agree
    on how budget hints are extracted. Returns the amount in cents (e.g.
    ``"under €1500"`` -> ``150000``) or ``None`` when no budget hint is present.
    The matched currency token is intentionally ignored here — callers decide
    which currency to denominate the amount in.
    """

    m = _BUDGET_RE.search(text)
    if not m:
        return None
    amount = float(m.group(1).replace(",", ""))
    return int(amount * 100)


def _h(key: str, lo: int, hi: int) -> int:
    """Deterministic pseudo-random int in [lo, hi] from ``key``."""

    digest = hashlib.sha256(key.lower().encode()).digest()
    span = hi - lo
    return lo + int.from_bytes(digest[:2], "big") % (span + 1)


def _price_num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


class TripPlannerService:
    """Trip planner backed by the live SerpApi flight/hotel/restaurant services."""

    def __init__(
        self,
        settings: Settings,
        flight_service: FlightService,
        hotel_service: HotelSearchService,
        restaurant_service: RestaurantService,
    ) -> None:
        self._settings = settings
        self._flights = flight_service
        self._hotels = hotel_service
        self._restaurants = restaurant_service

    async def plan(self, request: TripPlanRequest) -> TripPlanResponse:
        text = request.prompt.strip()
        route = _FROM_ROUTE_RE.search(text) or _ROUTE_RE.search(text)
        if not route:
            return TripPlanResponse(
                message=(
                    "I couldn't spot a route in that. Try something like "
                    "\"Istanbul to Rome weekend trip with hotel and transfer "
                    "under 1000 EUR\"."
                ),
                intent="clarify",
                trip_plan=None,
                requires_confirmation=False,
                confirmation_action="",
            )
        origin = route.group(1).strip().title()
        destination = route.group(2).strip().title()

        currency = "EUR"
        budget_cents = request.budget_cents
        if m := _BUDGET_RE.search(text):
            amount = float(m.group(1).replace(",", ""))
            budget_cents = int(amount * 100)
            if m.group(2):
                currency = _CURRENCY_MAP.get(m.group(2), m.group(2).upper())

        lowered = text.lower()
        nights = 2
        if m := _NIGHTS_RE.search(text):
            nights = max(1, min(int(m.group(1)), 30))
        elif "week " in lowered or lowered.endswith("week"):
            nights = 7

        wants_hotel = "hotel" in lowered or "stay" in lowered
        wants_restaurant = any(w in lowered for w in ("restaurant", "dinner", "dining"))
        wants_transfer = any(w in lowered for w in ("transfer", "uber", "ride", "taxi"))
        if not (wants_hotel or wants_restaurant or wants_transfer):
            wants_hotel = wants_restaurant = wants_transfer = True

        outbound = date.today() + timedelta(days=_DEPARTURE_OFFSET_DAYS)
        inbound = outbound + timedelta(days=nights)

        results = await self._fetch_live(
            origin=origin,
            destination=destination,
            outbound=outbound.isoformat(),
            inbound=inbound.isoformat(),
            currency=currency,
            wants_hotel=wants_hotel,
            wants_restaurant=wants_restaurant,
        )

        route_key = f"{origin}->{destination}"
        items: list[TripPlanItem] = [
            self._flight_item(origin, destination, route_key, results.get("flight"))
        ]
        if wants_hotel:
            items.append(
                self._hotel_item(destination, route_key, nights, results.get("hotel"))
            )
        if wants_restaurant:
            items.append(
                self._restaurant_item(destination, route_key, results.get("restaurant"))
            )
        if wants_transfer:
            items.append(
                TripPlanItem(
                    kind="transfer",
                    title="Airport transfer",
                    subtitle="Private ride, both ways · estimated fare",
                    amount_cents=_h(route_key + ":ride", 2800, 5200),
                    details={"estimatedPrice": True},
                )
            )

        total = sum(i.amount_cents for i in items)
        status = (
            "within_budget"
            if budget_cents is None or total <= budget_cents
            else "over_budget"
        )
        live = any(i.details.get("live") for i in items)
        price_note = "live prices" if live else "demo estimate"
        money = f"{total / 100:.0f} {currency}"
        if status == "over_budget" and budget_cents:
            over_by = f"{(total - budget_cents) / 100:.0f} {currency}"
            message = (
                f"Honest heads-up: this {destination} trip comes to {money} "
                f"({price_note}), which is {over_by} over your "
                f"{budget_cents / 100:.0f} {currency} budget. Consider raising "
                "the budget or trimming an item before confirming."
            )
        else:
            message = (
                f"I put together a {destination} trip for {money} ({price_note})"
                + (
                    f" — within your {budget_cents / 100:.0f} {currency} budget"
                    if budget_cents
                    else ""
                )
                + ". Review the plan and confirm to book everything in one tap."
            )
        return TripPlanResponse(
            message=message,
            trip_plan=TripPlan(
                origin=origin,
                destination=destination,
                items=items,
                total_cents=total,
                currency=currency,
                budget_cents=budget_cents,
                budget_status=status,
            ),
        )

    # ------------------------------------------------------------------ #
    # Live lookups (concurrent; each leg degrades independently)
    # ------------------------------------------------------------------ #
    async def _fetch_live(
        self,
        *,
        origin: str,
        destination: str,
        outbound: str,
        inbound: str,
        currency: str,
        wants_hotel: bool,
        wants_restaurant: bool,
    ) -> dict[str, Any]:
        if not self._settings.serpapi_api_key:
            return {}

        tasks: dict[str, Any] = {}
        origin_iata = CITY_TO_IATA.get(origin.lower())
        dest_iata = CITY_TO_IATA.get(destination.lower())
        if origin_iata and dest_iata:
            tasks["flight"] = self._flights.search(
                origin=origin_iata,
                destination=dest_iata,
                outbound_date=outbound,
                return_date=inbound,
                adults=1,
                currency=currency,
            )
        if wants_hotel:
            tasks["hotel"] = self._hotels.search(
                location=destination,
                check_in=outbound,
                check_out=inbound,
                currency=currency,
            )
        if wants_restaurant:
            tasks["restaurant"] = self._restaurants.search(
                query="best dinner restaurants", location=destination
            )
        if not tasks:
            return {}

        results = await asyncio.gather(
            *(
                asyncio.wait_for(coro, timeout=_LEG_TIMEOUT_SECONDS)
                for coro in tasks.values()
            ),
            return_exceptions=True,
        )
        # Exceptions/timeouts stay in the map; item builders treat anything
        # that isn't a non-empty list as "fall back to demo pricing".
        return dict(zip(tasks.keys(), results))

    # ------------------------------------------------------------------ #
    # Item builders (live first, deterministic fallback)
    # ------------------------------------------------------------------ #
    def _flight_item(
        self, origin: str, destination: str, route_key: str, result: Any
    ) -> TripPlanItem:
        if isinstance(result, list):
            priced = [o for o in result if _price_num(o.get("price")) is not None]
            if priced:
                best = min(priced, key=lambda o: o["price"])
                airline = best.get("airline") or "Multiple airlines"
                return TripPlanItem(
                    kind="flight",
                    title=f"{origin} → {destination}",
                    subtitle=f"{airline} · round trip · 1 adult",
                    amount_cents=round(float(best["price"]) * 100),
                    details={
                        "origin": origin,
                        "destination": destination,
                        "airline": airline,
                        "live": True,
                    },
                )
        return TripPlanItem(
            kind="flight",
            title=f"{origin} → {destination}",
            subtitle="Round trip · Economy · 1 adult",
            amount_cents=_h(route_key + ":flight", 16000, 38000),
            details={"origin": origin, "destination": destination, "live": False},
        )

    def _hotel_item(
        self, destination: str, route_key: str, nights: int, result: Any
    ) -> TripPlanItem:
        night_label = f"{nights} night{'s' if nights != 1 else ''}"
        if isinstance(result, list):
            priced = sorted(
                (o for o in result if _price_num(o.get("price")) is not None),
                key=lambda o: o["price"],
            )
            if priced:
                pick = priced[len(priced) // 2]  # mid-range: median by total price
                total_cents = round(float(pick["price"]) * 100)
                per_night = _price_num(pick.get("perNight"))
                per_night_cents = (
                    round(per_night * 100)
                    if per_night is not None
                    else total_cents // max(nights, 1)
                )
                rating = _price_num(pick.get("rating"))
                subtitle = (
                    f"{night_label} · {rating:.1f}★" if rating else night_label
                )
                return TripPlanItem(
                    kind="hotel",
                    title=str(pick["name"]),
                    subtitle=subtitle,
                    amount_cents=total_cents,
                    details={
                        "nights": nights,
                        "perNightCents": per_night_cents,
                        "live": True,
                    },
                )
        per_night = _h(route_key + ":hotel", 9000, 19000)
        return TripPlanItem(
            kind="hotel",
            title=f"Boutique hotel in {destination}",
            subtitle=f"{night_label} · 4★ · breakfast included",
            amount_cents=per_night * nights,
            details={"nights": nights, "perNightCents": per_night, "live": False},
        )

    def _restaurant_item(
        self, destination: str, route_key: str, result: Any
    ) -> TripPlanItem:
        if isinstance(result, list) and result:
            top = max(result, key=lambda o: o.get("rating") or 0.0)
            name = top.get("name")
            if name:
                price_level = top.get("priceLevel") or ""
                dollars = price_level.count("$") if isinstance(price_level, str) else 0
                per_person = dollars * 3000 if dollars else 6000
                return TripPlanItem(
                    kind="restaurant",
                    title=f"Dinner at {name}",
                    subtitle="estimated · table for 2",
                    amount_cents=per_person * 2,
                    details={"live": True, "estimatedPrice": True},
                )
        return TripPlanItem(
            kind="restaurant",
            title=f"Signature dinner in {destination}",
            subtitle="Table for 2 · chef's menu",
            amount_cents=_h(route_key + ":food", 5000, 9000),
            details={"live": False},
        )
