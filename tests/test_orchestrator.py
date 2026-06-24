"""End-to-end tests for the Loyalty Orchestrator (real DB).

Drives the API against the freshly seeded test database: the demo guest has 12
linked ecosystems summing to 1,240,500 points (booking_com/sixt/miles_smiles
first) and 3 discovered ones. Linking folds a discovered ecosystem's points into
the aggregate; auto-scan links them all. All assertions hit Postgres.
"""

from __future__ import annotations

from httpx import AsyncClient

SUMMARY_URL = "/api/v1/orchestrator?guestId=guest_demo"


async def test_summary_returns_seeded_shape(client: AsyncClient) -> None:
    resp = await client.get(SUMMARY_URL)
    assert resp.status_code == 200
    body = resp.json()

    assert body["totalPoints"] == 1240500
    assert body["trendPct"] == 12
    assert body["ecosystemsCount"] == 12
    assert body["ecosystemsNew"] == 2

    integrations = body["integrations"]
    assert len(integrations) == 12
    # Top row matches the mockup: booking_com, sixt, miles_smiles first.
    assert [p["id"] for p in integrations[:3]] == [
        "booking_com",
        "sixt",
        "miles_smiles",
    ]
    assert all(p["linked"] is True for p in integrations)
    assert all(p["points"] is not None for p in integrations)
    assert all(p["detectedLabel"] is None for p in integrations)
    # Linked points sum to the headline total.
    assert sum(p["points"] for p in integrations) == 1240500

    # Brand metadata is surfaced.
    sixt = next(p for p in integrations if p["id"] == "sixt")
    assert sixt["brandColorHex"] == "#FF5F00"
    assert sixt["icon"] == "directions_car"

    discovered = body["discovered"]
    assert {p["id"] for p in discovered} == {"uber", "amex", "marriott"}
    assert all(p["linked"] is False for p in discovered)
    assert all(p["detectedLabel"] for p in discovered)
    uber = next(p for p in discovered if p["id"] == "uber")
    assert uber["detectedLabel"] == "2,450 points detected"
    # Discovered points are not exposed (only revealed once linked).
    assert uber["points"] is None


async def test_link_moves_provider_to_integrations(client: AsyncClient) -> None:
    before = (await client.get(SUMMARY_URL)).json()

    resp = await client.post(
        "/api/v1/orchestrator/link",
        json={"guestId": "guest_demo", "providerId": "uber"},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["ecosystemsCount"] == 13
    assert body["totalPoints"] == before["totalPoints"] + 2450

    integration_ids = {p["id"] for p in body["integrations"]}
    assert "uber" in integration_ids
    uber = next(p for p in body["integrations"] if p["id"] == "uber")
    assert uber["linked"] is True
    assert uber["points"] == 2450
    assert uber["detectedLabel"] is None

    discovered_ids = {p["id"] for p in body["discovered"]}
    assert "uber" not in discovered_ids
    assert discovered_ids == {"amex", "marriott"}
    assert len(body["discovered"]) == 2


async def test_link_creates_sandbox_connection(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/orchestrator/link",
        json={"guestId": "guest_demo", "providerId": "uber"},
    )
    conns = (await client.get("/api/v1/connections?guestId=guest_demo")).json()
    uber_conn = next(
        c for c in conns if c["provider"] == "orchestrator:uber"
    )
    assert uber_conn["sandbox"] is True
    assert uber_conn["status"] == "linked"


async def test_auto_scan_links_all_discovered(client: AsyncClient) -> None:
    before = (await client.get(SUMMARY_URL)).json()
    discovered_points = 2450 + 31000 + 56000

    resp = await client.post(
        "/api/v1/orchestrator/auto-scan",
        json={"guestId": "guest_demo"},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["discovered"] == []
    assert body["ecosystemsCount"] == 15
    assert body["totalPoints"] == before["totalPoints"] + discovered_points
    integration_ids = {p["id"] for p in body["integrations"]}
    assert {"uber", "amex", "marriott"} <= integration_ids


async def test_link_unknown_provider_returns_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/orchestrator/link",
        json={"guestId": "guest_demo", "providerId": "does_not_exist"},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Unknown provider"}


async def test_link_already_linked_returns_409(client: AsyncClient) -> None:
    # sixt is seeded as linked; re-linking must conflict.
    resp = await client.post(
        "/api/v1/orchestrator/link",
        json={"guestId": "guest_demo", "providerId": "sixt"},
    )
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Provider already linked"}


async def test_link_unknown_guest_returns_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/orchestrator/link",
        json={"guestId": "ghost", "providerId": "uber"},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Guest not found"}


async def test_auto_scan_unknown_guest_returns_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/orchestrator/auto-scan",
        json={"guestId": "ghost"},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Guest not found"}


async def test_link_then_summary_is_consistent(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/orchestrator/link",
        json={"guestId": "guest_demo", "providerId": "marriott"},
    )
    summary = (await client.get(SUMMARY_URL)).json()
    assert summary["ecosystemsCount"] == 13
    assert summary["totalPoints"] == 1240500 + 56000
    assert {p["id"] for p in summary["discovered"]} == {"uber", "amex"}
