"""Lever ATS — api.lever.co."""
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

class LeverDiscovery:
    source_ats = "lever"

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
                if b.get("ats_type") and b.get("ats_type") != "lever":
                    continue
                s = b.get("slug")
                if s:
                    slugs.append(str(s))
        # if boards contain mix, we still handle lever slugs only — but if spec passes filtered boards, fine
        # fallback: if no slugs after filter, use all
        if not slugs and boards:
            # boards were pre-filtered by caller, respect them
            slugs = [str(b.get("slug")) for b in boards if isinstance(b, dict) and b.get("slug")]  # type: ignore
        loc_re = re.compile(location_filter, re.I) if location_filter else _h.LOCATION_RE
        tit_re = re.compile(title_filter, re.I) if title_filter else _h.TITLE_RE

        results: list[dict[str, Any]] = []
        cursor_candidates: list[str] = []
        async with _h.make_client() as client:
            for slug in slugs:
                skip = 0
                limit = 100
                while True:
                    url = f"https://api.lever.co/v0/postings/{slug}?mode=json&skip={skip}&limit={limit}"
                    data = await _h.fetch_json(client, url)
                    if data is None:
                        break
                    # Lever returns list or dict with data
                    postings: list[dict] = []
                    has_more = False
                    if isinstance(data, list):
                        postings = data
                    elif isinstance(data, dict):
                        postings = data.get("data") or data.get("postings") or []
                        # handle paginated if response has hasMore
                        has_more = bool(data.get("hasMore") or data.get("hasNext"))
                        if not postings and isinstance(data.get("data"), list):
                            postings = data["data"]
                    if not postings:
                        break
                    for j in postings:
                        title = j.get("text") or j.get("title") or j.get("name") or ""
                        # Lever company is slug
                        company = j.get("company") or slug
                        # location: categories.location or location
                        location = j.get("workplaceType") or ""
                        cat = j.get("categories") or {}
                        loc2 = cat.get("location") if isinstance(cat, dict) else ""
                        if loc2:
                            location = f"{location} {loc2}".strip()
                        if not location:
                            location = j.get("location") or ""
                        if isinstance(location, dict):
                            location = location.get("name") or ""
                        if not tit_re.search(title or ""):
                            continue
                        if not loc_re.search(location or ""):
                            continue
                        desc_html = j.get("description") or j.get("descriptionPlain") or j.get("content") or ""
                        description = _html_to_text(str(desc_html)) if "<" in str(desc_html) else str(desc_html)
                        # compensation if present
                        comp = j.get("salaryDescription") or j.get("compensation") or ""
                        if comp:
                            description = f"{description} {comp}".strip()
                        url_j = j.get("hostedUrl") or j.get("applyUrl") or j.get("url") or f"https://jobs.lever.co/{slug}/{j.get('id','')}"
                        source_id = str(j.get("id") or j.get(" Lever") or url_j)
                        cid = canonical_id(str(company), str(title), str(location), source_id)
                        jh = jd_hash({"title": title, "company": company, "location": location, "description": description})
                        sh = simhash64(f"{url_j} {title}")
                        updated_at = j.get("updatedAt") or j.get("updated_at") or j.get("createdAt") or j.get("created_at") or j.get("postedAt") or ""
                        updated_at = str(updated_at) if updated_at else ""
                        if updated_at:
                            cursor_candidates.append(updated_at)
                        results.append({
                            "canonical_id": cid,
                            "jd_hash": jh,
                            "simhash": sh,
                            "title": title,
                            "company": company,
                            "location": str(location),
                            "description": description,
                            "url": url_j,
                            "source_ats": self.source_ats,
                            "source_id": source_id,
                            "cursor": updated_at,
                            "updated_at": updated_at,
                            "posted_date": j.get("createdAt") or j.get("created_at") or "",
                        })
                    if not has_more:
                        break
                    skip += limit
                    if skip > 500:
                        break
        if results and cursor_candidates:
            max_cur = max(cursor_candidates)
            for r in results:
                if not r.get("cursor"):
                    r["cursor"] = max_cur
        return results

async def search(boards, location_filter=None, title_filter=None):
    return await LeverDiscovery().search(boards, location_filter, title_filter)
