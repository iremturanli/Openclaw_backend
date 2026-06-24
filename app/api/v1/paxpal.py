"""PaxPal endpoints: cards, shared expense groups (settle up) and live FX.

Everything is real: cards live in Postgres and are programmed with an
HMAC-signed token (presented over NFC by the app); settle-up MOVES REAL demo
balances between members' wallets atomically; FX rates are fetched live from
the free frankfurter.dev API (ECB data) — when it is unreachable the endpoint
fails honestly instead of inventing rates.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_wallet_service
from app.core.config import Settings, get_settings
from app.db.models.paxpal import (
    ExpenseGroupORM,
    GroupExpenseORM,
    GroupMemberORM,
    PaxCardORM,
)
from app.db.models.user import UserORM
from app.db.session import get_session
from app.models.paxpal import (
    AddExpenseRequest,
    CardControlsRequest,
    FxRatesOut,
    GroupExpenseOut,
    GroupMemberOut,
    GroupOut,
    IssueCardRequest,
    PaxCardOut,
    ProgramCardResponse,
    SettleResponse,
    SettleTransferOut,
)
from app.services.wallet_service import WalletService

router = APIRouter(prefix="/paxpal", tags=["paxpal"])


# ── Cards ─────────────────────────────────────────────────────────────────
@router.get("/cards", response_model=list[PaxCardOut], summary="My PaxCards")
async def list_cards(
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[PaxCardOut]:
    rows = (
        await session.execute(
            select(PaxCardORM)
            .where(PaxCardORM.guest_id == user.guest_id)
            .order_by(PaxCardORM.created_at.desc())
        )
    ).scalars()
    return [PaxCardOut.model_validate(r) for r in rows]


@router.post(
    "/cards",
    response_model=PaxCardOut,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a new PaxCard",
)
async def issue_card(
    request: IssueCardRequest,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PaxCardOut:
    card = PaxCardORM(
        id=f"pxc_{secrets.token_hex(8)}",
        guest_id=user.guest_id,
        label=request.label,
        holder=user.full_name,
        kind=request.kind,
        last4=f"{secrets.randbelow(10000):04d}",
        color=request.color,
        created_at=datetime.now(timezone.utc),
    )
    session.add(card)
    await session.flush()
    return PaxCardOut.model_validate(card)


@router.post(
    "/cards/{card_id}/freeze",
    response_model=PaxCardOut,
    summary="Toggle a card's frozen state",
)
async def freeze_card(
    card_id: str,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PaxCardOut:
    card = await session.get(PaxCardORM, card_id)
    if card is None or card.guest_id != user.guest_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown card")
    card.frozen = not card.frozen
    await session.flush()
    return PaxCardOut.model_validate(card)


@router.patch(
    "/cards/{card_id}/controls",
    response_model=PaxCardOut,
    summary="Update a card's security/spending controls",
)
async def update_card_controls(
    card_id: str,
    request: CardControlsRequest,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PaxCardOut:
    card = await session.get(PaxCardORM, card_id)
    if card is None or card.guest_id != user.guest_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown card")
    if request.contactless is not None:
        card.contactless = request.contactless
    if request.international is not None:
        card.international = request.international
    if request.atm is not None:
        card.atm = request.atm
    if request.monthly_limit_cents is not None:
        card.monthly_limit_cents = request.monthly_limit_cents
    await session.flush()
    return PaxCardOut.model_validate(card)


@router.post(
    "/cards/{card_id}/program",
    response_model=ProgramCardResponse,
    summary="Program the card's RFID payload (HMAC-signed token)",
)
async def program_card(
    card_id: str,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProgramCardResponse:
    card = await session.get(PaxCardORM, card_id)
    if card is None or card.guest_id != user.guest_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown card")
    if card.frozen:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Unfreeze the card before programming."
        )
    claims = {
        "cid": card.id,
        "last4": card.last4,
        "holder": card.holder,
        "exp": (datetime.now(timezone.utc) + timedelta(days=4 * 365)).isoformat(),
        "jti": secrets.token_urlsafe(8),
    }
    payload = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(
        settings.key_signing_secret.encode(), payload, hashlib.sha256
    ).digest()

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    card.programmed = True
    await session.flush()
    return ProgramCardResponse(
        card_id=card.id, token=f"{b64(payload)}.{b64(signature)}", programmed=True
    )


# ── Expense groups ────────────────────────────────────────────────────────
async def _group_out(
    group: ExpenseGroupORM, session: AsyncSession
) -> GroupOut:
    members = (
        await session.execute(
            select(GroupMemberORM).where(GroupMemberORM.group_id == group.id)
        )
    ).scalars().all()
    expenses = (
        await session.execute(
            select(GroupExpenseORM)
            .where(GroupExpenseORM.group_id == group.id)
            .order_by(GroupExpenseORM.created_at.desc())
        )
    ).scalars().all()
    names = {m.guest_id: m.display_name for m in members}

    total = sum(e.amount_cents for e in expenses)
    open_expenses = [e for e in expenses if not e.settled]
    unsettled = sum(e.amount_cents for e in open_expenses)
    member_count = max(1, len(members))

    paid: dict[str, int] = {m.guest_id: 0 for m in members}
    for e in open_expenses:
        paid[e.payer_guest_id] = paid.get(e.payer_guest_id, 0) + e.amount_cents
    share = unsettled // member_count

    return GroupOut(
        id=group.id,
        name=group.name,
        total_cents=total,
        unsettled_cents=unsettled,
        members=[
            GroupMemberOut(
                guest_id=m.guest_id,
                display_name=m.display_name,
                paid_cents=paid.get(m.guest_id, 0),
                share_cents=share,
                net_cents=paid.get(m.guest_id, 0) - share,
            )
            for m in members
        ],
        expenses=[
            GroupExpenseOut(
                id=e.id,
                title=e.title,
                payer_guest_id=e.payer_guest_id,
                payer_name=names.get(e.payer_guest_id, e.payer_guest_id),
                amount_cents=e.amount_cents,
                currency=e.currency,
                settled=e.settled,
                created_at=e.created_at,
            )
            for e in expenses
        ],
    )


@router.get("/groups", response_model=list[GroupOut], summary="My expense groups")
async def list_groups(
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[GroupOut]:
    group_ids = (
        await session.execute(
            select(GroupMemberORM.group_id).where(
                GroupMemberORM.guest_id == user.guest_id
            )
        )
    ).scalars().all()
    out: list[GroupOut] = []
    for gid in group_ids:
        group = await session.get(ExpenseGroupORM, gid)
        if group is not None:
            out.append(await _group_out(group, session))
    return out


@router.post(
    "/groups/{group_id}/expenses",
    response_model=GroupOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a shared expense (paid by me, split equally)",
)
async def add_expense(
    group_id: str,
    request: AddExpenseRequest,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> GroupOut:
    group = await session.get(ExpenseGroupORM, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown group")
    member = (
        await session.execute(
            select(GroupMemberORM).where(
                GroupMemberORM.group_id == group_id,
                GroupMemberORM.guest_id == user.guest_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a member")
    session.add(
        GroupExpenseORM(
            id=f"gex_{secrets.token_hex(8)}",
            group_id=group_id,
            payer_guest_id=user.guest_id,
            title=request.title,
            amount_cents=request.amount_cents,
            currency="USD",
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.flush()
    return await _group_out(group, session)


@router.post(
    "/groups/{group_id}/settle",
    response_model=SettleResponse,
    summary="Settle my share — REAL wallet transfers to the members I owe",
)
async def settle_up(
    group_id: str,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    wallet: WalletService = Depends(get_wallet_service),
) -> SettleResponse:
    group = await session.get(ExpenseGroupORM, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown group")
    view = await _group_out(group, session)
    me = next((m for m in view.members if m.guest_id == user.guest_id), None)
    if me is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a member")
    if me.net_cents >= 0:
        return SettleResponse(
            transfers=[],
            balance_cents=(await wallet.ensure_budget(user.guest_id)).balance_cents,
            settled_cents=0,
        )

    owed = -me.net_cents
    my_budget = await wallet.ensure_budget(user.guest_id)
    if owed > my_budget.balance_cents:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Settling would exceed your remaining balance.",
        )

    # Pay creditors proportionally to what they're owed — real balance moves.
    creditors = [m for m in view.members if m.net_cents > 0]
    total_credit = sum(m.net_cents for m in creditors) or 1
    now = datetime.now(timezone.utc)
    transfers: list[SettleTransferOut] = []
    remaining = owed
    for i, creditor in enumerate(creditors):
        amount = (
            remaining
            if i == len(creditors) - 1
            else owed * creditor.net_cents // total_credit
        )
        if amount <= 0:
            continue
        remaining -= amount
        their_budget = await wallet.ensure_budget(creditor.guest_id)
        their_budget.balance_cents += amount
        their_budget.updated_at = now
        transfers.append(
            SettleTransferOut(
                to_guest_id=creditor.guest_id,
                to_name=creditor.display_name,
                amount_cents=amount,
            )
        )
    my_budget.balance_cents -= owed
    my_budget.updated_at = now

    # Mark this round of expenses settled so balances reset.
    for expense in (
        await session.execute(
            select(GroupExpenseORM).where(
                GroupExpenseORM.group_id == group_id,
                GroupExpenseORM.settled.is_(False),
            )
        )
    ).scalars():
        expense.settled = True
    await session.flush()
    return SettleResponse(
        transfers=transfers,
        balance_cents=my_budget.balance_cents,
        settled_cents=owed,
    )


# ── Live FX (frankfurter.dev — ECB reference rates, no key needed) ────────
_FX_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_FX_TTL_SECONDS = 3600.0


@router.get("/fx", response_model=FxRatesOut, summary="Live FX rates (ECB)")
async def fx_rates(base: str = Query(default="USD", min_length=3, max_length=3)) -> FxRatesOut:
    base = base.upper()
    cached = _FX_CACHE.get(base)
    if cached and time.monotonic() - cached[0] < _FX_TTL_SECONDS:
        data = cached[1]
    else:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(
                    "https://api.frankfurter.dev/v1/latest",
                    params={"base": base},
                )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Live FX provider unreachable — rates unavailable.",
            ) from exc
        if resp.status_code != 200:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail=f"Live FX provider error {resp.status_code}.",
            )
        data = resp.json()
        _FX_CACHE[base] = (time.monotonic(), data)
    return FxRatesOut(
        base=data.get("base", base),
        date=str(data.get("date", "")),
        rates={k: float(v) for k, v in (data.get("rates") or {}).items()},
    )
