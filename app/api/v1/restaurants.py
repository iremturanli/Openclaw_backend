"""Restaurant search + table booking.

Search runs live through SerpApi's Google Local engine when the key is set and
falls back to a curated sandbox list otherwise, so the screen always renders.
Booking a table records a wallet purchase (deposit may be 0) and awards points.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    get_current_user,
    get_restaurant_service,
    get_settings,
    get_wallet_service,
)
from app.core.config import Settings
from app.db.models.user import UserORM
from app.models.market import (
    BookTableRequest,
    BookTableResponse,
    RestaurantSearchResponse,
)
from app.services.restaurant_service import RestaurantSearchError, RestaurantService
from app.services.wallet_service import (
    InsufficientBudgetError,
    InvalidPurchaseError,
    WalletService,
)

router = APIRouter(prefix="/restaurants", tags=["restaurants"])

_SANDBOX_RESTAURANTS: list[dict[str, Any]] = [
    {
        "id": "re_mahara",
        "name": "Al Mahara",
        "rating": 4.9,
        "reviews": 1240,
        "priceLevel": "$$$$",
        "type": "Seafood · Fine Dining",
        "address": "Burj Al Arab, Dubai",
        "image": None,
        "badge": "MICHELIN",
    },
    {
        "id": "re_gilded",
        "name": "The Gilded Fork",
        "rating": 4.7,
        "reviews": 860,
        "priceLevel": "$$$",
        "type": "Modern French",
        "address": "DIFC, Dubai",
        "image": None,
        "badge": "STAYWALLET PARTNER",
    },
    {
        "id": "re_mirage",
        "name": "Mirage Grill",
        "rating": 4.6,
        "reviews": 2105,
        "priceLevel": "$$",
        "type": "International · Grill",
        "address": "Downtown Dubai",
        "image": None,
    },
    {
        "id": "re_sakura",
        "name": "Sakura Sky",
        "rating": 4.8,
        "reviews": 654,
        "priceLevel": "$$$",
        "type": "Japanese · Omakase",
        "address": "Palm Jumeirah, Dubai",
        "image": None,
    },
]


@router.get("/search", response_model=RestaurantSearchResponse, summary="Search restaurants")
async def search_restaurants(
    q: str = Query(default="best restaurants"),
    location: str | None = Query(default=None),
    restaurants: RestaurantService = Depends(get_restaurant_service),
    settings: Settings = Depends(get_settings),
) -> RestaurantSearchResponse:
    live = bool(settings.serpapi_api_key)
    options: list[dict[str, Any]] = []
    if live:
        try:
            options = await restaurants.search(query=q, location=location)
        except RestaurantSearchError:
            options = []
    if not options:
        return RestaurantSearchResponse(
            provider="sandbox", sandbox=True, options=_SANDBOX_RESTAURANTS
        )
    return RestaurantSearchResponse(provider="serpapi", sandbox=False, options=options)


@router.post(
    "/book-table",
    response_model=BookTableResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Reserve a table (deposit may be 0)",
)
async def book_table(
    request: BookTableRequest,
    user: UserORM = Depends(get_current_user),
    wallet: WalletService = Depends(get_wallet_service),
) -> BookTableResponse:
    try:
        purchase, budget = await wallet.purchase(
            guest_id=user.guest_id,
            kind="restaurant",
            title=request.restaurant_name,
            subtitle=f"Table for {request.guests} · {request.date} {request.time}",
            amount_cents=request.deposit_cents,
            currency=request.currency,
            details={
                "guests": request.guests,
                "date": request.date,
                "time": request.time,
                "note": request.note,
            },
        )
    except InvalidPurchaseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid booking.") from exc
    except InsufficientBudgetError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This would exceed your remaining budget.",
        ) from exc
    # Flat demo reward per seat, mirroring the "Est Reward" on the design.
    points = request.guests * 225
    return BookTableResponse(
        booking_id=purchase.id,
        restaurant_name=request.restaurant_name,
        guests=request.guests,
        date=request.date,
        time=request.time,
        points_earned=points,
        balance_cents=budget.balance_cents,
    )
