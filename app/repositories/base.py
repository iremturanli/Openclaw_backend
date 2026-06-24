"""Repository interfaces (Protocols).

These define the async persistence contract the service layer depends on. The
DB-backed implementations (``app/repositories/db.py``) conform to them; the
services and routers depend only on these Protocols, so persistence can be
swapped without touching business logic.
"""

from __future__ import annotations

from typing import Protocol

from datetime import datetime

from app.models.check_in import CheckInConfirmation
from app.models.connection import ProviderConnectionOut
from app.models.menu import MenuItem
from app.models.orchestrator import OrchestratorProvider
from app.models.order import Order
from app.models.stay import StayInfo
from app.models.travel import FeaturedDeal, ServiceCategory


class StayRepository(Protocol):
    """Read access to bookings."""

    async def get(self, stay_id: str) -> StayInfo | None:
        """Return the stay with ``stay_id`` or ``None`` if it does not exist."""
        ...


class MenuRepository(Protocol):
    """Read access to the room-service menu."""

    async def list(self) -> list[MenuItem]:
        """Return all menu items."""
        ...

    async def get(self, item_id: str) -> MenuItem | None:
        """Return the menu item with ``item_id`` or ``None`` if unknown."""
        ...


class OrderRepository(Protocol):
    """Persistence for placed room-service orders."""

    async def save(self, order: Order) -> Order:
        """Persist ``order`` and return it."""
        ...

    async def list_for_stay(self, stay_id: str) -> list[Order]:
        """Return the stay's orders, most recent first."""
        ...


class CheckInRepository(Protocol):
    """Persistence for completed/attempted check-ins."""

    async def save(
        self, confirmation: CheckInConfirmation, *, rejection_reason: str | None = None
    ) -> CheckInConfirmation:
        """Persist ``confirmation`` and return it."""
        ...

    async def get(self, check_in_id: str) -> CheckInConfirmation | None:
        """Return the check-in with ``check_in_id`` or ``None``."""
        ...


class TravelRepository(Protocol):
    """Read access to travel categories and featured deals, plus bookings."""

    async def list_categories(self) -> list[ServiceCategory]:
        """Return all travel-service categories (sorted)."""
        ...

    async def get_category(self, category_id: str) -> ServiceCategory | None:
        """Return the category or ``None`` if unknown."""
        ...

    async def list_deals(self) -> list[FeaturedDeal]:
        """Return all featured deals (sorted)."""
        ...

    async def get_deal(self, deal_id: str) -> FeaturedDeal | None:
        """Return the featured deal or ``None`` if unknown."""
        ...

    async def category_base_price_cents(self, category_id: str) -> int | None:
        """Return the indicative price (cents) of a category, or ``None``."""
        ...

    async def deal_base_price_cents(self, deal_id: str) -> int | None:
        """Return the indicative price (cents) of a deal, or ``None``."""
        ...

    async def create_booking(
        self,
        *,
        booking_id: str,
        guest_id: str,
        category_id: str | None,
        deal_id: str | None,
        title: str,
        total_cents: int,
        points_earned: int,
    ) -> None:
        """Persist a confirmed booking row."""
        ...


class LoyaltyRepository(Protocol):
    """Persistence for the loyalty ledger (append-only transactions)."""

    async def balance(self, guest_id: str) -> int:
        """Return the guest's balance as SUM(amount) over their ledger rows."""
        ...

    async def add_transaction(
        self,
        *,
        guest_id: str,
        amount: int,
        kind: str,
        source: str,
        reference_id: str | None,
        description: str,
    ) -> None:
        """Append an immutable ledger row (earn: amount>0, redeem: amount<0)."""
        ...

    async def guest_exists(self, guest_id: str) -> bool:
        """Return ``True`` if a guest with ``guest_id`` exists."""
        ...


class ConnectionRepository(Protocol):
    """Persistence for provider connections and their imported stays."""

    async def create(
        self,
        *,
        connection_id: str,
        guest_id: str,
        provider: str,
        status: str,
        scopes: list[str],
        genius_level: int | None,
        sandbox: bool,
        access_token: str | None,
        connected_at: datetime,
    ) -> None:
        """Persist a new provider-connection row."""
        ...

    async def set_imported_stays(self, connection_id: str, count: int) -> None:
        """Update the cached imported-stays count on a connection."""
        ...

    async def upsert_imported_stay(
        self,
        *,
        connection_id: str,
        external_ref: str,
        property_name: str,
        room: str,
        check_in: datetime,
        check_out: datetime,
        address: str,
    ) -> None:
        """Insert or update an imported stay keyed by ``external_ref``.

        Idempotent: re-linking the same reservation updates the existing stay
        instead of creating a duplicate.
        """
        ...

    async def clear_imported_stays(self, connection_id: str) -> None:
        """Delete all stays imported via ``connection_id`` (for clean re-import)."""
        ...

    async def get(self, connection_id: str) -> ProviderConnectionOut | None:
        """Return the connection or ``None`` if unknown."""
        ...

    async def list_for_guest(self, guest_id: str) -> list[ProviderConnectionOut]:
        """Return the guest's connections, most recent first."""
        ...

    async def delete(self, connection_id: str) -> bool:
        """Delete the connection (keeping imported stays, nulling their FK).

        Return ``True`` if a row was deleted, ``False`` if it did not exist.
        """
        ...


class OrchestratorAccount:
    """A guest's account row joined with its catalog provider (DTO).

    Plain attribute holder returned by :class:`OrchestratorRepository`; the
    service maps it to the API :class:`OrchestratorProvider`. Defined as a small
    dataclass-like value object so the service stays persistence-agnostic.
    """

    __slots__ = (
        "provider_id",
        "name",
        "brand_color_hex",
        "logo_url",
        "icon",
        "sort_order",
        "linked",
        "discovered",
        "points",
        "detected_label",
        "created_at",
    )

    def __init__(
        self,
        *,
        provider_id: str,
        name: str,
        brand_color_hex: str,
        logo_url: str | None,
        icon: str | None,
        sort_order: int,
        linked: bool,
        discovered: bool,
        points: int | None,
        detected_label: str | None,
        created_at: datetime,
    ) -> None:
        self.provider_id = provider_id
        self.name = name
        self.brand_color_hex = brand_color_hex
        self.logo_url = logo_url
        self.icon = icon
        self.sort_order = sort_order
        self.linked = linked
        self.discovered = discovered
        self.points = points
        self.detected_label = detected_label
        self.created_at = created_at


class OrchestratorRepository(Protocol):
    """Persistence for the Loyalty Orchestrator (catalog + guest accounts)."""

    async def provider_exists(self, provider_id: str) -> bool:
        """Return ``True`` if ``provider_id`` is in the catalog."""
        ...

    async def list_accounts(self, guest_id: str) -> list["OrchestratorAccount"]:
        """Return the guest's accounts (linked + discovered), provider-ordered."""
        ...

    async def get_account(
        self, guest_id: str, provider_id: str
    ) -> "OrchestratorAccount | None":
        """Return one account row for the guest+provider, or ``None``."""
        ...

    async def link_account(self, guest_id: str, provider_id: str) -> int:
        """Flip a discovered account to linked, folding in its points.

        Returns the points contributed by the now-linked ecosystem.
        """
        ...

    async def link_all_discovered(self, guest_id: str) -> int:
        """Link every discovered account for the guest. Returns count linked."""
        ...
