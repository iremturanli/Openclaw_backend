"""SQLAlchemy declarative base.

A single :class:`Base` is shared by every ORM model so Alembic can discover the
full metadata for autogeneration. Importing :mod:`app.db.models` registers all
mapped classes against this metadata.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all StayWallet ORM models."""
