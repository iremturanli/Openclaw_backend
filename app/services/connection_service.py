"""Provider-connection business logic (account linking + sync).

Orchestrates the connector framework: resolve the provider's connector, run the
OAuth-shaped authorize -> exchange flow, then sync profile/bookings into real
rows -- all inside the request's unit of work so the connection row, imported
stays and Genius level commit (or roll back) together.

The Booking.com connector runs in sandbox mode (simulated external data, flagged
``sandbox=True``); this service is provider-agnostic and unaware of that, so a
real partner API swaps in by replacing only the connector.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from app.models.connection import ProviderConnectionOut
from app.repositories.base import ConnectionRepository, LoyaltyRepository
from app.services.connectors import ProviderConnector, get_connector
from app.services.exceptions import ConnectionNotFoundError, GuestNotFoundError

# Recognised scopes (validated for shape by the Pydantic model; semantics here).
SCOPE_IMPORT_BOOKINGS = "import_bookings"
SCOPE_SYNC_GENIUS = "sync_genius"
SCOPE_EXPENSE_TRACKING = "expense_tracking"


class ConnectionService:
    """Links external provider accounts and syncs their data atomically."""

    def __init__(
        self,
        connection_repository: ConnectionRepository,
        loyalty_repository: LoyaltyRepository,
    ) -> None:
        self._connections = connection_repository
        # LoyaltyRepository is reused only for its guest_exists check.
        self._guests = loyalty_repository

    async def link(
        self, guest_id: str, provider: str, scopes: list[str]
    ) -> ProviderConnectionOut:
        """Link ``provider`` for ``guest_id`` with ``scopes`` and sync.

        Steps (atomic within the request transaction):
          1. Validate the guest and resolve the connector for ``provider``.
          2. Run the OAuth-shaped flow: authorize -> exchange_code -> token.
          3. Create the ``provider_connections`` row.
          4. If ``sync_genius``: fetch profile, store ``genius_level``.
          5. If ``import_bookings``: clear+reimport reservations as ``stays``
             (source='booking.com'), keyed by external_ref so re-linking does
             not duplicate; cache the imported count.
          6. ``expense_tracking`` is recorded as a granted scope (no-op data).

        Raises:
            GuestNotFoundError: If ``guest_id`` is unknown.
            UnknownProviderError: If no connector exists for ``provider`` (404).
        """

        if not await self._guests.guest_exists(guest_id):
            raise GuestNotFoundError(guest_id)

        connector: ProviderConnector = get_connector(provider)

        # OAuth-shaped flow. In sandbox mode authorize_url is informational and
        # exchange_code returns a deterministic placeholder token.
        state = secrets.token_urlsafe(16)
        connector.authorize_url(state)
        token = await connector.exchange_code(code=f"sandbox-code::{state}")

        connection_id = f"conn_{secrets.token_hex(6)}"
        connected_at = datetime.now(timezone.utc)

        genius_level: int | None = None
        if SCOPE_SYNC_GENIUS in scopes:
            profile = await connector.fetch_profile(token)
            genius_level = profile.genius_level

        await self._connections.create(
            connection_id=connection_id,
            guest_id=guest_id,
            provider=provider,
            status="linked",
            scopes=scopes,
            genius_level=genius_level,
            sandbox=token.sandbox,
            access_token=token.access_token,
            connected_at=connected_at,
        )

        imported_count = 0
        if SCOPE_IMPORT_BOOKINGS in scopes:
            # Clear any stays previously imported for THIS connection, then
            # re-import; combined with the unique external_ref this keeps
            # re-linking idempotent (no duplicate stays).
            await self._connections.clear_imported_stays(connection_id)
            reservations = await connector.fetch_bookings(token)
            for res in reservations:
                await self._connections.upsert_imported_stay(
                    connection_id=connection_id,
                    external_ref=res.external_ref,
                    property_name=res.property_name,
                    room=res.room,
                    check_in=res.check_in,
                    check_out=res.check_out,
                    address=res.address,
                )
            imported_count = len(reservations)
            await self._connections.set_imported_stays(
                connection_id, imported_count
            )

        # expense_tracking: scope is persisted on the connection row above; no
        # additional data to write yet.

        connection = await self._connections.get(connection_id)
        assert connection is not None  # just created in this transaction
        return connection

    async def list(self, guest_id: str) -> list[ProviderConnectionOut]:
        """Return all provider connections for ``guest_id``."""

        return await self._connections.list_for_guest(guest_id)

    async def unlink(self, connection_id: str) -> None:
        """Delete a connection. Imported stays are kept (their FK is nulled).

        Raises:
            ConnectionNotFoundError: If ``connection_id`` is unknown (404).
        """

        deleted = await self._connections.delete(connection_id)
        if not deleted:
            raise ConnectionNotFoundError(connection_id)
