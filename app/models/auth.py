"""Pydantic schemas for authentication endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

_PHONE_CHARS = set("0123456789+ -()")
_EMAIL_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-@"
)


def _normalize_phone(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


def _validate_phone(value: str | None) -> str | None:
    normalized = _normalize_phone(value)
    if normalized is None:
        return None
    if not (7 <= len(normalized) <= 32):
        raise ValueError("Phone number must be 7-32 characters long.")
    if any(ch not in _PHONE_CHARS for ch in normalized):
        raise ValueError("Phone number contains unsupported characters.")
    digits = sum(ch.isdigit() for ch in normalized)
    if digits < 7:
        raise ValueError("Phone number must include at least 7 digits.")
    return normalized


def _validate_email(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or "@" not in normalized:
        raise ValueError("Enter a valid email address.")
    if any(ch not in _EMAIL_CHARS for ch in normalized):
        raise ValueError("Email address contains unsupported characters.")
    local, _, domain = normalized.partition("@")
    if not local or "." not in domain:
        raise ValueError("Enter a valid email address.")
    return normalized


class RegisterRequest(BaseModel):
    """Sign-up payload."""

    email: str
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=255, alias="fullName")
    phone_number: str | None = Field(
        default=None, max_length=32, alias="phoneNumber"
    )

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str | None) -> str | None:
        return _validate_phone(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_email(value)


class LoginRequest(BaseModel):
    """Sign-in payload."""

    email: str
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_email(value)


class UserOut(BaseModel):
    """Public user representation."""

    id: str
    email: str
    full_name: str = Field(..., alias="fullName")
    phone_number: str | None = Field(default=None, alias="phoneNumber")
    guest_id: str = Field(..., alias="guestId")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class AuthResponse(BaseModel):
    """Returned by register & login: the user plus a token pair."""

    user: UserOut
    access_token: str = Field(..., alias="accessToken")
    refresh_token: str = Field(..., alias="refreshToken")
    token_type: str = Field(default="bearer", alias="tokenType")

    model_config = ConfigDict(populate_by_name=True)


class RefreshRequest(BaseModel):
    """Exchange a refresh token for a fresh token pair."""

    refresh_token: str = Field(..., alias="refreshToken")

    model_config = ConfigDict(populate_by_name=True)


class UpdateProfileRequest(BaseModel):
    """Patchable profile fields for the signed-in user."""

    full_name: str | None = Field(
        default=None, min_length=1, max_length=255, alias="fullName"
    )
    phone_number: str | None = Field(
        default=None, max_length=32, alias="phoneNumber"
    )

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str | None) -> str | None:
        return _validate_phone(value)
