"""Async SQLAlchemy engine, session factory and FastAPI dependency.

The engine and sessionmaker are created lazily and cached so the application
shares a single connection pool. ``get_session`` is the FastAPI dependency that
yields an :class:`AsyncSession`; it commits on success and rolls back on error,
giving routers/services a transactional unit of work per request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide async engine (one connection pool)."""

    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the cached async session factory bound to the engine."""

    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional :class:`AsyncSession`.

    Commits when the request handler returns successfully; rolls back if it
    raises. The session is always closed.
    """

    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
