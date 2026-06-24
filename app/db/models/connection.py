"""ORM model for provider account connections (external account linking).

A :class:`ProviderConnectionORM` is a guest's link to an external travel provider
(Booking.com, and later Airbnb/Expedia). The link is produced by the connector
framework (``app/services/connectors``) which runs an OAuth-shaped
authorize -> exchange -> sync flow. The Booking.com connector currently runs in
**sandbox** mode (``sandbox=True``): the OAuth shape and the rows written here
are real, but the external profile/bookings are simulated because Booking.com has
no public consumer API. Swapping to a real partner API means replacing only the
connector implementation, not this table.

``scopes`` is stored as a JSONB array so it stays queryable (e.g.
``scopes ? 'import_bookings'``) without a child table.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Boolean, DateTime

from app.db.base import Base


class ProviderConnectionORM(Base):
    """A guest's linked external-provider account."""

    __tablename__ = "provider_connections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    guest_id: Mapped[str] = mapped_column(
        ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # status enum: linked | pending | error
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Queryable JSONB array of granted scopes.
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    genius_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imported_stays: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Sandbox placeholder token; in real mode this is the provider access token.
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Stays imported via this connection. On unlink the connection is deleted but
    # imported stays are kept (their FK is nulled, see connection_service.unlink).
    imported_stay_rows: Mapped[list["StayORM"]] = relationship(  # noqa: F821
        back_populates="provider_connection",
        passive_deletes=True,
    )
