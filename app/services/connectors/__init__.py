"""Provider-agnostic account-connection (connector) framework.

A :class:`ProviderConnector` encapsulates everything provider-specific about
linking an external travel account: the OAuth-shaped authorize -> exchange flow
and the profile/bookings sync. The service layer
(:mod:`app.services.connection_service`) depends only on this interface, so
adding a new provider means writing one connector and registering it -- no
changes to the service, repository, router or schema.

The Booking.com connector currently runs in **sandbox** mode (clearly flagged):
Booking.com has no public consumer API to read a traveler's Genius level or
reservations, so the external data is simulated. The architecture is real; only
the connector body is a stub, and swapping in a real partner/affiliate API means
replacing :class:`BookingComConnector` alone.
"""

from __future__ import annotations

from app.services.connectors.base import (
    ProviderConnector,
    ProviderProfile,
    ProviderReservation,
    ProviderToken,
)
from app.services.connectors.booking import BookingComConnector
from app.services.connectors.registry import get_connector, register_connector

__all__ = [
    "BookingComConnector",
    "ProviderConnector",
    "ProviderProfile",
    "ProviderReservation",
    "ProviderToken",
    "get_connector",
    "register_connector",
]
