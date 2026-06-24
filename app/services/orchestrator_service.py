"""Loyalty Orchestrator business logic (cross-ecosystem aggregator).

Aggregates a guest's loyalty points across linked ecosystems and surfaces
"discovered" programs they could link. Built on the provider catalog
(``providers``), per-guest accounts (``loyalty_accounts``) and the connector
framework: linking a discovered ecosystem flips its account to linked AND creates
a real, sandbox-flagged ``provider_connections`` row via the connector framework,
so every link is auditable like any other connection.

Aggregation rules (see ``backend/README.md`` -> "Loyalty Orchestrator"):

* ``totalPoints``     = SUM(points) over the guest's **linked** accounts.
* ``ecosystemsCount`` = number of linked accounts.
* ``ecosystemsNew``   = linked accounts created within the trailing
  ``orchestrator_new_window_days`` window (recently linked).
* ``trendPct``        = configured headline growth metric.
* ``integrations``    = linked accounts (points set), brand-ordered.
* ``discovered``      = discovered-but-not-linked accounts (detectedLabel set).

All point/state changes happen inside the request's unit of work, so a link (and
its connection row) commit atomically.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import Settings, get_settings
from app.models.orchestrator import OrchestratorProvider, OrchestratorSummary
from app.repositories.base import (
    ConnectionRepository,
    LoyaltyRepository,
    OrchestratorAccount,
    OrchestratorRepository,
)
from app.services.connectors import ProviderConnector, register_connector
from app.services.connectors.registry import _REGISTRY
from app.services.connectors.sandbox import SandboxOrchestratorConnector
from app.services.exceptions import (
    GuestNotFoundError,
    OrchestratorProviderNotFoundError,
    ProviderAlreadyLinkedError,
)


class OrchestratorService:
    """Computes orchestrator summaries and links ecosystems atomically."""

    def __init__(
        self,
        orchestrator_repository: OrchestratorRepository,
        connection_repository: ConnectionRepository,
        loyalty_repository: LoyaltyRepository,
        settings: Settings | None = None,
    ) -> None:
        self._accounts = orchestrator_repository
        self._connections = connection_repository
        self._guests = loyalty_repository
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    async def get_summary(self, guest_id: str) -> OrchestratorSummary:
        """Return the aggregate :class:`OrchestratorSummary` for ``guest_id``."""

        accounts = await self._accounts.list_accounts(guest_id)
        return self._build_summary(accounts)

    def _build_summary(
        self, accounts: list[OrchestratorAccount]
    ) -> OrchestratorSummary:
        integrations = [
            self._to_provider(a) for a in accounts if a.linked
        ]
        discovered = [
            self._to_provider(a) for a in accounts if a.discovered and not a.linked
        ]
        total_points = sum(a.points or 0 for a in accounts if a.linked)
        ecosystems_new = self._count_recent(accounts)
        return OrchestratorSummary(
            total_points=total_points,
            trend_pct=self._settings.orchestrator_trend_pct,
            ecosystems_count=len(integrations),
            ecosystems_new=ecosystems_new,
            integrations=integrations,
            discovered=discovered,
        )

    def _count_recent(self, accounts: list[OrchestratorAccount]) -> int:
        """Count linked accounts created within the trailing 'new' window."""

        cutoff = datetime.now(timezone.utc) - timedelta(
            days=self._settings.orchestrator_new_window_days
        )
        recent = 0
        for account in accounts:
            if not account.linked:
                continue
            created = account.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created >= cutoff:
                recent += 1
        return recent

    @staticmethod
    def _to_provider(account: OrchestratorAccount) -> OrchestratorProvider:
        return OrchestratorProvider(
            id=account.provider_id,
            name=account.name,
            brand_color_hex=account.brand_color_hex,
            linked=account.linked,
            logo_url=account.logo_url,
            icon=account.icon,
            points=account.points if account.linked else None,
            detected_label=None if account.linked else account.detected_label,
        )

    # ------------------------------------------------------------------ #
    # Link
    # ------------------------------------------------------------------ #
    async def link(self, guest_id: str, provider_id: str) -> OrchestratorSummary:
        """Link one discovered ecosystem and return the refreshed summary.

        Raises:
            GuestNotFoundError: unknown guest (404).
            OrchestratorProviderNotFoundError: unknown provider id (404).
            ProviderAlreadyLinkedError: provider already linked (409).
        """

        if not await self._guests.guest_exists(guest_id):
            raise GuestNotFoundError(guest_id)
        if not await self._accounts.provider_exists(provider_id):
            raise OrchestratorProviderNotFoundError(provider_id)

        account = await self._accounts.get_account(guest_id, provider_id)
        if account is not None and account.linked:
            raise ProviderAlreadyLinkedError(provider_id)
        if account is None:
            # Provider exists in the catalog but the guest has no account row
            # for it: nothing was discovered to link.
            raise OrchestratorProviderNotFoundError(provider_id)

        await self._accounts.link_account(guest_id, provider_id)
        await self._create_sandbox_connection(guest_id, provider_id)

        accounts = await self._accounts.list_accounts(guest_id)
        return self._build_summary(accounts)

    async def auto_scan(self, guest_id: str) -> OrchestratorSummary:
        """Link every discovered ecosystem and return the refreshed summary."""

        if not await self._guests.guest_exists(guest_id):
            raise GuestNotFoundError(guest_id)

        discovered_before = [
            a
            for a in await self._accounts.list_accounts(guest_id)
            if a.discovered and not a.linked
        ]
        await self._accounts.link_all_discovered(guest_id)
        for account in discovered_before:
            await self._create_sandbox_connection(guest_id, account.provider_id)

        accounts = await self._accounts.list_accounts(guest_id)
        return self._build_summary(accounts)

    # ------------------------------------------------------------------ #
    # Connector framework integration
    # ------------------------------------------------------------------ #
    async def _create_sandbox_connection(
        self, guest_id: str, provider_id: str
    ) -> None:
        """Run the OAuth-shaped sandbox flow and persist a connection row.

        Reuses the connector framework so each orchestrator link is a real,
        auditable ``provider_connections`` row flagged ``sandbox=True`` (the
        external membership data is simulated until real partner APIs exist).
        """

        connector = self._connector_for(provider_id)
        state = secrets.token_urlsafe(16)
        connector.authorize_url(state)
        token = await connector.exchange_code(code=f"sandbox-code::{state}")

        await self._connections.create(
            connection_id=f"conn_{secrets.token_hex(6)}",
            guest_id=guest_id,
            provider=f"orchestrator:{provider_id}",
            status="linked",
            scopes=["loyalty_points"],
            genius_level=None,
            sandbox=token.sandbox,
            access_token=token.access_token,
            connected_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _connector_for(provider_id: str) -> ProviderConnector:
        """Return (registering on first use) the sandbox connector for an id."""

        key = f"orchestrator:{provider_id}"
        connector = _REGISTRY.get(key)
        if connector is None:
            connector = SandboxOrchestratorConnector(provider=key)
            register_connector(connector)
        return connector
