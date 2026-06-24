"""Room-service order request/response schemas.

Money is always integer cents. Pricing fields (``subtotalCents``,
``discountCents``, ``totalCents``) and per-line ``priceCents``/``name`` are
computed server-side; the client only ever sends ``itemId`` + ``quantity``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderStatus


class OrderLineRequest(BaseModel):
    """A single requested line in a new order.

    Only ``itemId`` and ``quantity`` are accepted from the client; the server
    resolves name/price from the seeded menu.
    """

    model_config = ConfigDict(populate_by_name=True)

    item_id: str = Field(..., alias="itemId", min_length=1, examples=["m_burger"])
    quantity: int = Field(..., ge=1, examples=[1])


class OrderRequest(BaseModel):
    """The POST body for placing an order."""

    model_config = ConfigDict(populate_by_name=True)

    lines: list[OrderLineRequest] = Field(..., min_length=1)


class OrderLine(BaseModel):
    """A priced line on a placed order (server-authoritative)."""

    model_config = ConfigDict(populate_by_name=True)

    item_id: str = Field(..., alias="itemId", examples=["m_burger"])
    name: str = Field(..., examples=["Wagyu Beef Burger"])
    price_cents: int = Field(..., alias="priceCents", examples=[2800])
    quantity: int = Field(..., examples=[1])


class Order(BaseModel):
    """A placed room-service order. Returned by POST and GET order endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., examples=["ord_123"])
    stay_id: str = Field(..., alias="stayId", examples=["stay_123"])
    lines: list[OrderLine]
    subtotal_cents: int = Field(..., alias="subtotalCents", examples=[3400])
    discount_cents: int = Field(..., alias="discountCents", examples=[510])
    total_cents: int = Field(..., alias="totalCents", examples=[2890])
    status: OrderStatus
    placed_at: datetime = Field(..., alias="placedAt")
