"""Schemas for the AI travel assistant chat endpoint."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """The full conversation so far (client keeps history; server is stateless)."""

    messages: list[ChatMessage] = Field(..., min_length=1)


class ChatResponse(BaseModel):
    reply: str
    # Options surfaced by the agent this turn (for rich cards in the UI).
    flight_options: list[dict[str, Any]] = Field(
        default_factory=list, alias="flightOptions"
    )
    hotel_options: list[dict[str, Any]] = Field(
        default_factory=list, alias="hotelOptions"
    )
    restaurant_options: list[dict[str, Any]] = Field(
        default_factory=list, alias="restaurantOptions"
    )
    # A booking made this turn, if any (triggers the app to refresh lists).
    booked: dict[str, Any] | None = None
    # Live budget after this turn (minor units).
    balance_cents: int | None = Field(default=None, alias="balanceCents")
    currency: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class TranslateRequest(BaseModel):
    """A request to translate ``text`` into ``target_lang``.

    ``source_lang`` is optional: when omitted (``null``) the service
    auto-detects the source language and returns the detected code/name.
    """

    text: str = Field(..., min_length=1)
    target_lang: str = Field(..., alias="targetLang", min_length=2)
    source_lang: str | None = Field(default=None, alias="sourceLang")

    model_config = ConfigDict(populate_by_name=True)


class TranslateResponse(BaseModel):
    """The translation result (Live Translation, vision board #3).

    ``romanization`` is a Latin-script pronunciation hint, present only when the
    target uses a non-Latin script (e.g. zh, ja, ar, ru); otherwise ``null``.
    ``is_demo`` is ``true`` on the honest fallback path (no key / upstream
    failure), where ``target_text`` echoes the original and ``note`` explains.
    """

    source_text: str = Field(..., alias="sourceText")
    source_lang: str | None = Field(default=None, alias="sourceLang")
    source_lang_name: str | None = Field(default=None, alias="sourceLangName")
    target_text: str = Field(..., alias="targetText")
    target_lang: str = Field(..., alias="targetLang")
    target_lang_name: str | None = Field(default=None, alias="targetLangName")
    romanization: str | None = None
    is_demo: bool = Field(default=False, alias="isDemo")
    note: str | None = None

    model_config = ConfigDict(populate_by_name=True)
