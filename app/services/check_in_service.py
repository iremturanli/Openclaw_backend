"""Check-in business logic.

Validation policy (documented for the contract):

* Unknown stay  -> :class:`StayNotFoundError` (router returns 404).
* Structural payload errors (missing names, bad shapes) are rejected by
  Pydantic at the boundary and surface as HTTP 422.
* **Expired passport** -> the check-in is accepted and persisted with status
  ``rejected`` and a human-readable reason, and **no digital key is issued**.
  This is preferred over 422 so the wallet can display the rejection state and
  reason rather than just a validation failure. (See README "Decisions".)
* A failed MRZ checksum (``checksumValid == false``) is likewise treated as a
  ``rejected`` check-in.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from app.models.check_in import CheckInConfirmation, CheckInRequest, FaceVerification
from app.models.enums import CheckInStatus
from app.models.passport import PassportData
from app.repositories.base import CheckInRepository, StayRepository
from app.services.exceptions import CheckInNotFoundError, StayNotFoundError
from app.services.key_service import KeyService


class CheckInService:
    """Orchestrates validation, key issuance and persistence of check-ins."""

    def __init__(
        self,
        stay_repository: StayRepository,
        check_in_repository: CheckInRepository,
        key_service: KeyService,
    ) -> None:
        self._stays = stay_repository
        self._check_ins = check_in_repository
        self._keys = key_service

    @staticmethod
    def _evaluate_passport(
        passport: PassportData, *, now: datetime | None = None
    ) -> tuple[CheckInStatus, str | None]:
        """Decide the check-in status from passport validity.

        Returns a ``(status, rejection_reason)`` tuple. ``rejection_reason`` is
        ``None`` when the passport is acceptable.
        """

        reference = now or datetime.now(timezone.utc)
        if passport.is_expired(now=reference):
            return CheckInStatus.REJECTED, "Passport is expired."
        if not passport.checksum_valid:
            return CheckInStatus.REJECTED, "Passport MRZ checksum is invalid."
        return CheckInStatus.VERIFIED, None

    @staticmethod
    def _evaluate_face_verification(
        face_verification: FaceVerification | None,
        *,
        selfie_provided: bool,
        now: datetime | None = None,
    ) -> tuple[CheckInStatus, str | None]:
        """Decide whether the selfie verification evidence is acceptable."""

        if not selfie_provided:
            return CheckInStatus.REJECTED, "Selfie verification is required."
        if face_verification is None or not face_verification.passed:
            return (
                CheckInStatus.REJECTED,
                "Face verification did not complete successfully.",
            )
        if face_verification.capture_count < 2:
            return (
                CheckInStatus.REJECTED,
                "Face verification challenge was incomplete.",
            )

        reference = now or datetime.now(timezone.utc)
        completed_at = face_verification.completed_at
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)
        if completed_at < reference - timedelta(minutes=10):
            return (
                CheckInStatus.REJECTED,
                "Face verification is too old. Please verify again.",
            )
        return CheckInStatus.VERIFIED, None

    async def create_check_in(
        self,
        request: CheckInRequest,
        *,
        selfie_provided: bool = False,
        now: datetime | None = None,
    ) -> CheckInConfirmation:
        """Validate a check-in, issue a key on success, and persist the result.

        Args:
            request: Parsed check-in payload.
            selfie_provided: Whether a selfie file accompanied the request
                (reserved for future face-verification; optional in the mock).
            now: Override for the current time (used in tests).

        Raises:
            StayNotFoundError: If ``request.stay_id`` is unknown.
        """

        stay = await self._stays.get(request.stay_id)
        if stay is None:
            raise StayNotFoundError(request.stay_id)

        status, reason = self._evaluate_passport(request.passport, now=now)
        if status is CheckInStatus.VERIFIED:
            status, reason = self._evaluate_face_verification(
                request.face_verification,
                selfie_provided=selfie_provided,
                now=now,
            )

        digital_key = self._keys.issue_key(stay) if status is CheckInStatus.VERIFIED else None

        confirmation = CheckInConfirmation(
            check_in_id=f"ci_{secrets.token_hex(6)}",
            status=status,
            stay=stay,
            digital_key=digital_key,
            rejection_reason=reason,
        )
        return await self._check_ins.save(confirmation, rejection_reason=reason)

    async def get_check_in(self, check_in_id: str) -> CheckInConfirmation:
        """Return a stored check-in.

        Raises:
            CheckInNotFoundError: If no such check-in exists.
        """

        confirmation = await self._check_ins.get(check_in_id)
        if confirmation is None:
            raise CheckInNotFoundError(check_in_id)
        return confirmation
