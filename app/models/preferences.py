"""Pydantic schema for habit-aware travel preferences.

These are the traveller's saved habits (home city/airport, preferred cabin,
hotel tier, dietary needs, language, currency, …). They are persisted on
``users.preferences`` and fed to the AI concierge as *soft* defaults so plans
adapt to how the user usually travels.

Everything is optional: the mobile app may send any subset on ``PUT`` and the
``GET`` always returns the full shape (camelCase) with sensible empty defaults.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Allowed enum values (lower-cased on input; unknown values are rejected).
_CABINS = {"economy", "premium_economy", "business", "first"}
_HOTEL_TIERS = {"budget", "standard", "luxury"}
_SEAT_PREFERENCES = {"window", "aisle", "no_preference"}

_MAX_LIST_ITEMS = 20
_MAX_ITEM_LEN = 80
_MAX_NOTES_LEN = 500


def _clean_str(value: str | None, *, max_len: int) -> str | None:
    """Trim a free-text string, clipping to ``max_len`` and dropping blanks."""

    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed[:max_len]


def _clean_str_list(value: list[str] | None) -> list[str]:
    """Normalise a list of short strings (trim, drop blanks/dupes, clip)."""

    if not value:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        trimmed = item.strip()[:_MAX_ITEM_LEN]
        if not trimmed:
            continue
        key = trimmed.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(trimmed)
        if len(cleaned) >= _MAX_LIST_ITEMS:
            break
    return cleaned


def _validate_enum(value: str | None, allowed: set[str], label: str) -> str | None:
    """Lower-case and validate an optional enum-like string."""

    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized not in allowed:
        raise ValueError(
            f"{label} must be one of: {', '.join(sorted(allowed))}."
        )
    return normalized


class TravelPreferences(BaseModel):
    """The traveller's habit-aware travel preferences (all fields optional).

    Used for BOTH the ``GET``/``PUT`` response and the ``PUT`` request body.
    Unknown fields are ignored; enums are validated and free-text is clipped.
    """

    home_city: str | None = Field(default=None, alias="homeCity")
    home_airport: str | None = Field(default=None, alias="homeAirport")
    preferred_cabin: str | None = Field(default=None, alias="preferredCabin")
    hotel_tier: str | None = Field(default=None, alias="hotelTier")
    seat_preference: str | None = Field(default=None, alias="seatPreference")
    dietary: list[str] = Field(default_factory=list)
    language: str | None = Field(default=None)
    currency: str | None = Field(default=None)
    interests: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None)

    # Accept camelCase (from the app) or snake_case; ignore unknown keys.
    model_config = ConfigDict(
        populate_by_name=True, from_attributes=True, extra="ignore"
    )

    @field_validator("home_city", "home_airport", "language", "currency")
    @classmethod
    def _trim_short(cls, value: str | None) -> str | None:
        return _clean_str(value, max_len=_MAX_ITEM_LEN)

    @field_validator("notes")
    @classmethod
    def _trim_notes(cls, value: str | None) -> str | None:
        return _clean_str(value, max_len=_MAX_NOTES_LEN)

    @field_validator("preferred_cabin")
    @classmethod
    def _validate_cabin(cls, value: str | None) -> str | None:
        return _validate_enum(value, _CABINS, "preferredCabin")

    @field_validator("hotel_tier")
    @classmethod
    def _validate_hotel_tier(cls, value: str | None) -> str | None:
        return _validate_enum(value, _HOTEL_TIERS, "hotelTier")

    @field_validator("seat_preference")
    @classmethod
    def _validate_seat(cls, value: str | None) -> str | None:
        return _validate_enum(value, _SEAT_PREFERENCES, "seatPreference")

    @field_validator("dietary", "interests", mode="before")
    @classmethod
    def _validate_lists(cls, value: list[str] | None) -> list[str]:
        return _clean_str_list(value)

    def to_storage(self) -> dict:
        """Serialise to the camelCase dict persisted on ``users.preferences``."""

        return self.model_dump(by_alias=True)
