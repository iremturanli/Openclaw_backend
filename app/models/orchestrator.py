"""Loyalty Orchestrator schemas.

Conform to ``docs/api_contract.md`` -> "Loyalty Orchestrator". camelCase aliases
match the Flutter data layer. A :class:`OrchestratorProvider` represents one
ecosystem tile in either the ``integrations`` (linked) or ``discovered`` list of
an :class:`OrchestratorSummary`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OrchestratorProvider(BaseModel):
    """One loyalty ecosystem, either linked (points set) or discovered."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., examples=["sixt"])
    name: str = Field(..., examples=["Sixt"])
    brand_color_hex: str = Field(
        ..., alias="brandColorHex", examples=["#FF5F00"]
    )
    linked: bool = Field(..., examples=[True])
    logo_url: str | None = Field(default=None, alias="logoUrl", examples=[None])
    icon: str | None = Field(default=None, examples=["directions_car"])
    # Set for linked providers (their points contribution); null when discovered.
    points: int | None = Field(default=None, examples=[8200])
    # Set for discovered providers ("2,450 points detected"); null when linked.
    detected_label: str | None = Field(
        default=None, alias="detectedLabel", examples=["2,450 points detected"]
    )


class OrchestratorSummary(BaseModel):
    """Aggregate view across a guest's linked and discovered ecosystems."""

    model_config = ConfigDict(populate_by_name=True)

    total_points: int = Field(..., alias="totalPoints", examples=[1240500])
    trend_pct: int = Field(..., alias="trendPct", examples=[12])
    ecosystems_count: int = Field(..., alias="ecosystemsCount", examples=[12])
    ecosystems_new: int = Field(..., alias="ecosystemsNew", examples=[2])
    integrations: list[OrchestratorProvider] = Field(default_factory=list)
    discovered: list[OrchestratorProvider] = Field(default_factory=list)


class OrchestratorLinkRequest(BaseModel):
    """POST body for linking one discovered provider."""

    model_config = ConfigDict(populate_by_name=True)

    guest_id: str = Field(
        ..., alias="guestId", min_length=1, examples=["guest_demo"]
    )
    provider_id: str = Field(
        ..., alias="providerId", min_length=1, examples=["uber"]
    )


class OrchestratorAutoScanRequest(BaseModel):
    """POST body for auto-linking every discovered provider."""

    model_config = ConfigDict(populate_by_name=True)

    guest_id: str = Field(
        ..., alias="guestId", min_length=1, examples=["guest_demo"]
    )
