"""End-to-end tests for room-service (menu + orders), async DB-backed."""

from __future__ import annotations

from httpx import AsyncClient


async def test_get_menu_returns_seeded_items(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/stays/stay_123/menu")
    assert resp.status_code == 200
    items = resp.json()
    by_id = {item["id"]: item for item in items}

    # Contract example items are present with the expected prices in cents.
    assert by_id["m_burger"]["name"] == "Wagyu Beef Burger"
    assert by_id["m_burger"]["priceCents"] == 2800
    assert by_id["m_burger"]["category"] == "Mains"
    assert by_id["m_cola"]["name"] == "Coca Cola"
    assert by_id["m_cola"]["priceCents"] == 600


async def test_get_menu_unknown_stay_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/stays/nope/menu")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Stay not found"}


async def test_place_order_computes_server_side_pricing(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/stays/stay_123/orders",
        json={
            "lines": [
                {"itemId": "m_burger", "quantity": 1},
                {"itemId": "m_cola", "quantity": 1},
            ]
        },
    )
    assert resp.status_code == 201
    body = resp.json()

    assert body["id"].startswith("ord_")
    assert body["stayId"] == "stay_123"
    assert body["status"] == "placed"
    # Server-authoritative pricing: burger 2800 + cola 600 = 3400, 15% off.
    assert body["subtotalCents"] == 3400
    assert body["discountCents"] == 510
    assert body["totalCents"] == 2890

    # Lines are enriched with canonical name/price from the menu.
    line_by_id = {line["itemId"]: line for line in body["lines"]}
    assert line_by_id["m_burger"]["name"] == "Wagyu Beef Burger"
    assert line_by_id["m_burger"]["priceCents"] == 2800
    assert line_by_id["m_burger"]["quantity"] == 1
    assert line_by_id["m_cola"]["priceCents"] == 600

    # ISO-8601 UTC with a trailing Z.
    assert body["placedAt"].endswith("Z")


async def test_place_order_ignores_client_supplied_totals(client: AsyncClient) -> None:
    # Extra/bogus pricing fields in the body must not influence the result.
    resp = await client.post(
        "/api/v1/stays/stay_123/orders",
        json={
            "lines": [{"itemId": "m_burger", "quantity": 2}],
            "subtotalCents": 1,
            "discountCents": 0,
            "totalCents": 1,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["subtotalCents"] == 5600  # 2800 * 2
    assert body["discountCents"] == 840  # round(5600 * 0.15)
    assert body["totalCents"] == 4760


async def test_place_order_unknown_item_returns_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/stays/stay_123/orders",
        json={"lines": [{"itemId": "m_does_not_exist", "quantity": 1}]},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Menu item not found"}


async def test_place_order_unknown_stay_returns_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/stays/nope/orders",
        json={"lines": [{"itemId": "m_burger", "quantity": 1}]},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Stay not found"}


async def test_place_order_empty_lines_returns_422(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/stays/stay_123/orders", json={"lines": []})
    assert resp.status_code == 422


async def test_place_order_zero_quantity_returns_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/stays/stay_123/orders",
        json={"lines": [{"itemId": "m_burger", "quantity": 0}]},
    )
    assert resp.status_code == 422


async def test_list_orders_returns_placed_order_most_recent_first(
    client: AsyncClient,
) -> None:
    # Empty to start.
    assert (await client.get("/api/v1/stays/stay_123/orders")).json() == []

    first = (
        await client.post(
            "/api/v1/stays/stay_123/orders",
            json={"lines": [{"itemId": "m_cola", "quantity": 1}]},
        )
    ).json()
    second = (
        await client.post(
            "/api/v1/stays/stay_123/orders",
            json={"lines": [{"itemId": "m_burger", "quantity": 1}]},
        )
    ).json()

    resp = await client.get("/api/v1/stays/stay_123/orders")
    assert resp.status_code == 200
    orders = resp.json()
    assert len(orders) == 2
    # Most recent first.
    assert orders[0]["id"] == second["id"]
    assert orders[1]["id"] == first["id"]


async def test_orders_are_scoped_per_stay(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/stays/stay_123/orders",
        json={"lines": [{"itemId": "m_burger", "quantity": 1}]},
    )
    # Another known stay has no orders of its own.
    resp = await client.get("/api/v1/stays/stay_456/orders")
    assert resp.status_code == 200
    assert resp.json() == []
