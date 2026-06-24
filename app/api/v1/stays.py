"""Stay endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_stay_repository
from app.models.stay import StayInfo
from app.repositories.base import StayRepository

router = APIRouter(prefix="/stays", tags=["stays"])


@router.get(
    "/{stay_id}",
    response_model=StayInfo,
    response_model_by_alias=True,
    summary="Fetch the booking the guest is checking into",
)
async def get_stay(
    stay_id: str,
    stays: StayRepository = Depends(get_stay_repository),
) -> StayInfo:
    """Return the :class:`StayInfo` for ``stay_id``.

    Raises a 404 with ``{"detail": "Stay not found"}`` when unknown.
    """

    stay = await stays.get(stay_id)
    if stay is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stay not found",
        )
    return stay
