"""Shared pytest fixtures.

Tests run against a **real, dedicated Postgres test database** (``staywallet_test``
on the same server as the dev DB). The database is created once per session, its
schema is built from the ORM metadata, and the app's ``get_session`` dependency
is overridden to use a test engine. Each test starts from a clean, freshly
seeded state via TRUNCATE + reseed, giving full isolation without leaking
between tests.

No mocks, no in-memory fakes: every query hits Postgres.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.db.base import Base
import app.db.models  # noqa: F401  (register tables on Base.metadata)
from app.db.session import get_session
from app.db import seed as seed_module
from app.main import app

TEST_DB_NAME = "staywallet_test"


def _swap_db_name(url: str, db_name: str) -> str:
    """Return ``url`` with its database name replaced by ``db_name``."""

    base, _, _old = url.rpartition("/")
    return f"{base}/{db_name}"


@pytest.fixture(scope="session", autouse=True)
def _disable_rate_limit() -> Iterator[None]:
    """Disable the global rate limiter for the suite.

    The middleware keys on client IP; every ASGI test shares one peer, so the
    in-process counters would trip 429s across unrelated tests. The dedicated
    rate-limit test re-enables it locally. We mutate the cached Settings the
    middleware already holds, so the change takes effect without rebuilding app.
    """

    settings = get_settings()
    original = settings.rate_limit_enabled
    settings.rate_limit_enabled = False
    yield
    settings.rate_limit_enabled = original


@pytest.fixture(scope="session")
def test_db_urls() -> dict[str, str]:
    """Async + sync URLs pointing at the dedicated test database."""

    settings = get_settings()
    return {
        "async": _swap_db_name(settings.database_url, TEST_DB_NAME),
        "sync": _swap_db_name(settings.database_url_sync, TEST_DB_NAME),
        "admin_sync": _swap_db_name(settings.database_url_sync, "postgres"),
    }


@pytest.fixture(scope="session", autouse=True)
def _create_test_database(test_db_urls: dict[str, str]) -> Iterator[None]:
    """Create the test database for the session, drop it at the end."""

    admin = create_engine(test_db_urls["admin_sync"], isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": TEST_DB_NAME},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin.dispose()

    # Build the schema from ORM metadata (equivalent to `alembic upgrade head`).
    schema_engine = create_engine(test_db_urls["sync"])
    Base.metadata.create_all(schema_engine)
    schema_engine.dispose()

    yield

    admin = create_engine(test_db_urls["admin_sync"], isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": TEST_DB_NAME},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"'))
    admin.dispose()


@pytest_asyncio.fixture
async def engine(test_db_urls: dict[str, str]):
    """Per-test async engine bound to the test database.

    Function-scoped so the engine lives in the same event loop as the test (and
    its asyncpg connections), avoiding cross-loop reuse errors.
    """

    eng = create_async_engine(test_db_urls["async"], future=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessionmaker_(
    engine,
) -> async_sessionmaker[AsyncSession]:
    """Session factory bound to the per-test engine."""

    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture(autouse=True)
async def _reset_and_seed(sessionmaker_, engine) -> AsyncIterator[None]:
    """Truncate all tables and reseed demo data before each test."""

    table_names = ", ".join(
        f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables)
    )
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE")
        )

    # Reuse the production seed against the test session factory.
    factory = sessionmaker_
    async with factory() as session:
        async with session.begin():
            await seed_module._seed_guest(session)
            await seed_module._seed_demo_user(session)
            await seed_module._seed_stays(session)
            await seed_module._seed_menu(session)
            await seed_module._seed_travel(session)
            await seed_module._seed_providers(session)
            await seed_module._seed_loyalty_accounts(session)
            await seed_module._seed_loyalty_ledger(session)

    yield


@pytest_asyncio.fixture
async def client(sessionmaker_) -> AsyncIterator[AsyncClient]:
    """Async HTTP client driving the ASGI app against the test database."""

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker_() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_session, None)
