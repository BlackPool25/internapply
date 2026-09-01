"""Greenhouse ATS — boards-api.greenhouse.io."""
from __future__ import annotations

import re
from typing import Any

from . import _http as _h  # Retry-After handled via _http.fetch_json (tenacity clamp max_wait=30 + jitter)

try:
    from backend.app.discovery.hash_utils import canonical_id, jd_hash, simhash64
except ImportError:
    from backend.app.discovery.hash_utils import canonical_id, jd_hash, simhash64  # type: ignore

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None  # type: ignore

def _html_to_text(html: str) -> str:
    if not html:
        return ""
    if BeautifulSoup is not None:
        try:
            return BeautifulSoup(html, "html.parser").get_text(separator=" ")
        except Exception:
            pass
    return re.sub(r"<[^>]+>", " ", html)

def _cursor_val(job: dict) -> str | None:
    # updated_at or created_at fallback, also handle camelCase
    for k in ("updated_at", "updatedAt", "created_at", "createdAt", "posted_date", "absolute_url"):
        v = job.get(k)
        if v:
            return str(v)
    # location updated_at inside?
    return None

def _extract_jobs(payload: Any, slug: str) -> list[dict]:
    if isinstance(payload, dict) and "jobs" in payload:
        return payload.get("jobs") or []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "data" in payload:
        return payload.get("data") or []
    return []

async def _fetch_board(client, slug: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    data = await _h.fetch_json(client, url)
    if data is None:
        return []
    return _extract_jobs(data, slug)

class GreenhouseDiscovery:
    source_ats = "greenhouse"

    async def search(
        self,
        boards: list[dict] | list[str] | None = None,
        location_filter: str | None = None,
        title_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        # config-driven only — caller passes boards; if None try config
        if boards is None:
            try:
                from backend.app.config import settings
                boards = settings.ats_boards
            except Exception:
                boards = []
        # normalize board slugs
        slugs: list[str] = []
        for b in boards:
            if isinstance(b, str):
                slugs.append(b)
            elif isinstance(b, dict):
                s = b.get("slug")
                if s:
                    slugs.append(str(s))
        # compile filters or use defaults
        loc_re = re.compile(location_filter, re.I) if location_filter else _h.LOCATION_RE
        tit_re = re.compile(title_filter, re.I) if title_filter else _h.TITLE_RE

        results: list[dict[str, Any]] = []
        cursor_candidates: list[str] = []
        async with _h.make_client() as client:
            for slug in slugs:
                jobs = await _fetch_board(client, slug)
                for j in jobs:
                    title = j.get("title") or j.get("name") or ""
                    company = j.get("company_name") or (j.get("company") or {}).get("name") if isinstance(j.get("company"), dict) else j.get("company") or slug
                    if isinstance(company, dict):
                        company = company.get("name") or slug
                    location = ""
                    loc_obj = j.get("location") or j.get("location_name") or j.get("offices") or ""
                    if isinstance(loc_obj, dict):
                        location = loc_obj.get("name") or loc_obj.get("location") or ""
                    elif isinstance(loc_obj, list) and loc_obj:
                        # Greenhouse offices is list
                        first = loc_obj[0]
                        if isinstance(first, dict):
                            location = first.get("name") or first.get("location") or ""
                        else:
                            location = str(first)
                    else:
                        location = str(loc_obj) if loc_obj else ""
                    # client-side filtering
                    if not tit_re.search(title or ""):
                        continue
                    if not loc_re.search(location or ""):
                        continue
                    content_html = j.get("content") or j.get("description") or j.get("absolute_url") or ""
                    # content may be html
                    description = _html_to_text(str(content_html)) if "<" in str(content_html) else str(content_html or "")
                    # url
                    url = j.get("absolute_url") or j.get("url") or f"https://boards.greenhouse.io/{slug}/jobs/{j.get('id','')}"
                    source_id = str(j.get("id") or j.get("internal_job_id") or url)
                    cid = canonical_id(str(company), str(title), str(location), source_id)
                    jh = jd_hash({"title": title, "company": company, "location": location, "description": description})
                    sh = simhash64(f"{url} {title}")
                    # cursor = max(updated_at or posted_date) fallback
                    updated_at = j.get("updated_at") or j.get("updatedAt") or j.get("created_at") or j.get("createdAt") or j.get("posted_date") or ""
                    updated_at = str(updated_at) if updated_at else ""
                    if updated_at:
                        cursor_candidates.append(updated_at)
                    # fallback if none yet: use updated_at or empty
                    cursor = updated_at
                    job_dict: dict[str, Any] = {
                        "canonical_id": cid,
                        "jd_hash": jh,
                        "simhash": sh,
                        "title": title,
                        "company": company,
                        "location": location,
                        "description": description,
                        "url": url,
                        "source_ats": self.source_ats,
                        "source_id": source_id,
                        "cursor": cursor,
                        "updated_at": updated_at,
                        "posted_date": j.get("created_at") or j.get("createdAt") or "",
                    }
                    results.append(job_dict)
        # normalize cursor to max value lexicographically (ISO8601) — caller can compute max
        if results and cursor_candidates:
            max_cur = max(cursor_candidates)
            for r in results:
                if not r.get("cursor"):
                    r["cursor"] = max_cur
        return results

# module-level function for task spec
async def search(boards, location_filter=None, title_filter=None):
    return await GreenhouseDiscovery().search(boards, location_filter, title_filter)
