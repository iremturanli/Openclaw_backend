"""Sixt connector -- SANDBOX implementation.

Sixt's partner API requires commercial credentials, so this connector returns a
simulated Platinum profile (no reservations to import -- rentals are not
stays), flagged ``sandbox=True``. To go live, swap the method bodies for real
HTTP calls against the Sixt partner API; nothing outside this file changes.
"""

from __future__ import annotations

from app.services.connectors.base import (
    ProviderConnector,
    ProviderProfile,
    ProviderReservation,
    ProviderToken,
)


class SixtConnector(ProviderConnector):
    """Sandbox Sixt connector (Platinum tier, deterministic)."""

    provider = "sixt"

    AUTHORIZE_ENDPOINT = "https://account.sixt.com/oauth2/authorize"

    def authorize_url(self, state: str) -> str:
        return (
            f"{self.AUTHORIZE_ENDPOINT}"
            f"?response_type=code&client_id=staywallet-sandbox&state={state}"
        )

    async def exchange_code(self, code: str) -> ProviderToken:
        return ProviderToken(access_token=f"sandbox-token::{code}", sandbox=True)

    async def fetch_profile(self, token: ProviderToken) -> ProviderProfile:
        return ProviderProfile(
            genius_level=None,
            display_name="Sixt Platinum · Member ID 86288*** (sandbox)",
            sandbox=True,
        )

    async def fetch_bookings(
        self, token: ProviderToken
    ) -> list[ProviderReservation]:
        # Car rentals are not hotel stays; nothing to import.
        return []


class UberConnector(ProviderConnector):
    """Sandbox Uber connector (rides account, deterministic)."""

    provider = "uber"

    AUTHORIZE_ENDPOINT = "https://auth.uber.com/oauth/v2/authorize"

    def authorize_url(self, state: str) -> str:
        return (
            f"{self.AUTHORIZE_ENDPOINT}"
            f"?response_type=code&client_id=staywallet-sandbox&state={state}"
        )

    async def exchange_code(self, code: str) -> ProviderToken:
        return ProviderToken(access_token=f"sandbox-token::{code}", sandbox=True)

    async def fetch_profile(self, token: ProviderToken) -> ProviderProfile:
        return ProviderProfile(
            genius_level=None,
            display_name="Uber Rider · Gold (sandbox)",
            sandbox=True,
        )

    async def fetch_bookings(
        self, token: ProviderToken
    ) -> list[ProviderReservation]:
        return []
