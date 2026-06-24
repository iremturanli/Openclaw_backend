"""Idempotent database seed.

Run after migrations::

    python -m app.db.seed

Seeds the demo guest, stays, room-service menu, travel categories, the featured
Porsche deal, and a loyalty ledger that sums to exactly **12450** points for
``guest_demo`` (so the UI shows a real, ledger-derived balance — never a
hardcoded constant). Re-running is safe: existing rows are upserted by primary
key and the loyalty ledger is only seeded if the guest has no rows yet.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.db.models.menu import MenuItemORM
from app.db.models.orchestrator import LoyaltyAccountORM, ProviderORM
from app.db.models.stay import StayORM
from app.db.models.travel import (
    FeaturedDealORM,
    GuestORM,
    LoyaltyTransactionORM,
    TravelCategoryORM,
)
from app.db.models.user import UserORM
from app.db.session import get_sessionmaker

DEMO_GUEST_ID = "guest_demo"

# A ready-to-use demo login mapped to the seeded ``guest_demo`` loyalty data, so
# signing in shows the full rich dashboard (points, ecosystems, ledger).
DEMO_USER_ID = "usr_demo"
DEMO_USER_EMAIL = "demo@staywallet.app"
DEMO_USER_PASSWORD = "staywallet1"
PORSCHE_IMAGE_URL = (
    "https://images.unsplash.com/photo-1503376780353-7e6692767b70"
    "?auto=format&fit=crop&w=1200&q=80"
)


def _dt(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


async def _upsert(session: AsyncSession, model, rows: list[dict]) -> None:
    """Insert rows that don't already exist (by primary key ``id``)."""

    for data in rows:
        existing = await session.get(model, data["id"])
        if existing is None:
            session.add(model(**data))
        else:
            for key, value in data.items():
                if key != "id":
                    setattr(existing, key, value)


async def _seed_guest(session: AsyncSession) -> None:
    await _upsert(
        session,
        GuestORM,
        [
            {
                "id": DEMO_GUEST_ID,
                "display_name": "Ahmet Yılmaz",
                "created_at": _dt(2026, 1, 1, 9, 0),
            }
        ],
    )


async def _seed_demo_user(session: AsyncSession) -> None:
    """Create (or adopt) the demo login and map it to ``guest_demo``.

    Idempotent + collision-safe: if a user already exists under the demo EMAIL
    (e.g. created via an earlier sign-up under a generated id), we must NOT try
    to insert a second ``usr_demo`` row — that violates the unique-email
    constraint and rolls back the entire seed. Instead we *adopt* the existing
    row, pointing its ``guest_id`` at the seeded ``guest_demo`` so the demo login
    sees all the seeded loyalty / orchestrator / stay data.
    """
    existing = await session.get(UserORM, DEMO_USER_ID)
    if existing is not None:
        existing.guest_id = DEMO_GUEST_ID
        existing.phone_number = existing.phone_number or "+905551112233"
        return

    by_email = await session.scalar(
        select(UserORM).where(UserORM.email == DEMO_USER_EMAIL)
    )
    if by_email is not None:
        # A stray demo user (different id) already owns the email — adopt it.
        by_email.guest_id = DEMO_GUEST_ID
        by_email.phone_number = by_email.phone_number or "+905551112233"
        return

    session.add(
        UserORM(
            id=DEMO_USER_ID,
            email=DEMO_USER_EMAIL,
            hashed_password=security.hash_password(DEMO_USER_PASSWORD),
            full_name="Ahmet Yılmaz",
            phone_number="+905551112233",
            guest_id=DEMO_GUEST_ID,
            created_at=_dt(2026, 1, 1, 9, 0),
        )
    )


async def _seed_paxpal(session: AsyncSession) -> None:
    """PaxPal demo: two real companion accounts, a travel group with shared
    expenses, and one issued PaxCard. The companions are REAL users (login
    works) so settle-up moves real wallet balances between accounts."""

    from app.db.models.paxpal import (
        ExpenseGroupORM,
        GroupExpenseORM,
        GroupMemberORM,
        PaxCardORM,
    )

    companions = [
        ("usr_mert", "mert@staywallet.app", "Mert Aksoy", "guest_mert"),
        ("usr_lara", "lara@staywallet.app", "Lara Demir", "guest_lara"),
    ]
    for user_id, email, name, guest_id in companions:
        await _upsert(
            session,
            GuestORM,
            [{"id": guest_id, "display_name": name,
              "created_at": _dt(2026, 6, 1, 9, 0)}],
        )
        if await session.get(UserORM, user_id) is None:
            session.add(
                UserORM(
                    id=user_id,
                    email=email,
                    hashed_password=security.hash_password(DEMO_USER_PASSWORD),
                    full_name=name,
                    phone_number=f"+90555000{user_id[-2:]}{user_id[-2:]}",
                    guest_id=guest_id,
                    created_at=_dt(2026, 6, 1, 9, 0),
                )
            )
        else:
            existing_user = await session.get(UserORM, user_id)
            if existing_user is not None:
                existing_user.phone_number = (
                    existing_user.phone_number
                    or f"+90555000{user_id[-2:]}{user_id[-2:]}"
                )

    await _upsert(
        session,
        ExpenseGroupORM,
        [{"id": "grp_rome", "name": "Rome Trip Crew",
          "created_at": _dt(2026, 6, 8, 10, 0)}],
    )
    members = [
        (DEMO_GUEST_ID, "Ahmet Yılmaz"),
        ("guest_mert", "Mert Aksoy"),
        ("guest_lara", "Lara Demir"),
    ]
    for guest_id, name in members:
        exists = await session.scalar(
            select(func.count())
            .select_from(GroupMemberORM)
            .where(
                GroupMemberORM.group_id == "grp_rome",
                GroupMemberORM.guest_id == guest_id,
            )
        )
        if not exists:
            session.add(
                GroupMemberORM(
                    group_id="grp_rome", guest_id=guest_id, display_name=name
                )
            )

    await _upsert(
        session,
        GroupExpenseORM,
        [
            {"id": "gex_seed_dinner", "group_id": "grp_rome",
             "payer_guest_id": "guest_mert", "title": "Trastevere dinner",
             "amount_cents": 14400, "currency": "USD", "settled": False,
             "created_at": _dt(2026, 6, 8, 21, 30)},
            {"id": "gex_seed_taxi", "group_id": "grp_rome",
             "payer_guest_id": "guest_lara", "title": "Fiumicino taxi",
             "amount_cents": 5700, "currency": "USD", "settled": False,
             "created_at": _dt(2026, 6, 9, 8, 15)},
        ],
    )

    await _upsert(
        session,
        PaxCardORM,
        [{"id": "pxc_demo", "guest_id": DEMO_GUEST_ID,
          "label": "StayWallet Platinum", "holder": "Ahmet Yılmaz",
          "kind": "virtual", "last4": "4242", "color": "#2667F2",
          "frozen": False, "programmed": False,
          "created_at": _dt(2026, 6, 9, 12, 0)}],
    )


async def _seed_stays(session: AsyncSession) -> None:
    await _upsert(
        session,
        StayORM,
        [
            {
                "id": "stay_123",
                "property_name": "The Bosphorus Suites",
                "room_number": "402",
                "check_in_date": _dt(2026, 6, 4, 14, 0),
                "check_out_date": _dt(2026, 6, 8, 11, 0),
                "address": "Kennedy Cd. No:12, Beşiktaş, İstanbul",
            },
            {
                "id": "stay_456",
                "property_name": "Cappadocia Cave Hotel",
                "room_number": "7B",
                "check_in_date": _dt(2026, 7, 1, 15, 0),
                "check_out_date": _dt(2026, 7, 4, 10, 0),
                "address": "Aydınlı Mah., Göreme, Nevşehir",
            },
        ],
    )


async def _seed_menu(session: AsyncSession) -> None:
    await _upsert(
        session,
        MenuItemORM,
        [
            {
                "id": "m_burger",
                "name": "Wagyu Beef Burger",
                "description": "Aged wagyu, brioche bun, truffle aioli",
                "price_cents": 2800,
                "category": "Mains",
                "image_url": "https://cdn.staywallet.example/menu/burger.jpg",
                "sort_order": 10,
            },
            {
                "id": "m_cola",
                "name": "Coca Cola",
                "description": "Chilled 330ml",
                "price_cents": 600,
                "category": "Drinks",
                "image_url": "https://cdn.staywallet.example/menu/cola.jpg",
                "sort_order": 20,
            },
            {
                "id": "m_caesar",
                "name": "Caesar Salad",
                "description": "Cos lettuce, parmesan, anchovy dressing, croutons",
                "price_cents": 1500,
                "category": "Starters",
                "image_url": "https://cdn.staywallet.example/menu/caesar.jpg",
                "sort_order": 30,
            },
            {
                "id": "m_cheesecake",
                "name": "Baked Cheesecake",
                "description": "Vanilla bean, berry compote",
                "price_cents": 1200,
                "category": "Desserts",
                "image_url": "https://cdn.staywallet.example/menu/cheesecake.jpg",
                "sort_order": 40,
            },
        ],
    )


async def _seed_travel(session: AsyncSession) -> None:
    await _upsert(
        session,
        TravelCategoryORM,
        [
            {
                "id": "rental_car",
                "name": "Rental Car",
                "subtitle": "Luxury & economy options",
                "icon": "directions_car",
                "accent": "blue",
                "featured": False,
                "base_price_cents": 15000,  # $150 → 150 * 3 = 450 pts
                "sort_order": 10,
            },
            {
                "id": "hotel",
                "name": "Hotels",
                "subtitle": "Handpicked stays worldwide",
                "icon": "hotel",
                "accent": "emerald",
                "featured": False,
                "base_price_cents": 22000,
                "sort_order": 20,
            },
            {
                "id": "restaurants",
                "name": "Restaurants",
                "subtitle": "Reserve top tables",
                "icon": "restaurant",
                "accent": "orange",
                "featured": False,
                "base_price_cents": 9000,
                "sort_order": 30,
            },
            {
                "id": "travel_insurance",
                "name": "Travel Insurance",
                "subtitle": "Cover for every trip",
                "icon": "health_and_safety",
                "accent": "purple",
                "featured": False,
                "base_price_cents": 5000,
                "sort_order": 40,
            },
            {
                "id": "e_visa",
                "name": "E-Visa Services",
                "subtitle": "Fast-track your global travels",
                "icon": "fact_check",
                "accent": "amber",
                "featured": True,
                "base_price_cents": 8000,
                "sort_order": 50,
            },
        ],
    )

    await _upsert(
        session,
        FeaturedDealORM,
        [
            {
                "id": "porsche_911",
                "title": "Porsche 911 Carrera S",
                "subtitle": "Exotic Rental Experience",
                "image_url": PORSCHE_IMAGE_URL,
                "badge": "Partner Spotlight",
                "discount_label": "-15% OFF",
                "discount_note": "with StayWallet card",
                "base_price_cents": 75000,  # $750 → 750 * 3 = 2250 pts
                "sort_order": 10,
            }
        ],
    )


# --------------------------------------------------------------------------- #
# Loyalty Orchestrator: provider catalog + the demo guest's accounts
# --------------------------------------------------------------------------- #
# Provider catalog. ``sort_order`` puts booking_com, sixt and miles_smiles first
# so the app's grid top row matches the mockup. Brand colours/icons are real.
_PROVIDER_CATALOG: list[dict] = [
    {"id": "booking_com", "name": "Booking.com", "brand_color_hex": "#003580",
     "icon": "hotel", "category": "hotel", "sort_order": 10},
    {"id": "sixt", "name": "Sixt", "brand_color_hex": "#FF5F00",
     "icon": "directions_car", "category": "car", "sort_order": 20},
    {"id": "miles_smiles", "name": "Miles&Smiles", "brand_color_hex": "#01355D",
     "icon": "flight", "category": "airline", "sort_order": 30},
    {"id": "uber", "name": "Uber", "brand_color_hex": "#000000",
     "icon": "local_taxi", "category": "rideshare", "sort_order": 40},
    {"id": "amex", "name": "American Express", "brand_color_hex": "#006FCF",
     "icon": "credit_card", "category": "card", "sort_order": 50},
    {"id": "marriott", "name": "Marriott Bonvoy", "brand_color_hex": "#6B0000",
     "icon": "hotel", "category": "hotel", "sort_order": 60},
    {"id": "hilton_honors", "name": "Hilton Honors", "brand_color_hex": "#104C97",
     "icon": "hotel", "category": "hotel", "sort_order": 70},
    {"id": "ihg_one", "name": "IHG One Rewards", "brand_color_hex": "#5C0F8B",
     "icon": "hotel", "category": "hotel", "sort_order": 80},
    {"id": "emirates_skywards", "name": "Emirates Skywards",
     "brand_color_hex": "#D71921", "icon": "flight", "category": "airline",
     "sort_order": 90},
    {"id": "avis", "name": "Avis Preferred", "brand_color_hex": "#D4002A",
     "icon": "directions_car", "category": "car", "sort_order": 100},
    {"id": "shell_go", "name": "Shell Go+", "brand_color_hex": "#FBCE07",
     "icon": "local_gas_station", "category": "fuel", "sort_order": 110},
    {"id": "starbucks", "name": "Starbucks Rewards", "brand_color_hex": "#00704A",
     "icon": "local_cafe", "category": "coffee", "sort_order": 120},
    {"id": "turkish_airlines_extra", "name": "Turkish Airlines Extra",
     "brand_color_hex": "#C1121C", "icon": "flight", "category": "airline",
     "sort_order": 130},
    {"id": "world_of_hyatt", "name": "World of Hyatt",
     "brand_color_hex": "#8B6F4E", "icon": "hotel", "category": "hotel",
     "sort_order": 140},
    {"id": "accor_all", "name": "ALL - Accor Live Limitless",
     "brand_color_hex": "#2E1A47", "icon": "hotel", "category": "hotel",
     "sort_order": 150},
]

# The demo guest's 12 LINKED ecosystems. Points SUM to exactly 1,240,500.
# booking_com / sixt / miles_smiles are listed first (catalog sort_order also
# puts them first). ``recent`` flags the 2 ecosystems counted in ``ecosystemsNew``.
_DEMO_LINKED: list[tuple[str, int, bool]] = [
    ("booking_com", 845000, False),
    ("sixt", 8200, True),
    ("miles_smiles", 120300, True),
    ("hilton_honors", 64000, False),
    ("ihg_one", 42000, False),
    ("emirates_skywards", 78500, False),
    ("avis", 15600, False),
    ("shell_go", 9400, False),
    ("starbucks", 3100, False),
    ("turkish_airlines_extra", 21500, False),
    ("world_of_hyatt", 18900, False),
    ("accor_all", 14000, False),
]
DEMO_TOTAL_POINTS = sum(points for _id, points, _recent in _DEMO_LINKED)  # 1240500

# The demo guest's 3 DISCOVERED ecosystems. ``points`` is the membership balance
# that folds into the aggregate when the program is linked (sandbox-simulated
# until real partner APIs exist).
_DEMO_DISCOVERED: list[tuple[str, int, str]] = [
    ("uber", 2450, "2,450 points detected"),
    ("amex", 31000, "Elite access found"),
    ("marriott", 56000, "Titanium Elite detected"),
]


async def _seed_providers(session: AsyncSession) -> None:
    await _upsert(session, ProviderORM, _PROVIDER_CATALOG)


async def _seed_loyalty_accounts(session: AsyncSession) -> None:
    """Seed the demo guest's linked + discovered ecosystem accounts.

    Idempotent: only seeds when the guest has no accounts yet, so re-running (or
    running after a link/auto-scan) does not resurrect discovered rows or
    double-count points.
    """

    count = await session.scalar(
        select(func.count())
        .select_from(LoyaltyAccountORM)
        .where(LoyaltyAccountORM.guest_id == DEMO_GUEST_ID)
    )
    if count:
        return

    # Older linked accounts predate the 30-day "new" window; ``recent`` ones fall
    # inside it so ``ecosystemsNew`` resolves to exactly 2.
    old_ts = _dt(2026, 1, 15, 10, 0)
    recent_ts = _dt(2026, 6, 1, 10, 0)
    for provider_id, points, recent in _DEMO_LINKED:
        session.add(
            LoyaltyAccountORM(
                guest_id=DEMO_GUEST_ID,
                provider_id=provider_id,
                linked=True,
                discovered=False,
                points=points,
                detected_label=None,
                created_at=recent_ts if recent else old_ts,
            )
        )
    for provider_id, points, label in _DEMO_DISCOVERED:
        session.add(
            LoyaltyAccountORM(
                guest_id=DEMO_GUEST_ID,
                provider_id=provider_id,
                linked=False,
                discovered=True,
                points=points,
                detected_label=label,
                created_at=old_ts,
            )
        )


async def _seed_loyalty_ledger(session: AsyncSession) -> None:
    """Seed ledger rows totalling exactly 12450 points for the demo guest.

    Only seeds when the guest currently has no ledger rows, so re-running the
    seed (or running it after orders/bookings have earned points) does not
    inflate the balance.
    """

    count = await session.scalar(
        select(func.count())
        .select_from(LoyaltyTransactionORM)
        .where(LoyaltyTransactionORM.guest_id == DEMO_GUEST_ID)
    )
    if count:
        return

    # Earn rows (positive) minus a redemption (negative) → net 12450.
    #   4200 + 2250 + 3500 + 5000 + 1000 - 3500 = 12450
    rows = [
        (4200, "earn", "seed", "ord_seed_001", "Welcome bonus + early room service"),
        (2250, "earn", "seed", "bk_seed_001", "Travel booking: Porsche 911 (3x)"),
        (3500, "earn", "seed", "bk_seed_002", "Travel booking: Hotel stay (3x)"),
        (5000, "earn", "seed", "promo_2026", "Spring promotion bonus"),
        (1000, "earn", "seed", "ord_seed_002", "Dining order"),
        (-3500, "redeem", "seed", "redeem_001", "Redeemed against rental car bill"),
    ]
    base = _dt(2026, 2, 1, 12, 0)
    for index, (amount, kind, source, ref, desc) in enumerate(rows):
        session.add(
            LoyaltyTransactionORM(
                guest_id=DEMO_GUEST_ID,
                amount=amount,
                kind=kind,
                source=source,
                reference_id=ref,
                description=desc,
                created_at=base.replace(day=1 + index),
            )
        )


async def seed() -> None:
    """Run the full idempotent seed inside a single transaction."""

    factory = get_sessionmaker()
    async with factory() as session:
        async with session.begin():
            await _seed_guest(session)
            await _seed_demo_user(session)
            await _seed_paxpal(session)
            await _seed_stays(session)
            await _seed_menu(session)
            await _seed_travel(session)
            await _seed_providers(session)
            await _seed_loyalty_accounts(session)
            await _seed_loyalty_ledger(session)

        balance = await session.scalar(
            select(func.coalesce(func.sum(LoyaltyTransactionORM.amount), 0)).where(
                LoyaltyTransactionORM.guest_id == DEMO_GUEST_ID
            )
        )
        orchestrator_total = await session.scalar(
            select(func.coalesce(func.sum(LoyaltyAccountORM.points), 0)).where(
                LoyaltyAccountORM.guest_id == DEMO_GUEST_ID,
                LoyaltyAccountORM.linked.is_(True),
            )
        )
    print(
        f"Seed complete. {DEMO_GUEST_ID} loyalty balance = {balance} points; "
        f"orchestrator linked total = {orchestrator_total} points."
    )


if __name__ == "__main__":
    asyncio.run(seed())
