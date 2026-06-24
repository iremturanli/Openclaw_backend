"""Travel Services & Loyalty schemas.

Conform to ``docs/api_contract.md`` → "Travel Services & Loyalty". camelCase
aliases match the Flutter data layer; all money stays integer cents.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ServiceCategory(BaseModel):
    """A bookable travel-service category."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., examples=["rental_car"])
    name: str = Field(..., examples=["Rental Car"])
    subtitle: str = Field(..., examples=["Luxury & economy options"])
    icon: str = Field(..., examples=["directions_car"])
    # accent ∈ blue | emerald | orange | purple | amber
    accent: str = Field(..., examples=["blue"])
    featured: bool = Field(default=False, examples=[False])


class FeaturedDeal(BaseModel):
    """A promoted partner deal."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., examples=["porsche_911"])
    title: str = Field(..., examples=["Porsche 911 Carrera S"])
    subtitle: str = Field(..., examples=["Exotic Rental Experience"])
    image_url: str = Field(..., alias="imageUrl", examples=["https://..."])
    badge: str = Field(..., examples=["Partner Spotlight"])
    discount_label: str = Field(..., alias="discountLabel", examples=["-15% OFF"])
    discount_note: str = Field(
        ..., alias="discountNote", examples=["with StayWallet card"]
    )


class LoyaltyBalance(BaseModel):
    """A guest's loyalty balance, derived from the ledger."""

    model_config = ConfigDict(populate_by_name=True)

    points: int = Field(..., examples=[12450])
    multiplier_label: str = Field(..., alias="multiplierLabel", examples=["3x"])
    note: str = Field(
        ...,
        examples=["Use points to cover up to 50% of your rental car or dining bill."],
    )


class BookingRequest(BaseModel):
    """POST body for creating a travel booking.

    Exactly one of ``categoryId`` / ``dealId`` must be supplied; supplying
    neither raises a validation error (HTTP 422).
    """

    model_config = ConfigDict(populate_by_name=True)

    guest_id: str = Field(..., alias="guestId", min_length=1, examples=["guest_demo"])
    category_id: str | None = Field(
        default=None, alias="categoryId", examples=["rental_car"]
    )
    deal_id: str | None = Field(default=None, alias="dealId", examples=["porsche_911"])

    @model_validator(mode="after")
    def _require_one_target(self) -> "BookingRequest":
        if not self.category_id and not self.deal_id:
            raise ValueError("Either categoryId or dealId must be provided.")
        return self


class BookingConfirmation(BaseModel):
    """Result of a travel booking, including loyalty points awarded."""

    model_config = ConfigDict(populate_by_name=True)

    booking_id: str = Field(..., alias="bookingId", examples=["bk_123"])
    title: str = Field(..., examples=["Rental Car"])
    points_earned: int = Field(..., alias="pointsEarned", examples=[450])
    new_balance: int = Field(..., alias="newBalance", examples=[12900])
