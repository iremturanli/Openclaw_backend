"""Application settings loaded via pydantic-settings.

Settings are read from environment variables (optionally a ``.env`` file) and
fall back to sensible demo defaults so the app runs out of the box.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the StayWallet backend."""

    model_config = SettingsConfigDict(
        env_prefix="STAYWALLET_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "StayWallet API"
    api_v1_prefix: str = "/api/v1"

    # PostgreSQL connection URLs. ``database_url`` is the async (asyncpg) URL used
    # by the application at runtime; ``database_url_sync`` is the psycopg2 URL used
    # by Alembic migrations. Both default to the docker-compose ``db`` service
    # (host port 5544) so the app runs against the local dev database out of the
    # box; override via STAYWALLET_DATABASE_URL / STAYWALLET_DATABASE_URL_SYNC to
    # point at managed Postgres.
    database_url: str = (
        "postgresql+asyncpg://staywallet:staywallet@localhost:5544/staywallet"
    )
    database_url_sync: str = (
        "postgresql+psycopg2://staywallet:staywallet@localhost:5544/staywallet"
    )

    # Echo SQL to the logger (debugging only).
    db_echo: bool = False

    # Loyalty earning rule. Guests earn ``loyalty_points_per_dollar`` point per
    # whole dollar of an order/booking total. Travel bookings apply
    # ``loyalty_travel_multiplier`` (3x) to match the "3x points" promo; room
    # service uses a 1x multiplier. Centralised so the rule is consistent and
    # documented (see README "Loyalty earn rule").
    loyalty_points_per_dollar: int = 1
    loyalty_travel_multiplier: int = 3
    loyalty_multiplier_label: str = "3x"
    loyalty_note: str = (
        "Use points to cover up to 50% of your rental car or dining bill."
    )

    # Loyalty Orchestrator presentation metrics. ``trend_pct`` is the headline
    # period-over-period growth shown on the dashboard; ``new_window_days`` is the
    # trailing window over which a newly linked ecosystem counts as "new"
    # (``ecosystemsNew``). Both are deterministic so the summary is reproducible.
    orchestrator_trend_pct: int = 12
    orchestrator_new_window_days: int = 30

    # Guest credited with loyalty points earned by room-service orders in the
    # demo (orders have no guest concept in the contract, so they accrue to the
    # demo member). Override in production once orders carry a real guest id.
    demo_guest_id: str = "guest_demo"

    # Comma-free list of allowed CORS origins. "*" allows any origin (demo only).
    cors_origins: list[str] = ["*"]

    # Secret used to sign opaque digital-key access tokens. In production this
    # MUST be overridden with a real secret (e.g. STAYWALLET_KEY_SIGNING_SECRET).
    key_signing_secret: str = "demo-insecure-signing-secret-change-me"

    # StayWallet member discount applied server-side to room-service orders,
    # as a fraction of the subtotal (0.15 == 15%). Centralised here so pricing
    # is consistent across the service.
    member_discount_rate: float = 0.15

    # ElevenLabs text-to-speech credentials for the AI concierge voice proxy.
    # The API key lives server-side only (never shipped in the mobile app). When
    # unset, the TTS endpoint returns 503 and the app falls back to on-device
    # speech. ``elevenlabs_voice_id`` is the default voice ("Rachel"), overridable
    # per request via the ``voiceId`` field.
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    # SerpApi key powering the live places/hotels directory. Server-side only —
    # the mobile app calls our /places proxy, never SerpApi directly, so the key
    # never ships in the binary. When unset, the proxy returns empty results and
    # the app falls back to its seed/placeholder data.
    serpapi_api_key: str | None = None
    serpapi_base_url: str = "https://serpapi.com/search.json"

    # OpenAI powers the AI travel assistant (function-calling agent). Key lives
    # server-side only. When unset, the assistant endpoint returns 503.
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"

    # Marketplace provider selection. Each vertical reads one switch; "mock"/
    # sandbox providers work with no keys, live values (e.g. "sixt", "uber")
    # require the matching partner credentials and fail with an explanatory
    # error when they are missing. Flights/hotels/restaurants run live through
    # SerpApi whenever ``serpapi_api_key`` is set.
    car_provider: str = "mock"  # mock | booking (Demand API) | sixt
    transfer_provider: str = "mock"  # mock | uber
    sixt_client_id: str | None = None
    sixt_client_secret: str | None = None
    # Uber Guest Trips API (https://developer.uber.com/docs/guest-rides).
    # Auth precedence in TransferService:
    #   1. ``uber_server_token`` — legacy Bearer (Uber no longer issues new
    #      server tokens, kept for existing ones).
    #   2. ``uber_access_token`` — a pre-obtained OAuth bearer pasted in directly
    #      (e.g. from the dashboard's "Generate token" or your own OAuth flow).
    #   3. ``uber_client_id`` + ``uber_client_secret`` — the backend fetches an
    #      app-level token via the OAuth 2.0 client_credentials grant against
    #      ``uber_oauth_token_url`` and caches it until it expires. This covers
    #      app-level Guest Trips endpoints such as trip estimates and trip
    #      creation using the ``guests.trips`` scope.
    uber_client_id: str | None = None
    uber_client_secret: str | None = None
    uber_server_token: str | None = None
    uber_access_token: str | None = None
    uber_oauth_token_url: str = "https://login.uber.com/oauth/v2/token"
    uber_oauth_scopes: str = "guests.trips"
    uber_api_base_url: str = "https://api.uber.com/v1/guests"
    # Booking.com Demand API v3.1 cars (https://developers.booking.com/demand):
    # bearer token + X-Affiliate-Id header. Point the base URL at
    # https://demandapi-sandbox.booking.com/3.1 for the sandbox.
    booking_demand_token: str | None = None
    booking_affiliate_id: str | None = None
    booking_demand_base_url: str = "https://demandapi.booking.com/3.1"
    # Stripe (sandbox/test). Hosted Checkout uses only the secret key server-side;
    # the publishable key is kept for a future in-app PaymentSheet. The webhook
    # secret (``whsec_...``) verifies inbound Stripe webhook signatures — set it
    # to the value Stripe shows when you register the ``/payments/webhook``
    # endpoint; without it the webhook endpoint rejects all events.
    stripe_secret_key: str | None = None
    stripe_publishable_key: str | None = None
    stripe_webhook_secret: str | None = None

    # Demo travel budget granted to a new guest (minor units / cents) + currency.
    # Purchases deduct from this; it is never real money.
    demo_budget_cents: int = 500000  # $5,000.00
    demo_budget_currency: str = "USD"

    # Authentication. ``auth_secret`` signs JWT access/refresh tokens — it MUST be
    # overridden in production (STAYWALLET_AUTH_SECRET). Access tokens are short
    # lived; refresh tokens are long lived so the app can stay signed in.
    auth_secret: str = "demo-insecure-auth-secret-change-me"
    auth_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    # ── Rate limiting (in-process, per-client sliding window) ────────────────
    # A lightweight first line of defence against brute-force and AI-cost abuse.
    # In-process counters are per-worker; for multi-instance production move the
    # store to Redis (see app/core/rate_limit.py). Limits are requests/minute.
    rate_limit_enabled: bool = True
    rate_limit_default_per_minute: int = 120  # everything not matched below
    rate_limit_auth_per_minute: int = 10  # /auth/* (login, signup, refresh)
    rate_limit_ai_per_minute: int = 20  # AI/voice (OpenAI/ElevenLabs cost)
    # Only trust X-Forwarded-For when behind a known proxy/LB; left False the
    # limiter keys on the real peer IP so clients cannot spoof the header.
    rate_limit_trust_forwarded: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""

    return Settings()
