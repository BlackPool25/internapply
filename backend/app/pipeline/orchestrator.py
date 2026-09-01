"""Truncated pipeline: discover → filter → save with seen_canonical_id + cursor.

Fan-out tiers:
  Tier0 ATS (probed ~100 boards, cursor max_seen = max(updated_at|last_seen_at|posted_date))
  → Tier1 Hirist/Unstop/Internshala XHR
  → Tier3 free APIs overflow (Arbeitnow/Remotive/TheMuse/Jobicy)
  → Tier2 JobSpy Naukri/Indeed
  → Tier3 LinkedIn overflow (respect breaker 999 → skip)

Dedup at save_to_db via canonical_id (64 hex UNIQUE), jd_hash primary gate → skip,
etag tiebreaker only if both present, diff_change_log → change_log JSONB.
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from loguru import logger

from backend.app.pipeline.state import PipelineState

# ---------------------------------------------------------------------------
# Mock data for dry-run
# ---------------------------------------------------------------------------
_MOCK_JOB_LISTINGS: list[dict[str, Any]] = [
    {
        "title": "Python Backend Intern",
        "company": "TechCorp",
        "location": "Remote",
        "stipend_min": 15000,
        "stipend_max": 25000,
        "skills": ["Python", "FastAPI", "PostgreSQL"],
        "description": "Build and maintain backend services using Python and FastAPI.",
        "source": "linkedin",
        "source_ats": "linkedin",
        "url": "https://linkedin.com/jobs/view/1",
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
        "skills": ["Java", "Spring Boot", "MySQL"],
        "description": "Develop microservices for a banking platform.",
        "source": "indeed",
        "source_ats": "indeed",
        "url": "https://indeed.com/view/2",
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


def _log_stage(state: PipelineState, name: str) -> None:
    dry = " [DRY RUN]" if state.get("dry_run") else ""
    logger.info("━━━ Stage: {}{} ━━━", name, dry)


def _log_completion(name: str, start: float, count: int, errors: int = 0) -> None:
    elapsed = time.monotonic() - start
    if errors:
        logger.info("Node '{}' finished in {:.2f}s — {} items, {} errors", name, elapsed, count, errors)
    else:
        logger.info("Node '{}' finished in {:.2f}s — {} items", name, elapsed, count)


def _cursor_for_job(job: dict[str, Any]) -> str:
    """Cursor fallback: updated_at or last_seen_at or posted_date."""
    for k in ("updated_at", "last_seen_at", "posted_date", "cursor"):
        v = job.get(k)
        if v:
            return str(v)
    return ""


# ===================================================================
# Node 1 — discover_job_board (Tiered fan-out)
# ===================================================================

async def discover_job_board(state: PipelineState) -> dict[str, Any]:
    """Tiered discovery with seen_canonical_id dedup + cursor."""
    _log_stage(state, "discover_job_board")
    start = time.monotonic()

    if state.get("dry_run"):
        logger.info("[DRY RUN] Tiered discovery mock (ATS→Hirist→free→JobSpy→LinkedIn)")
        # ensure seen_canonical_id in state for tests
        all_mock = list(_MOCK_JOB_LISTINGS)
        max_cursor = max((_cursor_for_job(j) for j in all_mock), default="")
        logger.info("[DRY RUN] cursor max_seen={}", max_cursor)
        _log_completion("discover_job_board", start, len(all_mock))
        return {
            "job_listings": all_mock,
            "stage": "discover_job_board",
            "_cursor_max_seen": max_cursor,
        }

    errors: list[str] = []
    all_jobs: list[dict[str, Any]] = []
    seen_canonical_id: set[str] = set()
    cursor_candidates: list[str] = []

    def _add_jobs(jobs: list[dict[str, Any]]) -> None:
        for job in jobs:
            cid = job.get("canonical_id") or ""
            # fallback compute canonical_id if missing but url present
            if not cid:
                url = job.get("url") or job.get("source_job_id") or ""
                if not url:
                    continue
                # compute deterministically from available fields
                try:
                    from backend.app.discovery.hash_utils import canonical_id as _cid
                    cid = _cid(job.get("company",""), job.get("title",""), job.get("location",""), url)
                    job["canonical_id"] = cid
                except Exception:
                    continue
            if cid in seen_canonical_id:
                continue
            seen_canonical_id.add(cid)
            all_jobs.append(job)
            cur = _cursor_for_job(job)
            if cur:
                cursor_candidates.append(cur)

    # ── Tier0 ATS (Greenhouse/Lever/Ashby/SmartRecruiters) probed ~100 boards ──
    try:
        from backend.app.config import settings as _settings
        boards = []
        try:
            boards = _settings.ats_boards
        except Exception:
            boards = []
        # fan across ATS types
        from backend.app.discovery.ats.ashby import AshbyDiscovery
        from backend.app.discovery.ats.greenhouse import GreenhouseDiscovery
        from backend.app.discovery.ats.lever import LeverDiscovery
        from backend.app.discovery.ats.smartrecruiters import SmartRecruitersDiscovery

        for Cls in (GreenhouseDiscovery, LeverDiscovery, AshbyDiscovery, SmartRecruitersDiscovery):
            try:
                disc = Cls()
                jobs = await disc.search(boards=boards)
                # SmartRecruiters handles 200-empty ambiguous internally (returns [] not exception)
                _add_jobs(jobs if isinstance(jobs, list) else [])
                logger.info("Tier0 {} returned {} jobs", Cls.__name__, len(jobs) if isinstance(jobs, list) else 0)
            except Exception as exc:
                msg = f"Tier0 {Cls.__name__} failed: {exc}"
                logger.warning(msg)
                errors.append(msg)
    except Exception as exc:
        msg = f"Tier0 ATS fan-out failed: {exc}"
        logger.warning(msg)
        errors.append(msg)

    # ── Tier1 Hirist / Unstop / Internshala XHR ──
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
            # ensure close if needed
            try:
                await disc.close()  # type: ignore
            except Exception:
                pass
            _add_jobs(jobs if isinstance(jobs, list) else [])
            logger.info("Tier1 {} returned {} jobs", _name, len(jobs) if isinstance(jobs, list) else 0)
        except Exception as exc:
            msg = f"Tier1 {_name} failed: {exc}"
            logger.warning(msg)
            errors.append(msg)

    # ── Tier3 free APIs overflow (Arbeitnow/Remotive/TheMuse/Jobicy) ──
    try:
        from backend.app.discovery.free_apis import FreeAPIsDiscovery
        disc = FreeAPIsDiscovery()
        jobs = await disc.search()
        try:
            await disc.close()
        except Exception:
            pass
        _add_jobs(jobs if isinstance(jobs, list) else [])
        logger.info("Tier3 free APIs returned {} jobs", len(jobs) if isinstance(jobs, list) else 0)
    except Exception as exc:
        msg = f"Tier3 free APIs failed: {exc}"
        logger.warning(msg)
        errors.append(msg)

    # ── Tier2 JobSpy Naukri/Indeed ──
    try:
        from backend.app.discovery.jobspy_linkedin import JobSpyLinkedInDiscovery
        disc = JobSpyLinkedInDiscovery()
        # Respect breaker for linkedin overflow; JobSpyLinkedInDiscovery handles naukri+indeed first, linkedin last with breaker check
        jobs = await disc.search(search_term="DevOps intern", location="Bangalore", hours_old=24)
        # filter to non-linkedin for Tier2 logging? but disc returns all; we treat all as Tier2+overflow
        # dedup still via canonical_id
        _add_jobs(jobs if isinstance(jobs, list) else [])
        logger.info("Tier2 JobSpy (Naukri/Indeed+LinkedIn) returned {} jobs", len(jobs) if isinstance(jobs, list) else 0)
    except Exception as exc:
        msg = f"Tier2 JobSpy failed: {exc}"
        logger.warning(msg)
        errors.append(msg)

    # LinkedIn overflow already included above with breaker respect; no separate call needed
    # If breaker open, JobSpyLinkedInDiscovery skips linkedin and logs "breaker:linkedin open 60s"

    # cursor max_seen
    max_seen = max(cursor_candidates) if cursor_candidates else ""
    if max_seen:
        logger.info("Discovery cursor max_seen={} (from {} jobs)", max_seen, len(all_jobs))

    result: dict[str, Any] = {
        "job_listings": all_jobs,
        "stage": "discover_job_board",
        "_cursor_max_seen": max_seen,
    }
    if errors:
        result["errors"] = errors
    _log_completion("discover_job_board", start, len(all_jobs), len(errors))
    return result


# ===================================================================
# Node 2 — filter_jobs (canonical_id dedup, no LLM)
# ===================================================================

async def filter_jobs(state: PipelineState) -> dict[str, Any]:
    """Filter: canonical_id dedup + stipend/location pass-through, no LLM."""
    _log_stage(state, "filter_jobs")
    start = time.monotonic()
    raw = list(state.get("job_listings", []))
    if not raw:
        _log_completion("filter_jobs", start, 0)
        return {"job_listings": [], "stage": "filter_jobs"}

    seen_canonical_id: set[str] = set()
    filtered: list[dict[str, Any]] = []
    for job in raw:
        cid = job.get("canonical_id") or ""
        if cid:
            if cid in seen_canonical_id:
                continue
            seen_canonical_id.add(cid)
        # keep all that have canonical_id; no LLM filtering
        filtered.append(job)

    logger.info("Filter: {} → {} (dedup by canonical_id)", len(raw), len(filtered))
    _log_completion("filter_jobs", start, len(filtered))
    return {"job_listings": filtered, "stage": "filter_jobs"}


# ===================================================================
# Node — generate_outreach (kept for skill, NOT in auto pipeline)
# ===================================================================

async def generate_outreach(state: PipelineState) -> dict[str, Any]:
    """Kept for skill invocation only — NOT wired in auto pipeline graph.

    Skill path: opencode skill:resume-tailor per JD with jd_hash cache.
    This function remains callable via skill without being in create_pipeline edges.
    """
    _log_stage(state, "generate_outreach")
    start = time.monotonic()
    # No LLM in auto path — skill handles single-JD tailoring with cache
    logger.info("generate_outreach kept for skill only — no auto LLM in batch")
    _log_completion("generate_outreach", start, 0)
    return {"stage": "generate_outreach"}


# ===================================================================
# Node 3 — save_to_db (canonical_id dedup, jd_hash gate, change_log)
# ===================================================================

async def save_to_db(state: PipelineState) -> dict[str, Any]:
    """Persist with dedup via canonical_id, jd_hash primary gate, change_log JSONB."""
    _log_stage(state, "save_to_db")
    start = time.monotonic()

    if state.get("dry_run"):
        logger.info("[DRY RUN] Would persist {} listings via canonical_id dedup", len(state.get("job_listings", [])))
        _log_completion("save_to_db", start, 0)
        return {"stage": "save_to_db"}

    errors: list[str] = []
    try:
        from sqlalchemy import select

        from backend.app.database import get_session, init_db
        from backend.app.discovery.hash_utils import diff_change_log
        from backend.app.models import JobListing as ORMJobListing

        db_url = state.get("config", {}).get("DATABASE_URL", "") if isinstance(state.get("config"), dict) else ""
        if not db_url:
            from backend.app.config import settings
            db_url = settings.database_url
        await init_db(db_url)

        async for session in get_session():
            # ensure pipeline run bookkeeping minimal
            from backend.app.models import PipelineRun as ORMPipelineRun
            pipeline_run = ORMPipelineRun(run_type="full", status="saving")
            session.add(pipeline_run)
            await session.flush()

            for job in state.get("job_listings", []):
                canonical_id = job.get("canonical_id") or ""
                if not canonical_id:
                    # compute if missing
                    try:
                        from backend.app.discovery.hash_utils import canonical_id as _cid
                        canonical_id = _cid(job.get("company",""), job.get("title",""), job.get("location",""), job.get("url") or job.get("source_job_id") or "")
                        job["canonical_id"] = canonical_id
                    except Exception:
                        continue
                # Dedup via canonical_id not url
                existing = await session.execute(
                    select(ORMJobListing).where(ORMJobListing.canonical_id == canonical_id)
                )
                row = existing.scalar_one_or_none()
                if row is not None:
                    # jd_hash equality primary gate → skip (etag tiebreaker only if both present)
                    new_jd = job.get("jd_hash")
                    old_jd = row.jd_hash
                    if new_jd and old_jd and new_jd == old_jd:
                        # etag tiebreaker only if both present — still skip, just check
                        new_etag = job.get("etag")
                        old_etag = row.etag
                        if new_etag and old_etag and new_etag != old_etag:
                            # etag differs but jd same → still skip (no meaningful change)
                            pass
                        # update last_seen_at only
                        try:
                            row.last_seen_at = datetime.now(UTC)
                            await session.flush()
                        except Exception:
                            pass
                        logger.debug("canonical_id {} jd_hash hit → skip (etag tiebreaker)", canonical_id[:8])
                        continue
                    # jd_hash differs → diff_change_log excluding volatile, append to change_log JSONB
                    try:
                        old_desc = row.description or ""
                        new_desc = job.get("description") or ""
                        # use dict form for richer diff
                        old_payload = {"title": row.title, "company": row.company, "location": row.location or "", "description": old_desc}
                        new_payload = {"title": job.get("title",""), "company": job.get("company",""), "location": job.get("location",""), "description": new_desc}
                        diff = diff_change_log(old_payload, new_payload)
                    except Exception:
                        diff = {"changed": True}
                    if not diff:
                        # no meaningful change (volatile stripped)
                        try:
                            row.last_seen_at = datetime.now(UTC)
                            await session.flush()
                        except Exception:
                            pass
                        continue
                    # meaningful change → update row and append change_log
                    try:
                        existing_log = row.change_log or {}
                        # store diff with timestamp
                        new_log = {**existing_log, **diff, "at": datetime.now(UTC).isoformat()}
                        row.change_log = new_log
                        # update jd_hash/snapshot fields
                        if job.get("jd_hash"):
                            row.jd_hash = job["jd_hash"]
                        if job.get("simhash") is not None:
                            row.simhash = job["simhash"]
                        if job.get("etag"):
                            row.etag = job["etag"]
                        if job.get("description"):
                            row.description = job["description"]
                        if job.get("title"):
                            row.title = job["title"]
                        if job.get("company"):
                            row.company = job["company"]
                        if job.get("location"):
                            row.location = job["location"]
                        if job.get("url"):
                            row.url = job["url"]
                        row.last_seen_at = datetime.now(UTC)
                        await session.flush()
                        logger.info("canonical_id {} changed → change_log updated", canonical_id[:8])
                    except Exception as exc:
                        logger.warning("change_log update failed for {}: {}", canonical_id[:8], exc)
                    continue

                # insert new
                try:
                    orm_job = ORMJobListing(
                        title=job.get("title", ""),
                        company=job.get("company", ""),
                        location=job.get("location"),
                        stipend_min=job.get("stipend_min"),
                        stipend_max=job.get("stipend_max"),
                        stipend_raw=job.get("stipend_raw"),
                        skills=job.get("skills"),
                        description=job.get("description"),
                        source=job.get("source") or job.get("source_ats") or "unknown",
                        url=job.get("url") or f"https://example.com/{canonical_id[:8]}",
                        posted_at=job.get("posted_at") or job.get("posted_date"),
                        is_paid=job.get("is_paid", True),
                        is_remote=job.get("is_remote", False),
                        canonical_id=canonical_id,
                        jd_hash=job.get("jd_hash"),
                        simhash=job.get("simhash"),
                        etag=job.get("etag"),
                        change_log={},
                        source_ats=job.get("source_ats"),
                        last_seen_at=datetime.now(UTC),
                    )
                    session.add(orm_job)
                    await session.flush()
                except Exception as exc:
                    # UNIQUE violation etc → log not crash
                    logger.warning("Insert failed for {}: {}", canonical_id[:8], exc)
                    continue

            pipeline_run.status = "completed"
            pipeline_run.jobs_found = len(state.get("job_listings", []))

        logger.info("save_to_db persisted {} listings (canonical_id dedup)", len(state.get("job_listings", [])))

    except Exception as exc:
        msg = f"save_to_db failed: {exc}"
        logger.error(msg)
        errors.append(msg)

    result: dict[str, Any] = {"stage": "save_to_db"}
    if errors:
        result["errors"] = errors
    _log_completion("save_to_db", start, 0, len(errors))
    return result


# ===================================================================
# Graph factory — 3 nodes only: discover → filter → save
# ===================================================================

def create_pipeline() -> StateGraph:
    """Create truncated pipeline: discover_job_board → filter_jobs → save_to_db.

    Edges: discover → filter → save → END.
    Removes analyze/tailor/cover_letter/email/apply.
    Keeps MemorySaver (arq handles checkpoint but keep for now).
    generate_outreach kept for skill only, not in graph.
    """
    workflow = StateGraph(PipelineState)

    workflow.add_node("discover_job_board", discover_job_board)
    workflow.add_node("filter_jobs", filter_jobs)
    workflow.add_node("save_to_db", save_to_db)

    workflow.add_edge("discover_job_board", "filter_jobs")
    workflow.add_edge("filter_jobs", "save_to_db")
    workflow.add_edge("save_to_db", END)

    workflow.set_entry_point("discover_job_board")

    checkpointer = MemorySaver()
    compiled = workflow.compile(checkpointer=checkpointer)

    logger.debug("Truncated pipeline graph compiled with {} nodes", len(workflow.nodes))
    return compiled


__all__ = [
    "create_pipeline",
    "discover_job_board",
    "filter_jobs",
    "generate_outreach",
    "save_to_db",
]
