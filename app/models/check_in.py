"""Check-in request/response and digital-key schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CheckInStatus
from app.models.passport import PassportData
from app.models.stay import StayInfo


class FaceVerificationChallenge(str, Enum):
    """Challenge completed by the guest during on-device selfie verification."""

    SMILE = "smile"
    TURN_SIDE = "turnSide"


class FaceVerification(BaseModel):
    """Summary of the on-device selfie verification session."""

    model_config = ConfigDict(populate_by_name=True)

    passed: bool
    challenge: FaceVerificationChallenge
    confidence: float = Field(..., ge=0, le=1)
    completed_at: datetime = Field(..., alias="completedAt")
    capture_count: int = Field(..., alias="captureCount", ge=1)


class CheckInRequest(BaseModel):
    """The JSON ``payload`` part of the multipart check-in request.

    The selfie file is handled separately at the transport layer and is not
    part of this model.
    """

    model_config = ConfigDict(populate_by_name=True)

    stay_id: str = Field(..., alias="stayId", min_length=1, examples=["stay_123"])
    passport: PassportData
    face_verification: FaceVerification | None = Field(
        default=None,
        alias="faceVerification",
    )


class DigitalKey(BaseModel):
    """An issued room key. ``accessToken`` is opaque to the client."""

    model_config = ConfigDict(populate_by_name=True)

    key_id: str = Field(..., alias="keyId", examples=["key_456"])
    access_token: str = Field(..., alias="accessToken", examples=["eyJ...opaque"])
    valid_from: datetime = Field(..., alias="validFrom")
    valid_until: datetime = Field(..., alias="validUntil")


class CheckInConfirmation(BaseModel):
    """Result of a check-in. Returned by both POST and GET check-in endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    check_in_id: str = Field(..., alias="checkInId", examples=["ci_789"])
    status: CheckInStatus
    stay: StayInfo
    # ``digitalKey`` is null for pending/rejected check-ins.
    digital_key: DigitalKey | None = Field(default=None, alias="digitalKey")
    rejection_reason: str | None = Field(default=None, alias="rejectionReason")
