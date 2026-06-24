"""Tests for the AI concierge text-to-speech proxy (async).

These tests NEVER hit the real ElevenLabs API: a stub ``httpx.MockTransport`` is
injected into the service so the upstream call is fully simulated. They use the
ASGI ``client`` fixture (real app) with the TTS provider overridden.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from httpx import AsyncClient

from app.api.deps import get_tts_service
from app.core.config import Settings
from app.main import app
from app.services.tts_service import TtsService

# Fixed fake MP3 payload returned by the stub transport.
FAKE_MP3 = b"ID3FAKE-MP3-BYTES"


def _make_stub_client(captured: dict | None = None) -> httpx.AsyncClient:
    """Return an AsyncClient whose transport returns FAKE_MP3 without networking."""

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["url"] = str(request.url)
            captured["xi-api-key"] = request.headers.get("xi-api-key")
            captured["body"] = request.content
        return httpx.Response(
            200, content=FAKE_MP3, headers={"content-type": "audio/mpeg"}
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    """Ensure the TTS dependency override doesn't leak between tests."""

    yield
    app.dependency_overrides.pop(get_tts_service, None)


async def test_tts_returns_mp3_audio(client: AsyncClient) -> None:
    captured: dict = {}
    settings = Settings(
        elevenlabs_api_key="test-key", elevenlabs_voice_id="voice_default"
    )

    app.dependency_overrides[get_tts_service] = lambda: TtsService(
        settings=settings, client=_make_stub_client(captured)
    )

    resp = await client.post("/api/v1/voice/tts", json={"text": "Hello there"})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == FAKE_MP3
    # Default voice used; key sent server-side; never echoed to the client.
    assert captured["url"].endswith("/voice_default")
    assert captured["xi-api-key"] == "test-key"


async def test_tts_uses_request_voice_id_override(client: AsyncClient) -> None:
    captured: dict = {}
    settings = Settings(
        elevenlabs_api_key="test-key", elevenlabs_voice_id="voice_default"
    )

    app.dependency_overrides[get_tts_service] = lambda: TtsService(
        settings=settings, client=_make_stub_client(captured)
    )

    resp = await client.post(
        "/api/v1/voice/tts",
        json={"text": "Hello", "voiceId": "custom_voice"},
    )

    assert resp.status_code == 200
    assert captured["url"].endswith("/custom_voice")


async def test_tts_returns_503_when_no_api_key(client: AsyncClient) -> None:
    settings = Settings(elevenlabs_api_key=None)
    app.dependency_overrides[get_tts_service] = lambda: TtsService(settings=settings)

    resp = await client.post("/api/v1/voice/tts", json={"text": "Hello"})
    assert resp.status_code == 503


async def test_tts_returns_422_for_empty_text(client: AsyncClient) -> None:
    settings = Settings(elevenlabs_api_key="test-key")
    app.dependency_overrides[get_tts_service] = lambda: TtsService(
        settings=settings, client=_make_stub_client()
    )

    resp = await client.post("/api/v1/voice/tts", json={"text": ""})
    assert resp.status_code == 422


async def test_tts_returns_422_for_whitespace_only_text(client: AsyncClient) -> None:
    settings = Settings(elevenlabs_api_key="test-key")
    app.dependency_overrides[get_tts_service] = lambda: TtsService(
        settings=settings, client=_make_stub_client()
    )

    resp = await client.post("/api/v1/voice/tts", json={"text": "   "})
    assert resp.status_code == 422


async def test_tts_returns_422_for_too_long_text(client: AsyncClient) -> None:
    settings = Settings(elevenlabs_api_key="test-key")
    app.dependency_overrides[get_tts_service] = lambda: TtsService(
        settings=settings, client=_make_stub_client()
    )

    resp = await client.post("/api/v1/voice/tts", json={"text": "a" * 501})
    assert resp.status_code == 422


async def test_tts_returns_502_on_upstream_failure(client: AsyncClient) -> None:
    settings = Settings(elevenlabs_api_key="test-key")

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"upstream boom")

    app.dependency_overrides[get_tts_service] = lambda: TtsService(
        settings=settings,
        client=httpx.AsyncClient(transport=httpx.MockTransport(failing_handler)),
    )

    resp = await client.post("/api/v1/voice/tts", json={"text": "Hello"})
    assert resp.status_code == 502
