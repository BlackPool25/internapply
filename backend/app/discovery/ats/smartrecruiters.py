"""SmartRecruiters ATS — api.smartrecruiters.com."""
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

class SmartRecruitersDiscovery:
    source_ats = "smartrecruiters"

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
                if b.get("ats_type") and b.get("ats_type") != "smartrecruiters":
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
                url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset=0"
                data = await _h.fetch_json(client, url)
                if data is None:
                    continue
                # SmartRecruiters shape: {"content": [...], "totalFound": N} or {"data": [...]} or list
                postings: list[dict] = []
                total_found = None
                if isinstance(data, dict):
                    if "content" in data:
                        postings = data.get("content") or []
                        total_found = data.get("totalFound")
                    elif "data" in data:
                        postings = data.get("data") or []
                        total_found = data.get("totalFound")
                    elif "postings" in data:
                        postings = data.get("postings") or []
                    else:
                        # ambiguous 200-empty: if empty array with no totalFound, treat as dead
                        if not data:
                            continue
                        # sometimes dict with no known keys
                        postings = []
                elif isinstance(data, list):
                    postings = data
                # handle 200-empty ambiguous → dead vs valid: if empty array with no totalFound, treat as dead (skip)
                if not postings:
                    if total_found is None:
                        # try to detect if data was {"content":[]} without totalFound vs valid empty
                        # per spec: empty array with no totalFound -> dead, already skipped
                        continue
                    if total_found == 0:
                        continue
                    # totalFound present but 0 => dead
                    continue
                for j in postings:
                    title = j.get("name") or j.get("title") or ""
                    company = j.get("company") or {}
                    if isinstance(company, dict):
                        company = company.get("name") or slug
                    else:
                        company = str(company) if company else slug
                    # location: location.city + country or location.fullLocation
                    loc_obj = j.get("location") or j.get("locationName") or {}
                    location = ""
                    if isinstance(loc_obj, dict):
                        location = loc_obj.get("city") or loc_obj.get("fullLocation") or loc_obj.get("country") or loc_obj.get("region") or ""
                        # fallback to stringified
                        if not location:
                            location = str(loc_obj.get("city") or loc_obj.get("country") or "")
                    elif isinstance(loc_obj, str):
                        location = loc_obj
                    # also check workplace
                    if not location:
                        location = j.get("workplaceType") or ""
                    if not tit_re.search(title or ""):
                        continue
                    if not loc_re.search(str(location) or ""):
                        continue
                    desc_html = j.get("jobAd") or j.get("description") or j.get("content") or ""
                    # jobAd may be dict with sections
                    if isinstance(desc_html, dict):
                        desc_html = desc_html.get("sections") or desc_html.get("text") or str(desc_html)
                        if isinstance(desc_html, list):
                            parts = []
                            for s in desc_html:
                                if isinstance(s, dict):
                                    parts.append(s.get("text") or s.get("title") or "")
                                else:
                                    parts.append(str(s))
                            desc_html = " ".join(parts)
                    description = _html_to_text(str(desc_html)) if "<" in str(desc_html) else str(desc_html)
                    url_j = j.get("ref") or j.get("applyUrl") or j.get("url") or f"https://jobs.smartrecruiters.com/{slug}/{j.get('id','')}"
                    source_id = str(j.get("id") or j.get("uuid") or url_j)
                    cid = canonical_id(str(company), str(title), str(location), source_id)
                    jh = jd_hash({"title": title, "company": company, "location": location, "description": description})
                    sh = simhash64(f"{url_j} {title}")
                    # cursor = max(updated_at or posted_date) fallback
                    updated_at = j.get("updatedOn") or j.get("updated_at") or j.get("releasedDate") or j.get("createdOn") or j.get("created_at") or j.get("posted_date") or ""
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
                        "posted_date": j.get("releasedDate") or j.get("createdOn") or "",
                    })
        if results and cursor_candidates:
            max_cur = max(cursor_candidates)
            for r in results:
                if not r.get("cursor"):
                    r["cursor"] = max_cur
        return results

async def search(boards, location_filter=None, title_filter=None):
    return await SmartRecruitersDiscovery().search(boards, location_filter, title_filter)
