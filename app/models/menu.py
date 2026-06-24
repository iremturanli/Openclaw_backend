"""Room-service menu schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MenuItem(BaseModel):
    """A single orderable room-service item.

    Matches the ``MenuItem`` shape in ``docs/api_contract.md``. ``priceCents`` is
    an integer number of cents to avoid float rounding.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., examples=["m_burger"])
    name: str = Field(..., examples=["Wagyu Beef Burger"])
    description: str = Field(..., examples=["Aged wagyu, brioche bun, truffle aioli"])
    price_cents: int = Field(..., alias="priceCents", ge=0, examples=[2800])
    category: str = Field(..., examples=["Mains"])
    image_url: str = Field(..., alias="imageUrl", examples=["https://.../burger.jpg"])
