"""Load/save the signed-in user's habit-aware travel preferences.

A thin service over [UserRepository] that reads and persists the
``users.preferences`` JSON column, returning a validated [TravelPreferences]
in both directions so the API layer stays free of SQL and validation glue.
"""

from __future__ import annotations

from app.db.models.user import UserORM
from app.models.preferences import TravelPreferences
from app.repositories.user_repo import UserRepository


class PreferencesService:
    """Read/update a user's travel preferences."""

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    @staticmethod
    def load(user: UserORM) -> TravelPreferences:
        """Return the user's saved preferences, or empty defaults if none."""

        raw = user.preferences or {}
        # Tolerate partial/legacy dicts: validation fills missing fields with
        # sensible empty defaults and ignores unknown keys.
        return TravelPreferences.model_validate(raw)

    async def save(
        self, user: UserORM, preferences: TravelPreferences
    ) -> TravelPreferences:
        """Persist the (validated) preferences and return the saved shape."""

        await self._users.update_preferences(
            user, preferences=preferences.to_storage()
        )
        return PreferencesService.load(user)
