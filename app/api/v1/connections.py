"""Provider-connection endpoints (external account linking).

Thin transport layer: validation is in the Pydantic models and all orchestration
lives in :class:`app.services.connection_service.ConnectionService`. Domain
exceptions are translated to HTTP status codes here.

See ``docs/api_contract.md`` -> "Provider Connections". The Booking.com connector
runs in sandbox mode; responses carry ``sandbox: true``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_connection_service
from app.models.connection import LinkRequest, ProviderConnectionOut
from app.services.connection_service import ConnectionService
from app.services.exceptions import (
    ConnectionNotFoundError,
    GuestNotFoundError,
    UnknownProviderError,
)

router = APIRouter(prefix="/connections", tags=["connections"])

# The URL uses the short provider slug ``booking``; it maps to the connector
# registry key ``booking.com``.
_PROVIDER_SLUGS = {"booking": "booking.com"}


@router.post(
    "/{provider_slug}/link",
    response_model=ProviderConnectionOut,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Link an external provider account and sync its data",
)
async def link_provider(
    provider_slug: str,
    request: LinkRequest,
    service: ConnectionService = Depends(get_connection_service),
) -> ProviderConnectionOut:
    """Run the connector (authorize -> token -> sync) and persist the connection.

    Imports reservations as ``stays`` (source='booking.com') when
    ``import_bookings`` is granted, and stores the Genius level when
    ``sync_genius`` is granted. Returns 404 for an unknown provider or guest,
    and 422 (via Pydantic) when ``scopes`` is empty.
    """

    provider = _PROVIDER_SLUGS.get(provider_slug, provider_slug)
    try:
        return await service.link(
            guest_id=request.guest_id,
            provider=provider,
            scopes=request.scopes,
        )
    except UnknownProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown provider",
        ) from exc
    except GuestNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guest not found",
        ) from exc


@router.get(
    "",
    response_model=list[ProviderConnectionOut],
    response_model_by_alias=True,
    summary="List a guest's provider connections",
)
async def list_connections(
    guest_id: str = Query(..., alias="guestId", min_length=1),
    service: ConnectionService = Depends(get_connection_service),
) -> list[ProviderConnectionOut]:
    """Return all provider connections for ``guestId``."""

    return await service.list(guest_id)


@router.delete(
    "/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink (delete) a provider connection",
)
async def unlink_connection(
    connection_id: str,
    service: ConnectionService = Depends(get_connection_service),
) -> None:
    """Delete a connection. Imported stays are kept (their FK is nulled).

    Returns 404 if the connection does not exist.
    """

    try:
        await service.unlink(connection_id)
    except ConnectionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found",
        ) from exc
