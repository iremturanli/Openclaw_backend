"""Check-in endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from app.api.deps import get_check_in_service
from app.models.check_in import CheckInConfirmation, CheckInRequest
from app.services.check_in_service import CheckInService
from app.services.exceptions import CheckInNotFoundError, StayNotFoundError

router = APIRouter(prefix="/check-ins", tags=["check-ins"])


def _parse_payload(payload: str) -> CheckInRequest:
    """Parse and validate the multipart ``payload`` JSON string.

    Raises an HTTP 422 mirroring FastAPI's default validation error shape when
    the JSON is malformed or fails schema validation.
    """

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "loc": ["body", "payload"],
                    "msg": f"payload is not valid JSON: {exc.msg}",
                    "type": "value_error.json",
                }
            ],
        ) from exc

    try:
        return CheckInRequest.model_validate(data)
    except ValidationError as exc:
        # Re-emit Pydantic errors under the ``payload`` location for clarity.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {**err, "loc": ["body", "payload", *err.get("loc", ())]}
                for err in exc.errors()
            ],
        ) from exc


@router.post(
    "",
    response_model=CheckInConfirmation,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a completed check-in and issue a digital key",
)
async def create_check_in(
    payload: str = Form(..., description="CheckInRequest as a JSON string"),
    selfie: UploadFile | None = None,
    service: CheckInService = Depends(get_check_in_service),
) -> CheckInConfirmation:
    """Create a check-in.

    Accepts ``multipart/form-data`` with a ``payload`` JSON field and an
    optional ``selfie`` image. Returns the :class:`CheckInConfirmation`.
    """

    request = _parse_payload(payload)
    try:
        return await service.create_check_in(
            request,
            selfie_provided=selfie is not None,
        )
    except StayNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stay not found",
        ) from exc


@router.get(
    "/{check_in_id}",
    response_model=CheckInConfirmation,
    response_model_by_alias=True,
    summary="Fetch a previously created check-in / wallet state",
)
async def get_check_in(
    check_in_id: str,
    service: CheckInService = Depends(get_check_in_service),
) -> CheckInConfirmation:
    """Return a stored :class:`CheckInConfirmation`, or 404 if unknown."""

    try:
        return await service.get_check_in(check_in_id)
    except CheckInNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Check-in not found",
        ) from exc
