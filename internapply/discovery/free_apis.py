"""Tier3 overflow free APIs: Arbeitnow, Remotive, TheMuse, Jobicy.

Tier3 overflow only — EU/US remote feeds, expect 90%+ filtered for Bangalore narrow.
Never fail whole run if one source fails (per-source try/catch).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import httpx
from loguru import logger
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from internapply.discovery.hash_utils import canonical_id, jd_hash, simhash64

ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
THEMUSE_URL = "https://www.themuse.com/api/public/jobs"
JOBICY_URL = "https://jobicy.com/api/v2/remote-jobs"


def _passes_filter(location: str) -> bool:
    loc = (location or "").lower()
    return "bangalore" in loc or "remote" in loc


def _is_enabled(flag: str, default: bool = True) -> bool:
    for mod in ("internapply.config", "backend.app.config"):
        try:
            m = __import__(mod, fromlist=["get_config", "settings", flag])
            if hasattr(m, "get_config"):
                try:
                    v = getattr(m.get_config(), flag, default)
                    if isinstance(v, bool):
                        return v
                except Exception:
                    pass
            if hasattr(m, "settings"):
                try:
                    v = getattr(m.settings, flag, default)
                    if isinstance(v, bool):
                        return v
                except Exception:
                    pass
        except Exception:
            continue
    env = os.getenv(flag)
    if env is not None:
        return env.lower() in ("1", "true", "yes", "on")
    return default


async def _set_breaker(source: str) -> None:
    """Redis SETNX breaker:source EX 60 — best-effort, never crash."""
    try:
        import redis.asyncio as aioredis  # type: ignore[import-not-found]

        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = aioredis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        try:
            await r.set(f"breaker:{source}", "1", nx=True, ex=60)
        finally:
            try:
                await r.aclose()
            except Exception:
                pass
    except Exception:
        pass


class _Retry429(Exception):
    def __init__(self, retry_after: float = 1.0, source: str = ""):
        self.retry_after = min(retry_after, 30.0)
        self.source = source
        super().__init__(f"429 {source} retry after {self.retry_after}s")


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, _Retry429)


def _parse_retry_after(headers: Any) -> float:
    try:
        ra = (headers.get("Retry-After") or headers.get("retry-after") or "1") if headers else "1"
    except Exception:
        ra = "1"
    try:
        return float(str(ra).strip())
    except ValueError:
        return 1.0


# ── parsers ──


def _parse_arbeitnow_jobs(payload: Any) -> list[dict[str, Any]]:
    # Arbeitnow: {"data": [...]} or {"jobs": [...]} or list
    items: Any = None
    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("jobs") or payload.get("results") or []
    elif isinstance(payload, list):
        items = payload
    else:
        return []
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for j in items:
        if not isinstance(j, dict):
            continue
        jid = str(j.get("slug") or j.get("id") or j.get("_id") or "")
        title = str(j.get("title") or j.get("jobTitle") or "").strip()
        company = str(j.get("company_name") or j.get("company") or j.get("companyName") or "").strip()
        location = str(j.get("location") or j.get("city") or "").strip()
        # Arbeitnow location can be "Berlin, Germany" etc
        desc = str(j.get("description") or j.get("desc") or "")
        url = str(j.get("url") or (f"https://www.arbeitnow.com/jobs/{jid}" if jid else ""))
        posted = str(j.get("created_at") or j.get("publishedAt") or j.get("createdAt") or "")
        if not title and not jid:
            continue
        cid = canonical_id(company, title, location, jid or url)
        jd = jd_hash({"title": title, "company": company, "location": location, "description": desc})
        sh = simhash64(f"{title} {company} {desc[:500]}")
        out.append({
            "title": title, "company": company, "location": location,
            "description": desc, "stipend_raw": "", "posted_date": posted,
            "url": url, "source_job_id": jid, "source_ats": "arbeitnow",
            "canonical_id": cid, "jd_hash": jd, "simhash": sh,
        })
    return out


def _parse_remotive_jobs(payload: Any) -> list[dict[str, Any]]:
    items: Any = None
    if isinstance(payload, dict):
        items = payload.get("jobs") or payload.get("data") or payload.get("results") or []
    elif isinstance(payload, list):
        items = payload
    else:
        return []
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for j in items:
        if not isinstance(j, dict):
            continue
        jid = str(j.get("id") or j.get("_id") or "")
        title = str(j.get("title") or j.get("jobTitle") or "").strip()
        company = str(j.get("company_name") or j.get("company") or "")
        if isinstance(company, dict):
            company = str(company.get("name") or "")
        location = str(j.get("candidate_required_location") or j.get("location") or j.get("city") or "").strip()
        desc = str(j.get("description") or j.get("desc") or "")
        url = str(j.get("url") or j.get("jobUrl") or "")
        posted = str(j.get("publication_date") or j.get("createdAt") or "")
        if not title and not jid:
            continue
        cid = canonical_id(company, title, location, jid or url)
        jd = jd_hash({"title": title, "company": company, "location": location, "description": desc})
        sh = simhash64(f"{title} {company} {desc[:500]}")
        out.append({
            "title": title, "company": company, "location": location,
            "description": desc, "stipend_raw": "", "posted_date": posted,
            "url": url, "source_job_id": jid, "source_ats": "remotive",
            "canonical_id": cid, "jd_hash": jd, "simhash": sh,
        })
    return out


def _parse_themuse_jobs(payload: Any) -> list[dict[str, Any]]:
    items: Any = None
    if isinstance(payload, dict):
        items = payload.get("results") or payload.get("jobs") or payload.get("data") or []
        # some responses nest page_count
    elif isinstance(payload, list):
        items = payload
    else:
        return []
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for j in items:
        if not isinstance(j, dict):
            continue
        jid = str(j.get("id") or "")
        title = str(j.get("name") or j.get("title") or "").strip()
        comp = j.get("company") or {}
        if isinstance(comp, dict):
            company = str(comp.get("name") or "")
        else:
            company = str(comp)
        # locations: [{"name": "New York, NY"}, ...]
        locs = j.get("locations") or j.get("location") or []
        if isinstance(locs, list):
            location = ", ".join(str(x.get("name") if isinstance(x, dict) else x) for x in locs)
        elif isinstance(locs, dict):
            location = str(locs.get("name") or "")
        else:
            location = str(locs)
        # contents or description
        desc = str(j.get("contents") or j.get("description") or j.get("content") or "")
        # url
        refs = j.get("refs") or {}
        url = str(refs.get("landing_page") or j.get("refs_landing_page") or j.get("url") or (f"https://www.themuse.com/jobs/{jid}" if jid else ""))
        posted = str(j.get("publication_date") or j.get("published_at") or "")
        if not title and not jid:
            continue
        cid = canonical_id(company, title, location, jid or url)
        jd = jd_hash({"title": title, "company": company, "location": location, "description": desc})
        sh = simhash64(f"{title} {company} {desc[:500]}")
        out.append({
            "title": title, "company": company, "location": location,
            "description": desc, "stipend_raw": "", "posted_date": posted,
            "url": url, "source_job_id": jid, "source_ats": "themuse",
            "canonical_id": cid, "jd_hash": jd, "simhash": sh,
        })
    return out


def _parse_jobicy_jobs(payload: Any) -> list[dict[str, Any]]:
    items: Any = None
    if isinstance(payload, dict):
        # Jobicy v2: {"jobs": [{"id","jobTitle","companyName","jobGeo","jobDescription","url","pubDate"}]}
        items = payload.get("jobs") or payload.get("data") or payload.get("results") or payload.get("jobList") or []
        if isinstance(items, dict):
            items = items.get("jobs") or items.get("data") or []
    elif isinstance(payload, list):
        items = payload
    else:
        return []
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for j in items:
        if not isinstance(j, dict):
            continue
        jid = str(j.get("id") or j.get("jobId") or j.get("_id") or "")
        title = str(j.get("jobTitle") or j.get("title") or j.get("name") or "").strip()
        company = str(j.get("companyName") or j.get("company") or "")
        if isinstance(company, dict):
            company = str(company.get("name") or "")
        location = str(j.get("jobGeo") or j.get("location") or j.get("city") or j.get("geo") or "").strip()
        desc = str(j.get("jobDescription") or j.get("description") or j.get("desc") or "")
        url = str(j.get("url") or j.get("jobUrl") or (f"https://jobicy.com/jobs/{jid}" if jid else ""))
        posted = str(j.get("pubDate") or j.get("publishedAt") or j.get("publication_date") or "")
        if not title and not jid:
            continue
        cid = canonical_id(company, title, location, jid or url)
        jd = jd_hash({"title": title, "company": company, "location": location, "description": desc})
        sh = simhash64(f"{title} {company} {desc[:500]}")
        out.append({
            "title": title, "company": company, "location": location,
            "description": desc, "stipend_raw": "", "posted_date": posted,
            "url": url, "source_job_id": jid, "source_ats": "jobicy",
            "canonical_id": cid, "jd_hash": jd, "simhash": sh,
        })
    return out


class FreeAPIsDiscovery:
    """Tier3 overflow free APIs discovery."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self._owns_client = client is None
        self._remotive_fetched = False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            http2=False,
        )
        self._owns_client = True
        return self._client

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    # ── per-source fetch with 429 handling ──

    @retry(retry=retry_if_exception(_is_retryable), stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=0.5, max=30), reraise=True)
    async def _get_with_429(self, client: httpx.AsyncClient, url: str, source: str, **kwargs: Any) -> httpx.Response:
        resp = await client.get(url, **kwargs)
        if resp.status_code == 429:
            delay = min(_parse_retry_after(resp.headers), 30.0)
            logger.warning("Tier3 {} 429 Retry-After {}", source, delay)
            await _set_breaker(source)
            # respect Retry-After explicitly (clamped 30) before tenacity retry
            try:
                await asyncio.sleep(delay)
            except Exception:
                pass
            raise _Retry429(delay, source)
        return resp

    async def _fetch_arbeitnow(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """Return raw (unfiltered) jobs; filtering + Tier3 logging happens in search()."""
        if not _is_enabled("ARBEITNOW_ENABLED", True):
            logger.info("Tier3 arbeitnow disabled via config")
            return []
        all_jobs: list[dict[str, Any]] = []
        for page in range(1, 11):  # max 10 pages
            url = f"{ARBEITNOW_URL}?page={page}"
            try:
                try:
                    resp = await self._get_with_429(client, url, "arbeitnow")
                except _Retry429:
                    logger.warning("Tier3 arbeitnow 429 retries exhausted at page {}", page)
                    break
                if resp.status_code == 404:
                    logger.info("Tier3 arbeitnow 404 at page {} — stop", page)
                    break
                if resp.status_code != 200:
                    logger.warning("Tier3 arbeitnow HTTP {} at page {} — stop", resp.status_code, page)
                    break
                try:
                    payload = resp.json()
                except Exception:
                    logger.warning("Tier3 arbeitnow non-JSON at page {}", page)
                    break
                jobs = _parse_arbeitnow_jobs(payload)
                if not jobs:
                    break
                all_jobs.extend(jobs)
                logger.debug("Tier3 arbeitnow page {}: {} jobs", page, len(jobs))
            except Exception as e:
                logger.error("Tier3 arbeitnow page {} failed: {}", page, e)
                break
        return all_jobs

    async def _fetch_remotive(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """Single GET https://remotive.com/api/remote-jobs — once per run."""
        if self._remotive_fetched:
            logger.debug("Tier3 remotive already fetched this run — skip (once per discovery)")
            return []
        self._remotive_fetched = True
        if not _is_enabled("REMOTIVE_ENABLED", True):
            logger.info("Tier3 remotive disabled via config")
            return []
        try:
            try:
                resp = await self._get_with_429(client, REMOTIVE_URL, "remotive")
            except _Retry429:
                logger.warning("Tier3 remotive 429 retries exhausted")
                return []
            if resp.status_code == 404:
                logger.info("Tier3 remotive 404 — skip")
                return []
            if resp.status_code != 200:
                logger.warning("Tier3 remotive HTTP {} — skip", resp.status_code)
                return []
            try:
                payload = resp.json()
            except Exception:
                logger.warning("Tier3 remotive non-JSON")
                return []
            jobs = _parse_remotive_jobs(payload)
            logger.debug("Tier3 remotive: {} jobs", len(jobs))
            return jobs
        except Exception as e:
            logger.error("Tier3 remotive failed: {}", e)
            return []

    async def _fetch_themuse(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """Paginated 20/page; handles 500/hr anon vs 3600/hr with api_key."""
        if not _is_enabled("THEMUSE_ENABLED", True):
            logger.info("Tier3 themuse disabled via config")
            return []
        all_jobs: list[dict[str, Any]] = []
        api_key = os.getenv("THEMUSE_API_KEY") or os.getenv("MUSE_API_KEY") or ""
        for page in range(1, 11):  # max 10 pages safety
            params: dict[str, Any] = {"page": page}
            if api_key:
                params["api_key"] = api_key
            try:
                try:
                    resp = await self._get_with_429(client, THEMUSE_URL, "themuse", params=params)
                except _Retry429:
                    logger.warning("Tier3 themuse 429 retries exhausted at page {}", page)
                    break
                if resp.status_code == 404:
                    logger.info("Tier3 themuse 404 at page {} — stop", page)
                    break
                if resp.status_code != 200:
                    logger.warning("Tier3 themuse HTTP {} at page {} — stop", resp.status_code, page)
                    break
                try:
                    payload = resp.json()
                except Exception:
                    logger.warning("Tier3 themuse non-JSON at page {}", page)
                    break
                jobs = _parse_themuse_jobs(payload)
                if not jobs:
                    break
                all_jobs.extend(jobs)
                logger.debug("Tier3 themuse page {}: {} jobs", page, len(jobs))
                if isinstance(payload, dict):
                    page_count = payload.get("page_count") or payload.get("pageCount")
                    if page_count is not None:
                        try:
                            if page >= int(page_count):
                                break
                        except Exception:
                            pass
            except Exception as e:
                logger.error("Tier3 themuse page {} failed: {}", page, e)
                break
        return all_jobs

    async def _fetch_jobicy(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        if not _is_enabled("JOBICY_ENABLED", True):
            logger.info("Tier3 jobicy disabled via config")
            return []
        try:
            try:
                resp = await self._get_with_429(client, f"{JOBICY_URL}?count=100", "jobicy")
            except _Retry429:
                logger.warning("Tier3 jobicy 429 retries exhausted")
                return []
            if resp.status_code == 404:
                logger.info("Tier3 jobicy 404 — skip")
                return []
            if resp.status_code != 200:
                logger.warning("Tier3 jobicy HTTP {} — skip", resp.status_code)
                return []
            try:
                payload = resp.json()
            except Exception:
                logger.warning("Tier3 jobicy non-JSON")
                return []
            jobs = _parse_jobicy_jobs(payload)
            logger.debug("Tier3 jobicy: {} jobs", len(jobs))
            return jobs
        except Exception as e:
            logger.error("Tier3 jobicy failed: {}", e)
            return []

    async def search(self, **_: Any) -> list[dict[str, Any]]:
        """Discovery entrypoint — never fails whole run if one source dies. Tier3 overflow only."""
        client = await self._get_client()

        async def _run(source: str, coro: Any) -> list[dict[str, Any]]:
            try:
                jobs = await coro
                return jobs if isinstance(jobs, list) else []
            except Exception as e:
                logger.error("Tier3 {} failed (overflow only, continue): {}", source, e)
                return []

        arbeitnow_raw = await _run("arbeitnow", self._fetch_arbeitnow(client))
        remotive_raw = await _run("remotive", self._fetch_remotive(client))
        themuse_raw = await _run("themuse", self._fetch_themuse(client))
        jobicy_raw = await _run("jobicy", self._fetch_jobicy(client))

        before = len(arbeitnow_raw) + len(remotive_raw) + len(themuse_raw) + len(jobicy_raw)
        all_raw = arbeitnow_raw + remotive_raw + themuse_raw + jobicy_raw
        filtered = [j for j in all_raw if _passes_filter(j.get("location", ""))]
        after = len(filtered)
        logger.info("Tier3 free APIs returned {} before filter, {} after", before, after)
        return filtered

    async def __aenter__(self):
        await self._get_client()
        return self

    async def __aexit__(self, *a):
        await self.close()
