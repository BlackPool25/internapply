"""Circuit breaker via Redis SETNX breaker:{source} EX 60, fail_max=5, exclude 404.

25-30% stale boards expected not failure — 404 never counts.
Redis SETNX breaker:{source} EX 60 fail_max=5 reset_timeout=60 exclude 404
In-memory fallback for tests / when redis unavailable.
"""

from __future__ import annotations

import os
import time

# in-memory fallback stores: key -> expiry timestamp, and failure counts
_fallback_state: dict[str, float] = {}
_failure_counts: dict[str, int] = {}
_dead_letters: list[dict] = []  # for observability/tests; real table in Todo 11

FAIL_MAX = 5
RESET_TIMEOUT = 60
EXCLUDE_STATUS = {404}


def _key(source: str) -> str:
    return f"breaker:{source}"


def check_breaker(source: str) -> bool:
    """Helper: True if breaker open for source."""
    return CircuitBreaker.is_open(source)


class CircuitBreaker:
    """Redis SETNX breaker with in-memory fallback."""

    @staticmethod
    def _key(source: str) -> str:
        return _key(source)

    @staticmethod
    def is_open(source: str) -> bool:
        key = _key(source)
        # check redis first (best-effort)
        try:
            import redis as _redis  # type: ignore

            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            r = _redis.from_url(url, socket_connect_timeout=0.2, socket_timeout=0.2)
            try:
                ttl = r.ttl(key)
                if ttl is not None and ttl > 0:
                    return True
                # also check exists
                if r.exists(key):
                    return True
            finally:
                try:
                    r.close()
                except Exception:
                    pass
        except Exception:
            pass
        # fallback in-memory
        exp = _fallback_state.get(key, 0)
        if exp and time.time() < exp:
            return True
        if exp and time.time() >= exp:
            _fallback_state.pop(key, None)
            _failure_counts.pop(source, None)
        return False

    @staticmethod
    async def is_open_async(source: str) -> bool:
        key = _key(source)
        try:
            import redis.asyncio as aioredis  # type: ignore

            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            r = aioredis.from_url(url, socket_connect_timeout=0.2, socket_timeout=0.2)
            try:
                ttl = await r.ttl(key)
                if ttl is not None and ttl > 0:
                    return True
                exists = await r.exists(key)
                if exists:
                    return True
            finally:
                try:
                    await r.aclose()
                except Exception:
                    pass
        except Exception:
            pass
        return CircuitBreaker.is_open(source)

    @staticmethod
    def record_success(source: str) -> None:
        _failure_counts.pop(source, None)
        # also clear fallback breaker if success resets
        _fallback_state.pop(_key(source), None)
        # best-effort clear redis
        try:
            import redis as _redis

            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            r = _redis.from_url(url, socket_connect_timeout=0.2, socket_timeout=0.2)
            try:
                r.delete(_key(source))
            finally:
                try:
                    r.close()
                except Exception:
                    pass
        except Exception:
            pass

    @staticmethod
    async def record_success_async(source: str) -> None:
        CircuitBreaker.record_success(source)
        # also try async delete
        try:
            import redis.asyncio as aioredis

            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            r = aioredis.from_url(url, socket_connect_timeout=0.2, socket_timeout=0.2)
            try:
                await r.delete(_key(source))
            finally:
                try:
                    await r.aclose()
                except Exception:
                    pass
        except Exception:
            pass

    @staticmethod
    def record_failure(source: str, status_code: int | None = None) -> bool:
        """Record failure; returns True if breaker tripped. Exclude 404."""
        if status_code in EXCLUDE_STATUS:
            return False
        # count
        cnt = _failure_counts.get(source, 0) + 1
        _failure_counts[source] = cnt
        if cnt >= FAIL_MAX:
            key = _key(source)
            # Redis SETNX EX 60
            try:
                import redis as _redis

                url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                r = _redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5)
                try:
                    r.set(key, "1", nx=True, ex=RESET_TIMEOUT)
                finally:
                    try:
                        r.close()
                    except Exception:
                        pass
            except Exception:
                pass
            # always set in-memory fallback
            _fallback_state[key] = time.time() + RESET_TIMEOUT
            return True
        return False

    @staticmethod
    async def record_failure_async(source: str, status_code: int | None = None) -> bool:
        if status_code in EXCLUDE_STATUS:
            return False
        cnt = _failure_counts.get(source, 0) + 1
        _failure_counts[source] = cnt
        if cnt >= FAIL_MAX:
            key = _key(source)
            try:
                import redis.asyncio as aioredis

                url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                r = aioredis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5)
                try:
                    await r.set(key, "1", nx=True, ex=RESET_TIMEOUT)
                finally:
                    try:
                        await r.aclose()
                    except Exception:
                        pass
            except Exception:
                pass
            _fallback_state[key] = time.time() + RESET_TIMEOUT
            return True
        return False


# dead_letters helper (in-memory until Todo 11 DB table)
def add_dead_letter(source: str, url: str, status_code: int, error: str = "", retry_count: int = 0) -> None:
    _dead_letters.append(
        {"source": source, "url": url, "status_code": status_code, "error": error, "retry_count": retry_count}
    )


def get_dead_letters(source: str | None = None) -> list[dict]:
    if source is None:
        return list(_dead_letters)
    return [d for d in _dead_letters if d["source"] == source]


def clear_dead_letters() -> None:
    _dead_letters.clear()


# for tests: reset all state
def _reset_for_tests() -> None:
    _fallback_state.clear()
    _failure_counts.clear()
    _dead_letters.clear()
