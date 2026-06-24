"""ORM models for stays, check-ins and issued digital keys."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime

from app.db.base import Base


class StayORM(Base):
    """A booking the guest checks into. Source for :class:`StayInfo`."""

    __tablename__ = "stays"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    property_name: Mapped[str] = mapped_column(String(255), nullable=False)
    room_number: Mapped[str] = mapped_column(String(32), nullable=False)
    check_in_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    check_out_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    address: Mapped[str] = mapped_column(Text, nullable=False)
    # Origin of the stay: 'manual' (created in-app) or 'booking.com' (imported via
    # a provider connection). Tagged so imported reservations are distinguishable.
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual", server_default="manual"
    )
    # Set when this stay was imported via a provider connection. Nullable so
    # in-app stays have no connection, and so unlink can null it (keeping the
    # imported stay row).
    provider_connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Deterministic external key for an imported reservation (provider + ref),
    # used to make re-imports idempotent (no duplicate stays).
    external_ref: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True
    )

    check_ins: Mapped[list["CheckInORM"]] = relationship(
        back_populates="stay", cascade="all, delete-orphan"
    )
    orders: Mapped[list["OrderORM"]] = relationship(  # noqa: F821
        back_populates="stay", cascade="all, delete-orphan"
    )
    provider_connection: Mapped["ProviderConnectionORM | None"] = relationship(  # noqa: F821
        back_populates="imported_stay_rows"
    )


class CheckInORM(Base):
    """A completed/attempted check-in result."""

    __tablename__ = "check_ins"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    stay_id: Mapped[str] = mapped_column(
        ForeignKey("stays.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    stay: Mapped["StayORM"] = relationship(back_populates="check_ins")
    digital_key: Mapped["DigitalKeyORM | None"] = relationship(
        back_populates="check_in",
        cascade="all, delete-orphan",
        uselist=False,
    )


class DigitalKeyORM(Base):
    """An issued room key bound 1:1 to a verified check-in."""

    __tablename__ = "digital_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    check_in_id: Mapped[str] = mapped_column(
        ForeignKey("check_ins.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    valid_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    check_in: Mapped["CheckInORM"] = relationship(back_populates="digital_key")
