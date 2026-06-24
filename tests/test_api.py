"""End-to-end API tests (async httpx client against a real Postgres test DB)."""

from __future__ import annotations

import json
from copy import deepcopy

from httpx import AsyncClient

VALID_PASSPORT = {
    "documentNumber": "P1234567",
    "surname": "YILMAZ",
    "givenNames": "AHMET",
    "nationality": "TUR",
    "issuingCountry": "TUR",
    "dateOfBirth": "1990-05-12T00:00:00Z",
    "expiryDate": "2030-05-12T00:00:00Z",
    "sex": "male",
    "checksumValid": True,
}


def _payload(stay_id: str = "stay_123", **passport_overrides: object) -> str:
    passport = deepcopy(VALID_PASSPORT)
    passport.update(passport_overrides)
    return json.dumps(
        {
            "stayId": stay_id,
            "passport": passport,
            "faceVerification": {
                "passed": True,
                "challenge": "smile",
                "confidence": 0.91,
                "completedAt": "2099-06-04T12:00:00Z",
                "captureCount": 2,
            },
        }
    )


async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_get_seeded_stay(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/stays/stay_123")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "stay_123"
    assert body["propertyName"] == "The Bosphorus Suites"
    assert body["roomNumber"] == "402"
    assert body["checkInDate"] == "2026-06-04T14:00:00Z"
    assert body["checkOutDate"] == "2026-06-08T11:00:00Z"
    assert "address" in body


async def test_get_unknown_stay_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/stays/does_not_exist")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Stay not found"}


async def test_successful_check_in_issues_key(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/check-ins",
        data={"payload": _payload()},
        files={"selfie": ("selfie.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "verified"
    assert body["checkInId"].startswith("ci_")
    assert body["stay"]["id"] == "stay_123"

    key = body["digitalKey"]
    assert key is not None
    assert key["keyId"].startswith("key_")
    assert key["accessToken"]
    # Validity window equals the stay's check-in/out dates.
    assert key["validFrom"] == body["stay"]["checkInDate"]
    assert key["validUntil"] == body["stay"]["checkOutDate"]


async def test_check_in_without_selfie_is_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/check-ins", data={"payload": _payload()})
    assert resp.status_code == 201
    assert resp.json()["status"] == "rejected"
    assert resp.json()["rejectionReason"] == "Selfie verification is required."


async def test_expired_passport_is_rejected_without_key(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/check-ins",
        data={"payload": _payload(expiryDate="2000-01-01T00:00:00Z")},
    )
    # Accepted and persisted, but with a rejected status and no key.
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["digitalKey"] is None


async def test_invalid_checksum_is_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/check-ins",
        data={"payload": _payload(checksumValid=False)},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["digitalKey"] is None


async def test_check_in_without_face_verification_is_rejected(client: AsyncClient) -> None:
    payload = json.dumps({"stayId": "stay_123", "passport": deepcopy(VALID_PASSPORT)})
    resp = await client.post(
        "/api/v1/check-ins",
        data={"payload": payload},
        files={"selfie": ("selfie.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "rejected"
    assert (
        resp.json()["rejectionReason"]
        == "Face verification did not complete successfully."
    )


async def test_check_in_unknown_stay_returns_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/check-ins",
        data={"payload": _payload(stay_id="nope")},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Stay not found"}


async def test_missing_required_field_returns_422(client: AsyncClient) -> None:
    passport = deepcopy(VALID_PASSPORT)
    del passport["surname"]
    payload = json.dumps({"stayId": "stay_123", "passport": passport})
    resp = await client.post("/api/v1/check-ins", data={"payload": payload})
    assert resp.status_code == 422


async def test_malformed_json_payload_returns_422(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/check-ins", data={"payload": "{not json"})
    assert resp.status_code == 422


async def test_get_check_in_roundtrip(client: AsyncClient) -> None:
    created = (
        await client.post("/api/v1/check-ins", data={"payload": _payload()})
    ).json()
    check_in_id = created["checkInId"]

    fetched = await client.get(f"/api/v1/check-ins/{check_in_id}")
    assert fetched.status_code == 200
    assert fetched.json() == created


async def test_get_unknown_check_in_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/check-ins/ci_missing")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Check-in not found"}
