"""Ashby ATS — api.ashbyhq.com."""
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

class AshbyDiscovery:
    source_ats = "ashby"

    async def search(
        self,
        boards: list[dict] | list[str] | None = None,
        location_filter: str | None = None,
        title_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        if boards is None:
            try:
                from backend.app.config import settings
                boards = settings.ats_boards
            except Exception:
                boards = []
        slugs: list[str] = []
        for b in boards:
            if isinstance(b, str):
                slugs.append(b)
            elif isinstance(b, dict):
                if b.get("ats_type") and b.get("ats_type") != "ashby":
                    continue
                s = b.get("slug")
                if s:
                    slugs.append(str(s))
        if not slugs and boards:
            slugs = [str(b.get("slug")) for b in boards if isinstance(b, dict) and b.get("slug")]  # type: ignore
        loc_re = re.compile(location_filter, re.I) if location_filter else _h.LOCATION_RE
        tit_re = re.compile(title_filter, re.I) if title_filter else _h.TITLE_RE

        results: list[dict[str, Any]] = []
        cursor_candidates: list[str] = []
        async with _h.make_client() as client:
            for slug in slugs:
                # includeCompensation flag required per spec
                url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
                data = await _h.fetch_json(client, url)
                if data is None:
                    continue
                # Ashby shape: {"jobs": [...]} or {"data": [...]} or {"postings": [...]}
                jobs: list[dict] = []
                if isinstance(data, dict):
                    jobs = data.get("jobs") or data.get("data") or data.get("postings") or []
                    if not jobs and isinstance(data.get("jobBoard"), dict):
                        jobs = data["jobBoard"].get("jobs") or []
                elif isinstance(data, list):
                    jobs = data
                for j in jobs:
                    title = j.get("title") or j.get("name") or ""
                    company = j.get("companyName") or j.get("company") or slug
                    if isinstance(company, dict):
                        company = company.get("name") or slug
                    location = j.get("location") or j.get("locationName") or j.get("workplaceType") or ""
                    if isinstance(location, dict):
                        location = location.get("name") or ""
                    if isinstance(location, list):
                        location = ", ".join(str(x.get("name") if isinstance(x, dict) else x) for x in location)
                    if not tit_re.search(title or ""):
                        continue
                    if not loc_re.search(str(location) or ""):
                        continue
                    desc_html = j.get("descriptionHtml") or j.get("description") or j.get("content") or j.get("jobDescription") or ""
                    description = _html_to_text(str(desc_html)) if "<" in str(desc_html) else str(desc_html)
                    comp = j.get("compensation") or j.get("compensationBand") or j.get("salaryRange") or ""
                    if comp:
                        if isinstance(comp, dict):
                            comp = str(comp.get("summary") or comp.get("display") or comp)
                        description = f"{description} {comp}".strip()
                    url_j = j.get("jobUrl") or j.get("url") or j.get("applyUrl") or j.get("hostedUrl") or f"https://jobs.ashbyhq.com/{slug}/{j.get('id','')}"
                    source_id = str(j.get("id") or j.get("jobId") or url_j)
                    cid = canonical_id(str(company), str(title), str(location), source_id)
                    jh = jd_hash({"title": title, "company": company, "location": location, "description": description})
                    sh = simhash64(f"{url_j} {title}")
                    updated_at = j.get("updatedAt") or j.get("updated_at") or j.get("publishedAt") or j.get("published_at") or j.get("createdAt") or j.get("created_at") or j.get("postedAt") or j.get("posted_date") or ""
                    updated_at = str(updated_at) if updated_at else ""
                    if updated_at:
                        cursor_candidates.append(updated_at)
                    results.append({
                        "canonical_id": cid,
                        "jd_hash": jh,
                        "simhash": sh,
                        "title": title,
                        "company": str(company),
                        "location": str(location),
                        "description": description,
                        "url": url_j,
                        "source_ats": self.source_ats,
                        "source_id": source_id,
                        "cursor": updated_at,
                        "updated_at": updated_at,
                        "posted_date": j.get("publishedAt") or j.get("createdAt") or "",
                    })
        if results and cursor_candidates:
            max_cur = max(cursor_candidates)
            for r in results:
                if not r.get("cursor"):
                    r["cursor"] = max_cur
        return results

async def search(boards, location_filter=None, title_filter=None):
    return await AshbyDiscovery().search(boards, location_filter, title_filter)
