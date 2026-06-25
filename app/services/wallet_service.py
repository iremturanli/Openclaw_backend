"""Demo travel budget + purchases.

A single per-guest budget (minor units). Purchasing deducts atomically and
records the item so the app can show a live balance and "My Flights / Hotels /
Reservations". Never real money.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.stay import StayORM
from app.db.models.travel_wallet import PurchaseORM, WalletBudgetORM

VALID_KINDS = {
    "flight",
    "hotel",
    "restaurant",
    "car",
    "transfer",
    "scooter",
    "activity",
}


class InsufficientBudgetError(Exception):
    """Raised when a purchase exceeds the remaining budget."""

    def __init__(self, balance_cents: int) -> None:
        self.balance_cents = balance_cents
        super().__init__("Insufficient budget")


class InvalidPurchaseError(Exception):
    """Raised for a malformed purchase (bad kind / non-positive amount)."""


class WalletService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def ensure_budget(self, guest_id: str) -> WalletBudgetORM:
        budget = await self._session.get(WalletBudgetORM, guest_id)
        if budget is None:
            budget = WalletBudgetORM(
                guest_id=guest_id,
                balance_cents=self._settings.demo_budget_cents,
                currency=self._settings.demo_budget_currency,
                updated_at=datetime.now(timezone.utc),
            )
            self._session.add(budget)
            await self._session.flush()
        return budget

    async def list_purchases(
        self, guest_id: str, kind: str | None = None
    ) -> list[PurchaseORM]:
        stmt = select(PurchaseORM).where(PurchaseORM.guest_id == guest_id)
        if kind is not None:
            stmt = stmt.where(PurchaseORM.kind == kind)
        stmt = stmt.order_by(PurchaseORM.created_at.desc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_purchase(self, purchase_id: str) -> PurchaseORM | None:
        return await self._session.get(PurchaseORM, purchase_id)

    async def topup(
        self, *, guest_id: str, amount_cents: int
    ) -> WalletBudgetORM:
        """Add demo funds to the guest's budget (never real money)."""

        if amount_cents <= 0 or amount_cents > 10_000_000:
            raise InvalidPurchaseError()
        budget = await self.ensure_budget(guest_id)
        budget.balance_cents += amount_cents
        budget.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return budget

    async def purchase(
        self,
        *,
        guest_id: str,
        kind: str,
        title: str,
        subtitle: str,
        amount_cents: int,
        currency: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> tuple[PurchaseORM, WalletBudgetORM]:
        # Restaurant reservations are free (amount 0); flights/hotels cost > 0.
        if kind not in VALID_KINDS or amount_cents < 0:
            raise InvalidPurchaseError()

        budget = await self.ensure_budget(guest_id)
        if amount_cents > budget.balance_cents:
            raise InsufficientBudgetError(budget.balance_cents)

        now = datetime.now(timezone.utc)
        normalized_details = dict(details or {})
        if kind == "hotel":
            stay = await self._ensure_hotel_stay(
                purchase_title=title,
                purchase_subtitle=subtitle,
                purchase_details=normalized_details,
                now=now,
            )
            normalized_details["stayId"] = stay.id
        budget.balance_cents -= amount_cents
        budget.updated_at = now
        purchase = PurchaseORM(
            id=f"pur_{uuid.uuid4().hex[:24]}",
            guest_id=guest_id,
            kind=kind,
            title=title,
            subtitle=subtitle,
            amount_cents=amount_cents,
            currency=currency or budget.currency,
            details=normalized_details,
            created_at=now,
        )
        self._session.add(purchase)
        await self._session.flush()
        return purchase, budget

    async def _ensure_hotel_stay(
        self,
        *,
        purchase_title: str,
        purchase_subtitle: str,
        purchase_details: dict[str, Any],
        now: datetime,
    ) -> StayORM:
        raw_stay_id = purchase_details.get("stayId")
        if isinstance(raw_stay_id, str) and raw_stay_id.strip():
            existing = await self._session.get(StayORM, raw_stay_id.strip())
            if existing is not None:
                return existing

        nights = 1
        raw_nights = purchase_details.get("nights")
        if isinstance(raw_nights, (int, float)) and raw_nights > 0:
            nights = min(int(raw_nights), 30)

        check_in = now.replace(minute=0, second=0, microsecond=0)
        check_out = (check_in + timedelta(days=nights)).replace(hour=11)
        stay_seed = uuid.uuid4().hex
        room_number = f"{4 + int(stay_seed[0], 16) % 4}{int(stay_seed[1:3], 16) % 30 + 1:02d}"

        stay = StayORM(
            id=f"stay_{stay_seed[:16]}",
            property_name=purchase_title,
            room_number=room_number,
            check_in_date=check_in,
            check_out_date=check_out,
            address=purchase_subtitle or "Booked via StayWallet",
            source="manual",
        )
        self._session.add(stay)
        await self._session.flush()
        return stay
