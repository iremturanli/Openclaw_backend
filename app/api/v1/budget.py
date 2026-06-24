"""Demo travel budget + purchases (authenticated).

The budget belongs to the signed-in user's loyalty guest; the same endpoints
back the manual UI and the AI agent so a flight bought by voice, chat or a
button all hit one wallet and one list.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user, get_wallet_service
from app.db.models.user import UserORM
from app.models.travel_wallet import (
    BudgetState,
    PurchaseOut,
    PurchaseRequest,
    PurchaseResult,
)
from app.services.wallet_service import (
    InsufficientBudgetError,
    InvalidPurchaseError,
    WalletService,
)

router = APIRouter(prefix="/budget", tags=["budget"])


@router.get("", response_model=BudgetState, summary="Current budget + recent purchases")
async def get_budget(
    user: UserORM = Depends(get_current_user),
    wallet: WalletService = Depends(get_wallet_service),
) -> BudgetState:
    budget = await wallet.ensure_budget(user.guest_id)
    recent = await wallet.list_purchases(user.guest_id)
    return BudgetState(
        balance_cents=budget.balance_cents,
        currency=budget.currency,
        recent_purchases=[PurchaseOut.model_validate(p) for p in recent[:5]],
    )


@router.get(
    "/purchases",
    response_model=list[PurchaseOut],
    summary="My purchases (optionally filtered by kind)",
)
async def list_purchases(
    kind: str | None = Query(default=None, examples=["flight"]),
    user: UserORM = Depends(get_current_user),
    wallet: WalletService = Depends(get_wallet_service),
) -> list[PurchaseOut]:
    rows = await wallet.list_purchases(user.guest_id, kind)
    return [PurchaseOut.model_validate(p) for p in rows]


@router.post("/topup", response_model=BudgetState, summary="Add demo funds")
async def topup(
    request: dict,
    user: UserORM = Depends(get_current_user),
    wallet: WalletService = Depends(get_wallet_service),
) -> BudgetState:
    try:
        amount = int(request.get("amountCents", 0))
        budget = await wallet.topup(guest_id=user.guest_id, amount_cents=amount)
    except (TypeError, ValueError, InvalidPurchaseError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid top-up amount.",
        ) from exc
    recent = await wallet.list_purchases(user.guest_id)
    return BudgetState(
        balance_cents=budget.balance_cents,
        currency=budget.currency,
        recent_purchases=[PurchaseOut.model_validate(p) for p in recent[:5]],
    )


@router.post(
    "/purchases",
    response_model=PurchaseResult,
    status_code=status.HTTP_201_CREATED,
    summary="Simulate a purchase, deducting the budget",
)
async def create_purchase(
    request: PurchaseRequest,
    user: UserORM = Depends(get_current_user),
    wallet: WalletService = Depends(get_wallet_service),
) -> PurchaseResult:
    try:
        purchase, budget = await wallet.purchase(
            guest_id=user.guest_id,
            kind=request.kind,
            title=request.title,
            subtitle=request.subtitle,
            amount_cents=request.amount_cents,
            currency=request.currency,
            details=request.details,
        )
    except InvalidPurchaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid purchase.",
        ) from exc
    except InsufficientBudgetError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This would exceed your remaining budget.",
        ) from exc
    return PurchaseResult(
        purchase=PurchaseOut.model_validate(purchase),
        balance_cents=budget.balance_cents,
    )
