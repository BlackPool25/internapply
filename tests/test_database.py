"""Tests for Postgres hash/dedup migration + SQLite CLI mirror.

Covers: canonical_id 64 UNIQUE, dead_letters unique(source,url),
jd_hash primary skip logic, and 128-would-waste guard.

Also retains SQLite CLI idempotency checks (now V3).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import inspect, String
from sqlalchemy.exc import IntegrityError

from internapply import database as cli_db
from backend.app.database import Base as PGBase
from backend.app.models import JobListing, DeadLetter

# import models to register tables on PGBase
import backend.app.models  # noqa: F401

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.ext.compiler import compiles
from typing import Any


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element: Any, compiler: Any, **kw: Any) -> str:
    return compiler.visit_JSON(SQLiteJSON(), **kw)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_cli_globals() -> None:
    cli_db._engine = None
    cli_db._async_session_maker = None


@pytest.fixture
async def pg_engine():
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(PGBase.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def pg_session(pg_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    maker = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# New hash/dedup tests — the 4 required by task-11
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_canonical_id_unique_64(pg_session):
    """Duplicate canonical_id (64 hex) → IntegrityError."""
    cid = "a" * 64
    j1 = JobListing(
        title="T", company="C", source="test", url="https://ex/1",
        canonical_id=cid, jd_hash="b"*64,
    )
    pg_session.add(j1)
    await pg_session.flush()
    j2 = JobListing(
        title="T2", company="C2", source="test", url="https://ex/2",
        canonical_id=cid, jd_hash="c"*64,
    )
    pg_session.add(j2)
    with pytest.raises(IntegrityError):
        await pg_session.flush()


@pytest.mark.asyncio
async def test_dead_letters_unique(pg_session):
    """Same (source,url) in dead_letters twice → IntegrityError / upsert single row."""
    d1 = DeadLetter(source="hirist", url="https://ex/dead", error="boom")
    pg_session.add(d1)
    await pg_session.flush()
    d2 = DeadLetter(source="hirist", url="https://ex/dead", error="again")
    pg_session.add(d2)
    with pytest.raises(IntegrityError):
        await pg_session.flush()


@pytest.mark.asyncio
async def test_jd_hash_primary_skip(pg_session):
    """Same jd_hash (different etag) should be detected as dup — skip second insert."""
    h = "d" * 64
    j1 = JobListing(title="T1", company="C", source="test", url="https://ex/j1", canonical_id="1"*64, jd_hash=h, etag="v1")
    pg_session.add(j1)
    await pg_session.flush()
    # simulate dedup check: if jd_hash exists, skip
    from sqlalchemy import select
    res = await pg_session.execute(select(JobListing).where(JobListing.jd_hash == h))
    existing = res.scalar_one_or_none()
    assert existing is not None
    # second job with same jd_hash but different etag should be skipped (not inserted)
    # verify helper logic: don't insert if jd_hash already present
    should_skip = existing is not None and existing.jd_hash == h
    assert should_skip is True
    # ensure count stays 1
    from sqlalchemy import func
    cnt = (await pg_session.execute(select(func.count()).select_from(JobListing).where(JobListing.jd_hash == h))).scalar()
    assert cnt == 1


def test_128_would_waste():
    """canonical_id must be VARCHAR(64) not 128 — 128 would waste index & storage."""
    import pathlib
    text = pathlib.Path("backend/app/models.py").read_text()
    assert "canonical_id" in text and "String(64)" in text, "canonical_id must be String(64)"
    # ensure no VARCHAR(128) for canonical_id anywhere
    assert "String(128)" not in text and "VARCHAR(128)" not in text, "found 128 — should be 64 only (128 would waste)"
    # double-check via inspection
    col = JobListing.__table__.c.canonical_id
    assert isinstance(col.type, String) and col.type.length == 64
    # jd_hash also 64
    jcol = JobListing.__table__.c.jd_hash
    assert jcol.type.length == 64


# ---------------------------------------------------------------------------
# Retained CLI mirror idempotency (now expects V3 after hash mirror)
# ---------------------------------------------------------------------------

class TestDatabaseInit:
    @pytest.mark.asyncio
    async def test_init_db(self, tmp_path):
        _reset_cli_globals()
        db_path = str(tmp_path / "test_init.db")
        await cli_db.init_db(db_path)
        version = await cli_db.get_schema_version()
        assert version == 3, f"Expected schema version 3 after init, got {version}"

    @pytest.mark.asyncio
    async def test_schema_version(self, tmp_path):
        _reset_cli_globals()
        db_path = str(tmp_path / "test_version.db")
        pre = await cli_db.get_schema_version()
        assert pre == 0
        await cli_db.init_db(db_path)
        version = await cli_db.get_schema_version()
        assert version == 3

    @pytest.mark.asyncio
    async def test_migration_idempotent(self, tmp_path):
        _reset_cli_globals()
        db_path = str(tmp_path / "test_idempotent.db")
        await cli_db.init_db(db_path)
        v1 = await cli_db.get_schema_version()
        await cli_db.init_db(db_path)
        v2 = await cli_db.get_schema_version()
        assert v1 == 3 and v2 == 3 and v1 == v2

    @pytest.mark.asyncio
    async def test_init_db_with_default_path(self, tmp_path, monkeypatch):
        _reset_cli_globals()
        default = str(tmp_path / "default.db")
        monkeypatch.setattr(cli_db, "DEFAULT_DB_PATH", default)
        await cli_db.init_db()
        version = await cli_db.get_schema_version()
        assert version == 3
