"""Async SQLAlchemy engine, session factory, and migration system for InternApply.

Uses SQLAlchemy 2.0 async with aiosqlite. Migration system uses a schema_version
table to track applied versions — migrations are Python functions run sequentially.
"""

import json
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    insert as sa_insert,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = "data/internapply.db"

# ---------------------------------------------------------------------------
# Globals — engine and session-maker are created lazily by init_db()
# ---------------------------------------------------------------------------

_engine: Any = None
_async_session_maker: async_sessionmaker[AsyncSession] | None = None

# ---------------------------------------------------------------------------
# schema_version table — tracked separately so it can be created before any
# migration (it lives on its own MetaData object).
# ---------------------------------------------------------------------------

_schema_metadata = MetaData()

schema_version_table = Table(
    "schema_version",
    _schema_metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", DateTime),
)


# ---------------------------------------------------------------------------
# ORM Base and models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    """Timezone-naive UTC now (SQLite compatible)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ORMJobListing(Base):
    __tablename__ = "job_listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    company: Mapped[str]
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    stipend_min: Mapped[int | None] = mapped_column(nullable=True)
    stipend_max: Mapped[int | None] = mapped_column(nullable=True)
    stipend_raw: Mapped[str | None] = mapped_column(nullable=True)
    skills_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str]
    url: Mapped[str]
    posted_at: Mapped[str | None] = mapped_column(nullable=True)
    posted_at_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ORMApplication(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_listings.id"))
    status: Mapped[str] = mapped_column(String, default="discovered")
    tailored_resume_path: Mapped[str | None] = mapped_column(nullable=True)
    cover_letter_path: Mapped[str | None] = mapped_column(nullable=True)
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_contacts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_draft_path: Mapped[str | None] = mapped_column(nullable=True)
    portal_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    portal_submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verifier_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    humanization_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ORMResume(Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str]
    phone: Mapped[str | None] = mapped_column(nullable=True)
    location: Mapped[str | None] = mapped_column(nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    education_json: Mapped[str] = mapped_column(Text)
    skills_json: Mapped[str] = mapped_column(Text)
    projects_json: Mapped[str] = mapped_column(Text)
    additional_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ORMEmailLookup(Base):
    __tablename__ = "email_lookups"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String, unique=True)
    emails_json: Mapped[str] = mapped_column(Text)
    cached_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ---------------------------------------------------------------------------
# Migration definitions
# ---------------------------------------------------------------------------

async def _migrate_v1() -> None:
    """V1: Create all initial tables (job_listings, applications, resumes, email_lookups)."""
    tables = [
        ORMJobListing.__table__,
        ORMApplication.__table__,
        ORMResume.__table__,
        ORMEmailLookup.__table__,
    ]
    async with _engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables, checkfirst=True)
        )
    logger.info("Migration V1 complete — tables: job_listings, applications, resumes, email_lookups")


async def _migrate_v2() -> None:
    """V2: Add posted_at_date DATE column to job_listings (idempotent).

    Checks for column existence via ``PRAGMA table_info`` before running
    the ``ALTER TABLE`` so the migration is safe even when the ORM model
    already includes the column (V1's ``create_all`` may have created it).
    """
    async with _engine.begin() as conn:
        exists = await conn.run_sync(
            _migrate_v2_column_exists
        )
        if not exists:
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    text("ALTER TABLE job_listings ADD COLUMN posted_at_date DATE")
                )
            )
    logger.info("Migration V2 complete — added posted_at_date column to job_listings")


def _migrate_v2_column_exists(sync_conn: Any) -> bool:
    """Return ``True`` if ``posted_at_date`` already exists in ``job_listings``."""
    rows = sync_conn.execute(
        text("PRAGMA table_info(job_listings)")
    ).fetchall()
    return any(row[1] == "posted_at_date" for row in rows)


MIGRATIONS: list[tuple[int, str, Any]] = [
    (1, "Create initial tables (job_listings, applications, resumes, email_lookups)", _migrate_v1),
    (2, "Add posted_at_date column to job_listings", _migrate_v2),
]


# ---------------------------------------------------------------------------
# Engine & session helpers
# ---------------------------------------------------------------------------

async def _ensure_engine(db_path: str | None = None) -> str:
    """Lazily create the engine and session-maker if not already set.

    Returns the resolved (absolute) database path.
    """
    global _engine, _async_session_maker

    if _engine is not None:
        # Determine the existing db path from the engine URL
        return str(_engine.url.database)

    resolved = _resolve_db_path(db_path)

    # Ensure the parent directory exists
    db_dir = os.path.dirname(resolved)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
        logger.debug(f"Ensured database directory: {db_dir}")

    db_url = f"sqlite+aiosqlite:///{resolved}"
    _engine = create_async_engine(db_url, echo=False)
    _async_session_maker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    logger.debug(f"Database engine created for: {resolved}")
    return resolved


def _resolve_db_path(db_path: str | None = None) -> str:
    """Resolve a relative or absolute database path to an absolute path."""
    path = db_path or DEFAULT_DB_PATH
    return os.path.abspath(path)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager that yields an async database session.

    The session is committed on normal exit and rolled back on exception.
    """
    if _async_session_maker is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")

    async with _async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------

async def _run_migrations() -> None:
    """Run pending migrations that have not yet been recorded in schema_version."""
    # 1. Ensure the schema_version table itself exists
    async with _engine.begin() as conn:
        await conn.run_sync(_schema_metadata.create_all)

    # 2. Read current version
    async with _async_session_maker() as session:
        result = await session.execute(
            select(func.max(schema_version_table.c.version))
        )
        current_version: int = result.scalar() or 0

    logger.info(f"Current schema version: {current_version}")

    # 3. Apply newer migrations sequentially
    for version, description, migration_fn in sorted(MIGRATIONS, key=lambda x: x[0]):
        if version > current_version:
            logger.info(f"Applying migration V{version}: {description}")
            await migration_fn()
            async with _async_session_maker() as session:
                await session.execute(
                    sa_insert(schema_version_table).values(
                        version=version, applied_at=_utcnow()
                    )
                )
                await session.commit()
            logger.info(f"Migration V{version} applied successfully")
            current_version = version


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def init_db(db_path: str | None = None) -> None:
    """Initialise the database and run any pending migrations.

    Creates the database directory if it does not exist, creates the SQLAlchemy
    engine, the schema_version table, and applies all unapplied migrations.

    Args:
        db_path: Path to the SQLite database file.  If ``None`` the default
            ``data/internapply.db`` (relative to CWD) is used.
    """
    resolved = await _ensure_engine(db_path)
    await _run_migrations()
    logger.info(f"Database initialised at {resolved}")


async def get_schema_version() -> int:
    """Return the current schema version from the database.

    Returns 0 if the database has not been initialised yet, or if no
    migrations have been applied.
    """
    if _async_session_maker is None:
        return 0

    try:
        async with _async_session_maker() as session:
            result = await session.execute(
                select(func.max(schema_version_table.c.version))
            )
            return result.scalar() or 0
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# DB helpers — queries & upserts
# ---------------------------------------------------------------------------


async def get_job_by_url(session: AsyncSession, url: str) -> ORMJobListing | None:
    """Return the job listing with the given URL, or ``None``.

    Args:
        session: An active async database session.
        url: The job listing URL to look up.

    Returns:
        The matching :class:`ORMJobListing` row, or ``None``.
    """
    result = await session.execute(
        select(ORMJobListing).where(ORMJobListing.url == url)
    )
    return result.scalar_one_or_none()


async def get_job_applied_urls(
    session: AsyncSession,
    statuses: list[str] | None = None,
) -> set[str]:
    """Return the set of job URLs that already have applications.

    Args:
        session: An active async database session.
        statuses: Application statuses to consider.  Defaults to
            ``["discovered", "applied", "submitted"]``.

    Returns:
        A set of job listing URLs (strings).
    """
    if statuses is None:
        statuses = ["discovered", "applied", "submitted"]

    result = await session.execute(
        select(ORMJobListing.url)
        .join(ORMApplication, ORMApplication.job_id == ORMJobListing.id)
        .where(ORMApplication.status.in_(statuses))
    )
    return {row[0] for row in result.fetchall() if row[0]}


async def upsert_job_listing(
    session: AsyncSession,
    job: dict[str, Any],
    posted_at_date_value: date | None = None,
) -> ORMJobListing:
    """Insert or update a job listing keyed on URL uniqueness.

    If a row with the same ``url`` already exists its fields are updated
    in-place; otherwise a new row is inserted.

    Args:
        session: An active async database session.
        job: A dict of job fields (must include ``url``).
        posted_at_date_value: Parsed posting date, or ``None``.

    Returns:
        The created or updated :class:`ORMJobListing` instance.
    """
    existing = await get_job_by_url(session, job.get("url", ""))
    if existing is not None:
        existing.title = job.get("title", existing.title)
        existing.company = job.get("company", existing.company)
        existing.location = job.get("location")
        existing.stipend_min = job.get("stipend_min")
        existing.stipend_max = job.get("stipend_max")
        existing.stipend_raw = job.get("stipend_raw")
        existing.skills_json = json.dumps(job.get("skills", []))
        existing.analysis_json = (
            json.dumps(job["analysis"]) if job.get("analysis") else existing.analysis_json
        )
        existing.description = job.get("description")
        existing.source = job.get("source", existing.source)
        existing.posted_at = job.get("posted_at")
        existing.posted_at_date = posted_at_date_value
        existing.is_paid = job.get("is_paid", False)
        existing.is_remote = job.get("is_remote", False)
        return existing

    listing = ORMJobListing(
        title=job.get("title", ""),
        company=job.get("company", ""),
        location=job.get("location"),
        stipend_min=job.get("stipend_min"),
        stipend_max=job.get("stipend_max"),
        stipend_raw=job.get("stipend_raw"),
        skills_json=json.dumps(job.get("skills", [])),
        analysis_json=json.dumps(job["analysis"]) if job.get("analysis") else None,
        description=job.get("description"),
        source=job.get("source", ""),
        url=job.get("url", ""),
        posted_at=job.get("posted_at"),
        posted_at_date=posted_at_date_value,
        is_paid=job.get("is_paid", False),
        is_remote=job.get("is_remote", False),
    )
    session.add(listing)
    return listing
