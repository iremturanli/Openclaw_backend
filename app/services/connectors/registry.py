"""Connector registry: resolve ``provider`` -> :class:`ProviderConnector`.

Extensible: register an Airbnb/Expedia connector later with
``register_connector(AirbnbConnector())`` and the service/router pick it up with
no other changes. Unknown providers raise :class:`UnknownProviderError`, which
the router maps to HTTP 404.
"""

from __future__ import annotations

from app.services.connectors.base import ProviderConnector
from app.services.connectors.booking import BookingComConnector
from app.services.connectors.sixt import SixtConnector, UberConnector
from app.services.exceptions import UnknownProviderError

# Single source of truth for supported providers.
_REGISTRY: dict[str, ProviderConnector] = {}


def register_connector(connector: ProviderConnector) -> None:
    """Register ``connector`` under its ``provider`` key."""

    _REGISTRY[connector.provider] = connector


def get_connector(provider: str) -> ProviderConnector:
    """Return the connector for ``provider``.

    Raises:
        UnknownProviderError: If no connector is registered for ``provider``.
    """

    connector = _REGISTRY.get(provider)
    if connector is None:
        raise UnknownProviderError(provider)
    return connector


# Register built-in connectors at import time.
register_connector(BookingComConnector())
register_connector(SixtConnector())
register_connector(UberConnector())
