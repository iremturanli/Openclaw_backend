"""AI concierge text-to-speech request schema.

The client sends the text to synthesise plus an optional ElevenLabs ``voiceId``.
The backend proxies ElevenLabs server-side and streams back raw MP3 bytes, so the
API key never ships in the mobile app binary.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Upper bound on synthesisable text. Keeps requests cheap and bounds upstream
# latency/cost; the contract specifies 422 for empty or over-long text.
MAX_TTS_TEXT_LENGTH = 500


class TtsRequest(BaseModel):
    """The POST body for the voice TTS proxy endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    text: str = Field(
        ...,
        min_length=1,
        max_length=MAX_TTS_TEXT_LENGTH,
        examples=["Your Wagyu Burger and Coke are on the way."],
    )
    voice_id: str | None = Field(
        default=None,
        alias="voiceId",
        examples=["21m00Tcm4TlvDq8ikWAM"],
    )

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        """Reject whitespace-only text (surfaces as HTTP 422)."""

        stripped = value.strip()
        if not stripped:
            raise ValueError("text must not be empty")
        if len(stripped) > MAX_TTS_TEXT_LENGTH:
            raise ValueError(f"text must be at most {MAX_TTS_TEXT_LENGTH} characters")
        return stripped
