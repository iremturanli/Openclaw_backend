"""Real-Time Spend Intelligence (authenticated).

Honest aggregation of the signed-in guest's REAL purchases into total spend,
top categories, recent transactions and a few heuristic insight lines
(``isDemo: false``). Mobile codes against this exact contract.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_spend_service
from app.db.models.user import UserORM
from app.services.spend_service import SpendService

router = APIRouter(prefix="/spend", tags=["spend"])


@router.get("/insights", summary="Live spend intelligence for the signed-in guest")
async def spend_insights(
    user: UserORM = Depends(get_current_user),
    spend: SpendService = Depends(get_spend_service),
) -> dict[str, Any]:
    """Aggregate the guest's real bookings into the spend-intelligence payload."""

    return await spend.insights(user.guest_id)
