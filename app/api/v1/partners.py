"""Partner/admin surface: provider status, commission HQ, onboarding preview.

Commission figures are deterministic demo data (no partner settlement system
exists yet); provider status reflects the real runtime configuration so the
admin screen honestly shows which verticals run live vs sandbox.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_settings
from app.core.config import Settings
from app.models.market import (
    CommissionOverview,
    OnboardingPreviewRequest,
    OnboardingPreviewResponse,
    PartnerRow,
    ProviderStatus,
)
from app.services.mobility_directory import (
    all_countries,
    country_mobility,
    integration_roadmap,
)

router = APIRouter(prefix="/partners", tags=["partners"])

_PARTNERS = [
    PartnerRow(name="Global Travels", category="Agency", commission_pct=12.5, plan="Enterprise", earnings_cents=16_100_000, revenue_cents=128_800_000),
    PartnerRow(name="Dubai Hotels Pro", category="Hotels", commission_pct=15.0, plan="Premium", earnings_cents=14_200_000, revenue_cents=94_600_000),
    PartnerRow(name="Dubai Adventures Ltd", category="Activities", commission_pct=18.0, plan="Standard", earnings_cents=9_590_000, revenue_cents=53_200_000),
    PartnerRow(name="Digital Hospitality", category="Restaurants", commission_pct=10.0, plan="Standard", earnings_cents=6_480_000, revenue_cents=64_800_000),
    PartnerRow(name="Sixt Rent a Car", category="Mobility", commission_pct=8.5, plan="Enterprise", earnings_cents=5_240_000, revenue_cents=61_600_000),
]

_TIERS = [
    {"name": "Standard", "commissionPct": 10.0, "note": "Self-serve partners"},
    {"name": "Premium", "commissionPct": 15.0, "note": "Priority placement"},
    {"name": "Enterprise", "commissionPct": 12.5, "note": "Negotiated volume rates"},
]


@router.get("/commissions", response_model=CommissionOverview, summary="Commission HQ data")
async def commissions() -> CommissionOverview:
    total = sum(p.earnings_cents for p in _PARTNERS)
    avg = sum(p.commission_pct for p in _PARTNERS) / len(_PARTNERS)
    return CommissionOverview(
        avg_commission_pct=round(avg, 1),
        total_earnings_cents=total,
        partners_count=382,
        tiers=_TIERS,
        partners=_PARTNERS,
    )


@router.get("/providers", response_model=list[ProviderStatus], summary="Vertical provider status")
async def provider_status(settings: Settings = Depends(get_settings)) -> list[ProviderStatus]:
    serp = bool(settings.serpapi_api_key)
    return [
        ProviderStatus(key="flights", label="Flights", provider="serpapi" if serp else "mock", live=serp, missing=[] if serp else ["SERPAPI_API_KEY"]),
        ProviderStatus(key="hotels", label="Hotels", provider="serpapi" if serp else "mock", live=serp, missing=[] if serp else ["SERPAPI_API_KEY"]),
        ProviderStatus(key="restaurants", label="Restaurants", provider="serpapi" if serp else "mock", live=serp, missing=[] if serp else ["SERPAPI_API_KEY"]),
        _car_status(settings),
        _transfer_status(settings),
        ProviderStatus(
            key="ai",
            label="AI Concierge",
            provider="openai" if settings.openai_api_key else "mock",
            live=bool(settings.openai_api_key),
            missing=[] if settings.openai_api_key else ["OPENAI_API_KEY"],
        ),
        ProviderStatus(
            key="voice",
            label="Voice (TTS)",
            provider="elevenlabs" if settings.elevenlabs_api_key else "device",
            live=bool(settings.elevenlabs_api_key),
            missing=[] if settings.elevenlabs_api_key else ["ELEVENLABS_API_KEY"],
        ),
        ProviderStatus(
            key="payments",
            label="Payments",
            provider="stripe" if settings.stripe_secret_key else "demo-wallet",
            live=bool(settings.stripe_secret_key),
            missing=[] if settings.stripe_secret_key else ["STRIPE_SECRET_KEY"],
        ),
    ]


def _car_status(settings: Settings) -> ProviderStatus:
    provider = settings.car_provider
    if provider == "booking":
        configured = bool(settings.booking_demand_token and settings.booking_affiliate_id)
        missing = [] if configured else ["BOOKING_DEMAND_TOKEN", "BOOKING_AFFILIATE_ID"]
        return ProviderStatus(key="cars", label="Cars", provider="booking.com demand", live=configured, missing=missing)
    if provider == "sixt":
        configured = bool(settings.sixt_client_id and settings.sixt_client_secret)
        missing = [] if configured else ["SIXT_CLIENT_ID", "SIXT_CLIENT_SECRET"]
        return ProviderStatus(key="cars", label="Cars", provider="sixt", live=configured, missing=missing)
    return ProviderStatus(key="cars", label="Cars", provider="mock", live=False, missing=["CAR_PROVIDER=booking + BOOKING_DEMAND_TOKEN"])


def _transfer_status(settings: Settings) -> ProviderStatus:
    if settings.transfer_provider == "uber":
        configured = bool(settings.uber_server_token)
        missing = [] if configured else ["UBER_SERVER_TOKEN"]
        return ProviderStatus(key="transfers", label="Transfers", provider="uber", live=configured, missing=missing)
    return ProviderStatus(key="transfers", label="Transfers", provider="mock", live=False, missing=["TRANSFER_PROVIDER=uber + UBER_SERVER_TOKEN"])


@router.get("/mobility", summary="Country-aware ride / mobility providers")
async def mobility(
    country: str | None = Query(None, description="ISO country code, e.g. TR"),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Ranked local mobility providers for ``country`` (board's country map)."""

    return country_mobility(country, settings)


@router.get("/mobility/countries", summary="Countries covered by the mobility map")
async def mobility_countries() -> list[dict[str, Any]]:
    return all_countries()


@router.get("/roadmap", summary="12-layer integration roadmap (vision)")
async def roadmap() -> dict[str, Any]:
    """The full AI-travel-finance super-app integration roadmap."""

    return integration_roadmap()


@router.post(
    "/onboarding/preview",
    response_model=OnboardingPreviewResponse,
    summary="Revenue projection for partner onboarding",
)
async def onboarding_preview(
    request: OnboardingPreviewRequest,
) -> OnboardingPreviewResponse:
    commission = int(request.monthly_gross_cents * request.commission_pct / 100)
    return OnboardingPreviewResponse(
        gross_cents=request.monthly_gross_cents,
        commission_cents=commission,
        projected_net_cents=request.monthly_gross_cents - commission,
    )
