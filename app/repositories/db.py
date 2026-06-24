"""DB-backed implementations of the repository protocols.

Every repository takes an :class:`AsyncSession` (provided per request by
``app.db.session.get_session``) and conforms to the Protocols in
``app.repositories.base``. Mapping between ORM rows and the Pydantic API models
happens here, keeping services/routers persistence-agnostic.

All timestamps read from the DB are normalised to UTC so the API emits ``Z``
suffixes (see ``docs/api_contract.md``).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.check_in import CheckInConfirmation, DigitalKey
from app.models.connection import ProviderConnectionOut
from app.models.enums import CheckInStatus, OrderStatus
from app.models.menu import MenuItem
from app.models.order import Order, OrderLine
from app.models.stay import StayInfo
from app.models.travel import FeaturedDeal, ServiceCategory
from app.repositories.base import OrchestratorAccount
from app.db.models.connection import ProviderConnectionORM
from app.db.models.menu import MenuItemORM, OrderLineORM, OrderORM
from app.db.models.orchestrator import LoyaltyAccountORM, ProviderORM
from app.db.models.stay import CheckInORM, DigitalKeyORM, StayORM
from app.db.models.travel import (
    BookingORM,
    FeaturedDealORM,
    GuestORM,
    LoyaltyTransactionORM,
    TravelCategoryORM,
)


def _utc(value: datetime) -> datetime:
    """Return ``value`` as a UTC-aware datetime (so Pydantic emits ``Z``)."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# Stays
# --------------------------------------------------------------------------- #
def _to_stay_info(row: StayORM) -> StayInfo:
    return StayInfo(
        id=row.id,
        property_name=row.property_name,
        room_number=row.room_number,
        check_in_date=_utc(row.check_in_date),
        check_out_date=_utc(row.check_out_date),
        address=row.address,
    )


class DbStayRepository:
    """:class:`StayRepository` backed by the ``stays`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, stay_id: str) -> StayInfo | None:
        row = await self._session.get(StayORM, stay_id)
        return _to_stay_info(row) if row is not None else None


# --------------------------------------------------------------------------- #
# Menu
# --------------------------------------------------------------------------- #
def _to_menu_item(row: MenuItemORM) -> MenuItem:
    return MenuItem(
        id=row.id,
        name=row.name,
        description=row.description,
        price_cents=row.price_cents,
        category=row.category,
        image_url=row.image_url,
    )


class DbMenuRepository:
    """:class:`MenuRepository` backed by the ``menu_items`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[MenuItem]:
        result = await self._session.execute(
            select(MenuItemORM).order_by(MenuItemORM.sort_order, MenuItemORM.id)
        )
        return [_to_menu_item(row) for row in result.scalars().all()]

    async def get(self, item_id: str) -> MenuItem | None:
        row = await self._session.get(MenuItemORM, item_id)
        return _to_menu_item(row) if row is not None else None


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #
def _to_order(row: OrderORM) -> Order:
    return Order(
        id=row.id,
        stay_id=row.stay_id,
        lines=[
            OrderLine(
                item_id=line.item_id,
                name=line.name,
                price_cents=line.price_cents,
                quantity=line.quantity,
            )
            for line in row.lines
        ],
        subtotal_cents=row.subtotal_cents,
        discount_cents=row.discount_cents,
        total_cents=row.total_cents,
        status=OrderStatus(row.status),
        placed_at=_utc(row.placed_at),
    )


class DbOrderRepository:
    """:class:`OrderRepository` backed by ``orders`` + ``order_lines``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, order: Order) -> Order:
        row = OrderORM(
            id=order.id,
            stay_id=order.stay_id,
            subtotal_cents=order.subtotal_cents,
            discount_cents=order.discount_cents,
            total_cents=order.total_cents,
            status=order.status.value,
            placed_at=order.placed_at,
            lines=[
                OrderLineORM(
                    item_id=line.item_id,
                    name=line.name,
                    price_cents=line.price_cents,
                    quantity=line.quantity,
                    position=index,
                )
                for index, line in enumerate(order.lines)
            ],
        )
        self._session.add(row)
        await self._session.flush()
        return order

    async def list_for_stay(self, stay_id: str) -> list[Order]:
        result = await self._session.execute(
            select(OrderORM)
            .where(OrderORM.stay_id == stay_id)
            .options(selectinload(OrderORM.lines))
            .order_by(OrderORM.placed_at.desc(), OrderORM.id.desc())
        )
        return [_to_order(row) for row in result.scalars().all()]


# --------------------------------------------------------------------------- #
# Check-ins
# --------------------------------------------------------------------------- #
def _to_confirmation(row: CheckInORM) -> CheckInConfirmation:
    digital_key: DigitalKey | None = None
    if row.digital_key is not None:
        key = row.digital_key
        digital_key = DigitalKey(
            key_id=key.id,
            access_token=key.access_token,
            valid_from=_utc(key.valid_from),
            valid_until=_utc(key.valid_until),
        )
    return CheckInConfirmation(
        check_in_id=row.id,
        status=CheckInStatus(row.status),
        stay=_to_stay_info(row.stay),
        digital_key=digital_key,
        rejection_reason=row.rejection_reason,
    )


class DbCheckInRepository:
    """:class:`CheckInRepository` backed by ``check_ins`` + ``digital_keys``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        confirmation: CheckInConfirmation,
        *,
        rejection_reason: str | None = None,
    ) -> CheckInConfirmation:
        row = CheckInORM(
            id=confirmation.check_in_id,
            stay_id=confirmation.stay.id,
            status=confirmation.status.value,
            rejection_reason=rejection_reason,
            created_at=datetime.now(timezone.utc),
        )
        if confirmation.digital_key is not None:
            key = confirmation.digital_key
            row.digital_key = DigitalKeyORM(
                id=key.key_id,
                access_token=key.access_token,
                valid_from=key.valid_from,
                valid_until=key.valid_until,
            )
        self._session.add(row)
        await self._session.flush()
        return confirmation

    async def get(self, check_in_id: str) -> CheckInConfirmation | None:
        result = await self._session.execute(
            select(CheckInORM)
            .where(CheckInORM.id == check_in_id)
            .options(
                selectinload(CheckInORM.stay),
                selectinload(CheckInORM.digital_key),
            )
        )
        row = result.scalar_one_or_none()
        return _to_confirmation(row) if row is not None else None


# --------------------------------------------------------------------------- #
# Travel
# --------------------------------------------------------------------------- #
def _to_category(row: TravelCategoryORM) -> ServiceCategory:
    return ServiceCategory(
        id=row.id,
        name=row.name,
        subtitle=row.subtitle,
        icon=row.icon,
        accent=row.accent,
        featured=row.featured,
    )


def _to_deal(row: FeaturedDealORM) -> FeaturedDeal:
    return FeaturedDeal(
        id=row.id,
        title=row.title,
        subtitle=row.subtitle,
        image_url=row.image_url,
        badge=row.badge,
        discount_label=row.discount_label,
        discount_note=row.discount_note,
    )


class DbTravelRepository:
    """:class:`TravelRepository` backed by travel tables + ``bookings``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_categories(self) -> list[ServiceCategory]:
        result = await self._session.execute(
            select(TravelCategoryORM).order_by(
                TravelCategoryORM.sort_order, TravelCategoryORM.id
            )
        )
        return [_to_category(row) for row in result.scalars().all()]

    async def get_category(self, category_id: str) -> ServiceCategory | None:
        row = await self._session.get(TravelCategoryORM, category_id)
        return _to_category(row) if row is not None else None

    async def list_deals(self) -> list[FeaturedDeal]:
        result = await self._session.execute(
            select(FeaturedDealORM).order_by(
                FeaturedDealORM.sort_order, FeaturedDealORM.id
            )
        )
        return [_to_deal(row) for row in result.scalars().all()]

    async def get_deal(self, deal_id: str) -> FeaturedDeal | None:
        row = await self._session.get(FeaturedDealORM, deal_id)
        return _to_deal(row) if row is not None else None

    async def category_base_price_cents(self, category_id: str) -> int | None:
        row = await self._session.get(TravelCategoryORM, category_id)
        return row.base_price_cents if row is not None else None

    async def deal_base_price_cents(self, deal_id: str) -> int | None:
        row = await self._session.get(FeaturedDealORM, deal_id)
        return row.base_price_cents if row is not None else None

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
        self._session.add(
            BookingORM(
                id=booking_id,
                guest_id=guest_id,
                category_id=category_id,
                deal_id=deal_id,
                title=title,
                total_cents=total_cents,
                points_earned=points_earned,
                created_at=datetime.now(timezone.utc),
            )
        )
        await self._session.flush()


# --------------------------------------------------------------------------- #
# Loyalty ledger
# --------------------------------------------------------------------------- #
class DbLoyaltyRepository:
    """:class:`LoyaltyRepository` backed by ``loyalty_transactions``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def balance(self, guest_id: str) -> int:
        result = await self._session.execute(
            select(
                func.coalesce(func.sum(LoyaltyTransactionORM.amount), 0)
            ).where(LoyaltyTransactionORM.guest_id == guest_id)
        )
        return int(result.scalar_one())

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
        self._session.add(
            LoyaltyTransactionORM(
                guest_id=guest_id,
                amount=amount,
                kind=kind,
                source=source,
                reference_id=reference_id,
                description=description,
                created_at=datetime.now(timezone.utc),
            )
        )
        await self._session.flush()

    async def guest_exists(self, guest_id: str) -> bool:
        row = await self._session.get(GuestORM, guest_id)
        return row is not None


# --------------------------------------------------------------------------- #
# Provider connections
# --------------------------------------------------------------------------- #
def _to_connection(row: ProviderConnectionORM) -> ProviderConnectionOut:
    return ProviderConnectionOut(
        connection_id=row.id,
        provider=row.provider,
        status=row.status,
        scopes=list(row.scopes or []),
        genius_level=row.genius_level,
        imported_stays=row.imported_stays,
        connected_at=_utc(row.connected_at),
        sandbox=row.sandbox,
    )


class DbConnectionRepository:
    """:class:`ConnectionRepository` backed by ``provider_connections``.

    Imported reservations are stored as ``stays`` rows tagged
    ``source='booking.com'`` and linked via ``provider_connection_id``, keyed by
    a deterministic ``external_ref`` for idempotent re-imports.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        self._session.add(
            ProviderConnectionORM(
                id=connection_id,
                guest_id=guest_id,
                provider=provider,
                status=status,
                scopes=scopes,
                genius_level=genius_level,
                imported_stays=0,
                sandbox=sandbox,
                access_token=access_token,
                connected_at=connected_at,
                created_at=datetime.now(timezone.utc),
            )
        )
        await self._session.flush()

    async def set_imported_stays(self, connection_id: str, count: int) -> None:
        row = await self._session.get(ProviderConnectionORM, connection_id)
        if row is not None:
            row.imported_stays = count
            await self._session.flush()

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
        result = await self._session.execute(
            select(StayORM).where(StayORM.external_ref == external_ref)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.provider_connection_id = connection_id
            existing.property_name = property_name
            existing.room_number = room
            existing.check_in_date = check_in
            existing.check_out_date = check_out
            existing.address = address
            existing.source = "booking.com"
        else:
            # Deterministic stay id derived from the external ref so the same
            # reservation always maps to the same stay row.
            stay_id = "stay_" + external_ref.split(":", 1)[-1]
            self._session.add(
                StayORM(
                    id=stay_id,
                    property_name=property_name,
                    room_number=room,
                    check_in_date=check_in,
                    check_out_date=check_out,
                    address=address,
                    source="booking.com",
                    provider_connection_id=connection_id,
                    external_ref=external_ref,
                )
            )
        await self._session.flush()

    async def clear_imported_stays(self, connection_id: str) -> None:
        await self._session.execute(
            delete(StayORM).where(
                StayORM.provider_connection_id == connection_id
            )
        )
        await self._session.flush()

    async def get(self, connection_id: str) -> ProviderConnectionOut | None:
        row = await self._session.get(ProviderConnectionORM, connection_id)
        return _to_connection(row) if row is not None else None

    async def list_for_guest(
        self, guest_id: str
    ) -> list[ProviderConnectionOut]:
        result = await self._session.execute(
            select(ProviderConnectionORM)
            .where(ProviderConnectionORM.guest_id == guest_id)
            .order_by(
                ProviderConnectionORM.connected_at.desc(),
                ProviderConnectionORM.id.desc(),
            )
        )
        return [_to_connection(row) for row in result.scalars().all()]

    async def delete(self, connection_id: str) -> bool:
        row = await self._session.get(ProviderConnectionORM, connection_id)
        if row is None:
            return False
        # Keep imported stays; the FK's ON DELETE SET NULL (with
        # passive_deletes=True on the relationship) nulls their
        # provider_connection_id at the DB level so the stays survive the unlink.
        await self._session.delete(row)
        await self._session.flush()
        return True


# --------------------------------------------------------------------------- #
# Loyalty Orchestrator (provider catalog + per-guest accounts)
# --------------------------------------------------------------------------- #
def _to_orchestrator_account(
    account: LoyaltyAccountORM, provider: ProviderORM
) -> OrchestratorAccount:
    return OrchestratorAccount(
        provider_id=provider.id,
        name=provider.name,
        brand_color_hex=provider.brand_color_hex,
        logo_url=provider.logo_url,
        icon=provider.icon,
        sort_order=provider.sort_order,
        linked=account.linked,
        discovered=account.discovered,
        points=account.points,
        detected_label=account.detected_label,
        created_at=_utc(account.created_at),
    )


class DbOrchestratorRepository:
    """:class:`OrchestratorRepository` backed by ``providers`` + ``loyalty_accounts``.

    A guest's accounts are joined to the catalog so the service gets brand
    metadata (colour/icon/name) alongside the per-guest linked/discovered state,
    ordered by the catalog ``sort_order`` so the grid's top row is deterministic.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def provider_exists(self, provider_id: str) -> bool:
        row = await self._session.get(ProviderORM, provider_id)
        return row is not None

    async def list_accounts(self, guest_id: str) -> list[OrchestratorAccount]:
        result = await self._session.execute(
            select(LoyaltyAccountORM, ProviderORM)
            .join(ProviderORM, LoyaltyAccountORM.provider_id == ProviderORM.id)
            .where(LoyaltyAccountORM.guest_id == guest_id)
            .order_by(ProviderORM.sort_order, ProviderORM.id)
        )
        return [
            _to_orchestrator_account(account, provider)
            for account, provider in result.all()
        ]

    async def get_account(
        self, guest_id: str, provider_id: str
    ) -> OrchestratorAccount | None:
        result = await self._session.execute(
            select(LoyaltyAccountORM, ProviderORM)
            .join(ProviderORM, LoyaltyAccountORM.provider_id == ProviderORM.id)
            .where(
                LoyaltyAccountORM.guest_id == guest_id,
                LoyaltyAccountORM.provider_id == provider_id,
            )
        )
        row = result.first()
        if row is None:
            return None
        account, provider = row
        return _to_orchestrator_account(account, provider)

    async def _get_account_row(
        self, guest_id: str, provider_id: str
    ) -> LoyaltyAccountORM | None:
        result = await self._session.execute(
            select(LoyaltyAccountORM).where(
                LoyaltyAccountORM.guest_id == guest_id,
                LoyaltyAccountORM.provider_id == provider_id,
            )
        )
        return result.scalar_one_or_none()

    async def link_account(self, guest_id: str, provider_id: str) -> int:
        """Flip the discovered account to linked and return its points.

        The points already live on the row (seeded as the detected amount); the
        aggregate is always SUM(points WHERE linked), so flipping the flags folds
        the ecosystem into the total atomically within the request transaction.
        """

        row = await self._get_account_row(guest_id, provider_id)
        if row is None:
            return 0
        row.linked = True
        row.discovered = False
        await self._session.flush()
        return int(row.points or 0)

    async def link_all_discovered(self, guest_id: str) -> int:
        result = await self._session.execute(
            select(LoyaltyAccountORM).where(
                LoyaltyAccountORM.guest_id == guest_id,
                LoyaltyAccountORM.discovered.is_(True),
            )
        )
        rows = list(result.scalars().all())
        for row in rows:
            row.linked = True
            row.discovered = False
        await self._session.flush()
        return len(rows)
