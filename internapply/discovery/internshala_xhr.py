"""Internshala XHR fragment — GET internships ajax + BS4 fragment parse."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from internapply.discovery.hash_utils import canonical_id, jd_hash, simhash64

XHR_URL = "https://internshala.com/internships/ajax"
XHR_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://internshala.com",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


class _Retry429(Exception):
    def __init__(self, d: float = 1.0):
        self.retry_after = min(d, 30.0)
        super().__init__(f"429 {self.retry_after}")


def _is_retry(e: BaseException) -> bool:
    return isinstance(e, _Retry429)


def _parse_fragment_card(card) -> dict[str, Any] | None:
    """Fragment-specific: NOT legacy full-page extractor — handles missing stipend_raw etc."""
    # URL
    url = None
    for a in card.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("/internship/", "/job/")):
            url = urljoin("https://internshala.com", href)
            break
    if not url:
        return None
    # Title: look for heading / link text
    title = ""
    for sel in ["h3", "h4", ".heading_4_5", ".profile", "a"]:
        el = card.select_one(sel)
        if el and el.get_text(strip=True) and len(el.get_text(strip=True)) >= 3:
            title = el.get_text(strip=True)
            break
    if not title:
        txt = card.get_text("\n", strip=True).split("\n")
        txt = [t.strip() for t in txt if t.strip()]
        if txt:
            title = txt[0]
    if not title or len(title) < 3:
        return None
    # Company
    company = ""
    for cls in ["company_name", "company-name", ".link_display_like_text"]:
        el = card.select_one(f".{cls}") if "." not in cls else card.select_one(cls)
        if el and el.get_text(strip=True):
            company = el.get_text(strip=True)
            break
    if not company:
        # fallback: second non-empty line
        parts = [p.strip() for p in card.get_text("\n", strip=True).split("\n") if p.strip()]
        if len(parts) > 1:
            company = parts[1]
    # Location
    location = ""
    loc_el = card.select_one(".location_link, .locations, [class*=location]")
    if loc_el:
        location = loc_el.get_text(strip=True)
    if not location:
        for p in card.get_text("\n", strip=True).split("\n"):
            pl = p.lower().strip()
            if any(k in pl for k in ["remote", "bangalore", "bengaluru", "mumbai", "delhi", "work from home"]):
                location = p.strip()
                break
    # Stipend — fragment may omit or format differently
    stipend_raw = ""
    stip_el = card.select_one(".stipend, [class*=stipend]")
    if stip_el:
        stipend_raw = stip_el.get_text(strip=True)
    if not stipend_raw:
        import re
        for p in card.get_text("\n", strip=True).split("\n"):
            if "₹" in p or re.search(r"\d{3,}.*month", p, re.I):
                stipend_raw = p.strip()
                break
    # Posted
    posted = ""
    import re
    for p in card.get_text("\n", strip=True).split("\n"):
        if re.search(r"today|yesterday|\d+\s*days?\s*ago", p, re.I):
            posted = p.strip()
            break
    return {"title": title, "company": company, "location": location, "stipend_raw": stipend_raw, "posted_date": posted, "url": url}


def _parse_fragment(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("div", class_="individual_internship")
    if not cards:
        # fallback regex class
        import re
        cards = soup.find_all("div", class_=re.compile(r"individual_internship"))
    out: list[dict[str, Any]] = []
    for c in cards:
        try:
            d = _parse_fragment_card(c)
            if d:
                out.append(d)
        except Exception:
            continue
    return out


class InternshalaXhrDiscovery:
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
            await self._client.aclose()
            self._client = None

    @retry(retry=retry_if_exception(_is_retry), stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=0.5, max=30), reraise=True)
    async def _get_resp(self, client: httpx.AsyncClient) -> httpx.Response:
        resp = await client.get(XHR_URL, headers=XHR_HEADERS)
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
                logger.warning("Internshala XHR 429 retries exhausted")
                return []
            except Exception as e:
                logger.error("Internshala XHR failed: {}", e)
                return []
            if resp.status_code == 404:
                logger.info("Internshala XHR 404 — skip")
                return []
            if resp.status_code == 403:
                logger.warning("Internshala XHR 403 — possible bot block, skip (low volume no anti-bot)")
                return []
            if resp.status_code != 200:
                logger.warning("Internshala XHR HTTP {} skip", resp.status_code)
                return []
            # JSON with html fragment or raw html
            html = ""
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
            cards = _parse_fragment(html)
            out: list[dict[str, Any]] = []
            for c in cards:
                cid = canonical_id(c["company"], c["title"], c["location"], c["url"])
                jd = jd_hash({"title": c["title"], "company": c["company"], "location": c["location"], "description": ""})
                sh = simhash64(f"{c['title']} {c['company']}")
                out.append({**c, "description": "", "source_ats": "internshala", "canonical_id": cid, "jd_hash": jd, "simhash": sh})
            logger.info("Internshala XHR: {} jobs", len(out))
            return out
        finally:
            pass

    async def __aenter__(self):
        await self._get()
        return self

    async def __aexit__(self, *a):
        await self.close()
InternshalaXHRDiscovery = InternshalaXhrDiscovery
