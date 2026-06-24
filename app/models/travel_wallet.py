"""Schemas for the demo budget, purchases, and flight search."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PurchaseOut(BaseModel):
    id: str
    kind: str
    title: str
    subtitle: str = ""
    amount_cents: int = Field(..., alias="amountCents")
    currency: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(..., alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class BudgetState(BaseModel):
    balance_cents: int = Field(..., alias="balanceCents")
    currency: str
    recent_purchases: list[PurchaseOut] = Field(
        default_factory=list, alias="recentPurchases"
    )

    model_config = ConfigDict(populate_by_name=True)


class PurchaseRequest(BaseModel):
    kind: str = Field(..., examples=["flight"])
    title: str = Field(..., min_length=1, max_length=255)
    subtitle: str = Field(default="", max_length=512)
    amount_cents: int = Field(..., gt=0, alias="amountCents")
    currency: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class PurchaseResult(BaseModel):
    purchase: PurchaseOut
    balance_cents: int = Field(..., alias="balanceCents")

    model_config = ConfigDict(populate_by_name=True)


class FlightSearchResponse(BaseModel):
    options: list[dict[str, Any]] = Field(default_factory=list)
