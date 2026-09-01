"""Shared httpx helper for ATS discovery — tenacity Retry-After clamp, no http2."""
from __future__ import annotations

import asyncio
import email.utils
import re
import time

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

# filters
LOCATION_RE = re.compile(r"bangalore|remote|wfh", re.I)
TITLE_RE = re.compile(r"devops|sre|platform|backend|infra|cloud|kubernetes|docker|terraform", re.I)

RETRY_STATUS = {429, 502, 503, 504}
SKIP_STATUS = {403, 404, 401, 422}

def location_match(loc: str | None) -> bool:
    if not loc:
        return False
    return bool(LOCATION_RE.search(loc))

def title_match(title: str | None) -> bool:
    if not title:
        return False
    return bool(TITLE_RE.search(title))

def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    v = value.strip()
    # seconds
    try:
        secs = float(v)
        return max(0, min(secs, 30))
    except ValueError:
        pass
    # HTTP-date
    try:
        dt = email.utils.parsedate_to_datetime(v)
        if dt is not None:
            now = time.time()
            target = dt.timestamp()
            secs = target - now
            if secs < 0:
                secs = 0
            return max(0, min(secs, 30))
    except Exception:
        pass
    return None

class RetryableError(Exception):
    def __init__(self, status: int, retry_after: float | None = None):
        super().__init__(f"retryable {status} retry_after={retry_after}")
        self.status = status
        self.retry_after = retry_after

def _is_retryable_exc(exc: BaseException) -> bool:
    if isinstance(exc, RetryableError):
        return exc.status in RETRY_STATUS
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout)):
        return True
    return False

def _wait_retry_after(retry_state) -> float:
    # check Retry-After from exception
    if retry_state.outcome and retry_state.outcome.failed:
        exc = retry_state.outcome.exception()
        if isinstance(exc, RetryableError) and exc.retry_after is not None:
            # clamp max_wait=30 + jitter small
            base = min(float(exc.retry_after), 30)
            # add jitter up to 0.5s to avoid thundering herd, still bounded by 30
            import random
            jitter = random.uniform(0, 0.5)
            return min(base + jitter, 30)
    # fallback exponential jitter multiplier 0.5 max 30
    return wait_exponential_jitter(multiplier=0.5, max=30)(retry_state)

def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        http2=False,
        headers={"User-Agent": "internapply-ats/0.1"},
    )

async def fetch_json(client: httpx.AsyncClient, url: str, *, max_retries: int = 3) -> dict | list | None:
    """Fetch JSON with tenacity on 429/502/503/504 + timeouts, skip 403/404."""
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_retries),
        wait=_wait_retry_after,
        retry=retry_if_exception(_is_retryable_exc),
        reraise=True,
    ):
        with attempt:
            resp = await client.get(url)
            if resp.status_code == 200:
                try:
                    return resp.json()
                except Exception:
                    return None
            if resp.status_code in SKIP_STATUS:
                # 403→skip, 404→skip, also 401/422 skip
                return None
            if resp.status_code in RETRY_STATUS:
                # parse Retry-After header (seconds or HTTP-date) clamp to 30
                raw = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
                ra = parse_retry_after(raw)
                raise RetryableError(resp.status_code, retry_after=ra)
            # other 5xx retryable
            if 500 <= resp.status_code < 600:
                raise RetryableError(resp.status_code)
            # unexpected 4xx -> skip (do not retry)
            return None
    return None
