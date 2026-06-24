"""AI concierge text-to-speech proxy.

Proxies ElevenLabs server-side so the API key never ships in the mobile app.
All HTTP-to-ElevenLabs detail is confined to this module; the router only sees
domain exceptions and raw MP3 bytes.

Validation / error policy (for the contract):

* No API key configured -> :class:`TtsNotConfiguredError`  (router returns 503).
* Upstream failure       -> :class:`TtsUpstreamError`      (router returns 502).
* Empty/over-long text is rejected by Pydantic at the boundary (HTTP 422).

The httpx client is **injectable** so tests can supply a stub transport and never
touch the network.
"""

from __future__ import annotations

import httpx

from app.core.config import Settings, get_settings
from app.services.exceptions import TtsNotConfiguredError, TtsUpstreamError

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1/text-to-speech"
ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"
# Bound the upstream call so a slow/hung ElevenLabs request can't pin a worker.
DEFAULT_TIMEOUT_SECONDS = 30.0


class TtsService:
    """Synthesises speech via ElevenLabs and returns raw MP3 bytes."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        # Injectable for tests; in production a fresh client is created per call
        # (see ``synthesize``) so the service stays stateless.
        self._client = client

    async def synthesize(self, text: str, voice_id: str | None = None) -> bytes:
        """Return MP3 bytes for ``text`` spoken in the requested/default voice.

        Raises:
            TtsNotConfiguredError: If no ElevenLabs API key is configured.
            TtsUpstreamError: If the ElevenLabs request fails or returns non-2xx.
        """

        api_key = self._settings.elevenlabs_api_key
        if not api_key:
            raise TtsNotConfiguredError()

        resolved_voice = voice_id or self._settings.elevenlabs_voice_id
        url = f"{ELEVENLABS_BASE_URL}/{resolved_voice}"
        headers = {
            "xi-api-key": api_key,
            "accept": "audio/mpeg",
            "content-type": "application/json",
        }
        payload = {"text": text, "model_id": ELEVENLABS_MODEL_ID}

        if self._client is not None:
            return await self._request(self._client, url, headers, payload)

        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            return await self._request(client, url, headers, payload)

    @staticmethod
    async def _request(
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        payload: dict[str, str],
    ) -> bytes:
        """Perform the POST and return MP3 bytes, mapping failures to domain errors."""

        try:
            response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise TtsUpstreamError(f"ElevenLabs request failed: {exc}") from exc

        if response.status_code >= 400:
            raise TtsUpstreamError(
                f"ElevenLabs returned status {response.status_code}"
            )

        return response.content
