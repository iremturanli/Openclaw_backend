"""Provider-connection schemas.

Conform to ``docs/api_contract.md`` -> "Provider Connections". camelCase aliases
match the Flutter data layer. ``sandbox`` is surfaced so clients can honestly
show that the external data is simulated.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Scopes a guest may grant when linking a provider.
ALLOWED_SCOPES = {"import_bookings", "sync_genius", "expense_tracking"}


class LinkRequest(BaseModel):
    """POST body for linking a provider account.

    ``scopes`` must be non-empty (HTTP 422 otherwise).
    """

    model_config = ConfigDict(populate_by_name=True)

    guest_id: str = Field(
        ..., alias="guestId", min_length=1, examples=["guest_demo"]
    )
    scopes: list[str] = Field(
        ...,
        min_length=1,
        examples=[["import_bookings", "sync_genius"]],
    )


class ProviderConnectionOut(BaseModel):
    """A linked provider connection returned to the client."""

    model_config = ConfigDict(populate_by_name=True)

    connection_id: str = Field(..., alias="connectionId", examples=["conn_123"])
    provider: str = Field(..., examples=["booking.com"])
    # status in linked | pending | error
    status: str = Field(..., examples=["linked"])
    scopes: list[str] = Field(
        ..., examples=[["import_bookings", "sync_genius"]]
    )
    genius_level: int | None = Field(
        default=None, alias="geniusLevel", examples=[2]
    )
    imported_stays: int = Field(..., alias="importedStays", examples=[2])
    connected_at: datetime = Field(..., alias="connectedAt")
    sandbox: bool = Field(..., examples=[True])
