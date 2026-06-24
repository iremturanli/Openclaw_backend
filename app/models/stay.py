"""Stay (booking) schema."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StayInfo(BaseModel):
    """A booking the guest is checking into.

    Matches the ``StayInfo`` shape in ``docs/api_contract.md``.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., examples=["stay_123"])
    property_name: str = Field(..., alias="propertyName", examples=["The Bosphorus Suites"])
    room_number: str = Field(..., alias="roomNumber", examples=["402"])
    check_in_date: datetime = Field(..., alias="checkInDate")
    check_out_date: datetime = Field(..., alias="checkOutDate")
    address: str = Field(..., examples=["Kennedy Cd. No:12, Beşiktaş, İstanbul"])
