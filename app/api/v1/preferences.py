"""Habit-aware travel preferences endpoints (authenticated).

Persists each traveller's habits (home city/airport, preferred cabin, hotel
tier, dietary needs, language, currency, …) on ``users.preferences`` and
returns them in a stable camelCase shape. These feed the AI concierge as soft
defaults so plans adapt to how the user usually travels.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_preferences_service
from app.db.models.user import UserORM
from app.models.preferences import TravelPreferences
from app.services.preferences_service import PreferencesService

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get(
    "",
    response_model=TravelPreferences,
    response_model_by_alias=True,
    summary="Get the signed-in user's travel preferences",
)
async def get_preferences(
    user: UserORM = Depends(get_current_user),
) -> TravelPreferences:
    """Return the saved preferences, or empty defaults if none are set."""

    return PreferencesService.load(user)


@router.put(
    "",
    response_model=TravelPreferences,
    response_model_by_alias=True,
    summary="Replace the signed-in user's travel preferences",
)
async def put_preferences(
    request: TravelPreferences,
    user: UserORM = Depends(get_current_user),
    service: PreferencesService = Depends(get_preferences_service),
) -> TravelPreferences:
    """Validate and persist the preferences, returning the full saved shape."""

    return await service.save(user, request)
