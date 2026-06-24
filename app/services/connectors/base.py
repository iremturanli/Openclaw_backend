"""Connector interface and the data shapes connectors return.

These are deliberately plain dataclasses (transport-agnostic): the connector
returns provider data, and the service maps it onto ORM rows / API models. A
connector never touches the database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ProviderToken:
    """An access token obtained from the provider's token endpoint.

    In sandbox mode this is a deterministic placeholder; in real mode it is the
    OAuth access token (and would carry expiry/refresh data).
    """

    access_token: str
    sandbox: bool = True


@dataclass(frozen=True)
class ProviderProfile:
    """The traveler's profile as read from the provider.

    ``genius_level`` is Booking.com's loyalty tier (1-3); other providers map
    their own tier onto this nullable field.
    """

    genius_level: int | None = None
    display_name: str | None = None
    sandbox: bool = True


@dataclass(frozen=True)
class ProviderReservation:
    """A single reservation read from the provider, ready to import as a stay.

    ``external_ref`` is a deterministic, provider-unique key used to make
    re-imports idempotent (no duplicate stays on re-link).
    """

    external_ref: str
    property_name: str
    room: str
    check_in: datetime
    check_out: datetime
    address: str


class ProviderConnector(ABC):
    """Provider-specific OAuth-shaped linking + sync.

    Real mode flow (documented, not yet wired for any provider):

    1. ``authorize_url(state)`` -> redirect the user to the provider's consent
       screen; the provider redirects back to our callback with a ``code``.
    2. ``exchange_code(code)`` -> POST the code to the provider's token endpoint
       and return the access token.
    3. ``fetch_profile`` / ``fetch_bookings`` -> call the provider's APIs with
       the token.

    Sandbox connectors short-circuit steps 1-2 (no real redirect) and return
    deterministic simulated data from steps 3-4, flagged ``sandbox=True``.
    """

    #: Stable provider identifier (e.g. ``"booking.com"``), used by the registry.
    provider: str

    @abstractmethod
    def authorize_url(self, state: str) -> str:
        """Return the provider authorize URL to redirect the user to."""

    @abstractmethod
    async def exchange_code(self, code: str) -> ProviderToken:
        """Exchange an authorization ``code`` for an access token."""

    @abstractmethod
    async def fetch_profile(self, token: ProviderToken) -> ProviderProfile:
        """Return the traveler's profile (Genius level, ...) for ``token``."""

    @abstractmethod
    async def fetch_bookings(
        self, token: ProviderToken
    ) -> list[ProviderReservation]:
        """Return the traveler's reservations for ``token``."""
