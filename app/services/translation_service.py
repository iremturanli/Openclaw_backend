"""Live Translation service — OpenAI-backed text translation for travellers.

Translates a traveller's text into a target language so they can communicate
abroad (taxi, hotel, restaurant). When ``source_lang`` is omitted the source
language is auto-detected. For non-Latin target scripts (Chinese, Japanese,
Arabic, Russian, …) a romanized pronunciation hint is included.

The service is *honest* about availability: if no OpenAI key is configured, or
the call/parse fails, it returns a deterministic demo fallback (``is_demo``
true, ``target_text`` echoing the original) rather than raising — so the
endpoint never 500s on a missing key or a flaky upstream.

The OpenAI client setup mirrors :mod:`app.services.agent_service` exactly:
``AsyncOpenAI(api_key=...)`` then ``await client.chat.completions.create(...)``.
"""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings

# A small lookup of human-readable names for the common ISO codes we expect, so
# the fallback path (and any model omissions) can still name a language. The
# model is asked to return names itself; this is only a safety net.
_LANG_NAMES: dict[str, str] = {
    "en": "English",
    "tr": "Turkish",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ar": "Arabic",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "el": "Greek",
    "hi": "Hindi",
    "th": "Thai",
}

# Target scripts that are non-Latin: the model should supply a romanization
# hint. Used only to nudge the prompt; the model decides per response.
_NON_LATIN = {"ar", "ru", "zh", "ja", "ko", "el", "hi", "th"}

_SYSTEM_PROMPT = (
    "You are a precise travel translator. Translate the user's text into the "
    "requested target language. Respond with ONLY a single JSON object, no "
    "markdown, no commentary, with EXACTLY these keys: "
    '"sourceLang" (ISO 639-1 code of the detected source language, lowercase), '
    '"sourceLangName" (English name of that language), '
    '"targetText" (the natural translation in the target language), '
    '"targetLangName" (English name of the target language), '
    '"romanization" (a Latin-script pronunciation hint for targetText when the '
    "target uses a non-Latin script such as Chinese, Japanese, Arabic, Russian, "
    "Korean, Greek, Hindi or Thai; otherwise null). "
    "Translate faithfully and naturally as a traveller would speak. "
    "Output JSON only."
)


def _lang_name(code: str | None) -> str | None:
    """Return a human-readable language name for an ISO code, if known."""

    if not code:
        return None
    return _LANG_NAMES.get(code.lower())


class TranslationService:
    """Translate traveller text between languages via OpenAI.

    Construct with the app :class:`Settings`; call :meth:`translate`. The
    service holds no per-request state and is safe to build per request.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str | None = None,
    ) -> dict[str, Any]:
        """Translate ``text`` into ``target_lang``.

        When ``source_lang`` is ``None`` the source language is auto-detected
        and returned. The result dict matches the API contract (snake_case keys
        here; the Pydantic response model applies camelCase aliases):

        ``source_text``, ``source_lang``, ``source_lang_name``, ``target_text``,
        ``target_lang``, ``target_lang_name``, ``romanization``, ``is_demo`` and
        an optional ``note`` (set only on the unavailable/fallback path).

        Never raises for a missing key or an upstream failure — returns the
        deterministic demo fallback instead.
        """

        target_lang = (target_lang or "").strip().lower()
        source_lang = source_lang.strip().lower() if source_lang else None

        if not self._settings.openai_api_key:
            return self._fallback(
                text,
                target_lang,
                source_lang,
                note="Live translation is unavailable (no OpenAI key configured).",
            )

        try:
            raw = await self._call_openai(text, target_lang, source_lang)
            return self._parse(raw, text, target_lang, source_lang)
        except Exception:  # noqa: BLE001 — any upstream/parse error degrades gracefully
            return self._fallback(
                text,
                target_lang,
                source_lang,
                note="Live translation failed; showing the original text.",
            )

    async def _call_openai(
        self, text: str, target_lang: str, source_lang: str | None,
    ) -> str:
        """Issue a single chat completion and return the raw content string."""

        client = AsyncOpenAI(api_key=self._settings.openai_api_key)

        if source_lang:
            user_instruction = (
                f"Source language is '{source_lang}'. "
                f"Translate into '{target_lang}'."
            )
        else:
            user_instruction = (
                f"Auto-detect the source language. Translate into '{target_lang}'."
            )
        if target_lang in _NON_LATIN:
            user_instruction += " Include a romanization hint for the translation."

        resp = await client.chat.completions.create(
            model=self._settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"{user_instruction}\n\nText: {text}",
                },
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""

    def _parse(
        self,
        raw: str,
        text: str,
        target_lang: str,
        source_lang: str | None,
    ) -> dict[str, Any]:
        """Map a raw LLM JSON string to the contract dict, robustly.

        Tolerates fenced/decorated output by extracting the first ``{...}``
        block. Raises :class:`ValueError` if no usable translation is found, so
        the caller can fall back.
        """

        data = self._extract_json(raw)

        target_text = (data.get("targetText") or "").strip()
        if not target_text:
            raise ValueError("LLM returned no translation")

        detected = source_lang or (data.get("sourceLang") or "").strip().lower() or None
        detected_name = (
            data.get("sourceLangName")
            or _lang_name(detected)
            or "Unknown"
        )
        target_name = (
            data.get("targetLangName")
            or _lang_name(target_lang)
            or target_lang.upper()
        )
        romanization = data.get("romanization")
        if isinstance(romanization, str):
            romanization = romanization.strip() or None
        else:
            romanization = None

        return {
            "source_text": text,
            "source_lang": detected,
            "source_lang_name": detected_name,
            "target_text": target_text,
            "target_lang": target_lang,
            "target_lang_name": target_name,
            "romanization": romanization,
            "is_demo": False,
            "note": None,
        }

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any]:
        """Parse a JSON object from possibly-decorated model output."""

        raw = (raw or "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError("no JSON object in LLM output")
            parsed = json.loads(raw[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("LLM output was not a JSON object")
        return parsed

    @staticmethod
    def _fallback(
        text: str,
        target_lang: str,
        source_lang: str | None,
        *,
        note: str,
    ) -> dict[str, Any]:
        """Deterministic passthrough used when live translation is unavailable.

        Echoes the original text as ``target_text`` and flags ``is_demo`` so the
        client can be honest with the traveller.
        """

        return {
            "source_text": text,
            "source_lang": source_lang,
            "source_lang_name": _lang_name(source_lang) or "Unavailable",
            "target_text": text,
            "target_lang": target_lang,
            "target_lang_name": _lang_name(target_lang) or target_lang.upper(),
            "romanization": None,
            "is_demo": True,
            "note": note,
        }
