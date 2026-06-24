"""ORM models for the demo travel budget and purchases.

The budget is a single per-guest balance in minor units (cents). Each purchase
(flight / hotel / restaurant) deducts from it atomically and is recorded so the
app can show "My Flights / Hotels / Reservations" and a live wallet. This is a
*demo* budget — never real money, no payment provider.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.db.base import Base


class WalletBudgetORM(Base):
    """A guest's single demo travel budget (minor units)."""

    __tablename__ = "wallet_budgets"

    guest_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    balance_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class PurchaseORM(Base):
    """A simulated purchase (flight / hotel / restaurant) against the budget."""

    __tablename__ = "purchases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    guest_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # 'flight' | 'hotel' | 'restaurant'
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    # Free-form snapshot of the booked item (airports, dates, airline, ...).
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
