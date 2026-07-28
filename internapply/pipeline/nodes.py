"""Pipeline node functions for the InternApply LangGraph.

Each node is an :term:`async` function that accepts a :class:`PipelineState`
dict and returns an *updated* state dict with the fields it is responsible
for populated.

Nodes are stubs for Wave 1 (MVP).  Real logic (LLM calls, scrapers, email
lookup, Playwright auto-apply) will be wired in Waves 2-3.  For now they
log what they *would* do and, in ``dry_run`` mode, return mock data so the
pipeline topology can be tested end-to-end.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from loguru import logger

from internapply.pipeline.state import PipelineState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_JOBS: list[dict[str, Any]] = [
    {
        "id": 1,
        "title": "Python Backend Intern",
        "company": "TechCorp",
        "location": "Remote",
        "stipend_min": 15000,
        "stipend_max": 25000,
        "stipend_raw": "₹15,000-25,000 /month",
        "skills": ["Python", "FastAPI", "PostgreSQL"],
        "description": "Build and maintain backend services.",
        "source": "internshala",
        "url": "https://internshala.com/internship/example-1",
        "is_paid": True,
        "is_remote": True,
        "posted_at": "3 days ago",
    },
    {
        "id": 2,
        "title": "Java Spring Boot Intern",
        "company": "FinServe",
        "location": "Bangalore",
        "stipend_min": 20000,
        "stipend_max": 30000,
        "stipend_raw": "₹20,000-30,000 /month",
        "skills": ["Java", "Spring Boot", "MySQL"],
        "description": "Develop microservices for banking platform.",
        "source": "naukri",
        "url": "https://naukri.com/job/example-2",
        "is_paid": True,
        "is_remote": False,
        "posted_at": "1 week ago",
    },
    {
        "id": 3,
        "title": "Full-Stack Intern (MERN)",
        "company": "StartupXYZ",
        "location": "Remote",
        "stipend_min": 10000,
        "stipend_max": 18000,
        "stipend_raw": "₹10,000-18,000 /month",
        "skills": ["React", "Node.js", "MongoDB"],
        "description": "Work on the core product across the stack.",
        "source": "internshala",
        "url": "https://internshala.com/internship/example-3",
        "is_paid": True,
        "is_remote": True,
        "posted_at": "5 days ago",
    },
]


def _log_stage(state: PipelineState, name: str) -> None:
    """Log that a pipeline stage has started."""
    logger.info("━━━ Stage: {} ━━━", name)


def _serialize_job(job: Any) -> dict[str, Any]:
    """Serialize a ``JobListing`` model (or any job dict) to a plain dict."""
    if hasattr(job, "model_dump"):
        return job.model_dump()
    if isinstance(job, dict):
        return job
    return dict(job)


# ---------------------------------------------------------------------------
# Node: discover_jobs
# ---------------------------------------------------------------------------


async def discover_jobs(state: PipelineState) -> dict[str, Any]:
    """Discover internship listings from configured sources.

    In ``dry_run`` mode returns a set of mock jobs.  Otherwise delegates
    to :class:`~internapply.discovery.internshala.InternshalaScraper` and
    :class:`~internapply.discovery.naukri.NaukriScraper`.

    Populates ``jobs``, ``raw_jobs_count``, and ``stage``.
    """
    _log_stage(state, "discover")

    if state["dry_run"]:
        logger.info("[DRY RUN] Would scrape Internshala & Naukri for jobs")
        mock = copy.deepcopy(_MOCK_JOBS)
        return {
            "jobs": mock,
            "raw_jobs_count": len(mock),
            "stage": "discover",
            "filtered_jobs_count": 0,
        }

    try:
        from internapply.config import get_config
        from internapply.discovery.internshala import InternshalaScraper
        from internapply.discovery.naukri import NaukriScraper

        cfg = get_config()
        all_jobs: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        # ── Internshala ────────────────────────────────────────────
        try:
            async with InternshalaScraper(min_stipend=cfg.MIN_STIPEND_INR) as scraper:
                internshala_jobs = await scraper.search(
                    keywords=cfg.SEARCH_KEYWORDS,
                    locations=cfg.SEARCH_LOCATIONS,
                )
            for job in internshala_jobs:
                serialized = _serialize_job(job)
                url = serialized.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_jobs.append(serialized)
            logger.info("Internshala returned {} jobs", len(internshala_jobs))
        except Exception as exc:
            msg = f"Internshala scrape failed: {exc}"
            logger.error(msg)
            return {"errors": [msg], "stage": "discover"}

        # ── Naukri ─────────────────────────────────────────────────
        try:
            async with NaukriScraper() as scraper:
                naukri_jobs = await scraper.search(
                    keywords=cfg.SEARCH_KEYWORDS,
                    locations=cfg.SEARCH_LOCATIONS,
                )
            for job in naukri_jobs:
                serialized = _serialize_job(job)
                url = serialized.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_jobs.append(serialized)
            logger.info("Naukri returned {} jobs", len(naukri_jobs))
        except Exception as exc:
            msg = f"Naukri scrape failed: {exc}"
            logger.error(msg)
            return {"errors": [msg], "stage": "discover"}

        return {
            "jobs": all_jobs,
            "raw_jobs_count": len(all_jobs),
            "stage": "discover",
            "filtered_jobs_count": 0,
        }

    except Exception as exc:
        msg = f"discover_jobs failed: {exc}"
        logger.error(msg)
        return {"errors": [msg], "stage": "discover"}


# ---------------------------------------------------------------------------
# Node: filter_jobs
# ---------------------------------------------------------------------------


async def filter_jobs(state: PipelineState) -> dict[str, Any]:
    """Apply post-filters and deduplicate by URL.

    Filters applied:
    * Exclude unpaid jobs (``is_paid == False``).
    * Exclude jobs below ``MIN_STIPEND_INR``.
    * Deduplicate by URL (keeps first occurrence).
    * Optionally location filter (case-insensitive substring).

    Populates ``filtered_jobs_count`` and updates ``jobs``.
    """
    _log_stage(state, "filter")

    raw_jobs = state.get("jobs", [])
    if not raw_jobs:
        logger.info("No jobs to filter")
        return {"jobs": [], "filtered_jobs_count": 0, "stage": "filter"}

    if state["dry_run"]:
        logger.info(
            "[DRY RUN] Would filter {} jobs (paid, stipend ≥{}, location match)",
            len(raw_jobs),
            state.get("config", {}).get("MIN_STIPEND_INR", 5000),
        )
        return {
            "filtered_jobs_count": len(raw_jobs),
            "stage": "filter",
        }

    try:
        cfg = state.get("config", {})
        min_stipend = cfg.get("MIN_STIPEND_INR", 5000)
        target_locations = [
            loc.lower() for loc in cfg.get("SEARCH_LOCATIONS", [])
        ]

        seen_urls: set[str] = set()
        filtered: list[dict[str, Any]] = []

        for job in raw_jobs:
            # Dedup by URL
            url = job.get("url", "")
            if url:
                if url in seen_urls:
                    continue
                seen_urls.add(url)

            # Paid check
            if not job.get("is_paid", False):
                continue

            # Stipend threshold
            stipend_min = job.get("stipend_min") or 0
            if stipend_min < min_stipend:
                continue

            # Location check (skip if configured and no match)
            if target_locations:
                loc_lower = (job.get("location") or "").lower()
                is_remote = "remote" in loc_lower or "work from home" in loc_lower
                if not is_remote and not any(
                    tloc in loc_lower for tloc in target_locations
                ):
                    continue

            filtered.append(job)

        logger.info(
            "Filtered: {} → {} jobs ({} removed)",
            len(raw_jobs),
            len(filtered),
            len(raw_jobs) - len(filtered),
        )

        return {
            "jobs": filtered,
            "filtered_jobs_count": len(filtered),
            "stage": "filter",
        }

    except Exception as exc:
        msg = f"filter_jobs failed: {exc}"
        logger.error(msg)
        return {"errors": [msg], "stage": "filter"}


# ---------------------------------------------------------------------------
# Node: analyze_job  (STUB)
# ---------------------------------------------------------------------------


async def analyze_job(state: PipelineState) -> dict[str, Any]:
    """Analyse the current job listing (STUB — wired in Wave 2).

    Wave 2 will call the JD analyser to extract requirements, weigh them
    against the master resume, and produce a match-score dict.
    """
    _log_stage(state, "analyze")

    current_job = state.get("current_job")
    if current_job:
        logger.info(
            "[STUB] Would analyse job: {} at {}",
            current_job.get("title", "?"),
            current_job.get("company", "?"),
        )
    else:
        logger.info("[STUB] No current job to analyse — iterating job list")

    # For now, just advance current_job_index if we have jobs lined up
    jobs = state.get("jobs", [])
    idx = state.get("current_job_index", 0)

    if idx < len(jobs):
        next_job = jobs[idx]
        return {
            "current_job": next_job,
            "current_job_index": idx + 1,
            "stage": "analyze",
        }

    logger.info("All {} jobs have been processed — nothing left to analyse", len(jobs))
    return {"stage": "analyze"}


# ---------------------------------------------------------------------------
# Node: tailor_resume  (STUB)
# ---------------------------------------------------------------------------


async def tailor_resume(state: PipelineState) -> dict[str, Any]:
    """Tailor the master resume for the current job (STUB — wired in Wave 2).

    Wave 2 will:
    1. Load the master resume from ``master_resume``.
    2. Call the LLM-based resume tailor to rewrite bullet points for the
       target job's requirements.
    3. Pass through the verifier gate (scorer) to ensure quality.
    4. Write the tailored resume to disk.
    """
    _log_stage(state, "tailor")

    if state["dry_run"]:
        logger.info("[DRY RUN] Would tailor resume for current job")

    master = state.get("master_resume")
    if master is None:
        logger.info("[STUB] No master resume loaded — would load from profile/resume.json")

    current_job = state.get("current_job")
    if current_job:
        logger.info(
            "[STUB] Would tailor resume for {} at {}",
            current_job.get("title", "?"),
            current_job.get("company", "?"),
        )
    else:
        logger.info("[STUB] No current job — skipping resume tailoring")

    return {"stage": "tailor"}


# ---------------------------------------------------------------------------
# Node: generate_cover_letter  (STUB)
# ---------------------------------------------------------------------------


async def generate_cover_letter(state: PipelineState) -> dict[str, Any]:
    """Generate a cover letter for the current job (STUB — wired in Wave 2).

    Wave 2 will use the LLM to compose a concise, tailored cover letter
    incorporating the candidate's background and the job requirements.
    """
    _log_stage(state, "cover_letter")

    if state["dry_run"]:
        logger.info("[DRY RUN] Would generate cover letter for current job")

    current_job = state.get("current_job")
    if current_job:
        logger.info(
            "[STUB] Would write cover letter for {} at {}",
            current_job.get("title", "?"),
            current_job.get("company", "?"),
        )
    else:
        logger.info("[STUB] No current job — skipping cover letter generation")

    return {"stage": "cover_letter"}


# ---------------------------------------------------------------------------
# Node: prepare_email  (STUB)
# ---------------------------------------------------------------------------


async def prepare_email(state: PipelineState) -> dict[str, Any]:
    """Prepare the cold-email outreach (STUB — wired in Wave 3).

    Wave 3 will:
    1. Use Hunter.io (or similar) to find recruiter emails for the company.
    2. Generate a personalised cold-email draft via LLM.
    3. Compute a humanisation score to avoid spam filters.
    """
    _log_stage(state, "email")

    if state["dry_run"]:
        logger.info("[DRY RUN] Would look up company email and draft cold email")

    current_job = state.get("current_job")
    if current_job:
        logger.info(
            "[STUB] Would find email for {} and draft cold email",
            current_job.get("company", "?"),
        )
    else:
        logger.info("[STUB] No current job — skipping email preparation")

    return {"stage": "email"}


# ---------------------------------------------------------------------------
# Node: apply_to_job  (STUB)
# ---------------------------------------------------------------------------


async def apply_to_job(state: PipelineState) -> dict[str, Any]:
    """Submit the application (STUB — wired in Wave 3).

    Wave 3 will use Playwright to:
    1. Navigate to the job listing URL.
    2. Fill in the application form (resume upload, cover letter text, etc.).
    3. Submit and record the result.
    """
    _log_stage(state, "apply")

    if state["dry_run"]:
        logger.info("[DRY RUN] Would submit application via portal/email")

    current_job = state.get("current_job")
    if current_job:
        logger.info(
            "[STUB] Would apply to {} at {} via {}",
            current_job.get("title", "?"),
            current_job.get("company", "?"),
            current_job.get("url", "?"),
        )
    else:
        logger.info("[STUB] No current job — skipping application")

    # Record a mock result in dry-run mode
    result: dict[str, Any] = {
        "job_url": (current_job or {}).get("url", ""),
        "title": (current_job or {}).get("title", ""),
        "company": (current_job or {}).get("company", ""),
        "status": "simulated" if state["dry_run"] else "pending",
        "run_id": state.get("run_id", str(uuid.uuid4())[:8]),
    }
    results = state.get("application_results", [])
    results.append(result)

    logger.info(
        "Application recorded: {} jobs processed so far",
        len(results),
    )

    return {
        "application_results": results,
        "stage": "apply",
    }


__all__ = [
    "analyze_job",
    "apply_to_job",
    "discover_jobs",
    "filter_jobs",
    "generate_cover_letter",
    "prepare_email",
    "tailor_resume",
]
