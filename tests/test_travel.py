"""End-to-end tests for Travel Services & Loyalty (real DB-backed ledger)."""

from __future__ import annotations

from httpx import AsyncClient

SEEDED_BALANCE = 12450


async def test_list_categories_returns_seeded(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/travel/categories")
    assert resp.status_code == 200
    cats = resp.json()
    by_id = {c["id"]: c for c in cats}

    assert {"rental_car", "hotel", "restaurants", "travel_insurance", "e_visa"} <= set(
        by_id
    )
    assert by_id["rental_car"]["icon"] == "directions_car"
    assert by_id["rental_car"]["accent"] == "blue"
    assert by_id["rental_car"]["featured"] is False
    assert by_id["e_visa"]["accent"] == "amber"
    assert by_id["e_visa"]["featured"] is True


async def test_list_deals_returns_porsche(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/travel/deals")
    assert resp.status_code == 200
    deals = resp.json()
    porsche = next(d for d in deals if d["id"] == "porsche_911")
    assert porsche["title"] == "Porsche 911 Carrera S"
    assert porsche["discountLabel"] == "-15% OFF"
    assert porsche["discountNote"] == "with StayWallet card"
    assert porsche["imageUrl"].startswith("http")


async def test_loyalty_balance_from_ledger(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/loyalty?guestId=guest_demo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["points"] == SEEDED_BALANCE
    assert body["multiplierLabel"] == "3x"
    assert "note" in body and body["note"]


async def test_unknown_guest_has_zero_balance(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/loyalty?guestId=guest_nobody")
    assert resp.status_code == 200
    assert resp.json()["points"] == 0


async def test_booking_category_awards_points_and_increases_balance(
    client: AsyncClient,
) -> None:
    before = (await client.get("/api/v1/loyalty?guestId=guest_demo")).json()["points"]

    resp = await client.post(
        "/api/v1/travel/bookings",
        json={"guestId": "guest_demo", "categoryId": "rental_car"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["bookingId"].startswith("bk_")
    assert body["title"] == "Rental Car"
    # rental_car base = $150 → 150 * 1 (per dollar) * 3 (travel) = 450 points.
    assert body["pointsEarned"] == 450
    assert body["newBalance"] == before + 450

    # Balance endpoint reflects the new ledger total.
    after = (await client.get("/api/v1/loyalty?guestId=guest_demo")).json()["points"]
    assert after == before + 450


async def test_booking_deal_awards_points(client: AsyncClient) -> None:
    before = (await client.get("/api/v1/loyalty?guestId=guest_demo")).json()["points"]
    resp = await client.post(
        "/api/v1/travel/bookings",
        json={"guestId": "guest_demo", "dealId": "porsche_911"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Porsche 911 Carrera S"
    # porsche base = $750 → 750 * 3 = 2250 points.
    assert body["pointsEarned"] == 2250
    assert body["newBalance"] == before + 2250


async def test_booking_unknown_category_returns_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/travel/bookings",
        json={"guestId": "guest_demo", "categoryId": "does_not_exist"},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Travel category or deal not found"}


async def test_booking_unknown_deal_returns_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/travel/bookings",
        json={"guestId": "guest_demo", "dealId": "no_such_deal"},
    )
    assert resp.status_code == 404


async def test_booking_unknown_guest_returns_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/travel/bookings",
        json={"guestId": "ghost", "categoryId": "rental_car"},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Guest not found"}


async def test_booking_without_target_returns_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/travel/bookings",
        json={"guestId": "guest_demo"},
    )
    assert resp.status_code == 422


async def test_room_service_order_awards_loyalty_points(client: AsyncClient) -> None:
    before = (await client.get("/api/v1/loyalty?guestId=guest_demo")).json()["points"]

    resp = await client.post(
        "/api/v1/stays/stay_123/orders",
        json={"lines": [{"itemId": "m_burger", "quantity": 1}]},
    )
    assert resp.status_code == 201
    total_cents = resp.json()["totalCents"]  # 2800 - 15% = 2380
    # 1x multiplier: floor(2380/100) = 23 points.
    expected = total_cents // 100

    after = (await client.get("/api/v1/loyalty?guestId=guest_demo")).json()["points"]
    assert after == before + expected
    assert expected == 23


async def test_booking_is_atomic_persists_booking_row(client: AsyncClient) -> None:
    # A successful booking persists a row that contributes to the balance even
    # across a fresh request (proving it committed, not just in-memory).
    await client.post(
        "/api/v1/travel/bookings",
        json={"guestId": "guest_demo", "categoryId": "hotel"},
    )
    # hotel base = $220 → 220 * 3 = 660 points on top of seeded 12450.
    after = (await client.get("/api/v1/loyalty?guestId=guest_demo")).json()["points"]
    assert after == SEEDED_BALANCE + 660
