"""Pipeline nodes — truncated to discover→filter→save (no LLM in batch)."""

from __future__ import annotations

import copy
import time
from typing import Any

from loguru import logger

from internapply.pipeline.state import PipelineState

_MOCK_JOBS: list[dict[str, Any]] = [
    {
        "title": "Python Backend Intern",
        "company": "TechCorp",
        "location": "Remote",
        "stipend_min": 15000,
        "stipend_max": 25000,
        "stipend_raw": "₹15,000-25,000 /month",
        "skills": ["Python", "FastAPI", "PostgreSQL"],
        "description": "Build and maintain backend services using Python and FastAPI.",
        "source": "internshala",
        "source_ats": "internshala",
        "url": "https://internshala.com/internship/example-1",
        "canonical_id": "mock-canonical-1",
        "jd_hash": "mock-jd-1",
        "simhash": 123,
        "is_paid": True,
        "is_remote": True,
        "posted_at": "3 days ago",
        "posted_date": "2026-08-29",
        "updated_at": "2026-08-29T10:00:00Z",
        "cursor": "2026-08-29T10:00:00Z",
    },
    {
        "title": "Java Spring Boot Intern",
        "company": "FinServe",
        "location": "Bangalore",
        "stipend_min": 20000,
        "stipend_max": 30000,
        "stipend_raw": "₹20,000-30,000 /month",
        "skills": ["Java", "Spring Boot", "MySQL"],
        "description": "Develop microservices for banking platform using Java and Spring Boot.",
        "source": "naukri",
        "source_ats": "naukri",
        "url": "https://naukri.com/job/example-2",
        "canonical_id": "mock-canonical-2",
        "jd_hash": "mock-jd-2",
        "simhash": 456,
        "is_paid": True,
        "is_remote": False,
        "posted_at": "1 week ago",
        "posted_date": "2026-08-22",
        "updated_at": "2026-08-22T10:00:00Z",
        "cursor": "2026-08-22T10:00:00Z",
    },
]

_LLM_CALL_COUNT = 0


def _get_llm_count() -> int:
    return _LLM_CALL_COUNT


def _reset_llm_count() -> None:
    global _LLM_CALL_COUNT
    _LLM_CALL_COUNT = 0


def _log_stage(state: PipelineState, name: str) -> None:
    logger.info("━━━ Stage: {} ━━━", name)


def _log_completion(name: str, start: float, count: int, errors: int = 0) -> None:
    elapsed = time.monotonic() - start
    if errors:
        logger.info("Node '{}' finished in {:.2f}s — {} items, {} errors", name, elapsed, count, errors)
    else:
        logger.info("Node '{}' finished in {:.2f}s — {} items", name, elapsed, count)


def _cursor_for_job(job: dict[str, Any]) -> str:
    for k in ("updated_at", "last_seen_at", "posted_date", "cursor"):
        v = job.get(k)
        if v:
            return str(v)
    return ""


async def discover_jobs(state: PipelineState) -> dict[str, Any]:
    """Tiered discovery with seen_canonical_id dedup + cursor (no LLM)."""
    _log_stage(state, "discover")
    start = time.monotonic()

    if state.get("dry_run"):
        logger.info("[DRY RUN] Tiered discovery mock (ATS→Hirist→free→JobSpy→LinkedIn)")
        mock = copy.deepcopy(_MOCK_JOBS)
        max_cur = max((_cursor_for_job(j) for j in mock), default="")
        _log_completion("discover", start, len(mock))
        return {"jobs": mock, "job_listings": mock, "raw_jobs_count": len(mock), "stage": "discover", "_cursor_max_seen": max_cur}

    # live path: try ATS → Hirist → free APIs → JobSpy with seen_canonical_id
    all_jobs: list[dict[str, Any]] = []
    seen_canonical_id: set[str] = set()
    cursor_candidates: list[str] = []
    errors: list[str] = []

    def _add(jobs: list[dict[str, Any]]) -> None:
        for j in jobs:
            cid = j.get("canonical_id") or ""
            if not cid:
                try:
                    from internapply.discovery.hash_utils import canonical_id as _cid
                    cid = _cid(j.get("company",""), j.get("title",""), j.get("location",""), j.get("url") or j.get("source_job_id") or "")
                    j["canonical_id"] = cid
                except Exception:
                    continue
            if cid in seen_canonical_id:
                continue
            seen_canonical_id.add(cid)
            all_jobs.append(j)
            cur = _cursor_for_job(j)
            if cur:
                cursor_candidates.append(cur)

    # Tier0 ATS
    try:
        from backend.app.config import settings as _settings
        boards = []
        try:
            boards = _settings.ats_boards
        except Exception:
            boards = []
        from backend.app.discovery.ats.greenhouse import GreenhouseDiscovery
        from backend.app.discovery.ats.lever import LeverDiscovery
        from backend.app.discovery.ats.ashby import AshbyDiscovery
        from backend.app.discovery.ats.smartrecruiters import SmartRecruitersDiscovery
        for Cls in (GreenhouseDiscovery, LeverDiscovery, AshbyDiscovery, SmartRecruitersDiscovery):
            try:
                jobs = await Cls().search(boards=boards)
                _add(jobs if isinstance(jobs, list) else [])
            except Exception as exc:
                errors.append(f"Tier0 {Cls.__name__} failed: {exc}")
    except Exception as exc:
        errors.append(f"Tier0 failed: {exc}")

    # Tier1 Hirist/Unstop/Internshala XHR
    for _name, _mod, _cls in [
        ("hirist", "backend.app.discovery.hirist", "HiristDiscovery"),
        ("unstop", "backend.app.discovery.unstop", "UnstopDiscovery"),
        ("internshala", "backend.app.discovery.internshala_xhr", "InternshalaXhrDiscovery"),
    ]:
        try:
            import importlib
            m = importlib.import_module(_mod)
            Cls = getattr(m, _cls)
            disc = Cls()
            jobs = await disc.search()
            try:
                await disc.close()  # type: ignore
            except Exception:
                pass
            _add(jobs if isinstance(jobs, list) else [])
        except Exception as exc:
            errors.append(f"Tier1 {_name} failed: {exc}")

    # Tier3 free APIs
    try:
        from backend.app.discovery.free_apis import FreeAPIsDiscovery
        disc = FreeAPIsDiscovery()
        jobs = await disc.search()
        try:
            await disc.close()
        except Exception:
            pass
        _add(jobs if isinstance(jobs, list) else [])
    except Exception as exc:
        errors.append(f"Tier3 free APIs failed: {exc}")

    # Tier2 JobSpy Naukri/Indeed + LinkedIn overflow (breaker respected)
    try:
        from backend.app.discovery.jobspy_linkedin import JobSpyLinkedInDiscovery
        jobs = await JobSpyLinkedInDiscovery().search(search_term="DevOps intern", location="Bangalore", hours_old=24)
        _add(jobs if isinstance(jobs, list) else [])
    except Exception as exc:
        errors.append(f"Tier2 JobSpy failed: {exc}")

    max_seen = max(cursor_candidates) if cursor_candidates else ""
    _log_completion("discover", start, len(all_jobs), len(errors))
    result: dict[str, Any] = {"jobs": all_jobs, "job_listings": all_jobs, "raw_jobs_count": len(all_jobs), "stage": "discover", "_cursor_max_seen": max_seen}
    if errors:
        result["errors"] = errors
    return result


async def filter_jobs(state: PipelineState) -> dict[str, Any]:
    """Dedup by canonical_id, no LLM."""
    _log_stage(state, "filter")
    start = time.monotonic()
    raw = state.get("jobs") or state.get("job_listings") or []
    if not raw:
        _log_completion("filter", start, 0)
        return {"jobs": [], "job_listings": [], "filtered_jobs_count": 0, "stage": "filter"}

    seen_canonical_id: set[str] = set()
    filtered: list[dict[str, Any]] = []
    for job in raw:
        cid = job.get("canonical_id") or ""
        if cid:
            if cid in seen_canonical_id:
                continue
            seen_canonical_id.add(cid)
        filtered.append(job)
    _log_completion("filter", start, len(filtered))
    return {"jobs": filtered, "job_listings": filtered, "filtered_jobs_count": len(filtered), "stage": "filter"}


async def save_jobs(state: PipelineState) -> dict[str, Any]:
    """Persist via canonical_id dedup, jd_hash gate, change_log (no LLM)."""
    _log_stage(state, "save")
    start = time.monotonic()
    if state.get("dry_run"):
        _log_completion("save", start, 0)
        return {"stage": "save"}
    # live save reuses backend models if available; else no-op
    try:
        from backend.app.database import get_session, init_db
        from backend.app.models import JobListing as ORMJobListing
        from backend.app.discovery.hash_utils import diff_change_log
        from sqlalchemy import select
        from datetime import datetime, timezone
        from backend.app.config import settings
        await init_db(settings.database_url)
        async for session in get_session():
            for job in state.get("jobs", []) or state.get("job_listings", []):
                cid = job.get("canonical_id") or ""
                if not cid:
                    continue
                existing = await session.execute(select(ORMJobListing).where(ORMJobListing.canonical_id == cid))
                row = existing.scalar_one_or_none()
                if row is not None:
                    new_jd = job.get("jd_hash")
                    old_jd = row.jd_hash
                    if new_jd and old_jd and new_jd == old_jd:
                        # etag tiebreaker only if both present
                        new_etag = job.get("etag")
                        old_etag = row.etag
                        if new_etag and old_etag and new_etag != old_etag:
                            pass
                        try:
                            row.last_seen_at = datetime.now(timezone.utc)
                            await session.flush()
                        except Exception:
                            pass
                        continue
                    # jd differs → diff_change_log
                    try:
                        diff = diff_change_log({"title": row.title, "company": row.company, "location": row.location or "", "description": row.description or ""},
                                               {"title": job.get("title",""), "company": job.get("company",""), "location": job.get("location",""), "description": job.get("description","")})
                    except Exception:
                        diff = {"changed": True}
                    if not diff:
                        try:
                            row.last_seen_at = datetime.now(timezone.utc)
                            await session.flush()
                        except Exception:
                            pass
                        continue
                    try:
                        row.change_log = {**(row.change_log or {}), **diff, "at": datetime.now(timezone.utc).isoformat()}
                        if job.get("jd_hash"):
                            row.jd_hash = job["jd_hash"]
                        if job.get("simhash") is not None:
                            row.simhash = job["simhash"]
                        if job.get("description"):
                            row.description = job["description"]
                        row.last_seen_at = datetime.now(timezone.utc)
                        await session.flush()
                    except Exception:
                        pass
                    continue
                try:
                    orm = ORMJobListing(
                        title=job.get("title",""), company=job.get("company",""), location=job.get("location"),
                        description=job.get("description"), source=job.get("source") or job.get("source_ats") or "unknown",
                        url=job.get("url") or f"https://example.com/{cid[:8]}",
                        canonical_id=cid, jd_hash=job.get("jd_hash"), simhash=job.get("simhash"),
                        etag=job.get("etag"), change_log={}, source_ats=job.get("source_ats"),
                        last_seen_at=datetime.now(timezone.utc),
                    )
                    session.add(orm)
                    await session.flush()
                except Exception:
                    continue
    except Exception as exc:
        logger.warning("save_jobs failed: {}", exc)
    _log_completion("save", start, 0)
    return {"stage": "save"}


# Kept for skill only — not in auto pipeline
async def tailor_resume(state: PipelineState) -> dict[str, Any]:  # pragma: no cover
    return {"stage": "tailor"}

async def generate_cover_letter(state: PipelineState) -> dict[str, Any]:  # pragma: no cover
    return {"stage": "cover_letter"}

async def prepare_email(state: PipelineState) -> dict[str, Any]:  # pragma: no cover
    return {"stage": "email"}

async def apply_to_job(state: PipelineState) -> dict[str, Any]:  # pragma: no cover
    return {"stage": "apply"}

async def analyze_job(state: PipelineState) -> dict[str, Any]:  # pragma: no cover
    return {"stage": "analyze"}


__all__ = ["discover_jobs", "filter_jobs", "save_jobs", "analyze_job", "tailor_resume", "generate_cover_letter", "prepare_email", "apply_to_job"]
