"""Domain exceptions raised by the service layer.

Routers translate these into HTTP responses; services stay transport-agnostic.
"""

from __future__ import annotations


class StayNotFoundError(Exception):
    """Raised when a referenced stay does not exist."""

    def __init__(self, stay_id: str) -> None:
        self.stay_id = stay_id
        super().__init__(f"Stay not found: {stay_id}")


class CheckInNotFoundError(Exception):
    """Raised when a referenced check-in does not exist."""

    def __init__(self, check_in_id: str) -> None:
        self.check_in_id = check_in_id
        super().__init__(f"Check-in not found: {check_in_id}")


class MenuItemNotFoundError(Exception):
    """Raised when an order references an unknown menu item."""

    def __init__(self, item_id: str) -> None:
        self.item_id = item_id
        super().__init__(f"Menu item not found: {item_id}")


class TravelTargetNotFoundError(Exception):
    """Raised when a booking references an unknown category or deal."""

    def __init__(self, target_id: str) -> None:
        self.target_id = target_id
        super().__init__(f"Travel category or deal not found: {target_id}")


class GuestNotFoundError(Exception):
    """Raised when a referenced guest does not exist."""

    def __init__(self, guest_id: str) -> None:
        self.guest_id = guest_id
        super().__init__(f"Guest not found: {guest_id}")


class UnknownProviderError(Exception):
    """Raised when no connector is registered for a requested provider."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"Unknown provider: {provider}")


class ConnectionNotFoundError(Exception):
    """Raised when a referenced provider connection does not exist."""

    def __init__(self, connection_id: str) -> None:
        self.connection_id = connection_id
        super().__init__(f"Provider connection not found: {connection_id}")


class OrchestratorProviderNotFoundError(Exception):
    """Raised when an orchestrator provider id is not in the catalog (404)."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        super().__init__(f"Orchestrator provider not found: {provider_id}")


class ProviderAlreadyLinkedError(Exception):
    """Raised when linking a provider that is already linked (409)."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        super().__init__(f"Provider already linked: {provider_id}")


class TtsNotConfiguredError(Exception):
    """Raised when no ElevenLabs API key is configured (router returns 503)."""

    def __init__(self) -> None:
        super().__init__("Text-to-speech is not configured")


class TtsUpstreamError(Exception):
    """Raised when the upstream ElevenLabs request fails (router returns 502)."""

    def __init__(self, message: str = "Text-to-speech upstream request failed") -> None:
        super().__init__(message)
