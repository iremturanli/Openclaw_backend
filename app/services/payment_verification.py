"""Server-authoritative record of which Stripe sessions have actually paid.

Populated ONLY by the signature-verified webhook (``checkout.session.completed``
with ``payment_status == 'paid'``), never by the client. Fulfilment (recording a
booking) should consult :meth:`PaymentVerificationStore.is_paid` instead of
trusting a client claim that payment succeeded.

This in-process store is a first cut: counters/records live per worker and are
lost on restart. For multi-instance production, back it with the database (a
``paid_sessions`` table) or Redis — the call sites here stay the same.
"""

from __future__ import annotations

from typing import Any


class PaymentVerificationStore:
    """Idempotent set of session ids confirmed paid by a verified webhook."""

    def __init__(self) -> None:
        self._paid: dict[str, dict[str, Any]] = {}

    def mark_paid(self, session_id: str, info: dict[str, Any] | None = None) -> None:
        """Record ``session_id`` as paid (idempotent)."""

        if session_id and session_id not in self._paid:
            self._paid[session_id] = info or {}

    def is_paid(self, session_id: str) -> bool:
        return session_id in self._paid

    def info(self, session_id: str) -> dict[str, Any] | None:
        return self._paid.get(session_id)


# Process-wide singleton; injected via a FastAPI dependency.
_store = PaymentVerificationStore()


def get_payment_store() -> PaymentVerificationStore:
    """Return the process-wide :class:`PaymentVerificationStore`."""

    return _store
