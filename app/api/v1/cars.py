"""Car rental endpoints (Sixt-branded sandbox; live adapter ready)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_car_service, get_current_user, get_wallet_service
from app.db.models.user import UserORM
from app.models.market import CarBookRequest, CarOffer, CarSearchResponse
from app.models.travel_wallet import PurchaseOut, PurchaseResult
from app.services.car_service import (
    CarProviderNotConfiguredError,
    CarSearchError,
    CarService,
)
from app.services.wallet_service import (
    InsufficientBudgetError,
    InvalidPurchaseError,
    WalletService,
)

router = APIRouter(prefix="/cars", tags=["cars"])


@router.get("/search", response_model=CarSearchResponse, summary="Search rental cars")
async def search_cars(
    pickup: str = Query(default=""),
    category: str | None = Query(default=None),
    cars: CarService = Depends(get_car_service),
) -> CarSearchResponse:
    try:
        offers = await cars.search(pickup=pickup, category=category)
    except CarProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Live car provider selected but credentials missing: {exc.missing}",
        ) from exc
    except CarSearchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Car search failed upstream. Please try again.",
        ) from exc
    return CarSearchResponse(provider=cars.provider, sandbox=cars.sandbox, offers=offers)


@router.get("/{offer_id}", response_model=CarOffer, summary="Car offer details")
async def get_car(
    offer_id: str,
    cars: CarService = Depends(get_car_service),
) -> CarOffer:
    offer = await cars.get(offer_id)
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown car offer")
    return offer


@router.post(
    "/book",
    response_model=PurchaseResult,
    status_code=status.HTTP_201_CREATED,
    summary="Book a rental car (charges the travel wallet)",
)
async def book_car(
    request: CarBookRequest,
    user: UserORM = Depends(get_current_user),
    cars: CarService = Depends(get_car_service),
    wallet: WalletService = Depends(get_wallet_service),
) -> PurchaseResult:
    offer = await cars.get(request.offer_id)
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown car offer")
    total = offer.price_per_day_cents * request.days
    try:
        purchase, budget = await wallet.purchase(
            guest_id=user.guest_id,
            kind="car",
            title=f"{offer.partner} · {offer.name}",
            subtitle=f"{request.days} day{'s' if request.days != 1 else ''} · {request.pickup or offer.pickup_location or 'Airport pickup'}",
            amount_cents=total,
            currency=offer.currency,
            details={
                "offerId": offer.id,
                "category": offer.category,
                "days": request.days,
                "pickup": request.pickup,
                "dropoff": request.dropoff,
                "pickupDate": request.pickup_date,
            },
        )
    except InvalidPurchaseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid booking.") from exc
    except InsufficientBudgetError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This would exceed your remaining budget.",
        ) from exc
    return PurchaseResult(
        purchase=PurchaseOut.model_validate(purchase),
        balance_cents=budget.balance_cents,
    )
