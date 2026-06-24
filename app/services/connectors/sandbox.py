"""Generic sandbox connector for Loyalty Orchestrator ecosystems.

================================ SANDBOX STUB ================================
The orchestrator links many third-party loyalty programs (Sixt, Amex, Uber, ...)
that have no public consumer API for reading a member's balance. This connector
provides the **real OAuth-shaped flow** (authorize -> exchange -> token) so each
link produces a genuine ``provider_connections`` row, while the external profile
is **simulated** and flagged ``sandbox=True``. The points themselves come from the
seeded ``loyalty_accounts`` rows, not from the connector.

To go live for a given program: register a real connector under that provider id
(``register_connector``) and replace the bodies below with real HTTP calls.
Nothing outside the connector needs to change.
=============================================================================
"""

from __future__ import annotations

from app.services.connectors.base import (
    ProviderConnector,
    ProviderProfile,
    ProviderReservation,
    ProviderToken,
)


class SandboxOrchestratorConnector(ProviderConnector):
    """A sandbox connector for one orchestrator ecosystem.

    One instance is registered per provider id (``sixt``, ``uber``, ...). It runs
    the OAuth-shaped flow and returns deterministic, sandbox-flagged data; it
    imports no reservations (orchestrator links carry points, not stays).
    """

    AUTHORIZE_ENDPOINT = "https://sandbox.staywallet.example/oauth2/authorize"

    def __init__(self, provider: str) -> None:
        self.provider = provider

    def authorize_url(self, state: str) -> str:
        """Return the (illustrative) authorize URL; informational in sandbox."""

        return (
            f"{self.AUTHORIZE_ENDPOINT}"
            f"?response_type=code&client_id=staywallet-sandbox"
            f"&provider={self.provider}&state={state}"
        )

    async def exchange_code(self, code: str) -> ProviderToken:
        """Return a deterministic sandbox token (no real network call)."""

        return ProviderToken(
            access_token=f"sandbox-token::{self.provider}::{code}", sandbox=True
        )

    async def fetch_profile(self, token: ProviderToken) -> ProviderProfile:
        """Return a simulated profile (no Genius tier for these programs)."""

        return ProviderProfile(
            genius_level=None,
            display_name=f"{self.provider} member (sandbox)",
            sandbox=True,
        )

    async def fetch_bookings(
        self, token: ProviderToken
    ) -> list[ProviderReservation]:
        """Orchestrator ecosystems import no reservations."""

        return []
