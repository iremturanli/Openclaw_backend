"""In-process, per-client rate limiting middleware.

A lightweight first line of defence — no Redis/extra deps — against
brute-forcing auth and running up AI (OpenAI/ElevenLabs) costs. Requests are
counted per ``(client-ip, bucket)`` in a fixed one-minute window; over the limit
returns ``429`` with a ``Retry-After`` header.

Buckets (limits come from :class:`Settings`):

- ``auth``     — paths under ``/auth`` (login/signup/refresh): strict.
- ``ai``       — AI/voice paths (chat, translate, ai-plan, voice/tts): moderate.
- ``default``  — everything else: generous.

Caveats / production path:
- Counters are per worker process; with N workers the effective limit is ~N×.
  For accurate multi-instance limiting, move ``_Counter`` to Redis (INCR+EXPIRE).
- Fixed windows allow a burst across a window boundary; a sliding window or
  token bucket is stricter. This is intentionally simple for a first cut.
- The Stripe webhook and health/docs paths are exempt (Stripe retries on 429;
  probes must never be throttled).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings

# Paths never rate limited (probes, API docs, and Stripe's own webhook).
_EXEMPT_SUFFIXES = ("/health", "/docs", "/redoc", "/openapi.json", "/payments/webhook")

# Substrings that classify a path into the AI/voice bucket (cost-sensitive).
_AI_MARKERS = (
    "/assistant/chat",
    "/assistant/translate",
    "/trips/ai-plan",
    "/voice/",
)


class _Counter:
    """Fixed one-minute window counters keyed by ``(ip, bucket)``.

    Stores ``{(ip, bucket): (window_start_minute, count)}``. Pruned lazily when
    the table grows, so memory stays bounded under churn.
    """

    _PRUNE_AT = 10_000

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], tuple[int, int]] = {}

    def increment(self, ip: str, bucket: str, *, now: float) -> int:
        minute = int(now // 60)
        key = (ip, bucket)
        window, count = self._hits.get(key, (minute, 0))
        if window != minute:
            window, count = minute, 0
        count += 1
        self._hits[key] = (window, count)
        if len(self._hits) > self._PRUNE_AT:
            self._prune(minute)
        return count

    def _prune(self, minute: int) -> None:
        # Drop entries whose window has elapsed (anything not in the live minute).
        self._hits = {
            key: value for key, value in self._hits.items() if value[0] == minute
        }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-client fixed-window rate limiter (see module docstring)."""

    def __init__(self, app: object, settings: Settings) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._settings = settings
        self._counter = _Counter()

    def _client_ip(self, request: Request) -> str:
        if self._settings.rate_limit_trust_forwarded:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                # First hop is the original client.
                return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    @staticmethod
    def _bucket(path: str) -> str:
        if "/auth/" in path or path.endswith("/auth"):
            return "auth"
        if any(marker in path for marker in _AI_MARKERS):
            return "ai"
        return "default"

    def _limit_for(self, bucket: str) -> int:
        if bucket == "auth":
            return self._settings.rate_limit_auth_per_minute
        if bucket == "ai":
            return self._settings.rate_limit_ai_per_minute
        return self._settings.rate_limit_default_per_minute

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if not self._settings.rate_limit_enabled or path.endswith(_EXEMPT_SUFFIXES):
            return await call_next(request)

        bucket = self._bucket(path)
        limit = self._limit_for(bucket)
        count = self._counter.increment(
            self._client_ip(request), bucket, now=time.time()
        )
        if count > limit:
            retry_after = 60 - int(time.time() % 60)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please slow down.",
                    "bucket": bucket,
                    "limit": limit,
                },
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
