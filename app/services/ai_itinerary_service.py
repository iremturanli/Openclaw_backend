"""AI-composed, day-by-day trip itinerary planner with **live pricing**.

The LLM (same OpenAI client setup as :class:`app.services.agent_service`) designs
only the *skeleton* of a trip — destination, number of days, and for each day the
intended restaurants / activities / transfers — and never invents prices. THIS
module then fills in REAL pricing from the live SerpApi flight/hotel/restaurant
services (reusing the helpers/patterns from
:mod:`app.services.trip_planner_service`). Activities (museums, tours, balloon
rides…) get a transparent deterministic estimate (``details.live == False``).

The result is a single bookable :class:`app.models.market.TripPlanResponse` whose
items carry a 1-based ``day`` index (per-day items) or ``None`` (trip-wide
flight / hotel stay), so the existing ``POST /trips/confirm`` ("Book All") works
unchanged. The reply ``message`` is written in the user's own language.

If OpenAI is not configured (or the call fails), the caller is expected to fall
back to the rule-based :class:`TripPlannerService`; this service signals that by
raising :class:`AiItineraryNotConfiguredError`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings
from app.models.market import TripPlan, TripPlanItem, TripPlanRequest, TripPlanResponse
from app.services.flight_service import FlightService
from app.services.hotel_search_service import HotelSearchService
from app.services.restaurant_service import RestaurantService
from app.services.trip_planner_service import (
    CITY_TO_IATA,
    _DEPARTURE_OFFSET_DAYS,
    _LEG_TIMEOUT_SECONDS,
    _h,
    _price_num,
    parse_budget_cents,
)

# Deterministic per-activity estimate band (minor units), keyed by a coarse
# "tier" the LLM picks. These are honest estimates, never flagged live.
_ACTIVITY_TIER_BAND: dict[str, tuple[int, int]] = {
    "free": (0, 0),
    "budget": (1500, 4000),
    "standard": (4000, 9000),
    "premium": (9000, 22000),
}
_DEFAULT_ACTIVITY_BAND = _ACTIVITY_TIER_BAND["standard"]

_SYSTEM_PROMPT = (
    "You are StayWallet's AI trip designer. Turn the user's request into a "
    "day-by-day SKELETON of a single trip. You decide the structure, the city, "
    "how many days, and what to do each day — but you NEVER state prices; real "
    "prices are filled in by the system from live data. "
    "Reply with ONLY a JSON object (no prose, no markdown) of this exact shape: "
    '{"origin": str, "destination": str, "days": int, '
    '"wantsFlight": bool, "wantsHotel": bool, '
    '"items": [ {"day": int, "kind": "restaurant"|"activity"|"transfer", '
    '"title": str, "subtitle": str, "cuisine": str|null, '
    '"activityTier": "free"|"budget"|"standard"|"premium"|null} ] }. '
    "Rules: (1) origin/destination are city names (English or as the user wrote "
    "them); if the user gives no origin, use \"Istanbul\". (2) days >= 1. "
    "(3) Every item's day is 1-based and within 1..days. (4) Use kind "
    "'restaurant' for meals (set cuisine, e.g. 'Turkish', 'seafood'), 'activity' "
    "for sights/tours/experiences (set activityTier to estimate cost; balloon "
    "rides/private tours = 'premium', museums = 'budget', a free viewpoint = "
    "'free'), 'transfer' for intra-trip rides/airport runs. (5) Honour any budget "
    "hint by keeping the plan modest, but still propose a complete trip. "
    "(6) Write title/subtitle in the SAME language the user wrote in (Turkish in "
    "-> Turkish out). (7) Do NOT include flights or the hotel stay in items; just "
    "set wantsFlight/wantsHotel — the system prices those as trip-wide items. "
    "(8) Keep it realistic: 1-3 items per day."
)

_SUMMARY_SYSTEM_PROMPT = (
    "You write a single friendly 1-2 sentence summary of a booked-ready trip "
    "itinerary for the StayWallet app. Reply in the SAME language the user wrote "
    "their request in (Turkish request -> Turkish reply). Mention the "
    "destination, the number of days and the total price exactly as given, and "
    "whether it fits the budget if a budget was provided. Be warm and concise. "
    "Return ONLY the sentence(s), no markdown."
)


class AiItineraryNotConfiguredError(Exception):
    """Raised when no OpenAI key is configured for the AI itinerary planner."""


class AiItineraryService:
    """OpenAI-designed, live-priced day-by-day itinerary planner."""

    def __init__(
        self,
        *,
        settings: Settings,
        flights: FlightService,
        hotels: HotelSearchService,
        restaurants: RestaurantService,
    ) -> None:
        self._settings = settings
        self._flights = flights
        self._hotels = hotels
        self._restaurants = restaurants

    async def plan(self, request: TripPlanRequest) -> TripPlanResponse:
        """Design + price a day-by-day itinerary for ``request.prompt``.

        Raises :class:`AiItineraryNotConfiguredError` when OpenAI is unset so the
        endpoint can fall back to the rule-based planner.
        """

        if not self._settings.openai_api_key:
            raise AiItineraryNotConfiguredError()

        client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        skeleton = await self._design_skeleton(client, request.prompt)

        origin = str(skeleton.get("origin") or "Istanbul").strip().title() or "Istanbul"
        destination = str(skeleton.get("destination") or "").strip().title()
        if not destination:
            raise AiItineraryNotConfiguredError()  # nothing to price -> fall back

        days = self._clamp_days(skeleton.get("days"))
        wants_flight = bool(skeleton.get("wantsFlight", True))
        wants_hotel = bool(skeleton.get("wantsHotel", True))
        currency = self._settings.demo_budget_currency

        outbound = date.today() + timedelta(days=_DEPARTURE_OFFSET_DAYS)
        inbound = outbound + timedelta(days=days)
        route_key = f"{origin}->{destination}"

        skeleton_items = self._normalise_items(skeleton.get("items"), days)

        # Live trip-wide lookups (flight + hotel) and per-day restaurant search,
        # concurrently. Each leg degrades to a deterministic estimate on failure.
        flight_res, hotel_res, restaurant_res = await self._fetch_live(
            origin=origin,
            destination=destination,
            outbound=outbound.isoformat(),
            inbound=inbound.isoformat(),
            currency=currency,
            wants_flight=wants_flight,
            wants_hotel=wants_hotel,
            wants_restaurant=any(i["kind"] == "restaurant" for i in skeleton_items),
        )

        items: list[TripPlanItem] = []
        if wants_flight:
            items.append(self._flight_item(origin, destination, route_key, flight_res))
        if wants_hotel:
            items.append(self._hotel_item(destination, route_key, days, hotel_res))

        for idx, spec in enumerate(skeleton_items):
            items.append(
                self._day_item(
                    spec=spec,
                    index=idx,
                    destination=destination,
                    route_key=route_key,
                    restaurant_res=restaurant_res,
                )
            )

        total = sum(i.amount_cents for i in items)
        # Mobile callers hit /trips/ai-plan without budgetCents, so an explicit
        # request budget takes precedence; otherwise parse a hint from the prompt
        # ("under €1500") and treat that number as an amount in the wallet
        # currency (no FX) — matching the rule-based planner's behaviour.
        budget_cents = request.budget_cents
        if budget_cents is None:
            budget_cents = parse_budget_cents(request.prompt)
        status = (
            "within_budget"
            if budget_cents is None or total <= budget_cents
            else "over_budget"
        )

        message = await self._summarise(
            client,
            prompt=request.prompt,
            destination=destination,
            days=days,
            total_cents=total,
            currency=currency,
            budget_cents=budget_cents,
            status=status,
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
    # OpenAI skeleton + summary
    # ------------------------------------------------------------------ #
    async def _design_skeleton(
        self, client: AsyncOpenAI, prompt: str
    ) -> dict[str, Any]:
        resp = await client.chat.completions.create(
            model=self._settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:  # malformed -> let caller fall back
            raise AiItineraryNotConfiguredError() from exc
        if not isinstance(data, dict):
            raise AiItineraryNotConfiguredError()
        return data

    async def _summarise(
        self,
        client: AsyncOpenAI,
        *,
        prompt: str,
        destination: str,
        days: int,
        total_cents: int,
        currency: str,
        budget_cents: int | None,
        status: str,
    ) -> str:
        money = f"{total_cents / 100:.0f} {currency}"
        budget_line = (
            f"Budget: {budget_cents / 100:.0f} {currency} "
            f"({'within budget' if status == 'within_budget' else 'over budget'})."
            if budget_cents is not None
            else "No budget given."
        )
        facts = (
            f"Destination: {destination}. Days: {days}. Total: {money}. "
            f"{budget_line}"
        )
        try:
            resp = await client.chat.completions.create(
                model=self._settings.openai_model,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": f"User request: {prompt}\n\n{facts}"},
                ],
                temperature=0.5,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return text
        except Exception:  # noqa: BLE001 — summary is non-critical, degrade safely
            pass
        # Deterministic fallback summary (English) if the model returns nothing.
        suffix = ""
        if budget_cents is not None:
            within = status == "within_budget"
            suffix = (
                f" — within your {budget_cents / 100:.0f} {currency} budget"
                if within
                else f", which is over your {budget_cents / 100:.0f} {currency} budget"
            )
        return (
            f"Here's a {days}-day {destination} itinerary for {money}{suffix}. "
            "Review the days and confirm to book everything in one tap."
        )

    # ------------------------------------------------------------------ #
    # Skeleton hygiene
    # ------------------------------------------------------------------ #
    @staticmethod
    def _clamp_days(value: Any) -> int:
        try:
            return max(1, min(int(value), 30))
        except (TypeError, ValueError):
            return 3

    def _normalise_items(self, raw: Any, days: int) -> list[dict[str, Any]]:
        """Coerce the LLM item list into clean per-day specs (day in 1..days)."""

        out: list[dict[str, Any]] = []
        if not isinstance(raw, list):
            return out
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            kind = str(entry.get("kind") or "").strip().lower()
            if kind not in {"restaurant", "activity", "transfer"}:
                continue
            title = str(entry.get("title") or "").strip()
            if not title:
                continue
            try:
                day = int(entry.get("day", 1))
            except (TypeError, ValueError):
                day = 1
            day = max(1, min(day, days))
            tier = str(entry.get("activityTier") or "").strip().lower()
            out.append(
                {
                    "kind": kind,
                    "title": title,
                    "subtitle": str(entry.get("subtitle") or "").strip(),
                    "cuisine": (str(entry.get("cuisine")).strip()
                                if entry.get("cuisine") else None),
                    "tier": tier if tier in _ACTIVITY_TIER_BAND else None,
                    "day": day,
                }
            )
        return out

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
        wants_flight: bool,
        wants_hotel: bool,
        wants_restaurant: bool,
    ) -> tuple[Any, Any, Any]:
        if not self._settings.serpapi_api_key:
            return None, None, None

        tasks: dict[str, Any] = {}
        if wants_flight:
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
            return None, None, None

        results = await asyncio.gather(
            *(
                asyncio.wait_for(coro, timeout=_LEG_TIMEOUT_SECONDS)
                for coro in tasks.values()
            ),
            return_exceptions=True,
        )
        mapped = dict(zip(tasks.keys(), results))
        return mapped.get("flight"), mapped.get("hotel"), mapped.get("restaurant")

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
                    day=None,
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
            day=None,
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
                subtitle = f"{night_label} · {rating:.1f}★" if rating else night_label
                return TripPlanItem(
                    kind="hotel",
                    title=str(pick["name"]),
                    subtitle=subtitle,
                    amount_cents=total_cents,
                    day=None,
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
            day=None,
            details={"nights": nights, "perNightCents": per_night, "live": False},
        )

    def _day_item(
        self,
        *,
        spec: dict[str, Any],
        index: int,
        destination: str,
        route_key: str,
        restaurant_res: Any,
    ) -> TripPlanItem:
        kind = spec["kind"]
        day = spec["day"]
        if kind == "restaurant":
            return self._restaurant_item(spec, day, destination, route_key, restaurant_res)
        if kind == "transfer":
            return TripPlanItem(
                kind="transfer",
                title=spec["title"],
                subtitle=spec["subtitle"] or "Private ride · estimated fare",
                amount_cents=_h(f"{route_key}:transfer:{index}", 1800, 4200),
                day=day,
                details={"live": False, "estimatedPrice": True},
            )
        # activity
        lo, hi = _ACTIVITY_TIER_BAND.get(spec.get("tier") or "", _DEFAULT_ACTIVITY_BAND)
        amount = 0 if hi == 0 else _h(f"{route_key}:activity:{index}", lo, hi)
        subtitle = spec["subtitle"] or "Estimated price · per person"
        return TripPlanItem(
            kind="activity",
            title=spec["title"],
            subtitle=subtitle,
            amount_cents=amount,
            day=day,
            details={
                "live": False,
                "estimatedPrice": True,
                "note": "Activity price is an estimate, not a live quote.",
                "tier": spec.get("tier") or "standard",
            },
        )

    def _restaurant_item(
        self,
        spec: dict[str, Any],
        day: int,
        destination: str,
        route_key: str,
        result: Any,
    ) -> TripPlanItem:
        cuisine = spec.get("cuisine")
        if isinstance(result, list) and result:
            top = max(result, key=lambda o: o.get("rating") or 0.0)
            name = top.get("name")
            if name:
                price_level = top.get("priceLevel") or ""
                dollars = price_level.count("$") if isinstance(price_level, str) else 0
                per_person = dollars * 3000 if dollars else 6000
                subtitle = spec["subtitle"] or "estimated · table for 2"
                return TripPlanItem(
                    kind="restaurant",
                    title=spec["title"] or f"Dinner at {name}",
                    subtitle=subtitle,
                    amount_cents=per_person * 2,
                    day=day,
                    details={
                        "live": True,
                        "estimatedPrice": True,
                        "venue": name,
                        "cuisine": cuisine,
                    },
                )
        seed = f"{route_key}:food:{cuisine or ''}:{day}"
        return TripPlanItem(
            kind="restaurant",
            title=spec["title"] or f"Signature dinner in {destination}",
            subtitle=spec["subtitle"] or "Table for 2 · chef's menu",
            amount_cents=_h(seed, 5000, 9000),
            day=day,
            details={"live": False, "cuisine": cuisine},
        )
