"""Loyalty ledger business logic.

The balance is **never** a stored number: it is always ``SUM(amount)`` over the
guest's ``loyalty_transactions`` rows (earn rows positive, redeem rows
negative). Both room-service orders and travel bookings earn points through this
single service, so the earn rule lives in exactly one place.

Earn rule (also documented in ``backend/README.md``):

    points = floor(total_cents / 100) * points_per_dollar * multiplier

* ``points_per_dollar`` and the per-source multiplier come from settings.
* Room service uses a 1x multiplier; travel bookings use the configurable
  travel multiplier (3x) to match the "3x points" promo.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.models.travel import LoyaltyBalance
from app.repositories.base import LoyaltyRepository


class LoyaltyService:
    """Computes balances and writes earn/redeem rows to the ledger."""

    def __init__(
        self,
        loyalty_repository: LoyaltyRepository,
        settings: Settings | None = None,
    ) -> None:
        self._ledger = loyalty_repository
        self._settings = settings or get_settings()

    def compute_points(self, total_cents: int, *, multiplier: int = 1) -> int:
        """Return points earned for ``total_cents`` under the earn rule."""

        whole_dollars = total_cents // 100
        return whole_dollars * self._settings.loyalty_points_per_dollar * multiplier

    async def get_balance(self, guest_id: str) -> LoyaltyBalance:
        """Return the guest's :class:`LoyaltyBalance` derived from the ledger."""

        points = await self._ledger.balance(guest_id)
        return LoyaltyBalance(
            points=points,
            multiplier_label=self._settings.loyalty_multiplier_label,
            note=self._settings.loyalty_note,
        )

    async def earn(
        self,
        *,
        guest_id: str,
        total_cents: int,
        source: str,
        reference_id: str,
        description: str,
        multiplier: int = 1,
    ) -> int:
        """Write an earn row and return the points awarded.

        The caller owns the surrounding transaction; this only flushes the row
        so the points participate in the same atomic unit of work as the order
        or booking that triggered them.
        """

        points = self.compute_points(total_cents, multiplier=multiplier)
        await self._ledger.add_transaction(
            guest_id=guest_id,
            amount=points,
            kind="earn",
            source=source,
            reference_id=reference_id,
            description=description,
        )
        return points
