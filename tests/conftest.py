"""Test configuration and shared fixtures for InternApply.

Provides:
- Project root path setup for imports
- Environment isolation (prevents ``.env`` file from overriding test defaults)
- Pytest markers: ``sqlite`` (old CLI), ``postgres`` (new backend)
- Reusable fixtures for PostgreSQL model tests (backed by in-memory SQLite)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# ═══════════════════════════════════════════════════════════════════════════
# sys.path — ensure the project root is importable
# ═══════════════════════════════════════════════════════════════════════════

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# ═══════════════════════════════════════════════════════════════════════════
# Environment isolation — prevent .env from leaking into test assertions
# ═══════════════════════════════════════════════════════════════════════════
#
# The old CLI's Config (pydantic-settings BaseSettings) reads from the
# project .env file at construction time — both via its own
# ``_ensure_env_loaded()`` helper and via pydantic-settings' built-in
# ``DotenvSettingsSource``.  Tests in ``test_config.py`` verify default
# fallback values and expect a clean environment.  We disable both
# mechanisms at conftest load time so that *all* tests see a consistent,
# .env-free environment.
#
# 1. Flag ``_ensure_env_loaded()`` as already done (prevents load_dotenv)
# 2. Clear the ``env_file`` key on Config's model_config (disables
#    pydantic-settings' own DotenvSettingsSource)

import internapply.config

internapply.config._dotenv_loaded = True

from internapply.config import Config

if "env_file" in Config.model_config:
    Config.model_config["env_file"] = None  # type: ignore[typeddict-item]


# ═══════════════════════════════════════════════════════════════════════════
# Pytest markers
# ═══════════════════════════════════════════════════════════════════════════


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers for the test suite."""
    config.addinivalue_line(
        "markers",
        "sqlite: tests that exercise the old SQLite-based CLI database",
    )
    config.addinivalue_line(
        "markers",
        "postgres: tests that exercise the new PostgreSQL backend models",
    )


# ═══════════════════════════════════════════════════════════════════════════
# Auto-use fixtures — applied to every test
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_db_globals() -> None:
    """Reset the old CLI's database module globals before each test.

    The ``internapply.database`` module holds module-level ``_engine`` and
    ``_async_session_maker`` singletons.  ``test_database.py`` already does
    this manually per test via ``_reset_db_globals()`` — this fixture
    provides a safety net for any test that may indirectly touch the old
    database module, ensuring isolation without requiring every test author
    to remember the reset.
    """
    import internapply.database

    internapply.database._engine = None
    internapply.database._async_session_maker = None


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures — PostgreSQL backend (in-memory SQLite stand-in)
# ═══════════════════════════════════════════════════════════════════════════
#
# These fixtures create an in-memory SQLite database that mirrors the
# PostgreSQL schema.  SQLAlchemy's core SQL compilation is almost
# identical for both dialects at the DDL + CRUD level, so model-creation,
# field-typing, and relationship tests work transparently.
#
# PostgreSQL-specific types (JSONB) are mapped to SQLite's JSON type
# via ``@compiles`` so the schema can be created without a real PG server.
#
# Tests that need PostgreSQL-specific *operators* (e.g. JSONB ``@>``,
# full-text search) should run against the live ``docker compose``
# environment instead.
# ---------------------------------------------------------------------------

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element: Any, compiler: Any, **kw: Any) -> str:
    return compiler.visit_JSON(SQLiteJSON(), **kw)


@pytest.fixture
def pg_base() -> type:
    """Return the SQLAlchemy declarative base for the PostgreSQL models."""
    from backend.app.database import Base

    return Base


@pytest.fixture
async def pg_engine() -> Any:
    """Create an in-memory SQLite engine with the full PostgreSQL schema.

    Creates all tables defined in ``backend.app.models``.  Yields the
    engine and disposes it after the test so no state leaks between tests.

    Usage::

        async def test_model_creation(pg_engine):
            async with pg_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            # ... test model operations ...
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from backend.app import models  # noqa: F401
    from backend.app.database import Base

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def pg_session(pg_engine: Any) -> Any:
    """Provide an async database session backed by in-memory SQLite.

    The session is rolled back after each test so no persistent state
    leaks between tests.  Commit explicitly within the test if needed.

    Usage::

        async def test_insert_job(pg_session):
            job = JobListing(title="...", ...)
            pg_session.add(job)
            await pg_session.commit()
            # ... query and assert ...
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    maker = async_sessionmaker(
        pg_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with maker() as session:
        yield session
        await session.rollback()


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures — SQLite CLI database (old CLI)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def sqlite_db_path(tmp_path: Path) -> str:
    """Return an absolute path to a temporary SQLite database file.

    Each test gets its own isolated database file inside ``tmp_path``.
    The file does not need to exist yet — ``internapply.database.init_db()``
    will create it.

    Usage::

        def test_something(sqlite_db_path):
            await database.init_db(sqlite_db_path)
            # ... test against an isolated SQLite database ...
    """
    return str(tmp_path / "test.db")
