"""Hirist gladiator search — POST gladiator.hirist.tech/job/search."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import httpx
from loguru import logger
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from backend.app.discovery.hash_utils import canonical_id, jd_hash, simhash64

HIRIST_URL = "https://gladiator.hirist.tech/job/search"
HIRIST_HEADERS = {
    "appId": "hirist",
    "Referer": "https://hirist.tech",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
HIRIST_BODY = {
    "query": "",
    "filters": {
        "skills": ["Docker", "Kubernetes", "AWS", "Terraform", "Linux", "Golang", "Python"],
        "experience": ["0-1", "1-2"],
        "locations": ["Bangalore"],
        "jobTypes": ["Internship"],
    },
}


class _Retry429(Exception):
    def __init__(self, retry_after: float = 1.0):
        self.retry_after = min(retry_after, 30.0)
        super().__init__(f"429 retry after {self.retry_after}s")


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, _Retry429)


def _parse_jobs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = payload.get("jobs") or payload.get("data") or payload.get("results") or []
    if isinstance(jobs, dict):
        jobs = jobs.get("jobs") or jobs.get("data") or []
    if not isinstance(jobs, list):
        return []
    out: list[dict[str, Any]] = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        jid = str(j.get("id") or j.get("jobId") or j.get("_id") or "")
        title = str(j.get("title") or j.get("jobTitle") or "").strip()
        company = str(j.get("company") or j.get("companyName") or j.get("org") or "").strip()
        location = str(j.get("location") or j.get("locations") or j.get("city") or "").strip()
        if isinstance(location, list):
            location = ", ".join(str(x) for x in location)
        desc = str(j.get("description") or j.get("jobDescription") or j.get("desc") or "")
        lpa = j.get("lpa") or j.get("salary") or j.get("ctc") or ""
        posted = str(j.get("postedDate") or j.get("createdAt") or j.get("publishedAt") or "")
        url = str(j.get("url") or j.get("jobUrl") or (f"https://hirist.tech/j/{jid}" if jid else ""))
        if not title and not jid:
            continue
        cid = canonical_id(company, title, location, jid or url)
        jd = jd_hash({"title": title, "company": company, "location": location, "description": desc})
        sh = simhash64(f"{title} {company} {desc[:500]}")
        out.append({
            "title": title, "company": company, "location": location,
            "description": desc, "stipend_raw": str(lpa), "posted_date": posted,
            "url": url, "source_job_id": jid, "source_ats": "hirist",
            "canonical_id": cid, "jd_hash": jd, "simhash": sh,
        })
    return out


class HiristDiscovery:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        self._client = httpx.AsyncClient(timeout=15.0)
        self._owns_client = True
        return self._client

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @retry(retry=retry_if_exception(_is_retryable), stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=0.5, max=30), reraise=True)
    async def _post(self, client: httpx.AsyncClient) -> httpx.Response:
        resp = await client.post(HIRIST_URL, headers=HIRIST_HEADERS, json=HIRIST_BODY)
        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After") or resp.headers.get("retry-after") or "1"
            try:
                delay = float(ra)
            except ValueError:
                delay = 1.0
            delay = min(delay, 30.0)
            logger.warning("Hirist 429 Retry-After {}", delay)
            raise _Retry429(delay)
        return resp

    async def search(self, **_: Any) -> list[dict[str, Any]]:
        client = await self._get_client()
        try:
            try:
                resp = await self._post(client)
            except _Retry429:
                logger.warning("Hirist retries exhausted")
                return []
            except Exception as e:
                logger.error("Hirist request failed: {}", e)
                return []
            if resp.status_code == 404:
                logger.info("Hirist 404 — skip")
                return []
            if resp.status_code != 200:
                logger.warning("Hirist HTTP {} — skip", resp.status_code)
                return []
            try:
                payload = resp.json()
            except Exception:
                logger.warning("Hirist non-JSON response")
                return []
            jobs = _parse_jobs(payload if isinstance(payload, dict) else {})
            logger.info("Hirist: {} jobs", len(jobs))
            return jobs
        finally:
            if self._owns_client and self._client is not None:
                pass

    async def __aenter__(self):
        await self._get_client()
        return self

    async def __aexit__(self, *a):
        await self.close()
