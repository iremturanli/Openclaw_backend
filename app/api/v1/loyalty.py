"""Loyalty balance endpoint (read from the ledger)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_loyalty_service
from app.models.travel import LoyaltyBalance
from app.services.loyalty_service import LoyaltyService

router = APIRouter(prefix="/loyalty", tags=["loyalty"])


@router.get(
    "",
    response_model=LoyaltyBalance,
    response_model_by_alias=True,
    summary="Get a guest's loyalty balance (computed from the ledger)",
)
async def get_loyalty_balance(
    guest_id: str = Query(..., alias="guestId", examples=["guest_demo"]),
    service: LoyaltyService = Depends(get_loyalty_service),
) -> LoyaltyBalance:
    """Return the guest's :class:`LoyaltyBalance`.

    ``points`` is the SUM over the guest's ledger rows (earned − redeemed); an
    unknown guest simply has a zero balance.
    """

    return await service.get_balance(guest_id)
