"""Schemas for the travel marketplace: cars, transfers, scooters, restaurants,
trip plans and the partner/commission admin surface.

All wire fields use camelCase aliases (``populate_by_name=True``), matching the
budget/purchase schemas in :mod:`app.models.travel_wallet`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Cars
# --------------------------------------------------------------------------- #
class CarOffer(BaseModel):
    id: str
    partner: str = "Sixt"
    name: str
    category: str
    seats: int
    bags: int
    transmission: str = "Automatic"
    fuel: str = "Petrol"
    price_per_day_cents: int = Field(..., alias="pricePerDayCents")
    currency: str = "USD"
    rating: float = 4.8
    image: str | None = None
    pickup_location: str = Field(default="", alias="pickupLocation")
    badge: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class CarSearchResponse(BaseModel):
    provider: str
    sandbox: bool = True
    offers: list[CarOffer] = Field(default_factory=list)


class CarBookRequest(BaseModel):
    offer_id: str = Field(..., alias="offerId")
    days: int = Field(default=1, ge=1, le=60)
    pickup: str = ""
    dropoff: str = ""
    pickup_date: str = Field(default="", alias="pickupDate")

    model_config = ConfigDict(populate_by_name=True)


# --------------------------------------------------------------------------- #
# Transfers (Uber-style rides) + scooters
# --------------------------------------------------------------------------- #
class TransferOption(BaseModel):
    id: str
    service: str
    description: str = ""
    eta_minutes: int = Field(..., alias="etaMinutes")
    arrival_label: str = Field(default="", alias="arrivalLabel")
    price_cents: int = Field(..., alias="priceCents")
    currency: str = "USD"
    seats: int = 4
    fare_id: str | None = Field(default=None, alias="fareId")
    badge: str | None = None
    no_cars_available: bool = Field(default=False, alias="noCarsAvailable")
    points_label: str | None = Field(default=None, alias="pointsLabel")

    model_config = ConfigDict(populate_by_name=True)


class TransferSearchResponse(BaseModel):
    provider: str
    sandbox: bool = True
    pickup: str
    destination: str
    options: list[TransferOption] = Field(default_factory=list)


class TransferBookRequest(BaseModel):
    option_id: str = Field(..., alias="optionId")
    pickup: str = ""
    destination: str = ""
    pickup_lat: float | None = Field(default=None, alias="pickupLat")
    pickup_lng: float | None = Field(default=None, alias="pickupLng")
    destination_lat: float | None = Field(default=None, alias="destinationLat")
    destination_lng: float | None = Field(default=None, alias="destinationLng")
    fare_id: str | None = Field(default=None, alias="fareId")

    model_config = ConfigDict(populate_by_name=True)


class TransferDriver(BaseModel):
    name: str
    rating: float
    vehicle: str
    plate: str

    model_config = ConfigDict(populate_by_name=True)


class TransferBooking(BaseModel):
    booking_id: str = Field(..., alias="bookingId")
    provider_trip_id: str | None = Field(default=None, alias="providerTripId")
    service: str
    pickup: str
    destination: str
    price_cents: int = Field(..., alias="priceCents")
    currency: str
    driver: TransferDriver
    eta_minutes: int = Field(..., alias="etaMinutes")
    status: str = "arriving"
    status_label: str | None = Field(default=None, alias="statusLabel")
    balance_cents: int = Field(..., alias="balanceCents")

    model_config = ConfigDict(populate_by_name=True)


class TransferTrack(BaseModel):
    booking_id: str = Field(..., alias="bookingId")
    status: str  # driver_assigned | arriving | in_progress | completed
    progress: float = Field(..., ge=0.0, le=1.0)
    eta_minutes: int = Field(..., alias="etaMinutes")
    driver: TransferDriver
    status_label: str | None = Field(default=None, alias="statusLabel")

    model_config = ConfigDict(populate_by_name=True)


class ScooterOffer(BaseModel):
    id: str
    model: str
    battery_pct: int = Field(..., alias="batteryPct")
    distance_meters: int = Field(..., alias="distanceMeters")
    unlock_fee_cents: int = Field(..., alias="unlockFeeCents")
    per_minute_cents: int = Field(..., alias="perMinuteCents")
    currency: str = "USD"
    bonus_label: str | None = Field(default=None, alias="bonusLabel")

    model_config = ConfigDict(populate_by_name=True)


class ScooterUnlockResponse(BaseModel):
    ride_id: str = Field(..., alias="rideId")
    model: str
    unlock_fee_cents: int = Field(..., alias="unlockFeeCents")
    per_minute_cents: int = Field(..., alias="perMinuteCents")
    currency: str
    balance_cents: int = Field(..., alias="balanceCents")

    model_config = ConfigDict(populate_by_name=True)


# --------------------------------------------------------------------------- #
# Restaurants
# --------------------------------------------------------------------------- #
class RestaurantSearchResponse(BaseModel):
    provider: str
    sandbox: bool
    options: list[dict[str, Any]] = Field(default_factory=list)


class BookTableRequest(BaseModel):
    restaurant_name: str = Field(..., alias="restaurantName", min_length=1)
    guests: int = Field(default=2, ge=1, le=20)
    date: str
    time: str
    note: str = ""
    deposit_cents: int = Field(default=0, alias="depositCents", ge=0)
    currency: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class BookTableResponse(BaseModel):
    booking_id: str = Field(..., alias="bookingId")
    restaurant_name: str = Field(..., alias="restaurantName")
    guests: int
    date: str
    time: str
    points_earned: int = Field(..., alias="pointsEarned")
    balance_cents: int = Field(..., alias="balanceCents")

    model_config = ConfigDict(populate_by_name=True)


# --------------------------------------------------------------------------- #
# Trip planner (AI concierge confirm flow)
# --------------------------------------------------------------------------- #
class TripPlanRequest(BaseModel):
    prompt: str = Field(..., min_length=3)
    budget_cents: int | None = Field(default=None, alias="budgetCents")

    model_config = ConfigDict(populate_by_name=True)


class TripPlanItem(BaseModel):
    kind: str  # flight | hotel | restaurant | transfer | activity
    title: str
    subtitle: str = ""
    amount_cents: int = Field(..., alias="amountCents")
    # 1-based day index for per-day items (restaurants, activities, transfers).
    # ``None`` marks trip-wide items (flights, the whole hotel stay). Additive;
    # omitting it keeps /trips/plan and /trips/confirm fully backwards-compatible.
    day: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class TripPlan(BaseModel):
    origin: str
    destination: str
    items: list[TripPlanItem] = Field(default_factory=list)
    total_cents: int = Field(..., alias="totalCents")
    currency: str
    budget_cents: int | None = Field(default=None, alias="budgetCents")
    budget_status: str = Field(..., alias="budgetStatus")  # within_budget | over_budget

    model_config = ConfigDict(populate_by_name=True)


class TripPlanResponse(BaseModel):
    message: str
    intent: str = "trip_plan"
    trip_plan: TripPlan | None = Field(default=None, alias="tripPlan")
    requires_confirmation: bool = Field(default=True, alias="requiresConfirmation")
    confirmation_action: str = Field(
        default="confirm_trip_booking", alias="confirmationAction"
    )

    model_config = ConfigDict(populate_by_name=True)


class TripConfirmRequest(BaseModel):
    trip_plan: TripPlan = Field(..., alias="tripPlan")

    model_config = ConfigDict(populate_by_name=True)


class TripConfirmResponse(BaseModel):
    booking_ids: list[str] = Field(default_factory=list, alias="bookingIds")
    total_cents: int = Field(..., alias="totalCents")
    currency: str
    balance_cents: int = Field(..., alias="balanceCents")

    model_config = ConfigDict(populate_by_name=True)


# --------------------------------------------------------------------------- #
# Digital room keys (issued from hotel bookings)
# --------------------------------------------------------------------------- #
class RoomKeyRequest(BaseModel):
    purchase_id: str = Field(..., alias="purchaseId", min_length=1)

    model_config = ConfigDict(populate_by_name=True)


class RoomKeyOut(BaseModel):
    key_id: str = Field(..., alias="keyId")
    property_name: str = Field(..., alias="propertyName")
    room_number: str = Field(..., alias="roomNumber")
    access_token: str = Field(..., alias="accessToken")
    valid_from: str = Field(..., alias="validFrom")
    valid_until: str = Field(..., alias="validUntil")

    model_config = ConfigDict(populate_by_name=True)


# --------------------------------------------------------------------------- #
# Partners / commission HQ
# --------------------------------------------------------------------------- #
class PartnerRow(BaseModel):
    name: str
    category: str
    commission_pct: float = Field(..., alias="commissionPct")
    plan: str
    earnings_cents: int = Field(..., alias="earningsCents")
    revenue_cents: int = Field(..., alias="revenueCents")

    model_config = ConfigDict(populate_by_name=True)


class CommissionOverview(BaseModel):
    avg_commission_pct: float = Field(..., alias="avgCommissionPct")
    total_earnings_cents: int = Field(..., alias="totalEarningsCents")
    partners_count: int = Field(..., alias="partnersCount")
    currency: str = "EUR"
    tiers: list[dict[str, Any]] = Field(default_factory=list)
    partners: list[PartnerRow] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class ProviderStatus(BaseModel):
    key: str
    label: str
    provider: str
    live: bool
    missing: list[str] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class OnboardingPreviewRequest(BaseModel):
    commission_pct: float = Field(..., alias="commissionPct", ge=0, le=50)
    monthly_gross_cents: int = Field(..., alias="monthlyGrossCents", ge=0)

    model_config = ConfigDict(populate_by_name=True)


class OnboardingPreviewResponse(BaseModel):
    gross_cents: int = Field(..., alias="grossCents")
    commission_cents: int = Field(..., alias="commissionCents")
    projected_net_cents: int = Field(..., alias="projectedNetCents")
    currency: str = "USD"

    model_config = ConfigDict(populate_by_name=True)
