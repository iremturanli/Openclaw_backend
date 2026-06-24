"""Rate-limit middleware: the auth bucket trips 429 past its per-minute limit.

The global limiter is disabled for the suite (see conftest ``_disable_rate_limit``);
this test re-enables it with a tiny auth limit and restores afterwards.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings


@pytest.mark.asyncio
async def test_auth_bucket_returns_429_over_limit(client) -> None:
    settings = get_settings()
    settings.rate_limit_enabled = True
    settings.rate_limit_auth_per_minute = 3
    try:
        statuses = []
        for _ in range(5):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "wrong"},
            )
            statuses.append(resp.status_code)
        # First 3 pass the limiter (and fail auth with 4xx); the rest are 429.
        assert 429 in statuses
        assert statuses.count(429) == 2
        assert statuses[-1] == 429
        # The 429 carries a Retry-After hint.
        last = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "wrong"},
        )
        assert last.status_code == 429
        assert "retry-after" in {k.lower() for k in last.headers}
    finally:
        settings.rate_limit_enabled = False
