"""Upwork webhook receiver — VOLLNA_RSS_URL gated (RSS dead 2024).

Never scrape Upwork direct — use Vollna/tryvibeworker webhook only if VOLLNA_RSS_URL set.
Direct RSS deprecated Aug 2024 per support article; webhook else skip.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from loguru import logger

from backend.app.discovery.hash_utils import jd_hash

# Fiverr passive (set once no poll) + Toptal/Turing skipped (vetting gate) — documented in README snippet below.
# See evidence file for README snippet.


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


def handle_upwork_webhook(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Handle Vollna/tryvibeworker webhook POST {title,budget,skills}.

    Returns job dict with source_ats=upwork_wrapper or None if skipped.
    Checks VOLLNA_RSS_URL env — if not set, logs skip and returns None.
    """
    vollna_url = os.getenv("VOLLNA_RSS_URL", "")
    # also check config
    if not vollna_url:
        for mod in ("internapply.config", "backend.app.config"):
            try:
                m = __import__(mod, fromlist=["settings", "get_config"])
                if hasattr(m, "settings"):
                    vollna_url = str(getattr(m.settings, "VOLLNA_RSS_URL", "") or "")
                elif hasattr(m, "get_config"):
                    vollna_url = str(getattr(m.get_config(), "VOLLNA_RSS_URL", "") or "")
                if vollna_url:
                    break
            except Exception:
                continue
    if not vollna_url:
        logger.info("Upwork webhook skipped — VOLLNA_RSS_URL not set (RSS dead 2024, webhook only if configured)")
        return None
    logger.info("Upwork webhook via VOLLNA_RSS_URL={} payload title={}", vollna_url[:40], payload.get("title", "")[:60])

    title = str(payload.get("title") or payload.get("job_title") or "").strip()
    budget = str(payload.get("budget") or payload.get("rate") or "").strip()
    skills = payload.get("skills") or payload.get("tags") or ""
    if isinstance(skills, list):
        skills = ", ".join(str(s) for s in skills)
    skills = str(skills)
    link = str(payload.get("url") or payload.get("link") or "")
    project_id = str(payload.get("id") or payload.get("project_id") or title[:80] or "upwork")
    canonical = hashlib.sha256(f"{_salt()}{project_id}".encode()).hexdigest()
    jd = jd_hash(f"{title} {budget} {skills}")
    return {
        "project_id": project_id,
        "title": title or "Untitled",
        "company": str(payload.get("company") or "Upwork"),
        "location": "Remote",
        "budget": budget,
        "skills": skills,
        "description": str(payload.get("description") or ""),
        "url": link,
        "link": link,
        "source_ats": "upwork_wrapper",
        "canonical_id": canonical,
        "jd_hash": jd,
    }


# Optional FastAPI router — only if FastAPI available
try:
    from fastapi import APIRouter, Request

    router = APIRouter()

    @router.post("/webhooks/upwork")
    async def upwork_webhook_endpoint(request: Request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        result = handle_upwork_webhook(payload if isinstance(payload, dict) else {})
        if result is None:
            return {"status": "skipped", "reason": "VOLLNA_RSS_URL not set"}
        return {"status": "ok", "job": result}
except ImportError:
    router = None  # type: ignore
