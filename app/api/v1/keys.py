"""Digital room keys issued from hotel bookings.

A hotel purchase in the travel wallet can be turned into a real, signed digital
key (same HMAC token + stay/check-in rows as the passport check-in flow), so
booked rooms open with the NFC hold-to-unlock screen. Issuance is idempotent
per purchase (re-requesting returns the same key).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_key_service, get_wallet_service
from app.db.models.stay import CheckInORM, DigitalKeyORM, StayORM
from app.db.models.user import UserORM
from app.db.session import get_session
from app.models.market import RoomKeyOut, RoomKeyRequest
from app.models.stay import StayInfo
from app.services.key_service import KeyService
from app.services.wallet_service import WalletService

router = APIRouter(prefix="/keys", tags=["keys"])


@router.post(
    "/hotel",
    response_model=RoomKeyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Issue (or fetch) the digital room key for a hotel booking",
)
async def issue_hotel_key(
    request: RoomKeyRequest,
    user: UserORM = Depends(get_current_user),
    wallet: WalletService = Depends(get_wallet_service),
    keys: KeyService = Depends(get_key_service),
    session: AsyncSession = Depends(get_session),
) -> RoomKeyOut:
    purchase = await wallet.get_purchase(request.purchase_id)
    if purchase is None or purchase.guest_id != user.guest_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown booking")
    if purchase.kind != "hotel":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Digital keys are issued for hotel bookings only.",
        )

    stay_id = (purchase.details or {}).get("stayId")
    existing = None
    if isinstance(stay_id, str) and stay_id.strip():
        existing = await session.get(StayORM, stay_id.strip())
    if existing is None:
        external_ref = f"wallet:{purchase.id}"
        existing = (
            await session.execute(
                select(StayORM).where(StayORM.external_ref == external_ref)
            )
        ).scalar_one_or_none()
    if existing is not None:
        key_row = (
            await session.execute(
                select(DigitalKeyORM)
                .join(CheckInORM, DigitalKeyORM.check_in_id == CheckInORM.id)
                .where(CheckInORM.stay_id == existing.id)
            )
        ).scalar_one_or_none()
        if key_row is not None:
            return _to_out(existing, key_row)

    nights = 1
    raw_nights = (purchase.details or {}).get("nights")
    if isinstance(raw_nights, (int, float)) and raw_nights > 0:
        nights = min(int(raw_nights), 30)

    now = datetime.now(timezone.utc)
    check_in = now.replace(minute=0, second=0, microsecond=0)
    check_out = (check_in + timedelta(days=nights)).replace(hour=11)
    # Deterministic, plausible room number per booking (4th-7th floor).
    digest = hashlib.sha256(purchase.id.encode()).digest()
    room_number = f"{4 + digest[0] % 4}{digest[1] % 30 + 1:02d}"

    stay = existing or StayORM(
        id=f"stay_{secrets.token_hex(8)}",
        property_name=purchase.title,
        room_number=room_number,
        check_in_date=check_in,
        check_out_date=check_out,
        address=purchase.subtitle or "Booked via StayWallet",
        source="manual",
        external_ref=f"wallet:{purchase.id}",
    )
    if existing is None:
        session.add(stay)
    check_in_row = CheckInORM(
        id=f"chk_{secrets.token_hex(8)}",
        stay_id=stay.id,
        status="VERIFIED",
        created_at=now,
    )
    session.add(check_in_row)

    digital_key = keys.issue_key(
        StayInfo(
            id=stay.id,
            property_name=stay.property_name,
            room_number=stay.room_number,
            check_in_date=stay.check_in_date,
            check_out_date=stay.check_out_date,
            address=stay.address,
        )
    )
    key_row = DigitalKeyORM(
        id=digital_key.key_id,
        check_in_id=check_in_row.id,
        access_token=digital_key.access_token,
        valid_from=digital_key.valid_from,
        valid_until=digital_key.valid_until,
    )
    session.add(key_row)
    await session.flush()
    return _to_out(stay, key_row)


def _to_out(stay: StayORM, key_row: DigitalKeyORM) -> RoomKeyOut:
    return RoomKeyOut(
        key_id=key_row.id,
        property_name=stay.property_name,
        room_number=stay.room_number,
        access_token=key_row.access_token,
        valid_from=key_row.valid_from.isoformat(),
        valid_until=key_row.valid_until.isoformat(),
    )
