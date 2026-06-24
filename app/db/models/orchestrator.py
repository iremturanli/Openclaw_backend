"""ORM models for the cross-ecosystem Loyalty Orchestrator.

Two tables back the orchestrator:

* :class:`ProviderORM` -- the **catalog** of loyalty ecosystems StayWallet knows
  about (Sixt, Miles&Smiles, Amex, ...). This is reference data: brand colour,
  Material icon, category. It carries no per-guest state.
* :class:`LoyaltyAccountORM` -- a guest's relationship to one catalog provider.
  A row is either **linked** (``linked=True``, ``points`` set -- it counts toward
  the aggregate) or **discovered** (``discovered=True``, ``detected_label`` set --
  surfaced as "you could link this"). A unique ``(guest_id, provider_id)`` pair
  keeps the relationship 1:1, so ``link`` flips a discovered row to linked
  atomically without ever duplicating it.

Per the connector framework, discovered providers are **simulated** (sandbox):
the points/labels are seeded sandbox data until real partner APIs exist. Linking
a provider creates a real ``provider_connections`` row (sandbox-flagged) via the
connector framework, so the link is auditable like any other connection.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Boolean, DateTime

from app.db.base import Base


class ProviderORM(Base):
    """A loyalty ecosystem in the orchestrator catalog (reference data)."""

    __tablename__ = "providers"

    # Stable slug, e.g. ``sixt`` / ``miles_smiles`` / ``booking_com``.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Brand colour as a #RRGGBB hex string (used for the app's program tiles).
    brand_color_hex: Mapped[str] = mapped_column(String(7), nullable=False)
    # Optional brand logo URL; when null the client falls back to the icon.
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional Material icon name, e.g. ``directions_car`` / ``flight``.
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Loose grouping: hotel | car | airline | rideshare | card | coffee | fuel.
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    # Display order so the grid's top row matches the mockup.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    accounts: Mapped[list["LoyaltyAccountORM"]] = relationship(
        back_populates="provider"
    )


class LoyaltyAccountORM(Base):
    """A guest's linked-or-discovered relationship to a catalog provider."""

    __tablename__ = "loyalty_accounts"
    __table_args__ = (
        UniqueConstraint(
            "guest_id", "provider_id", name="uq_loyalty_accounts_guest_provider"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guest_id: Mapped[str] = mapped_column(
        ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Linked ecosystems count toward the aggregate (points set, detected null).
    linked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Discovered-but-not-linked ecosystems carry a detected_label, points null.
    discovered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Points in this ecosystem (set when linked; null while merely discovered).
    points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Human label for a discovered program, e.g. "2,450 points detected".
    detected_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    provider: Mapped["ProviderORM"] = relationship(back_populates="accounts")
