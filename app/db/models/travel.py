"""ORM models for travel services, featured deals, guests, bookings and the
loyalty ledger."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime

from app.db.base import Base


class GuestORM(Base):
    """A loyalty member. The demo guest is ``guest_demo``."""

    __tablename__ = "guests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    bookings: Mapped[list["BookingORM"]] = relationship(back_populates="guest")
    loyalty_transactions: Mapped[list["LoyaltyTransactionORM"]] = relationship(
        back_populates="guest"
    )


class TravelCategoryORM(Base):
    """A bookable travel-service category (rental car, hotel, e-visa, ...)."""

    __tablename__ = "travel_categories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(255), nullable=False)
    icon: Mapped[str] = mapped_column(String(64), nullable=False)
    accent: Mapped[str] = mapped_column(String(16), nullable=False)
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Indicative price used to compute earned points on a category booking.
    base_price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class FeaturedDealORM(Base):
    """A promoted partner deal shown in the travel hub."""

    __tablename__ = "featured_deals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    badge: Mapped[str] = mapped_column(String(64), nullable=False)
    discount_label: Mapped[str] = mapped_column(String(64), nullable=False)
    discount_note: Mapped[str] = mapped_column(String(128), nullable=False)
    # Indicative price used to compute earned points on a deal booking.
    base_price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class BookingORM(Base):
    """A confirmed travel booking (against a category or a featured deal)."""

    __tablename__ = "bookings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    guest_id: Mapped[str] = mapped_column(
        ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[str | None] = mapped_column(
        ForeignKey("travel_categories.id", ondelete="SET NULL"), nullable=True
    )
    deal_id: Mapped[str | None] = mapped_column(
        ForeignKey("featured_deals.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    points_earned: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    guest: Mapped["GuestORM"] = relationship(back_populates="bookings")


class LoyaltyTransactionORM(Base):
    """A single immutable row in the loyalty ledger.

    ``amount`` is positive for an *earn* and negative for a *redeem*; the guest's
    balance is ``SUM(amount)`` over all their rows. ``source`` records what wrote
    the row (``order`` | ``booking`` | ``seed`` | ``adjustment``) and
    ``reference_id`` links back to that entity for auditability.
    """

    __tablename__ = "loyalty_transactions"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    guest_id: Mapped[str] = mapped_column(
        ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # earn | redeem
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    guest: Mapped["GuestORM"] = relationship(back_populates="loyalty_transactions")
