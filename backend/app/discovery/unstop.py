"""Unstop discovery — GET unstop.com/api/public/opportunity/search-result."""

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

UNSTOP_URL = "https://unstop.com/api/public/opportunity/search-result"
UNSTOP_PARAMS = {"opportunity": "all", "page": 1, "per_page": 50, "searchTerm": "devops"}
UNSTOP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://unstop.com/",
}


class _Retry429(Exception):
    def __init__(self, retry_after: float = 1.0):
        self.retry_after = min(retry_after, 30.0)
        super().__init__(f"429 {self.retry_after}")


def _is_retryable(e: BaseException) -> bool:
    return isinstance(e, _Retry429)


def _parse_unstop(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: Any = payload.get("data") or payload.get("opportunities") or payload.get("results") or []
    if isinstance(items, dict):
        items = items.get("data") or items.get("opportunities") or []
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        oid = str(it.get("id") or it.get("opportunity_id") or it.get("_id") or "")
        title = str(it.get("title") or it.get("opportunity_name") or it.get("name") or "").strip()
        company = str(it.get("organisation") or it.get("organization") or it.get("company") or it.get("org_name") or "").strip()
        if isinstance(company, dict):
            company = str(company.get("name") or "")
        location = str(it.get("location") or it.get("city") or it.get("region") or "").strip()
        desc = str(it.get("description") or it.get("details") or it.get("about") or "")
        stipend = str(it.get("stipend") or it.get("stipend_raw") or it.get("rewards") or it.get("prize") or "")
        url = str(it.get("url") or it.get("public_url") or (f"https://unstop.com/p/{oid}" if oid else ""))
        if not title and not oid:
            continue
        cid = canonical_id(company, title, location, oid or url)
        jd = jd_hash({"title": title, "company": company, "location": location, "description": desc})
        sh = simhash64(f"{title} {company} {desc[:500]}")
        out.append({
            "title": title, "company": company, "location": location,
            "description": desc, "stipend_raw": stipend,
            "url": url, "source_job_id": oid, "source_ats": "unstop",
            "canonical_id": cid, "jd_hash": jd, "simhash": sh,
        })
    return out


class UnstopDiscovery:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self._owns = client is None

    async def _get(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        self._client = httpx.AsyncClient(timeout=15.0)
        self._owns = True
        return self._client

    async def close(self) -> None:
        if self._client and self._owns:
            await self._client.aclose()
            self._client = None

    @retry(retry=retry_if_exception(_is_retryable), stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=0.5, max=30), reraise=True)
    async def _get_resp(self, client: httpx.AsyncClient) -> httpx.Response:
        resp = await client.get(UNSTOP_URL, params=UNSTOP_PARAMS, headers=UNSTOP_HEADERS)
        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After") or "1"
            try:
                d = float(ra)
            except ValueError:
                d = 1.0
            raise _Retry429(min(d, 30.0))
        return resp

    async def search(self, **_: Any) -> list[dict[str, Any]]:
        client = await self._get()
        try:
            try:
                resp = await self._get_resp(client)
            except _Retry429:
                logger.warning("Unstop 429 retries exhausted")
                return []
            except Exception as e:
                logger.error("Unstop request failed: {}", e)
                return []
            if resp.status_code == 404:
                logger.info("Unstop 404 — skip")
                return []
            if resp.status_code != 200:
                logger.warning("Unstop HTTP {} — skip", resp.status_code)
                return []
            try:
                payload = resp.json()
            except Exception:
                logger.warning("Unstop non-JSON")
                return []
            jobs = _parse_unstop(payload if isinstance(payload, dict) else {})
            logger.info("Unstop: {} jobs", len(jobs))
            return jobs
        finally:
            pass

    async def __aenter__(self):
        await self._get()
        return self

    async def __aexit__(self, *a):
        await self.close()
