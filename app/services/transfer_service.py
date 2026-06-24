"""Transfers (Uber Guest Trips) and Tier-style scooters.

Providers (``STAYWALLET_TRANSFER_PROVIDER``):

- ``mock`` (default): deterministic ride options, simulated driver tracking
  (progress derived from elapsed time since booking) and a scooter fleet, all
  flagged ``sandbox=True``.
- ``uber``: LIVE adapter for the Uber Guest Trips API (OAuth client
  credentials, ``guests.trips`` scope). Estimates use
  ``POST /v1/guests/trips/estimates`` and booking uses
  ``POST /v1/guests/trips``. Tracking polls ``GET /v1/guests/trips/{id}``
  while the app UI keeps its existing 3-second polling cadence.

Tier has no public API, so scooters are always sandbox.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import Settings
from app.models.market import (
    ScooterOffer,
    TransferBooking,
    TransferDriver,
    TransferOption,
    TransferTrack,
)

_TIMEOUT = httpx.Timeout(15.0)

# App-level OAuth (client_credentials) token cache, keyed by client_id so a
# config change invalidates it. Value is (access_token, monotonic_expiry). The
# cache is process-wide because TransferService is created per request; a 60s
# safety margin avoids using a token that expires mid-flight.
_UBER_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_UBER_TOKEN_MARGIN = 60.0

_DEFAULT_LAT, _DEFAULT_LNG = 25.2048, 55.2708
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class TransferSearchError(Exception):
    """Upstream transfer-search failure."""


class TransferProviderNotConfiguredError(Exception):
    """A live transfer provider is selected but its credentials are missing."""

    def __init__(self, missing: str) -> None:
        self.missing = missing
        super().__init__(f"Missing {missing}")


@dataclass(slots=True)
class LiveTrip:
    provider_trip_id: str
    status: str
    status_label: str | None
    eta_minutes: int
    driver: TransferDriver
    details: dict[str, Any]


_DRIVERS = [
    TransferDriver(name="Marco Rossi", rating=4.95, vehicle="Toyota Camry", plate="ABC-1234"),
    TransferDriver(name="Ayşe Demir", rating=4.91, vehicle="Skoda Superb", plate="34 TR 7821"),
    TransferDriver(name="Omar Haddad", rating=4.88, vehicle="Lexus ES", plate="D 48127"),
]

# A simulated ride lasts this long end-to-end (assign -> arrive -> ride -> done).
_RIDE_DURATION = timedelta(minutes=18)
_PICKUP_PHASE = timedelta(minutes=4)


def _stable_index(key: str, modulo: int) -> int:
    digest = hashlib.sha256(key.encode()).digest()
    return digest[0] % modulo


class TransferService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def provider(self) -> str:
        return self._settings.transfer_provider

    @property
    def sandbox(self) -> bool:
        return self._settings.transfer_provider == "mock"

    async def search(
        self,
        *,
        pickup: str,
        destination: str,
        pickup_lat: float | None = None,
        pickup_lng: float | None = None,
        destination_lat: float | None = None,
        destination_lng: float | None = None,
    ) -> list[TransferOption]:
        if self._settings.transfer_provider == "uber":
            return await self._search_uber_live(
                pickup=pickup,
                destination=destination,
                pickup_lat=pickup_lat,
                pickup_lng=pickup_lng,
                destination_lat=destination_lat,
                destination_lng=destination_lng,
            )
        # Base fare scales mildly with the route so different searches differ.
        base = 1800 + _stable_index(f"{pickup}->{destination}", 12) * 100
        now = datetime.now(timezone.utc)

        def arrival(minutes: int) -> str:
            return (now + timedelta(minutes=minutes)).strftime("%H:%M")

        return [
            TransferOption(
                id="ride_x",
                service="UberX",
                description="Affordable, everyday rides",
                eta_minutes=3,
                arrival_label=arrival(24),
                price_cents=base,
                seats=4,
                points_label="+25 StayPoints",
            ),
            TransferOption(
                id="ride_comfort",
                service="Comfort",
                description="Newer cars with extra legroom",
                eta_minutes=5,
                arrival_label=arrival(27),
                price_cents=int(base * 1.35),
                seats=4,
                badge="POPULAR",
                points_label="+40 StayPoints",
            ),
            TransferOption(
                id="ride_black",
                service="Black",
                description="Premium rides in luxury cars",
                eta_minutes=8,
                arrival_label=arrival(31),
                price_cents=int(base * 2.2),
                seats=4,
                points_label="+80 StayPoints",
            ),
        ]

    # ── Uber OAuth 2.0 ────────────────────────────────────────────────────
    async def _uber_access_token(self) -> str:
        """Return a Bearer token for the Uber API.

        Tries a legacy server token, then a pasted-in access token, then an
        OAuth ``client_credentials`` token (minted and cached until expiry).
        Raises :class:`TransferProviderNotConfiguredError` when no usable
        credential is set, naming what to provide.
        """

        settings = self._settings
        if settings.uber_server_token:
            return settings.uber_server_token
        if settings.uber_access_token:
            return settings.uber_access_token
        if not (settings.uber_client_id and settings.uber_client_secret):
            raise TransferProviderNotConfiguredError(
                "UBER_ACCESS_TOKEN or UBER_CLIENT_ID/UBER_CLIENT_SECRET"
            )

        cached = _UBER_TOKEN_CACHE.get(settings.uber_client_id)
        if cached and cached[1] > time.monotonic():
            return cached[0]

        data = {
            "client_id": settings.uber_client_id,
            "client_secret": settings.uber_client_secret,
            "grant_type": "client_credentials",
            "scope": settings.uber_oauth_scopes,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(settings.uber_oauth_token_url, data=data)
        except httpx.HTTPError as exc:
            raise TransferSearchError(f"Uber OAuth: {exc}") from exc
        if resp.status_code != 200:
            raise TransferSearchError(
                f"Uber OAuth {resp.status_code}: {resp.text[:200]}"
            )
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise TransferSearchError("Uber OAuth: no access_token in response")
        expires_in = float(payload.get("expires_in") or 0)
        _UBER_TOKEN_CACHE[settings.uber_client_id] = (
            token,
            time.monotonic() + max(expires_in - _UBER_TOKEN_MARGIN, 0.0),
        )
        return token

    async def _uber_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = await self._uber_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept-Language": "en_US",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.request(
                    method=method,
                    url=f"{self._settings.uber_api_base_url}{path}",
                    params=params,
                    json=json,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise TransferSearchError(f"Uber API request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise TransferSearchError(
                f"Uber API {resp.status_code}: {resp.text[:300]}"
            )
        payload = resp.json()
        if not isinstance(payload, dict):
            raise TransferSearchError("Uber API returned an unexpected payload.")
        return payload

    async def _resolve_coords(
        self, label: str, *, lat: float | None, lng: float | None
    ) -> tuple[float, float]:
        if lat is not None and lng is not None:
            return lat, lng
        query = label.strip()
        if not query:
            return _DEFAULT_LAT, _DEFAULT_LNG
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    _NOMINATIM_URL,
                    params={"q": query, "format": "jsonv2", "limit": "1"},
                    headers={"User-Agent": "StayWallet/1.0 (travel app)"},
                )
        except httpx.HTTPError as exc:
            raise TransferSearchError(
                "Location lookup failed before contacting Uber."
            ) from exc
        if resp.status_code != 200:
            raise TransferSearchError(
                f"Location lookup error {resp.status_code}."
            )
        results = resp.json()
        if not isinstance(results, list) or not results:
            raise TransferSearchError(
                f"Could not resolve '{query}' to map coordinates."
            )
        hit = results[0]
        try:
            return float(hit["lat"]), float(hit["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TransferSearchError(
                f"Location lookup returned invalid coordinates for '{query}'."
            ) from exc

    def _coerce_eta(self, value: Any, *, fallback: int) -> int:
        if isinstance(value, (int, float)):
            seconds = int(value)
            if seconds > 240:
                return max(1, round(seconds / 60))
            return max(1, seconds)
        return fallback

    def _coerce_money_cents(self, raw: Any) -> int:
        if isinstance(raw, dict):
            if isinstance(raw.get("value"), (int, float)):
                value = float(raw["value"])
                if value > 1000:
                    return int(round(value))
                return int(round(value * 100))
            if isinstance(raw.get("amount"), (int, float)):
                value = float(raw["amount"])
                if value > 1000:
                    return int(round(value))
                return int(round(value * 100))
            low = raw.get("low_estimate")
            high = raw.get("high_estimate")
            if isinstance(low, (int, float)) and isinstance(high, (int, float)):
                return int(round(((float(low) + float(high)) / 2) * 100))
            for key in ("estimate", "amount_estimate"):
                if isinstance(raw.get(key), (int, float)):
                    return int(round(float(raw[key]) * 100))
        if isinstance(raw, (int, float)):
            return int(round(float(raw) * 100))
        return 0

    def _extract_currency(self, *candidates: Any) -> str:
        for candidate in candidates:
            if isinstance(candidate, dict):
                for key in ("currency_code", "currencyCode", "currency"):
                    value = candidate.get(key)
                    if isinstance(value, str) and value:
                        return value
            if isinstance(candidate, str) and candidate:
                return candidate
        return "USD"

    def _estimate_items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("products", "product_estimates", "trip_estimates", "estimates"):
            items = payload.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return []

    def _driver_from_payload(
        self,
        payload: dict[str, Any],
        *,
        fallback_key: str,
        fallback_vehicle: str,
    ) -> TransferDriver:
        driver = payload.get("driver") if isinstance(payload.get("driver"), dict) else {}
        vehicle = (
            payload.get("vehicle")
            if isinstance(payload.get("vehicle"), dict)
            else {}
        )
        name = str(
            driver.get("name")
            or " ".join(
                part
                for part in (
                    driver.get("first_name"),
                    driver.get("last_name"),
                )
                if isinstance(part, str) and part
            ).strip()
            or "Driver assigned"
        )
        rating = driver.get("rating")
        try:
            rating_value = float(rating) if rating is not None else 4.8
        except (TypeError, ValueError):
            rating_value = 4.8
        return TransferDriver(
            name=name,
            rating=rating_value,
            vehicle=str(
                vehicle.get("display_name")
                or vehicle.get("make_model")
                or fallback_vehicle
            ),
            plate=str(vehicle.get("license_plate") or vehicle.get("plate") or "Pending"),
        )

    def _map_status(self, raw_status: str | None) -> tuple[str, float]:
        status = (raw_status or "").strip().lower()
        if status in {"completed", "droppedoff", "finished"}:
            return "completed", 1.0
        if status in {"on_trip", "in_progress", "en_route_to_dropoff"}:
            return "in_progress", 0.65
        if status in {"canceled", "cancelled"}:
            return "cancelled", 1.0
        if status in {"accepted", "arriving", "en_route_to_pickup", "processing"}:
            return "arriving", 0.2
        return "arriving", 0.1

    # ── Uber Guest Trips API (live) ────────────────────────────────────────
    async def _search_uber_live(
        self,
        *,
        pickup: str,
        destination: str,
        pickup_lat: float | None,
        pickup_lng: float | None,
        destination_lat: float | None,
        destination_lng: float | None,
    ) -> list[TransferOption]:
        """`POST /trips/estimates` mapped onto :class:`TransferOption`."""

        p_lat, p_lng = await self._resolve_coords(
            pickup, lat=pickup_lat, lng=pickup_lng
        )
        d_lat, d_lng = await self._resolve_coords(
            destination, lat=destination_lat, lng=destination_lng
        )
        payload = await self._uber_request(
            "POST",
            "/trips/estimates",
            json={
                "pickup_location": {
                    "latitude": p_lat,
                    "longitude": p_lng,
                    "address": pickup,
                },
                "dropoff_location": {
                    "latitude": d_lat,
                    "longitude": d_lng,
                    "address": destination,
                },
            },
        )
        now = datetime.now(timezone.utc)
        options: list[TransferOption] = []
        for i, product in enumerate(self._estimate_items(payload)):
            display_name = str(
                product.get("display_name")
                or product.get("product_name")
                or product.get("name")
                or "Uber"
            )
            eta = self._coerce_eta(
                product.get("pickup_estimate")
                or product.get("eta")
                or product.get("pickup_eta"),
                fallback=3 + i * 2,
            )
            fare = product.get("fare") or product.get("fare_estimate") or {}
            price_cents = self._coerce_money_cents(fare)
            if price_cents <= 0:
                price_cents = self._coerce_money_cents(
                    product.get("price")
                    or product.get("fare_estimate")
                    or product.get("estimate")
                )
            options.append(
                TransferOption(
                    id=str(
                        product.get("product_type_id")
                        or product.get("product_id")
                        or product.get("parent_product_type_id")
                        or f"uber_{i}"
                    ),
                    service=display_name,
                    description=str(
                        product.get("short_description")
                        or product.get("description")
                        or ""
                    ),
                    eta_minutes=eta,
                    arrival_label=(now + timedelta(minutes=eta + 20)).strftime(
                        "%H:%M"
                    ),
                    price_cents=price_cents,
                    currency=self._extract_currency(fare, product.get("currency")),
                    seats=int(product.get("capacity") or 4),
                    fare_id=(
                        str(product.get("fare_id"))
                        if product.get("fare_id") is not None
                        else (
                            str(fare.get("fare_id"))
                            if isinstance(fare, dict) and fare.get("fare_id") is not None
                            else None
                        )
                    ),
                    badge="POPULAR"
                    if str(product.get("product_group") or "").lower() == "uberx"
                    else None,
                    no_cars_available=bool(product.get("no_cars_available") is True),
                )
            )
        return options

    async def book_live_trip(
        self,
        *,
        option: TransferOption,
        pickup: str,
        destination: str,
        pickup_lat: float | None,
        pickup_lng: float | None,
        destination_lat: float | None,
        destination_lng: float | None,
        fare_id: str | None,
        guest_name: str,
        guest_phone_number: str | None,
    ) -> LiveTrip:
        if self.sandbox:
            raise TransferSearchError("Live trip booking is unavailable in sandbox mode.")
        if not guest_phone_number:
            raise TransferSearchError(
                "Your account needs a phone number before Uber can confirm a ride."
            )
        p_lat, p_lng = await self._resolve_coords(
            pickup, lat=pickup_lat, lng=pickup_lng
        )
        d_lat, d_lng = await self._resolve_coords(
            destination, lat=destination_lat, lng=destination_lng
        )
        parts = [part for part in guest_name.strip().split() if part]
        first_name = parts[0] if parts else "Guest"
        last_name = " ".join(parts[1:]) if len(parts) > 1 else "StayWallet"
        request_body: dict[str, Any] = {
            "guest": {
                "first_name": first_name,
                "last_name": last_name,
                "phone_number": guest_phone_number,
                "locale": "en_US",
            },
            "pickup_location": {
                "latitude": p_lat,
                "longitude": p_lng,
                "address": pickup,
            },
            "dropoff_location": {
                "latitude": d_lat,
                "longitude": d_lng,
                "address": destination,
            },
            "product_type_id": option.id,
            "expense_memo": f"StayWallet ride · {pickup} → {destination}",
            "sender_display_name": "StayWallet",
            "call_enabled": True,
        }
        if fare_id:
            request_body["fare_id"] = fare_id
        payload = await self._uber_request("POST", "/trips", json=request_body)
        trip_id = str(
            payload.get("request_id")
            or payload.get("trip_id")
            or payload.get("id")
            or ""
        ).strip()
        if not trip_id:
            raise TransferSearchError("Uber trip created but no trip id was returned.")
        raw_status = str(payload.get("status") or "accepted")
        status, _progress = self._map_status(raw_status)
        eta = self._coerce_eta(
            payload.get("pickup_estimate")
            or payload.get("eta")
            or payload.get("pickup_eta"),
            fallback=option.eta_minutes,
        )
        driver = self._driver_from_payload(
            payload,
            fallback_key=trip_id,
            fallback_vehicle=option.service,
        )
        return LiveTrip(
            provider_trip_id=trip_id,
            status=status,
            status_label=str(payload.get("status") or "").strip() or None,
            eta_minutes=eta,
            driver=driver,
            details={
                "provider": "uber",
                "providerTripId": trip_id,
                "fareId": fare_id,
                "pickupLat": p_lat,
                "pickupLng": p_lng,
                "destinationLat": d_lat,
                "destinationLng": d_lng,
                "status": raw_status,
                "resourceHref": payload.get("resource_href"),
            },
        )

    def driver_for(self, booking_id: str) -> TransferDriver:
        return _DRIVERS[_stable_index(booking_id, len(_DRIVERS))]

    def track(
        self, *, booking_id: str, booked_at: datetime
    ) -> tuple[str, float, int]:
        """Return (status, progress 0..1, eta_minutes) from elapsed wall time."""

        if booked_at.tzinfo is None:
            booked_at = booked_at.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - booked_at
        if elapsed < _PICKUP_PHASE:
            remaining = _PICKUP_PHASE - elapsed
            return (
                "arriving",
                min(elapsed / _PICKUP_PHASE, 1.0) * 0.2,
                max(1, int(remaining.total_seconds() // 60) + 1),
            )
        ride_elapsed = elapsed - _PICKUP_PHASE
        ride_span = _RIDE_DURATION - _PICKUP_PHASE
        if ride_elapsed < ride_span:
            frac = ride_elapsed / ride_span
            remaining = ride_span - ride_elapsed
            return (
                "in_progress",
                0.2 + frac * 0.8,
                max(1, int(remaining.total_seconds() // 60) + 1),
            )
        return ("completed", 1.0, 0)

    async def track_booking(
        self,
        *,
        booking_id: str,
        booked_at: datetime,
        purchase_details: dict[str, Any],
    ) -> TransferTrack:
        provider_trip_id = purchase_details.get("providerTripId")
        if self.sandbox or not isinstance(provider_trip_id, str) or not provider_trip_id:
            status_label, progress, eta = self.track(
                booking_id=booking_id, booked_at=booked_at
            )
            return TransferTrack(
                booking_id=booking_id,
                status=status_label,
                progress=progress,
                eta_minutes=eta,
                driver=self.driver_for(booking_id),
                status_label=None,
            )

        payload = await self._uber_request("GET", f"/trips/{provider_trip_id}")
        raw_status = str(payload.get("status") or "accepted")
        status, progress = self._map_status(raw_status)
        eta = self._coerce_eta(
            payload.get("pickup_estimate")
            or payload.get("eta")
            or payload.get("pickup_eta"),
            fallback=5,
        )
        driver = self._driver_from_payload(
            payload,
            fallback_key=provider_trip_id,
            fallback_vehicle=str(
                purchase_details.get("service") or payload.get("product_name") or "Uber"
            ),
        )
        return TransferTrack(
            booking_id=booking_id,
            status=status,
            progress=progress,
            eta_minutes=eta,
            driver=driver,
            status_label=raw_status,
        )

    async def scooters(self, *, near: str) -> list[ScooterOffer]:
        seed = near.strip().lower() or "downtown"
        out: list[ScooterOffer] = []
        for i in range(6):
            key = f"{seed}:{i}"
            out.append(
                ScooterOffer(
                    id=f"sc_{hashlib.sha256(key.encode()).hexdigest()[:8]}",
                    model="Tier-5 Gen 3" if i % 2 == 0 else "Tier-4 Gen 2",
                    battery_pct=55 + _stable_index(key, 45),
                    distance_meters=80 + _stable_index(key + "d", 9) * 60,
                    unlock_fee_cents=100,
                    per_minute_cents=35,
                    bonus_label="10% STAYWALLET POINTS BONUS",
                )
            )
        return out

    async def get_scooter(self, scooter_id: str, *, near: str) -> ScooterOffer | None:
        for s in await self.scooters(near=near):
            if s.id == scooter_id:
                return s
        return None
