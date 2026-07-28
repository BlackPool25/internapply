"""Tests for database initialisation, schema versioning, and migration idempotency.

Uses temporary SQLite files so no real database is touched.
Module globals (``_engine``, ``_async_session_maker``) are reset before
each test to guarantee isolation.
"""

from __future__ import annotations

import pytest

from internapply import database


# ---------------------------------------------------------------------------
# Helpers — reset the database module globals
# ---------------------------------------------------------------------------

def _reset_db_globals() -> None:
    """Reset the module-level engine and session-maker so each test starts clean."""
    database._engine = None
    database._async_session_maker = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDatabaseInit:
    """Database initialisation and schema versioning."""

    @pytest.mark.asyncio
    async def test_init_db(self, tmp_path):
        """Database initialises with correct schema version (V2)."""
        _reset_db_globals()
        db_path = str(tmp_path / "test_init.db")

        await database.init_db(db_path)

        version = await database.get_schema_version()
        assert version == 2, f"Expected schema version 2 after init, got {version}"

    @pytest.mark.asyncio
    async def test_schema_version(self, tmp_path):
        """Schema version starts at 2 after initialisation."""
        _reset_db_globals()
        db_path = str(tmp_path / "test_version.db")

        # Before init, version should be 0 (no engine)
        pre_version = await database.get_schema_version()
        assert pre_version == 0, f"Expected version 0 before init, got {pre_version}"

        await database.init_db(db_path)

        version = await database.get_schema_version()
        assert version == 2, f"Expected version 2 after init, got {version}"

    @pytest.mark.asyncio
    async def test_migration_idempotent(self, tmp_path):
        """Running init_db twice on the same database is safe (no double-migration)."""
        _reset_db_globals()
        db_path = str(tmp_path / "test_idempotent.db")

        # First call
        await database.init_db(db_path)
        version1 = await database.get_schema_version()

        # Second call — should not re-apply migrations
        await database.init_db(db_path)
        version2 = await database.get_schema_version()

        assert version1 == 2
        assert version2 == 2
        assert version1 == version2, "Schema version must not change across idempotent init"

    @pytest.mark.asyncio
    async def test_init_db_with_default_path(self, tmp_path, monkeypatch):
        """init_db() without a path uses the default path."""
        _reset_db_globals()
        # Point DEFAULT_DB_PATH into our temp dir
        default = str(tmp_path / "default.db")
        monkeypatch.setattr(database, "DEFAULT_DB_PATH", default)

        await database.init_db()  # no path → uses DEFAULT_DB_PATH

        version = await database.get_schema_version()
        assert version == 2
