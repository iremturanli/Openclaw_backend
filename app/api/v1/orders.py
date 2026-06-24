"""Room-service menu and order endpoints (nested under a stay)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_order_service
from app.models.menu import MenuItem
from app.models.order import Order, OrderRequest
from app.services.exceptions import MenuItemNotFoundError, StayNotFoundError
from app.services.order_service import OrderService

router = APIRouter(prefix="/stays", tags=["room-service"])


@router.get(
    "/{stay_id}/menu",
    response_model=list[MenuItem],
    response_model_by_alias=True,
    summary="List the room-service menu for a stay",
)
async def get_menu(
    stay_id: str,
    service: OrderService = Depends(get_order_service),
) -> list[MenuItem]:
    """Return the room-service menu, or 404 if the stay is unknown."""

    try:
        return await service.get_menu(stay_id)
    except StayNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stay not found",
        ) from exc


@router.post(
    "/{stay_id}/orders",
    response_model=Order,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="Place a room-service order (pricing computed server-side)",
)
async def place_order(
    stay_id: str,
    request: OrderRequest,
    service: OrderService = Depends(get_order_service),
) -> Order:
    """Place an order.

    The server recomputes all pricing from the menu; the client only supplies
    ``itemId`` + ``quantity``. Returns 404 for an unknown stay or item, and 422
    (via Pydantic) for empty lines or ``quantity < 1``.
    """

    try:
        return await service.place_order(stay_id, request)
    except StayNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stay not found",
        ) from exc
    except MenuItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu item not found",
        ) from exc


@router.get(
    "/{stay_id}/orders",
    response_model=list[Order],
    response_model_by_alias=True,
    summary="List a stay's room-service orders (most recent first)",
)
async def list_orders(
    stay_id: str,
    service: OrderService = Depends(get_order_service),
) -> list[Order]:
    """Return the stay's orders, most recent first, or 404 if stay unknown."""

    try:
        return await service.list_orders(stay_id)
    except StayNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stay not found",
        ) from exc
