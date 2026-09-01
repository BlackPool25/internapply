"""Freelancer RSS — GET freelancer.com/rss.xml hourly poll via arq cron.

Only living RSS per Freelancefeed (Upwork deprecated 2024, Guru removed).
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote

_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import httpx
from loguru import logger

from backend.app.discovery.hash_utils import jd_hash

DEFAULT_KEYWORDS = "devops docker kubernetes backend"
RSS_URL = "https://www.freelancer.com/rss.xml"


def _salt() -> str:
    for mod in ("internapply.config", "backend.app.config"):
        try:
            m = __import__(mod, fromlist=["settings", "get_config", "HASH_SALT"])
            if hasattr(m, "settings"):
                return str(getattr(m.settings, "HASH_SALT", "internapply-v1"))
            if hasattr(m, "get_config"):
                return str(m.get_config().HASH_SALT)
        except Exception:
            continue
    return os.getenv("HASH_SALT", "internapply-v1")


def _canonical_from_project_id(project_id: str) -> str:
    return hashlib.sha256(f"{_salt()}{project_id.strip()}".encode()).hexdigest()


_GUID_RE = re.compile(r"(\d{6,})")


def _extract_project_id(guid: str, link: str) -> str:
    for s in (guid, link):
        if not s:
            continue
        m = _GUID_RE.search(s)
        if m:
            return m.group(1)
        # fallback: last path segment
        seg = s.rstrip("/").split("/")[-1].split("?")[0]
        if seg.isdigit():
            return seg
    return (guid or link or "").strip() or "unknown"


def _parse_rss(xml_text: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    except ET.ParseError as e:
        logger.warning("Freelancer RSS parse error: {}", e)
        return []
    # find items — handle namespaces loosely
    items = root.findall(".//item")
    if not items:
        # try without namespace
        items = [el for el in root.iter() if el.tag.endswith("item")]
    out: list[dict[str, Any]] = []
    for it in items:
        def _t(tag: str) -> str:
            el = it.find(tag)
            if el is not None and el.text:
                return el.text.strip()
            # try namespace suffix
            for child in it:
                if child.tag.endswith(tag) and child.text:
                    return child.text.strip()
            return ""
        guid = _t("guid")
        link = _t("link")
        title = _t("title") or "Untitled"
        desc = _t("description") or ""
        # budget: try description or category
        budget = ""
        # description often contains budget text
        if desc:
            m = re.search(r"\$[\d,]+(?:\s*-\s*\$[\d,]+)?", desc)
            if m:
                budget = m.group(0)
        cat = _t("category")
        skills = cat or ""
        # also extract skills from description comma list heuristic
        project_id = _extract_project_id(guid, link)
        canonical_id = _canonical_from_project_id(project_id)
        jd = jd_hash(f"{title} {budget} {skills}")
        out.append({
            "project_id": project_id,
            "title": title,
            "company": "Freelancer",
            "location": "Remote",
            "budget": budget,
            "skills": skills,
            "description": desc,
            "url": link or guid,
            "link": link or guid,
            "source_ats": "freelancer_rss",
            "canonical_id": canonical_id,
            "jd_hash": jd,
        })
    return out


class FreelancerRSSDiscovery:
    """Hourly poll via arq cron — GET freelancer.com/rss.xml?keyword=..."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self._owns = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        self._client = httpx.AsyncClient(timeout=15.0, http2=False)
        self._owns = True
        return self._client

    async def close(self):
        if self._client and self._owns:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def fetch(self, keyword: str = "devops") -> list[dict[str, Any]]:
        kw = keyword or DEFAULT_KEYWORDS
        # encode keywords for rss
        q = quote(kw, safe="")
        # freelancer rss expects keyword param
        url = f"{RSS_URL}?keyword={q}"
        # if default multi-keywords not provided via single param, use encoded default
        if kw == DEFAULT_KEYWORDS:
            url = f"{RSS_URL}?keyword={quote(DEFAULT_KEYWORDS, safe='')}"
        client = await self._get_client()
        try:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        except Exception as e:
            logger.warning("Freelancer RSS fetch failed: {}", e)
            return []
        if resp.status_code != 200:
            logger.warning("Freelancer RSS HTTP {} skip", resp.status_code)
            return []
        jobs = _parse_rss(resp.text)
        logger.info("Freelancer RSS: {} projects for keyword={}", len(jobs), kw)
        return jobs

    # alias for orchestrator compatibility
    async def search(self, keyword: str = "devops", **_: Any) -> list[dict[str, Any]]:
        return await self.fetch(keyword=keyword)

    async def __aenter__(self):
        await self._get_client()
        return self
    async def __aexit__(self, *a):
        await self.close()
