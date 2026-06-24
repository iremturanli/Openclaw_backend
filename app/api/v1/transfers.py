"""Transfer (ride) + scooter endpoints (Uber/Tier sandbox; live adapter ready).

Booking charges the travel wallet; tracking derives the driver position from
wall-clock time since the booking so the demo "moves" with no live API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    get_current_user,
    get_transfer_service,
    get_wallet_service,
)
from app.db.models.user import UserORM
from app.models.market import (
    ScooterOffer,
    ScooterUnlockResponse,
    TransferBooking,
    TransferBookRequest,
    TransferSearchResponse,
    TransferTrack,
)
from app.services.transfer_service import (
    TransferProviderNotConfiguredError,
    TransferSearchError,
    TransferService,
)
from app.services.wallet_service import (
    InsufficientBudgetError,
    InvalidPurchaseError,
    WalletService,
)

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.get("/search", response_model=TransferSearchResponse, summary="Ride options")
async def search_transfers(
    pickup: str = Query(default="Current Location"),
    destination: str = Query(default="Airport"),
    pickup_lat: float | None = Query(default=None, alias="pickupLat"),
    pickup_lng: float | None = Query(default=None, alias="pickupLng"),
    destination_lat: float | None = Query(default=None, alias="destinationLat"),
    destination_lng: float | None = Query(default=None, alias="destinationLng"),
    transfers: TransferService = Depends(get_transfer_service),
) -> TransferSearchResponse:
    try:
        options = await transfers.search(
            pickup=pickup,
            destination=destination,
            pickup_lat=pickup_lat,
            pickup_lng=pickup_lng,
            destination_lat=destination_lat,
            destination_lng=destination_lng,
        )
    except TransferProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Live transfer provider selected but credentials missing: {exc.missing}",
        ) from exc
    except TransferSearchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Ride search failed upstream. Please try again.",
        ) from exc
    return TransferSearchResponse(
        provider=transfers.provider,
        sandbox=transfers.sandbox,
        pickup=pickup,
        destination=destination,
        options=options,
    )


@router.get("/scooters", response_model=list[ScooterOffer], summary="Nearby scooters")
async def list_scooters(
    near: str = Query(default="Downtown"),
    transfers: TransferService = Depends(get_transfer_service),
) -> list[ScooterOffer]:
    return await transfers.scooters(near=near)


@router.post(
    "/scooters/{scooter_id}/unlock",
    response_model=ScooterUnlockResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Unlock a scooter (charges the unlock fee)",
)
async def unlock_scooter(
    scooter_id: str,
    near: str = Query(default="Downtown"),
    user: UserORM = Depends(get_current_user),
    transfers: TransferService = Depends(get_transfer_service),
    wallet: WalletService = Depends(get_wallet_service),
) -> ScooterUnlockResponse:
    scooter = await transfers.get_scooter(scooter_id, near=near)
    if scooter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown scooter")
    try:
        purchase, budget = await wallet.purchase(
            guest_id=user.guest_id,
            kind="scooter",
            title=f"Tier · {scooter.model}",
            subtitle=f"Unlock fee · {scooter.per_minute_cents / 100:.2f}/min after",
            amount_cents=scooter.unlock_fee_cents,
            currency=scooter.currency,
            details={"scooterId": scooter.id, "batteryPct": scooter.battery_pct},
        )
    except (InvalidPurchaseError, InsufficientBudgetError) as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Could not charge the unlock fee."
        ) from exc
    return ScooterUnlockResponse(
        ride_id=purchase.id,
        model=scooter.model,
        unlock_fee_cents=scooter.unlock_fee_cents,
        per_minute_cents=scooter.per_minute_cents,
        currency=scooter.currency,
        balance_cents=budget.balance_cents,
    )


@router.post(
    "/book",
    response_model=TransferBooking,
    status_code=status.HTTP_201_CREATED,
    summary="Book a ride (charges the travel wallet)",
)
async def book_transfer(
    request: TransferBookRequest,
    user: UserORM = Depends(get_current_user),
    transfers: TransferService = Depends(get_transfer_service),
    wallet: WalletService = Depends(get_wallet_service),
) -> TransferBooking:
    try:
        options = await transfers.search(
            pickup=request.pickup or "Current Location",
            destination=request.destination or "Airport",
            pickup_lat=request.pickup_lat,
            pickup_lng=request.pickup_lng,
            destination_lat=request.destination_lat,
            destination_lng=request.destination_lng,
        )
    except (TransferProviderNotConfiguredError, TransferSearchError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ride provider unavailable. Please try again.",
        ) from exc
    option = next((o for o in options if o.id == request.option_id), None)
    if option is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown ride option")
    if option.no_cars_available:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Uber reports no nearby drivers for this route right now.",
        )

    trip_details: dict[str, object] = {
        "service": option.service,
        "pickup": request.pickup,
        "destination": request.destination,
        "fareId": request.fare_id or option.fare_id,
        "pickupLat": request.pickup_lat,
        "pickupLng": request.pickup_lng,
        "destinationLat": request.destination_lat,
        "destinationLng": request.destination_lng,
    }
    provider_trip_id: str | None = None
    live_status = "arriving"
    live_eta = option.eta_minutes
    live_driver = transfers.driver_for(f"{user.id}:{option.id}")
    live_status_label: str | None = None

    if not transfers.sandbox:
        try:
            budget = await wallet.ensure_budget(user.guest_id)
            if option.price_cents > budget.balance_cents:
                raise InsufficientBudgetError(budget.balance_cents)
            live_trip = await transfers.book_live_trip(
                option=option,
                pickup=request.pickup or "Current Location",
                destination=request.destination or "Airport",
                pickup_lat=request.pickup_lat,
                pickup_lng=request.pickup_lng,
                destination_lat=request.destination_lat,
                destination_lng=request.destination_lng,
                fare_id=request.fare_id or option.fare_id,
                guest_name=user.full_name,
                guest_phone_number=user.phone_number,
            )
        except TransferProviderNotConfiguredError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Live transfer provider selected but credentials missing: {exc.missing}",
            ) from exc
        except TransferSearchError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        provider_trip_id = live_trip.provider_trip_id
        live_status = live_trip.status
        live_eta = live_trip.eta_minutes
        live_driver = live_trip.driver
        live_status_label = live_trip.status_label
        trip_details.update(live_trip.details)
    try:
        purchase, budget = await wallet.purchase(
            guest_id=user.guest_id,
            kind="transfer",
            title=f"Uber {option.service}",
            subtitle=f"{request.pickup or 'Current Location'} → {request.destination or 'Airport'}",
            amount_cents=option.price_cents,
            currency=option.currency,
            details=trip_details,
        )
    except InvalidPurchaseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid booking.") from exc
    except InsufficientBudgetError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This would exceed your remaining budget.",
        ) from exc
    return TransferBooking(
        booking_id=purchase.id,
        provider_trip_id=provider_trip_id,
        service=option.service,
        pickup=request.pickup or "Current Location",
        destination=request.destination or "Airport",
        price_cents=option.price_cents,
        currency=option.currency,
        driver=live_driver,
        eta_minutes=live_eta,
        status=live_status,
        status_label=live_status_label,
        balance_cents=budget.balance_cents,
    )


@router.get(
    "/{booking_id}/track",
    response_model=TransferTrack,
    summary="Track a booked ride (simulated)",
)
async def track_transfer(
    booking_id: str,
    user: UserORM = Depends(get_current_user),
    transfers: TransferService = Depends(get_transfer_service),
    wallet: WalletService = Depends(get_wallet_service),
) -> TransferTrack:
    purchase = await wallet.get_purchase(booking_id)
    if purchase is None or purchase.guest_id != user.guest_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown booking")
    try:
        track = await transfers.track_booking(
            booking_id=booking_id,
            booked_at=purchase.created_at,
            purchase_details=purchase.details or {},
        )
    except TransferSearchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return track
