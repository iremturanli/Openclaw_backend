"""Data access for users + their loyalty guest row.

Kept as a focused, session-bound repository (mirroring the other DB
repositories) so the auth service stays free of SQL.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.travel import GuestORM
from app.db.models.user import UserORM


class UserRepository:
    """CRUD for [UserORM] (and the paired loyalty guest row)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> UserORM | None:
        result = await self._session.execute(
            select(UserORM).where(UserORM.email == email.lower())
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: str) -> UserORM | None:
        return await self._session.get(UserORM, user_id)

    async def create(
        self,
        *,
        user_id: str,
        email: str,
        hashed_password: str,
        full_name: str,
        phone_number: str | None = None,
    ) -> UserORM:
        """Insert a user and a matching loyalty guest (``guest_id == user_id``)."""
        now = datetime.now(timezone.utc)
        guest = GuestORM(id=user_id, display_name=full_name, created_at=now)
        user = UserORM(
            id=user_id,
            email=email.lower(),
            hashed_password=hashed_password,
            full_name=full_name,
            phone_number=phone_number,
            guest_id=user_id,
            created_at=now,
        )
        self._session.add(guest)
        self._session.add(user)
        await self._session.flush()
        return user

    async def update_profile(
        self,
        user: UserORM,
        *,
        full_name: str | None = None,
        phone_number: str | None = None,
    ) -> UserORM:
        """Update mutable profile fields and the paired guest display name."""

        if full_name is not None:
            user.full_name = full_name.strip()
            guest = await self._session.get(GuestORM, user.guest_id)
            if guest is not None:
                guest.display_name = user.full_name
        if phone_number is not None:
            user.phone_number = phone_number
        await self._session.flush()
        return user

    async def update_preferences(
        self, user: UserORM, *, preferences: dict
    ) -> UserORM:
        """Replace the user's habit-aware travel preferences (whole dict)."""

        user.preferences = preferences
        await self._session.flush()
        return user
