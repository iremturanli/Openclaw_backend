"""Booking.com connector -- SANDBOX implementation.

================================ SANDBOX STUB ================================
Booking.com has NO public consumer API for reading a traveler's Genius level or
reservations. This connector therefore returns **simulated** profile and
bookings, deterministically, and flags everything ``sandbox=True``. The
OAuth-shaped flow (authorize -> exchange -> sync) is real in structure; only the
external data is faked.

To go live: obtain Booking.com partner/affiliate (or Connectivity) credentials
and replace the bodies of ``exchange_code``, ``fetch_profile`` and
``fetch_bookings`` with real HTTP calls (e.g. httpx against the partner API),
and have ``authorize_url`` point at the real consent screen with a callback that
calls ``exchange_code``. Nothing outside this file needs to change.
=============================================================================
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.connectors.base import (
    ProviderConnector,
    ProviderProfile,
    ProviderReservation,
    ProviderToken,
)

# Deterministic sandbox dataset. Marked clearly as simulated.
_SANDBOX_GENIUS_LEVEL = 2
_SANDBOX_DISPLAY_NAME = "Booking.com Genius Traveler (sandbox)"


def _dt(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# Two upcoming, realistic-looking reservations. ``external_ref`` is stable so
# re-linking does not create duplicate stays.
_SANDBOX_RESERVATIONS: list[ProviderReservation] = [
    ProviderReservation(
        external_ref="booking.com:res_AMS_8842301",
        property_name="Hotel Estherea (Booking.com, sandbox)",
        room="Deluxe Canal View King",
        check_in=_dt(2026, 7, 15, 15, 0),
        check_out=_dt(2026, 7, 18, 11, 0),
        address="Singel 303-309, 1012 WJ Amsterdam, Netherlands",
    ),
    ProviderReservation(
        external_ref="booking.com:res_BCN_9912045",
        property_name="Yurbban Trafalgar Hotel (Booking.com, sandbox)",
        room="Superior Double Rooftop",
        check_in=_dt(2026, 8, 2, 14, 0),
        check_out=_dt(2026, 8, 6, 12, 0),
        address="Carrer de Trafalgar 30, 08010 Barcelona, Spain",
    ),
]


class BookingComConnector(ProviderConnector):
    """Sandbox Booking.com connector.

    Returns deterministic simulated data flagged ``sandbox=True``. See the module
    docstring for how the real partner API swaps in.
    """

    provider = "booking.com"

    # The authorize endpoint a real flow would redirect to. Documented here for
    # parity; in sandbox mode nobody actually visits it.
    AUTHORIZE_ENDPOINT = "https://account.booking.com/oauth2/authorize"

    def authorize_url(self, state: str) -> str:
        """Return the (illustrative) authorize URL.

        In real mode the user is redirected here and Booking.com calls our
        callback with a ``code``. In sandbox mode this URL is informational.
        """

        return (
            f"{self.AUTHORIZE_ENDPOINT}"
            f"?response_type=code&client_id=staywallet-sandbox&state={state}"
        )

    async def exchange_code(self, code: str) -> ProviderToken:
        """Return a deterministic sandbox token (no real network call)."""

        # Real mode: POST {code} to the token endpoint, parse access_token.
        return ProviderToken(access_token=f"sandbox-token::{code}", sandbox=True)

    async def fetch_profile(self, token: ProviderToken) -> ProviderProfile:
        """Return a simulated Genius profile (level 2)."""

        return ProviderProfile(
            genius_level=_SANDBOX_GENIUS_LEVEL,
            display_name=_SANDBOX_DISPLAY_NAME,
            sandbox=True,
        )

    async def fetch_bookings(
        self, token: ProviderToken
    ) -> list[ProviderReservation]:
        """Return two simulated upcoming reservations."""

        return list(_SANDBOX_RESERVATIONS)
