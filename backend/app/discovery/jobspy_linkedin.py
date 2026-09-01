from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_project_root))

import httpx
from loguru import logger

try:
    from backend.app.discovery.hash_utils import canonical_id, jd_hash
except ImportError:
    from internapply.discovery.hash_utils import canonical_id, jd_hash  # type: ignore

_breaker: dict[str, float] = {}
BREAKER_KEY = "breaker:linkedin"
BREAKER_TTL = 60
RATE_DELAY = 0.5


def _is_breaker_open(key: str = BREAKER_KEY) -> bool:
    exp = _breaker.get(key, 0)
    if exp and time.time() < exp:
        return True
    if exp and time.time() >= exp:
        _breaker.pop(key, None)
    return False


def _handle_999(exc: Exception | None = None) -> None:
    now = time.time()
    # try Redis SETNX EX 60 first
    try:
        import redis as _redis

        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = _redis.from_url(url, socket_connect_timeout=1)
        # SETNX with EX — only sets if not exists
        ok = r.set(BREAKER_KEY, "1", ex=BREAKER_TTL, nx=True)
        if ok:
            logger.warning("breaker:linkedin open 60s (999 detected) redis SETNX")
        else:
            ttl = r.ttl(BREAKER_KEY)
            logger.warning("breaker:linkedin open 60s (already open ttl={})", ttl)
        r.close()
    except Exception:
        pass
    # always set in-memory as fallback / mirror
    if BREAKER_KEY not in _breaker or time.time() >= _breaker.get(BREAKER_KEY, 0):
        _breaker[BREAKER_KEY] = now + BREAKER_TTL
    logger.warning("breaker:linkedin open 60s")
    if exc:
        logger.debug("999 cause: {}", exc)


async def _fallback_wreq(search_term: str, location: str) -> list[dict[str, Any]]:
    url = os.getenv("WREQ_SIDECAR_URL", "").rstrip("/")
    if not url:
        return []
    endpoint = f"{url}/linkedin/search"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(endpoint, json={"search_term": search_term, "location": location})
            if resp.status_code == 200:
                data = resp.json()
                jobs = data.get("jobs") or data.get("data") or []
                logger.info("wreq-js fallback returned {} jobs", len(jobs))
                out: list[dict[str, Any]] = []
                for j in jobs:
                    title = j.get("title", "")
                    company = j.get("company", "")
                    loc = j.get("location", location)
                    job_url = j.get("job_url") or j.get("url") or ""
                    out.append(
                        {
                            "title": title,
                            "company": company,
                            "location": loc,
                            "description": j.get("description", ""),
                            "source": "linkedin",
                            "source_ats": "linkedin",
                            "url": job_url,
                            "canonical_id": canonical_id(company, title, loc, job_url),
                            "jd_hash": jd_hash({"title": title, "company": company, "location": loc, "description": j.get("description", "")}),
                        }
                    )
                return out
            logger.warning("wreq-js fallback status {}", resp.status_code)
    except Exception as e:
        logger.warning("wreq-js fallback failed: {}", e)
    return []


def _is_999(exc: Exception) -> bool:
    msg = str(exc)
    if "999" in msg:
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code == 999:
        return True
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if status == 999:
        return True
    return False


def _row_to_job(row: Any, site: str) -> dict[str, Any]:
    title = str(row.get("title", "") or "")
    company = str(row.get("company", "") or "")
    loc = str(row.get("location", "") or "")
    job_url = str(row.get("job_url", "") or row.get("job_url_direct", "") or "")
    desc = str(row.get("description", "") or "")
    j: dict[str, Any] = {
        "title": title,
        "company": company,
        "location": loc,
        "description": desc,
        "source": site,
        "source_ats": site,
        "url": job_url,
        "job_type": str(row.get("job_type", "") or ""),
        "is_remote": bool(row.get("is_remote", False)),
        "posted_at": str(row.get("date_posted", "") or ""),
        "skills": [],
        "canonical_id": canonical_id(company, title, loc, job_url),
        "jd_hash": jd_hash({"title": title, "company": company, "location": loc, "description": desc}),
    }
    salary = row.get("salary", None)
    if isinstance(salary, dict):
        j["stipend_min"] = salary.get("min_amount")
        j["stipend_max"] = salary.get("max_amount")
        j["stipend_currency"] = salary.get("currency")
    return j


class JobSpyLinkedInDiscovery:
    def __init__(self) -> None:
        self._jobspy_available = self._check_jobspy()

    def _check_jobspy(self) -> bool:
        try:
            import jobspy  # noqa: F401

            return True
        except ImportError:
            logger.warning("python-jobspy not installed")
            return False

    async def search(
        self,
        search_term: str = "DevOps intern",
        location: str = "Bangalore",
        hours_old: int = 24,
        results_wanted: int = 20,
        country_indeed: str = "India",
    ) -> list[dict[str, Any]]:
        if not self._jobspy_available:
            logger.error("python-jobspy not available")
            return []
        try:
            from jobspy import scrape_jobs  # type: ignore
        except ImportError as e:
            logger.error("Missing dependency: {}", e)
            return []

        sites = ["naukri", "indeed", "linkedin"]
        all_jobs: list[dict[str, Any]] = []

        for idx, site in enumerate(sites):
            if site == "linkedin" and _is_breaker_open():
                logger.warning("breaker:linkedin open 60s — skipping linkedin")
                continue
            if idx > 0:
                await asyncio.sleep(RATE_DELAY)
            try:
                kwargs: dict[str, Any] = dict(
                    site_name=[site],
                    search_term=search_term,
                    location=location,
                    results_wanted=results_wanted,
                    hours_old=hours_old,
                    country_indeed=country_indeed,
                    linkedin_fetch_description=True,
                    description_format="markdown",
                )
                if site == "indeed":
                    kwargs["country_indeed"] = country_indeed
                # run sync scrape in thread to avoid blocking event loop
                df = await asyncio.to_thread(lambda k=kwargs: scrape_jobs(**k))
                if df is None or getattr(df, "empty", False):
                    logger.info("JobSpy {} returned no results for '{}'", site, search_term)
                    continue
                for _, row in df.iterrows():
                    all_jobs.append(_row_to_job(row, site))
                logger.info("JobSpy {} returned {} jobs", site, len([j for j in all_jobs if j["source_ats"] == site]))
            except Exception as e:
                if _is_999(e):
                    _handle_999(e)
                    if site == "linkedin":
                        fb = await _fallback_wreq(search_term, location)
                        if fb:
                            all_jobs.extend(fb)
                        else:
                            logger.info("breaker:linkedin open 60s and continue Naukri/Indeed batch")
                    else:
                        logger.warning("999 on {} — breaker:linkedin open 60s", site)
                    continue
                logger.error("JobSpy {} scrape failed: {}", site, e)
                continue

        # 999 circuit breaker never raises — return partial Naukri+Indeed
        return all_jobs
