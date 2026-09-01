"""Internshala Freelance XHR — reuse XHR with jobType=freelance (student-native 8/10)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from backend.app.discovery.hash_utils import canonical_id, jd_hash, simhash64
from backend.app.discovery.internshala_xhr import _parse_fragment, XHR_HEADERS

# Internshala freelance: same XHR endpoint, freelance filter
FREELANCE_XHR_URL = "https://internshala.com/freelance/ajax"
# fallback: internships ajax with freelance param
ALT_URL = "https://internshala.com/internships/ajax?jobType=freelance"


class InternshalaFreelanceDiscovery:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self._owns = client is None

    async def _get(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        self._client = httpx.AsyncClient(timeout=15.0)
        self._owns = True
        return self._client

    async def close(self):
        if self._client and self._owns:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def search(self, **_: Any) -> list[dict[str, Any]]:
        client = await self._get()
        html = ""
        # try freelance ajax first, then alt
        for url in (FREELANCE_XHR_URL, ALT_URL):
            try:
                resp = await client.get(url, headers=XHR_HEADERS)
            except Exception as e:
                logger.warning("Internshala freelance XHR {} failed: {}", url, e)
                continue
            if resp.status_code != 200:
                logger.debug("Internshala freelance {} HTTP {} skip", url, resp.status_code)
                continue
            try:
                payload = resp.json()
                if isinstance(payload, dict):
                    html = payload.get("html") or payload.get("data") or payload.get("content") or ""
                    if isinstance(html, dict):
                        html = html.get("html") or ""
                elif isinstance(payload, str):
                    html = payload
            except Exception:
                html = resp.text
            if not html:
                html = resp.text
            if html and "individual_internship" in html:
                break
        if not html:
            return []
        cards = _parse_fragment(html)
        # freelance cards may 404 due to /freelance/ url prefix — fix url if needed and retry parse directly
        if not cards and html:
            # parse freelance-prefixed cards manually
            soup = BeautifulSoup(html, "html.parser")
            raw_cards = soup.find_all("div", class_="individual_internship")
            if not raw_cards:
                import re as _re
                raw_cards = soup.find_all("div", class_=_re.compile(r"individual_internship"))
            for card in raw_cards:
                url = None
                for a in card.find_all("a", href=True):
                    href = a["href"]
                    if href.startswith(("/internship/", "/job/", "/freelance/")):
                        url = urljoin("https://internshala.com", href)
                        break
                if not url:
                    continue
                title = ""
                for sel in ["h3", "h4", ".heading_4_5", ".profile", "a"]:
                    el = card.select_one(sel)
                    if el and el.get_text(strip=True) and len(el.get_text(strip=True)) >= 3:
                        title = el.get_text(strip=True)
                        break
                if not title:
                    txt = [t.strip() for t in card.get_text("\n", strip=True).split("\n") if t.strip()]
                    if txt:
                        title = txt[0]
                if not title or len(title) < 3:
                    continue
                company = ""
                for cls in ["company_name", "company-name", ".link_display_like_text"]:
                    el = card.select_one(f".{cls}") if "." not in cls else card.select_one(cls)
                    if el and el.get_text(strip=True):
                        company = el.get_text(strip=True)
                        break
                if not company:
                    parts = [p.strip() for p in card.get_text("\n", strip=True).split("\n") if p.strip()]
                    if len(parts) > 1:
                        company = parts[1]
                location = ""
                loc_el = card.select_one(".location_link, .locations, [class*=location]")
                if loc_el:
                    location = loc_el.get_text(strip=True)
                cards.append({"title": title, "company": company, "location": location, "stipend_raw": "", "posted_date": "", "url": url})
        out: list[dict[str, Any]] = []
        for c in cards:
            cid = canonical_id(c["company"], c["title"], c["location"], c["url"])
            jd = jd_hash({"title": c["title"], "company": c["company"], "location": c["location"], "description": ""})
            sh = simhash64(f"{c['title']} {c['company']}")
            out.append({**c, "description": "", "source_ats": "internshala_freelance", "canonical_id": cid, "jd_hash": jd, "simhash": sh})
        logger.info("Internshala freelance XHR: {} jobs", len(out))
        return out

    async def fetch(self, keyword: str = "devops", **kw: Any) -> list[dict[str, Any]]:
        return await self.search(keyword=keyword, **kw)

    async def __aenter__(self):
        await self._get()
        return self
    async def __aexit__(self, *a):
        await self.close()
