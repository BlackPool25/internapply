"""Async SQLAlchemy engine, session factory, and Base for PostgreSQL (asyncpg)."""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import AsyncAdaptedQueuePool

# ---------------------------------------------------------------------------
# Globals — configured lazily via init_db()
# ---------------------------------------------------------------------------

engine: Any = None
async_session_maker: async_sessionmaker[AsyncSession] | None = None


# ---------------------------------------------------------------------------
# ORM Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def init_db(database_url: str) -> None:
    """Initialise the async engine and session factory."""
    global engine, async_session_maker

    if "@postgres:" in database_url:
        import socket
        try:
            socket.gethostbyname("postgres")
        except socket.gaierror:
            database_url = database_url.replace("@postgres:", "@127.0.0.1:")

    # (10 + 10) * 2 = 40 < 100 (postgres max_connections)
    assert (10 + 10) * 2 < 100

    engine = create_async_engine(
        database_url,
        echo=False,
        pool_size=10,
        max_overflow=10,
        pool_timeout=30,
        pool_pre_ping=True,
        pool_recycle=1800,
        poolclass=AsyncAdaptedQueuePool,
    )
    async_session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    import backend.app.models  # noqa: F401
    from backend.app.models import JobListing, Application
    from sqlalchemy import select

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Sync missing Application records so every job listing starts with 'discovered' status
    async with async_session_maker() as session:
        try:
            subquery = select(Application.job_listing_id).where(Application.job_listing_id.is_not(None))
            missing_stmt = select(JobListing.id).where(~JobListing.id.in_(subquery))
            res = await session.execute(missing_stmt)
            missing_ids = res.scalars().all()
            if missing_ids:
                for jid in missing_ids:
                    session.add(Application(job_listing_id=jid, status="discovered"))
                await session.commit()
        except Exception:
            await session.rollback()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session, committing on success or rolling back on error."""
    if async_session_maker is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")

    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db() -> None:
    """Dispose of the engine and release all connections."""
    global engine, async_session_maker

    if engine is not None:
        await engine.dispose()
    engine = None
    async_session_maker = None
