"""Auth profile + live transfer route tests."""

from __future__ import annotations

from datetime import datetime, timezone

from httpx import AsyncClient

from app.api.deps import get_transfer_service
from app.main import app
from app.models.market import TransferDriver, TransferOption, TransferTrack
from app.services.transfer_service import LiveTrip


async def _register_user(
    client: AsyncClient,
    *,
    email: str = "anna@example.com",
    phone_number: str = "+12025550100",
) -> tuple[str, dict]:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password123",
            "fullName": "Anna Eriksson",
            "phoneNumber": phone_number,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    return body["accessToken"], body["user"]


async def test_register_and_update_profile(client: AsyncClient) -> None:
    token, user = await _register_user(client)
    assert user["phoneNumber"] == "+12025550100"

    patch = await client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"fullName": "Anna E.", "phoneNumber": "+12025550199"},
    )
    assert patch.status_code == 200
    assert patch.json()["fullName"] == "Anna E."
    assert patch.json()["phoneNumber"] == "+12025550199"

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["phoneNumber"] == "+12025550199"


class _FakeLiveTransferService:
    provider = "uber"
    sandbox = False

    async def search(
        self,
        *,
        pickup: str,
        destination: str,
        pickup_lat: float | None = None,
        pickup_lng: float | None = None,
        destination_lat: float | None = None,
        destination_lng: float | None = None,
    ) -> list[TransferOption]:
        return [
            TransferOption(
                id="prod_x",
                service="UberX",
                description="Live test ride",
                eta_minutes=4,
                arrival_label="12:30",
                price_cents=2450,
                currency="USD",
                seats=4,
                fare_id="fare_live_123",
            )
        ]

    async def book_live_trip(
        self,
        *,
        option: TransferOption,
        pickup: str,
        destination: str,
        pickup_lat: float | None,
        pickup_lng: float | None,
        destination_lat: float | None,
        destination_lng: float | None,
        fare_id: str | None,
        guest_name: str,
        guest_phone_number: str | None,
    ) -> LiveTrip:
        assert guest_phone_number == "+12025550100"
        return LiveTrip(
            provider_trip_id="trip_live_123",
            status="arriving",
            status_label="accepted",
            eta_minutes=4,
            driver=TransferDriver(
                name="Marco Rossi",
                rating=4.95,
                vehicle="Toyota Camry",
                plate="ABC-1234",
            ),
            details={
                "provider": "uber",
                "providerTripId": "trip_live_123",
                "fareId": fare_id,
            },
        )

    async def track_booking(
        self,
        *,
        booking_id: str,
        booked_at: datetime,
        purchase_details: dict,
    ) -> TransferTrack:
        assert purchase_details["providerTripId"] == "trip_live_123"
        assert booked_at.tzinfo == timezone.utc
        return TransferTrack(
            booking_id=booking_id,
            status="in_progress",
            progress=0.55,
            eta_minutes=7,
            driver=TransferDriver(
                name="Marco Rossi",
                rating=4.95,
                vehicle="Toyota Camry",
                plate="ABC-1234",
            ),
            status_label="on_trip",
        )

    def driver_for(self, booking_id: str) -> TransferDriver:
        return TransferDriver(
            name="Marco Rossi",
            rating=4.95,
            vehicle="Toyota Camry",
            plate="ABC-1234",
        )


async def test_live_transfer_booking_and_tracking(client: AsyncClient) -> None:
    token, _user = await _register_user(client)
    app.dependency_overrides[get_transfer_service] = _FakeLiveTransferService
    try:
        booked = await client.post(
            "/api/v1/transfers/book",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "optionId": "prod_x",
                "pickup": "Grand Mirage Hotel",
                "destination": "Istanbul Airport",
                "fareId": "fare_live_123",
            },
        )
        assert booked.status_code == 201
        body = booked.json()
        assert body["providerTripId"] == "trip_live_123"
        assert body["status"] == "arriving"
        assert body["statusLabel"] == "accepted"

        tracked = await client.get(
            f"/api/v1/transfers/{body['bookingId']}/track",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert tracked.status_code == 200
        track = tracked.json()
        assert track["status"] == "in_progress"
        assert track["statusLabel"] == "on_trip"
        assert track["driver"]["name"] == "Marco Rossi"
    finally:
        app.dependency_overrides.pop(get_transfer_service, None)
