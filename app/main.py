"""StayWallet FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.rate_limit import RateLimitMiddleware


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""

    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Passport-based hotel self check-in backend.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting runs before the routers (outermost-added middleware runs
    # first on the request path). Toggle/tune via STAYWALLET_RATE_LIMIT_* env.
    app.add_middleware(RateLimitMiddleware, settings=settings)

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe."""

        return {"status": "ok"}

    return app


app = create_app()
