"""Loyalty Orchestrator endpoints (cross-ecosystem aggregator).

Thin transport layer: aggregation/linking live in
:class:`app.services.orchestrator_service.OrchestratorService`; domain exceptions
are translated to HTTP status codes here.

See ``docs/api_contract.md`` -> "Loyalty Orchestrator". Discovered ecosystems are
simulated (sandbox); linking creates a sandbox-flagged provider connection.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_orchestrator_service
from app.models.orchestrator import (
    OrchestratorAutoScanRequest,
    OrchestratorLinkRequest,
    OrchestratorSummary,
)
from app.services.exceptions import (
    GuestNotFoundError,
    OrchestratorProviderNotFoundError,
    ProviderAlreadyLinkedError,
)
from app.services.orchestrator_service import OrchestratorService

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


@router.get(
    "",
    response_model=OrchestratorSummary,
    response_model_by_alias=True,
    summary="Aggregate loyalty points across a guest's linked ecosystems",
)
async def get_summary(
    guest_id: str = Query(..., alias="guestId", min_length=1, examples=["guest_demo"]),
    service: OrchestratorService = Depends(get_orchestrator_service),
) -> OrchestratorSummary:
    """Return the guest's :class:`OrchestratorSummary` (linked + discovered)."""

    return await service.get_summary(guest_id)


@router.post(
    "/link",
    response_model=OrchestratorSummary,
    response_model_by_alias=True,
    summary="Link one discovered ecosystem and re-aggregate",
)
async def link_provider(
    request: OrchestratorLinkRequest,
    service: OrchestratorService = Depends(get_orchestrator_service),
) -> OrchestratorSummary:
    """Link a discovered provider, fold in its points, return the new summary.

    Returns 404 for an unknown guest or provider, and 409 if already linked.
    """

    try:
        return await service.link(
            guest_id=request.guest_id, provider_id=request.provider_id
        )
    except GuestNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found"
        ) from exc
    except OrchestratorProviderNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider"
        ) from exc
    except ProviderAlreadyLinkedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider already linked",
        ) from exc


@router.post(
    "/auto-scan",
    response_model=OrchestratorSummary,
    response_model_by_alias=True,
    summary="Link every discovered ecosystem and re-aggregate",
)
async def auto_scan(
    request: OrchestratorAutoScanRequest,
    service: OrchestratorService = Depends(get_orchestrator_service),
) -> OrchestratorSummary:
    """Link all discovered providers for the guest and return the new summary.

    Returns 404 for an unknown guest.
    """

    try:
        return await service.auto_scan(request.guest_id)
    except GuestNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Guest not found"
        ) from exc
