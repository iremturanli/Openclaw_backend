"""Passport (parsed MRZ) schema.

Privacy note: the passport *image* is never transmitted. Only the parsed MRZ
fields below are sent by the app; OCR runs on-device.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import Sex


class PassportData(BaseModel):
    """Parsed MRZ fields of a guest passport."""

    model_config = ConfigDict(populate_by_name=True)

    document_number: str = Field(..., alias="documentNumber", min_length=1, examples=["P1234567"])
    surname: str = Field(..., min_length=1, examples=["YILMAZ"])
    given_names: str = Field(..., alias="givenNames", min_length=1, examples=["AHMET"])
    nationality: str = Field(..., min_length=3, max_length=3, examples=["TUR"])
    issuing_country: str = Field(..., alias="issuingCountry", min_length=3, max_length=3, examples=["TUR"])
    date_of_birth: datetime = Field(..., alias="dateOfBirth")
    expiry_date: datetime = Field(..., alias="expiryDate")
    sex: Sex
    checksum_valid: bool = Field(..., alias="checksumValid")

    @field_validator("nationality", "issuing_country")
    @classmethod
    def _uppercase_country_code(cls, value: str) -> str:
        """Normalise ISO 3166-1 alpha-3 country codes to upper case."""

        return value.upper()

    def is_expired(self, *, now: datetime | None = None) -> bool:
        """Return ``True`` if the passport is expired relative to ``now`` (UTC)."""

        reference = now or datetime.now(timezone.utc)
        expiry = self.expiry_date
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry < reference
