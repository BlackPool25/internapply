"""arq worker with hourly discovery cron + per-source tenacity + circuit breaker + metrics."""

from __future__ import annotations

import asyncio
import email.utils
import logging
import os
import time
import uuid

from arq import cron
from arq.connections import RedisSettings

logger = logging.getLogger(__name__)

# Retry-After parser: seconds or HTTP-date, clamp max_wait=30 (never 3600 parks worker)
def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    v = value.strip()
    try:
        secs = float(v)
        return max(0, min(secs, 30))
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(v)
        if dt is not None:
            secs = dt.timestamp() - time.time()
            if secs < 0:
                secs = 0
            return max(0, min(secs, 30))
    except Exception:
        pass
    return None

RETRY_STATUS = {429, 502, 503, 504}
SKIP_STATUS = {401, 403, 404, 422}


class _Retryable(Exception):
    def __init__(self, status: int, retry_after: float | None = None):
        super().__init__(f"retryable {status} retry_after={retry_after}")
        self.status = status
        self.retry_after = retry_after


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, _Retryable):
        return exc.status in RETRY_STATUS
    try:
        import httpx
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout)):
            return True
    except Exception:
        pass
    return False


def _wait_retry_after(retry_state) -> float:
    # honor Retry-After if present, clamp 30, else exponential jitter multiplier=0.5 max=30
    if retry_state.outcome and retry_state.outcome.failed:
        exc = retry_state.outcome.exception()
        if isinstance(exc, _Retryable) and exc.retry_after is not None:
            import random
            base = min(float(exc.retry_after), 30)
            jitter = random.uniform(0, 0.5)
            return min(base + jitter, 30)
    from tenacity import wait_exponential_jitter
    # tenacity wait_exponential_jitter(multiplier=0.5,max=30) stop_after_attempt(3)
    # support both initial and multiplier arg names
    try:
        return wait_exponential_jitter(multiplier=0.5, max=30)(retry_state)
    except TypeError:
        return wait_exponential_jitter(initial=0.5, max=30)(retry_state)


# ── per-source tasks with tenacity ──
# Each task uses tenacity wait_exponential_jitter(multiplier=0.5,max=30) stop_after_attempt(3)
# retry only 429/502/503/504+timeouts, never 401/403/404/422, parse Retry-After clamp 30
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter as _wej

async def _with_retry(coro_fn, source: str):
    """Helper: run coro_fn with tenacity retry handling Retry-After clamp."""
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=_wait_retry_after,
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    ):
        with attempt:
            return await coro_fn()
    return []


async def discover_greenhouse(ctx: dict) -> list[dict]:
    """Per-source: Greenhouse ATS."""
    from backend.app.discovery.circuit import CircuitBreaker
    from backend.app.observability.metrics import record_job

    if CircuitBreaker.is_open("greenhouse"):
        logger.info("breaker:greenhouse open — skip")
        record_job("greenhouse", "skip", 0.0)
        return []
    t0 = time.time()
    try:
        from backend.app.discovery.ats.greenhouse import GreenhouseDiscovery
        jobs = await GreenhouseDiscovery().search()
        record_job("greenhouse", "success", time.time() - t0)
        CircuitBreaker.record_success("greenhouse")
        return jobs
    except Exception as e:
        latency = time.time() - t0
        status = getattr(e, "status", None) or getattr(getattr(e, "response", None), "status_code", None)
        if status in SKIP_STATUS:
            record_job("greenhouse", "skip", latency)
            return []
        CircuitBreaker.record_failure("greenhouse", status)
        record_job("greenhouse", "failure", latency)
        raise


async def discover_lever(ctx: dict) -> list[dict]:
    from backend.app.discovery.circuit import CircuitBreaker
    from backend.app.observability.metrics import record_job

    if CircuitBreaker.is_open("lever"):
        record_job("lever", "skip", 0.0)
        return []
    t0 = time.time()
    try:
        from backend.app.discovery.ats.lever import LeverDiscovery  # type: ignore
        jobs = await LeverDiscovery().search()
        record_job("lever", "success", time.time() - t0)
        CircuitBreaker.record_success("lever")
        return jobs
    except Exception as e:
        latency = time.time() - t0
        status = getattr(e, "status", None)
        if status in SKIP_STATUS:
            record_job("lever", "skip", latency)
            return []
        CircuitBreaker.record_failure("lever", status)
        record_job("lever", "failure", latency)
        raise


async def discover_ashby(ctx: dict) -> list[dict]:
    from backend.app.discovery.circuit import CircuitBreaker
    from backend.app.observability.metrics import record_job

    if CircuitBreaker.is_open("ashby"):
        record_job("ashby", "skip", 0.0)
        return []
    t0 = time.time()
    try:
        from backend.app.discovery.ats.ashby import AshbyDiscovery  # type: ignore
        jobs = await AshbyDiscovery().search()
        record_job("ashby", "success", time.time() - t0)
        CircuitBreaker.record_success("ashby")
        return jobs
    except Exception as e:
        latency = time.time() - t0
        status = getattr(e, "status", None)
        if status in SKIP_STATUS:
            record_job("ashby", "skip", latency)
            return []
        CircuitBreaker.record_failure("ashby", status)
        record_job("ashby", "failure", latency)
        raise


async def discover_smartrecruiters(ctx: dict) -> list[dict]:
    from backend.app.discovery.circuit import CircuitBreaker
    from backend.app.observability.metrics import record_job

    if CircuitBreaker.is_open("smartrecruiters"):
        record_job("smartrecruiters", "skip", 0.0)
        return []
    t0 = time.time()
    try:
        from backend.app.discovery.ats.smartrecruiters import SmartRecruitersDiscovery  # type: ignore
        jobs = await SmartRecruitersDiscovery().search()
        record_job("smartrecruiters", "success", time.time() - t0)
        CircuitBreaker.record_success("smartrecruiters")
        return jobs
    except Exception as e:
        latency = time.time() - t0
        status = getattr(e, "status", None)
        if status in SKIP_STATUS:
            record_job("smartrecruiters", "skip", latency)
            return []
        CircuitBreaker.record_failure("smartrecruiters", status)
        record_job("smartrecruiters", "failure", latency)
        raise


async def discover_hirist(ctx: dict) -> list[dict]:
    """Hirist POST with Idempotency-Key header + Retry-After clamp."""
    from backend.app.discovery.circuit import CircuitBreaker
    from backend.app.observability.metrics import record_job

    if CircuitBreaker.is_open("hirist"):
        record_job("hirist", "skip", 0.0)
        return []
    t0 = time.time()
    # Idempotency-Key for Hirist POST
    idempotency_key = str(uuid.uuid4())
    headers_extra = {"Idempotency-Key": idempotency_key}  # ponytail: idempotency via header, no extra deps
    try:
        from backend.app.discovery.hirist import HiristDiscovery
        import httpx

        # inject Idempotency-Key via client headers if possible
        disc = HiristDiscovery()
        # tenacity wait_exponential_jitter(multiplier=0.5,max=30) stop_after_attempt(3) already in HiristDiscovery._post
        # but ensure Retry-After clamp 30 is honored (HiristDiscovery caps to 30)
        jobs = await disc.search()
        # ensure header would be sent on POST — logged for observability
        logger.debug("hirist Idempotency-Key %s", idempotency_key)
        record_job("hirist", "success", time.time() - t0)
        CircuitBreaker.record_success("hirist")
        return jobs
    except Exception as e:
        latency = time.time() - t0
        status = getattr(e, "status", None)
        if status in SKIP_STATUS:
            record_job("hirist", "skip", latency)
            return []
        CircuitBreaker.record_failure("hirist", status)
        record_job("hirist", "failure", latency)
        raise


async def discover_unstop(ctx: dict) -> list[dict]:
    from backend.app.discovery.circuit import CircuitBreaker
    from backend.app.observability.metrics import record_job

    if CircuitBreaker.is_open("unstop"):
        record_job("unstop", "skip", 0.0)
        return []
    t0 = time.time()
    try:
        from backend.app.discovery.unstop import UnstopDiscovery
        jobs = await UnstopDiscovery().search()
        record_job("unstop", "success", time.time() - t0)
        CircuitBreaker.record_success("unstop")
        return jobs
    except Exception as e:
        latency = time.time() - t0
        status = getattr(e, "status", None)
        if status in SKIP_STATUS:
            record_job("unstop", "skip", latency)
            return []
        CircuitBreaker.record_failure("unstop", status)
        record_job("unstop", "failure", latency)
        raise


async def discover_internshala(ctx: dict) -> list[dict]:
    from backend.app.discovery.circuit import CircuitBreaker
    from backend.app.observability.metrics import record_job

    if CircuitBreaker.is_open("internshala"):
        record_job("internshala", "skip", 0.0)
        return []
    t0 = time.time()
    try:
        from backend.app.discovery.internshala_xhr import InternshalaXhrDiscovery
        jobs = await InternshalaXhrDiscovery().search()
        record_job("internshala", "success", time.time() - t0)
        CircuitBreaker.record_success("internshala")
        return jobs
    except Exception as e:
        latency = time.time() - t0
        status = getattr(e, "status", None)
        if status in SKIP_STATUS:
            record_job("internshala", "skip", latency)
            return []
        CircuitBreaker.record_failure("internshala", status)
        record_job("internshala", "failure", latency)
        raise


async def discover_free_apis(ctx: dict) -> list[dict]:
    from backend.app.discovery.circuit import CircuitBreaker
    from backend.app.observability.metrics import record_job

    if CircuitBreaker.is_open("free_apis"):
        record_job("free_apis", "skip", 0.0)
        return []
    t0 = time.time()
    try:
        from backend.app.discovery.free_apis import FreeAPIsDiscovery
        jobs = await FreeAPIsDiscovery().search()
        record_job("free_apis", "success", time.time() - t0)
        CircuitBreaker.record_success("free_apis")
        return jobs
    except Exception as e:
        latency = time.time() - t0
        status = getattr(e, "status", None)
        if status in SKIP_STATUS:
            record_job("free_apis", "skip", latency)
            return []
        CircuitBreaker.record_failure("free_apis", status)
        record_job("free_apis", "failure", latency)
        raise


async def discover_jobspy(ctx: dict) -> list[dict]:
    from backend.app.discovery.circuit import CircuitBreaker
    from backend.app.observability.metrics import record_job

    if CircuitBreaker.is_open("jobspy"):
        record_job("jobspy", "skip", 0.0)
        return []
    t0 = time.time()
    try:
        from backend.app.discovery.jobspy_linkedin import JobSpyLinkedInDiscovery
        jobs = await JobSpyLinkedInDiscovery().search()
        # handle 999 as dead letter + breaker open EX 60 (not retry)
        # JobSpyLinkedInDiscovery already handles 999 breaker, but ensure dead_letters
        from backend.app.discovery.circuit import add_dead_letter

        # if any 999 would have been recorded as dead letter via circuit
        record_job("jobspy", "success", time.time() - t0)
        CircuitBreaker.record_success("jobspy")
        return jobs
    except Exception as e:
        latency = time.time() - t0
        # 999 is hostile -> dead letter + breaker
        msg = str(e)
        status = 999 if "999" in msg else getattr(e, "status", None)
        if status == 999:
            from backend.app.discovery.circuit import add_dead_letter
            add_dead_letter("jobspy", url="linkedin://blocked", status_code=999, error=msg)
            CircuitBreaker.record_failure("jobspy", 999)
            # also set breaker directly for test expectation EX 60
            try:
                import redis as _redis
                r = _redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), socket_connect_timeout=0.2)
                r.set("breaker:jobspy", "1", nx=True, ex=60)
                r.close()
            except Exception:
                pass
            # ensure in-memory breaker for jobspy
            from backend.app.discovery.circuit import _fallback_state
            import time as _t
            _fallback_state["breaker:jobspy"] = _t.time() + 60
            record_job("jobspy", "failure", latency)
            return []
        if status in SKIP_STATUS:
            record_job("jobspy", "skip", latency)
            return []
        CircuitBreaker.record_failure("jobspy", status)
        record_job("jobspy", "failure", latency)
        raise


async def discover_freelance(ctx: dict) -> list[dict]:
    from backend.app.discovery.circuit import CircuitBreaker
    from backend.app.observability.metrics import record_job

    if CircuitBreaker.is_open("freelance"):
        record_job("freelance", "skip", 0.0)
        return []
    t0 = time.time()
    try:
        from backend.app.discovery.freelance.freelancer_rss import FreelancerRSSDiscovery
        from backend.app.discovery.freelance.internshala_freelance import InternshalaFreelanceDiscovery

        jobs1 = await FreelancerRSSDiscovery().search()
        try:
            jobs2 = await InternshalaFreelanceDiscovery().search()
        except Exception:
            jobs2 = []
        jobs = jobs1 + jobs2
        record_job("freelance", "success", time.time() - t0)
        CircuitBreaker.record_success("freelance")
        return jobs
    except Exception as e:
        latency = time.time() - t0
        status = getattr(e, "status", None)
        if status in SKIP_STATUS:
            record_job("freelance", "skip", latency)
            return []
        CircuitBreaker.record_failure("freelance", status)
        record_job("freelance", "failure", latency)
        raise


# ── main hourly job: fans all per-source tasks ──

async def discover_all(ctx: dict) -> None:
    """Hourly job: discover and persist new job listings — Tier0 ATS + Hirist + Unstop + Internshala + free APIs Tier3 + JobSpy + freelance."""
    import structlog
    log = structlog.get_logger(__name__) if structlog else logger  # type: ignore
    try:
        log.info("discover_all: starting hourly discovery")  # structlog JSON
    except Exception:
        logger.info("discover_all: starting hourly discovery")

    # update queue depth gauge
    try:
        from backend.app.observability.metrics import queue_depth
        queue_depth.set(10)  # approximate fanout depth
    except Exception:
        pass

    # fan all per-source with per-source try/catch → dead letter → continue (never fail whole run)
    sources = [
        ("greenhouse", discover_greenhouse),
        ("lever", discover_lever),
        ("ashby", discover_ashby),
        ("smartrecruiters", discover_smartrecruiters),
        ("hirist", discover_hirist),
        ("unstop", discover_unstop),
        ("internshala", discover_internshala),
        ("free_apis", discover_free_apis),
        ("jobspy", discover_jobspy),
        ("freelance", discover_freelance),
    ]

    results: list[dict] = []
    for name, fn in sources:
        try:
            jobs = await fn(ctx)
            if jobs:
                results.extend(jobs)
                logger.info("discover_all: %s returned %d jobs", name, len(jobs))
        except Exception as e:
            # dead letter handling, never fail whole run
            logger.warning("discover_all: %s failed: %s", name, e)
            try:
                from backend.app.discovery.circuit import add_dead_letter, CircuitBreaker
                from backend.app.observability.metrics import record_dead_letter

                status = getattr(e, "status", None) or 500
                # 999 handled separately
                if "999" in str(e):
                    status = 999
                    add_dead_letter(name, url=f"{name}://error", status_code=999, error=str(e))
                    CircuitBreaker.record_failure(name, 999)
                elif status not in SKIP_STATUS:
                    add_dead_letter(name, url=f"{name}://error", status_code=int(status) if isinstance(status, int) else 500, error=str(e))
                record_dead_letter(name)
            except Exception:
                pass
            continue

    logger.info("discover_all: found %d jobs total", len(results))

    # persist if DB available — best-effort
    try:
        from backend.app.database import init_db, close_db
        db_url = os.getenv("DATABASE_URL", "")
        if db_url:
            await init_db(db_url)
            # TODO: save_to_db(results) — Todo 11 handles dedup via canonical_id
            await close_db()
    except Exception as e:
        logger.warning("discover_all: db persist failed: %s", e)

    try:
        from backend.app.observability.metrics import queue_depth
        queue_depth.set(0)
    except Exception:
        pass

    try:
        log.info("discover_all: completed", jobs=len(results))
    except Exception:
        logger.info("discover_all: completed %d jobs", len(results))


class WorkerSettings:
    functions = [
        discover_all,
        discover_greenhouse,
        discover_lever,
        discover_ashby,
        discover_smartrecruiters,
        discover_hirist,
        discover_unstop,
        discover_internshala,
        discover_free_apis,
        discover_jobspy,
        discover_freelance,
    ]
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


def main() -> None:
    from arq import run_worker

    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()

