"""ORM models for PaxPal: issued cards + shared expense groups."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime

from app.db.base import Base


class PaxCardORM(Base):
    """A PaxCard issued to a guest (virtual or physical, NFC-programmable)."""

    __tablename__ = "pax_cards"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    guest_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    holder: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # virtual|physical
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    color: Mapped[str] = mapped_column(String(9), nullable=False)
    frozen: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    programmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Security & spending controls ("Manage Paxcard" surface).
    contactless: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    international: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    atm: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    monthly_limit_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=500000, server_default="500000"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ExpenseGroupORM(Base):
    """A shared travel group whose expenses are split between members."""

    __tablename__ = "expense_groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    members: Mapped[list["GroupMemberORM"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    expenses: Mapped[list["GroupExpenseORM"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupMemberORM(Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "guest_id", name="uq_group_member"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(
        ForeignKey("expense_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    guest_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    group: Mapped["ExpenseGroupORM"] = relationship(back_populates="members")


class GroupExpenseORM(Base):
    """One shared expense, paid by a member, split equally across the group."""

    __tablename__ = "group_expenses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_id: Mapped[str] = mapped_column(
        ForeignKey("expense_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payer_guest_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    settled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    group: Mapped["ExpenseGroupORM"] = relationship(back_populates="expenses")
