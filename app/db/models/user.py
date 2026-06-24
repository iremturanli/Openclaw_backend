"""ORM model for authenticated users.

A user is the login identity. Each user is 1:1 with a loyalty ``guest`` row
(``guest_id`` mirrors ``users.id``) so everything the app already keys on a
``guestId`` (loyalty, orchestrator, connections, bookings) is driven by the
signed-in account rather than a hard-coded demo guest.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.db.base import Base


class UserORM(Base):
    """A registered, password-authenticated user."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, unique=True, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Habit-aware travel preferences (camelCase dict). Fed to the AI concierge
    # as soft defaults so plans match the traveller's habits (home airport,
    # preferred cabin, hotel tier, dietary needs, language, …).
    preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # The loyalty member this login owns (mirrors `users.id`).
    guest_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
