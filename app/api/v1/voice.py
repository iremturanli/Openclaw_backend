"""AI concierge text-to-speech proxy endpoint.

Accepts text and an optional ``voiceId`` and returns raw MP3 bytes synthesised by
ElevenLabs server-side. The API key never leaves the backend.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_tts_service
from app.models.voice import TtsRequest
from app.services.exceptions import TtsNotConfiguredError, TtsUpstreamError
from app.services.tts_service import TtsService

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post(
    "/tts",
    summary="Synthesise concierge speech via the ElevenLabs proxy",
    responses={
        200: {"content": {"audio/mpeg": {}}, "description": "Raw MP3 audio"},
        422: {"description": "Text is empty or too long"},
        502: {"description": "Upstream text-to-speech provider failed"},
        503: {"description": "Text-to-speech is not configured"},
    },
)
async def synthesize_speech(
    request: TtsRequest,
    service: TtsService = Depends(get_tts_service),
) -> Response:
    """Return ``audio/mpeg`` bytes for the requested text.

    Returns 503 when no API key is configured, 502 on upstream failure, and 422
    (via Pydantic) for empty/over-long text.
    """

    try:
        audio = await service.synthesize(request.text, request.voice_id)
    except TtsNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Text-to-speech is not configured",
        ) from exc
    except TtsUpstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Text-to-speech upstream request failed",
        ) from exc

    return Response(content=audio, media_type="audio/mpeg")
