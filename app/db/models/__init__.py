"""ORM models package.

Importing this package registers every mapped class against
:data:`app.db.base.Base.metadata`, which is what Alembic autogeneration and the
test-DB schema builder rely on.
"""

from app.db.models.connection import ProviderConnectionORM
from app.db.models.menu import MenuItemORM, OrderLineORM, OrderORM
from app.db.models.orchestrator import LoyaltyAccountORM, ProviderORM
from app.db.models.paxpal import (
    ExpenseGroupORM,
    GroupExpenseORM,
    GroupMemberORM,
    PaxCardORM,
)
from app.db.models.stay import CheckInORM, DigitalKeyORM, StayORM
from app.db.models.travel import (
    BookingORM,
    FeaturedDealORM,
    GuestORM,
    LoyaltyTransactionORM,
    TravelCategoryORM,
)
from app.db.models.travel_wallet import PurchaseORM, WalletBudgetORM
from app.db.models.user import UserORM

__all__ = [
    "BookingORM",
    "CheckInORM",
    "DigitalKeyORM",
    "ExpenseGroupORM",
    "FeaturedDealORM",
    "GroupExpenseORM",
    "GroupMemberORM",
    "GuestORM",
    "PaxCardORM",
    "LoyaltyAccountORM",
    "LoyaltyTransactionORM",
    "MenuItemORM",
    "OrderLineORM",
    "OrderORM",
    "ProviderConnectionORM",
    "ProviderORM",
    "PurchaseORM",
    "StayORM",
    "TravelCategoryORM",
    "UserORM",
    "WalletBudgetORM",
]
