"""End-to-end tests for provider connections (real DB, sandbox connector).

Exercises the connector framework via the API against the real test database:
linking imports reservations as real ``stays`` rows tagged
``source='booking.com'`` and stores the sandbox Genius level; re-linking is
idempotent; unlink deletes the connection but keeps the imported stays.
"""

from __future__ import annotations

from httpx import AsyncClient


async def test_link_with_scopes_returns_201_linked_sandbox(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/api/v1/connections/booking/link",
        json={
            "guestId": "guest_demo",
            "scopes": ["import_bookings", "sync_genius"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["connectionId"].startswith("conn_")
    assert body["provider"] == "booking.com"
    assert body["status"] == "linked"
    assert body["sandbox"] is True
    assert set(body["scopes"]) == {"import_bookings", "sync_genius"}
    # sync_genius -> level set; import_bookings -> 2 reservations imported.
    assert body["geniusLevel"] == 2
    assert body["importedStays"] == 2
    assert "connectedAt" in body and body["connectedAt"].endswith("Z")


async def test_link_imports_real_stays_with_booking_source(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/api/v1/connections/booking/link",
        json={"guestId": "guest_demo", "scopes": ["import_bookings"]},
    )
    assert resp.status_code == 201
    assert resp.json()["importedStays"] == 2
    # No genius scope -> level stays null.
    assert resp.json()["geniusLevel"] is None

    # The imported reservations exist as real, fetchable stay rows.
    stay = await client.get("/api/v1/stays/stay_res_AMS_8842301")
    assert stay.status_code == 200
    body = stay.json()
    assert body["propertyName"].startswith("Hotel Estherea")
    assert body["roomNumber"] == "Deluxe Canal View King"

    stay2 = await client.get("/api/v1/stays/stay_res_BCN_9912045")
    assert stay2.status_code == 200


async def test_genius_only_scope_sets_level_no_imports(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/api/v1/connections/booking/link",
        json={"guestId": "guest_demo", "scopes": ["sync_genius"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["geniusLevel"] == 2
    assert body["importedStays"] == 0
    # No stays imported.
    assert (await client.get("/api/v1/stays/stay_res_AMS_8842301")).status_code == 404


async def test_relink_does_not_duplicate_imported_stays(
    client: AsyncClient,
) -> None:
    first = await client.post(
        "/api/v1/connections/booking/link",
        json={"guestId": "guest_demo", "scopes": ["import_bookings"]},
    )
    assert first.json()["importedStays"] == 2

    # Re-link: a new connection, but the same reservations (deterministic
    # external_ref) must not create duplicate stay rows.
    second = await client.post(
        "/api/v1/connections/booking/link",
        json={"guestId": "guest_demo", "scopes": ["import_bookings"]},
    )
    assert second.status_code == 201
    assert second.json()["importedStays"] == 2

    # The two deterministic stays still resolve (1:1 with the reservations).
    assert (
        await client.get("/api/v1/stays/stay_res_AMS_8842301")
    ).status_code == 200
    assert (
        await client.get("/api/v1/stays/stay_res_BCN_9912045")
    ).status_code == 200


async def test_list_returns_connection(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/connections/booking/link",
        json={"guestId": "guest_demo", "scopes": ["sync_genius"]},
    )
    conn_id = created.json()["connectionId"]

    resp = await client.get("/api/v1/connections?guestId=guest_demo")
    assert resp.status_code == 200
    conns = resp.json()
    assert any(c["connectionId"] == conn_id for c in conns)
    assert all(c["provider"] == "booking.com" for c in conns)


async def test_unlink_returns_204_then_list_empty(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/connections/booking/link",
        json={"guestId": "guest_demo", "scopes": ["import_bookings"]},
    )
    conn_id = created.json()["connectionId"]

    delete = await client.delete(f"/api/v1/connections/{conn_id}")
    assert delete.status_code == 204

    resp = await client.get("/api/v1/connections?guestId=guest_demo")
    assert resp.status_code == 200
    assert resp.json() == []

    # Imported stays are kept after unlink (FK nulled), documented behaviour.
    stay = await client.get("/api/v1/stays/stay_res_AMS_8842301")
    assert stay.status_code == 200


async def test_unlink_unknown_connection_returns_404(
    client: AsyncClient,
) -> None:
    resp = await client.delete("/api/v1/connections/conn_does_not_exist")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Connection not found"}


async def test_link_empty_scopes_returns_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/connections/booking/link",
        json={"guestId": "guest_demo", "scopes": []},
    )
    assert resp.status_code == 422


async def test_link_unknown_guest_returns_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/connections/booking/link",
        json={"guestId": "ghost", "scopes": ["sync_genius"]},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Guest not found"}


async def test_link_unknown_provider_returns_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/connections/airbnb/link",
        json={"guestId": "guest_demo", "scopes": ["sync_genius"]},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Unknown provider"}


async def test_expense_tracking_scope_recorded(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/connections/booking/link",
        json={"guestId": "guest_demo", "scopes": ["expense_tracking"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["scopes"] == ["expense_tracking"]
    assert body["importedStays"] == 0
    assert body["geniusLevel"] is None
