"""Pydantic schemas for the StayWallet API."""

from app.models.check_in import (
    CheckInConfirmation,
    CheckInRequest,
    DigitalKey,
)
from app.models.enums import CheckInStatus, Sex
from app.models.passport import PassportData
from app.models.stay import StayInfo
from app.models.travel import (
    BookingConfirmation,
    BookingRequest,
    FeaturedDeal,
    LoyaltyBalance,
    ServiceCategory,
)

__all__ = [
    "BookingConfirmation",
    "BookingRequest",
    "CheckInConfirmation",
    "CheckInRequest",
    "CheckInStatus",
    "DigitalKey",
    "FeaturedDeal",
    "LoyaltyBalance",
    "PassportData",
    "ServiceCategory",
    "Sex",
    "StayInfo",
]
