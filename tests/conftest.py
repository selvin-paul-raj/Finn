"""Shared fixtures for tests that touch a real Postgres database.

Requires TEST_DATABASE_URL (a disposable/scratch Postgres branch) in the
environment -- see DECISIONS.md for why this isn't persisted in .env.
"""

import os
import subprocess
import sys

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import create_app_async_engine

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
_REPO_ROOT = os.path.dirname(os.path.dirname(__file__))

requires_test_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set -- needs a scratch Postgres branch",
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
def migrated_schema():
    """Apply the Alembic migration once for the whole test session (against
    TEST_DATABASE_URL only), downgrade at the very end. Centralized here so
    every DB-touching test file shares one migrated schema instead of each
    file migrating/dropping independently and stepping on the others."""
    if not TEST_DATABASE_URL:
        yield
        return
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True, cwd=_REPO_ROOT, env=env,
    )
    yield
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        check=True, cwd=_REPO_ROOT, env=env,
    )


@pytest.fixture
async def test_engine():
    # Function-scoped, not session-scoped: asyncpg connections are bound to
    # the event loop they were created on, and pytest-anyio gives each async
    # test its own loop -- a shared engine across tests causes "another
    # operation is in progress" errors from a previous loop's connection.
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    engine = create_app_async_engine(TEST_DATABASE_URL)
    yield engine
    await engine.dispose()


@pytest.fixture
async def test_session_factory(test_engine):
    """A clean-slate session factory bound to test_engine (tables truncated
    first) -- for tests where the code under test opens its own sessions
    (e.g. MCP tools), rather than being handed one directly."""
    async with test_engine.begin() as conn:
        await conn.execute(sa.text(
            "TRUNCATE TABLE event_history, events, recurring_rules, "
            "categories, accounts, users RESTART IDENTITY CASCADE"
        ))
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture
async def db_session(test_session_factory):
    """A single clean-slate AsyncSession, for tests that just need to
    read/write directly."""
    async with test_session_factory() as session:
        yield session
