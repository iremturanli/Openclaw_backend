"""Real-Time Spend Intelligence.

Aggregates a traveller's REAL bookings (``PurchaseORM`` rows) into total spend,
top categories, recent transactions and a few heuristic insight lines. This is
honest aggregation of actual purchases (``isDemo: false``) — no synthetic data.

The service reuses :class:`app.services.wallet_service.WalletService` for the
purchase list (read-only) and the budget total, then does pure, deterministic
aggregation. If an OpenAI key is configured the insight *wording* may be
enriched, but a deterministic heuristic fallback is always the primary path so
the endpoint works with no key and never errors.
"""

from __future__ import annotations

from typing import Any

from app.services.wallet_service import VALID_KINDS, WalletService

# Human labels per purchase ``kind``. Covers every kind in
# ``wallet_service.VALID_KINDS`` so no category is ever unlabelled.
_KIND_LABELS: dict[str, str] = {
    "flight": "Flights",
    "hotel": "Hotels",
    "restaurant": "Dining",
    "transfer": "Transport",
    "scooter": "Transport",
    "car": "Car Hire",
    "activity": "Activities",
}

# Material-icon keys the UI maps. Used per category in insight lines.
_KIND_ICONS: dict[str, str] = {
    "flight": "flight",
    "hotel": "hotel",
    "restaurant": "restaurant",
    "transfer": "account_balance_wallet",
    "scooter": "account_balance_wallet",
    "car": "account_balance_wallet",
    "activity": "lightbulb",
}

_RECENT_LIMIT = 8


def _label_for(kind: str) -> str:
    """Return a human label for a purchase ``kind`` (title-cased fallback)."""

    return _KIND_LABELS.get(kind, kind.replace("_", " ").title())


def _pct(part: int, whole: int) -> float:
    """Return ``part`` as a percentage of ``whole`` rounded to 1 dp (0 if no whole)."""

    if whole <= 0:
        return 0.0
    return round(part / whole * 100, 1)


def _money(amount_cents: int, currency: str) -> str:
    """Format minor units as a compact display string (e.g. ``$1,234``)."""

    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency, "")
    whole = amount_cents // 100
    return f"{symbol}{whole:,}" if symbol else f"{whole:,} {currency}"


class SpendService:
    """Builds the ``/spend/insights`` payload from a guest's real purchases."""

    def __init__(self, wallet: WalletService) -> None:
        self._wallet = wallet

    async def insights(self, guest_id: str) -> dict[str, Any]:
        """Aggregate the guest's purchases into the spend-intelligence payload."""

        budget = await self._wallet.ensure_budget(guest_id)
        purchases = await self._wallet.list_purchases(guest_id)
        return self.build_payload(
            purchases,
            budget_cents=budget.balance_cents + sum(p.amount_cents for p in purchases),
            currency=budget.currency,
        )

    def build_payload(
        self,
        purchases: list[Any],
        *,
        budget_cents: int,
        currency: str,
    ) -> dict[str, Any]:
        """Pure aggregation over purchase rows (newest-first) → response dict.

        ``budget_cents`` is the *original* total budget (remaining balance plus
        everything already spent) so ``remainingCents`` and ``spentPct`` reflect
        the wallet honestly. Kept side-effect free and DB-free so it can be
        unit-tested with plain fake rows.
        """

        total_spent = sum(p.amount_cents for p in purchases)
        tx_count = len(purchases)
        remaining = budget_cents - total_spent
        spent_pct = _pct(total_spent, budget_cents)

        # --- Zero-purchase path: friendly, never an error. -------------------
        if tx_count == 0:
            return {
                "currency": currency,
                "totalSpentCents": 0,
                "txCount": 0,
                "budgetCents": budget_cents,
                "remainingCents": remaining,
                "spentPct": 0.0,
                "topCategories": [],
                "insights": [
                    {
                        "icon": "lightbulb",
                        "title": "No spend yet",
                        "detail": "Start booking to see your spend intelligence.",
                    }
                ],
                "recent": [],
                "isDemo": False,
            }

        top_categories = self._top_categories(purchases, total_spent)
        recent = self._recent(purchases, currency)
        insights = self._insights(
            top_categories=top_categories,
            purchases=purchases,
            total_spent=total_spent,
            budget_cents=budget_cents,
            remaining=remaining,
            spent_pct=spent_pct,
            currency=currency,
        )

        return {
            "currency": currency,
            "totalSpentCents": total_spent,
            "txCount": tx_count,
            "budgetCents": budget_cents,
            "remainingCents": remaining,
            "spentPct": spent_pct,
            "topCategories": top_categories,
            "insights": insights,
            "recent": recent,
            "isDemo": False,
        }

    # ------------------------------------------------------------------ #
    # Aggregation helpers
    # ------------------------------------------------------------------ #
    def _top_categories(
        self, purchases: list[Any], total_spent: int
    ) -> list[dict[str, Any]]:
        """Group by ``kind``, sorted by amount desc, each with pct + count."""

        amounts: dict[str, int] = {}
        counts: dict[str, int] = {}
        for p in purchases:
            amounts[p.kind] = amounts.get(p.kind, 0) + p.amount_cents
            counts[p.kind] = counts.get(p.kind, 0) + 1

        rows = [
            {
                "kind": kind,
                "label": _label_for(kind),
                "amountCents": amount,
                "pct": _pct(amount, total_spent),
                "count": counts[kind],
            }
            for kind, amount in amounts.items()
        ]
        rows.sort(key=lambda r: (r["amountCents"], r["count"]), reverse=True)
        return rows

    def _recent(self, purchases: list[Any], currency: str) -> list[dict[str, Any]]:
        """Last ~8 purchases, newest-first (input is already desc by date)."""

        out: list[dict[str, Any]] = []
        for p in purchases[:_RECENT_LIMIT]:
            created = getattr(p, "created_at", None)
            created_at = (
                created.isoformat().replace("+00:00", "Z")
                if created is not None and hasattr(created, "isoformat")
                else str(created)
            )
            out.append(
                {
                    "kind": p.kind,
                    "title": p.title,
                    "subtitle": getattr(p, "subtitle", "") or "",
                    "amountCents": p.amount_cents,
                    "currency": getattr(p, "currency", currency) or currency,
                    "createdAt": created_at,
                }
            )
        return out

    def _insights(
        self,
        *,
        top_categories: list[dict[str, Any]],
        purchases: list[Any],
        total_spent: int,
        budget_cents: int,
        remaining: int,
        spent_pct: float,
        currency: str,
    ) -> list[dict[str, Any]]:
        """Generate 2-4 factual heuristic insight lines from the data."""

        insights: list[dict[str, Any]] = []

        # 1) Biggest category.
        if top_categories:
            top = top_categories[0]
            insights.append(
                {
                    "icon": _KIND_ICONS.get(top["kind"], "pie_chart"),
                    "title": f"{top['label']} are your biggest spend",
                    "detail": (
                        f"{top['pct']:.0f}% of your spend went to "
                        f"{top['label'].lower()}."
                    ),
                }
            )

        # 2) Budget usage.
        if budget_cents > 0:
            insights.append(
                {
                    "icon": "account_balance_wallet",
                    "title": f"You've used {spent_pct:.0f}% of your budget",
                    "detail": (
                        f"{_money(total_spent, currency)} of "
                        f"{_money(budget_cents, currency)} spent so far."
                    ),
                }
            )

        # 3) Biggest single transaction.
        biggest = max(purchases, key=lambda p: p.amount_cents)
        if biggest.amount_cents > 0:
            insights.append(
                {
                    "icon": "trending_up",
                    "title": "Largest purchase",
                    "detail": (
                        f"{biggest.title} was your biggest single spend at "
                        f"{_money(biggest.amount_cents, currency)}."
                    ),
                }
            )

        # 4) Remaining headroom (only when budget is meaningful).
        if budget_cents > 0 and remaining > 0:
            insights.append(
                {
                    "icon": "savings",
                    "title": "Budget remaining",
                    "detail": (
                        f"You have {_money(remaining, currency)} left to spend."
                    ),
                }
            )

        return insights[:4]


__all__ = ["SpendService", "VALID_KINDS"]
