"""Room-service ordering business logic.

Pricing is **server-authoritative**: the client only sends ``itemId`` +
``quantity``; this service resolves the canonical name/price from the seeded
menu and recomputes subtotal, discount and total. Client-supplied totals are
never trusted.

Validation policy (documented for the contract):

* Unknown stay      -> :class:`StayNotFoundError`        (router returns 404).
* Unknown item id   -> :class:`MenuItemNotFoundError`    (router returns 404).
* Empty ``lines`` / ``quantity < 1`` are rejected by Pydantic at the boundary
  and surface as HTTP 422.

Money is integer cents throughout. The 15% StayWallet member discount rate is
centralised in :class:`Settings.member_discount_rate`.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from app.core.config import Settings, get_settings
from app.models.order import Order, OrderLine, OrderRequest
from app.models.enums import OrderStatus
from app.repositories.base import MenuRepository, OrderRepository, StayRepository
from app.services.exceptions import MenuItemNotFoundError, StayNotFoundError
from app.services.loyalty_service import LoyaltyService


class OrderService:
    """Orchestrates pricing, placement and retrieval of room-service orders.

    On placement the service also writes a loyalty **earn** row through the
    shared :class:`LoyaltyService`, so room service and travel bookings accrue
    points via the same ledger. The earn row is flushed inside the same request
    transaction as the order — points and the order commit (or roll back)
    atomically.
    """

    def __init__(
        self,
        stay_repository: StayRepository,
        menu_repository: MenuRepository,
        order_repository: OrderRepository,
        loyalty_service: LoyaltyService,
        settings: Settings | None = None,
    ) -> None:
        self._stays = stay_repository
        self._menu = menu_repository
        self._orders = order_repository
        self._loyalty = loyalty_service
        self._settings = settings or get_settings()

    @property
    def discount_rate(self) -> float:
        """The StayWallet member discount rate (fraction of subtotal)."""

        return self._settings.member_discount_rate

    async def get_menu(self, stay_id: str) -> list:
        """Return the room-service menu for ``stay_id``.

        Raises:
            StayNotFoundError: If ``stay_id`` is unknown.
        """

        if await self._stays.get(stay_id) is None:
            raise StayNotFoundError(stay_id)
        return await self._menu.list()

    async def place_order(
        self,
        stay_id: str,
        request: OrderRequest,
        *,
        now: datetime | None = None,
    ) -> Order:
        """Price and persist a new order with server-authoritative totals.

        Raises:
            StayNotFoundError: If ``stay_id`` is unknown.
            MenuItemNotFoundError: If any line references an unknown item.
        """

        if await self._stays.get(stay_id) is None:
            raise StayNotFoundError(stay_id)

        priced_lines: list[OrderLine] = []
        subtotal_cents = 0
        for line in request.lines:
            item = await self._menu.get(line.item_id)
            if item is None:
                raise MenuItemNotFoundError(line.item_id)
            subtotal_cents += item.price_cents * line.quantity
            priced_lines.append(
                OrderLine(
                    item_id=item.id,
                    name=item.name,
                    price_cents=item.price_cents,
                    quantity=line.quantity,
                )
            )

        discount_cents = round(subtotal_cents * self.discount_rate)
        total_cents = subtotal_cents - discount_cents

        order = Order(
            id=f"ord_{secrets.token_hex(6)}",
            stay_id=stay_id,
            lines=priced_lines,
            subtotal_cents=subtotal_cents,
            discount_cents=discount_cents,
            total_cents=total_cents,
            status=OrderStatus.PLACED,
            placed_at=now or datetime.now(timezone.utc),
        )
        saved = await self._orders.save(order)

        # Cross-feature integration: room-service orders earn loyalty points on
        # the order total (1x multiplier), atomically within this transaction.
        await self._loyalty.earn(
            guest_id=self._settings.demo_guest_id,
            total_cents=saved.total_cents,
            source="order",
            reference_id=saved.id,
            description=f"Room service order {saved.id}",
            multiplier=1,
        )
        return saved

    async def list_orders(self, stay_id: str) -> list[Order]:
        """Return the stay's orders, most recent first.

        Raises:
            StayNotFoundError: If ``stay_id`` is unknown.
        """

        if await self._stays.get(stay_id) is None:
            raise StayNotFoundError(stay_id)
        return await self._orders.list_for_stay(stay_id)
