"""arq worker with hourly discovery cron."""

import asyncio
import logging
import os

from arq import cron
from arq.connections import RedisSettings

logger = logging.getLogger(__name__)


async def discover_all(ctx: dict) -> None:
    """Hourly job: discover and persist new job listings."""
    logger.info("discover_all: starting hourly discovery")
    try:
        # Lazy import to avoid circular deps at worker startup
        from backend.app.database import init_db, close_db

        db_url = os.getenv("DATABASE_URL", "")
        if db_url:
            await init_db(db_url)

        # Try to import discovery; fall back to no-op if unavailable
        try:
            from internapply.discovery.internshala import discover_job_board  # type: ignore

            jobs = await discover_job_board()  # type: ignore
            logger.info("discover_all: found %d jobs", len(jobs) if jobs else 0)
        except ImportError:
            logger.info("discover_all: discover_job_board not available, skipping")
        except Exception as e:
            logger.warning("discover_all: discovery failed: %s", e)

        if db_url:
            await close_db()
    except Exception as e:
        logger.exception("discover_all failed: %s", e)


class WorkerSettings:
    functions = [discover_all]
    cron_jobs = [
        cron(
            discover_all,
            hour={*range(24)},
            minute=0,
            run_at_startup=False,
            unique=True,
            timeout=600,
            keep_result=0,
        )
    ]
    redis_settings = RedisSettings.from_dsn(
        os.getenv("REDIS_URL", "redis://redis:6379/0")
    )


async def main() -> None:
    """Allow `python -m backend.app.worker` entrypoint for arq."""
    from arq import run_worker

    await run_worker(WorkerSettings)


if __name__ == "__main__":
    asyncio.run(main())
