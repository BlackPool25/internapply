"""Pipeline node functions for the InternApply LangGraph.

Each node is an :term:`async` function that accepts a :class:`PipelineState`
dict and returns an *updated* state dict with the fields it is responsible
for populated.

All 7 nodes are wired with real implementations covering discovery, filtering,
JD analysis, resume tailoring (with verifier gate), cover-letter generation,
email preparation, and portal submission.  A token-bucket rate limiter guards
LLM API calls and structured logging tracks timing and item counts.
"""

from __future__ import annotations

import asyncio
import copy
import json
import random
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from internapply.pipeline.state import PipelineState

# ---------------------------------------------------------------------------
# Rate limiter — token-bucket for LLM API calls
# ---------------------------------------------------------------------------


class RateLimiter:
    """Token-bucket rate limiter for LLM API calls.

    Maintains a bucket of tokens that refill at a configurable rate per
    minute.  :meth:`acquire` blocks until a token is available.

    Thread-safe for async use via an internal :class:`asyncio.Lock`.
    """

    def __init__(self, max_per_minute: int = 30) -> None:
        self._max_per_minute = max_per_minute
        self._tokens = float(max_per_minute)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._total_acquired: int = 0

    @property
    def total_calls(self) -> int:
        """Return the total number of tokens acquired (LLM calls made)."""
        return self._total_acquired

    async def acquire(self) -> None:
        """Block until a token is available, then consume it."""
        async with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self._total_acquired += 1
                return

            # Token exhausted — compute wait and sleep
            wait = 60.0 / self._max_per_minute
            logger.debug("Rate limiter waiting {:.1f}s for next token", wait)
            async with self._lock:  # release outer lock while sleeping
                pass  # We need a different approach — refill outside lock
            # Actually sleep with lock held is fine for asyncio since it's
            # cooperative — but we want other coroutines to run.
            await asyncio.sleep(wait)

        # Re-acquire after sleep
        async with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
            else:
                # Still empty — force-grant one (should not happen after sleep)
                self._tokens = 0.0
            self._total_acquired += 1

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        refill = (elapsed / 60.0) * self._max_per_minute
        if refill > 0.5:
            self._tokens = min(float(self._max_per_minute), self._tokens + refill)
            self._last_refill = now
            if self._tokens < float(self._max_per_minute) * 0.2:
                logger.warning(
                    "Rate limiter: only {:.0f} tokens remaining ({:.0f}% capacity)",
                    self._tokens,
                    self._tokens / self._max_per_minute * 100,
                )

    def reset(self) -> None:
        """Reset the bucket to full."""
        self._tokens = float(self._max_per_minute)
        self._last_refill = time.monotonic()
        self._total_acquired = 0


# Module-level rate limiter singleton
_llm_rate_limiter = RateLimiter(max_per_minute=30)


# ---------------------------------------------------------------------------
# Mock data for dry-run mode
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
        "description": "Build and maintain backend services using Python and FastAPI.",
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
        "description": "Develop microservices for banking platform using Java and Spring Boot.",
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
        "description": "Work on the core product across the stack using MERN.",
        "source": "internshala",
        "url": "https://internshala.com/internship/example-3",
        "is_paid": True,
        "is_remote": True,
        "posted_at": "5 days ago",
    },
]

_MOCK_ANALYSIS: dict[str, Any] = {
    "required_skills": ["Python", "FastAPI", "PostgreSQL"],
    "nice_to_have_skills": ["Docker", "Redis"],
    "responsibilities": ["Build backend services", "Write unit tests"],
    "experience_level": "entry",
    "education_requirements": ["Bachelor's degree"],
    "top_keywords": ["Python", "FastAPI", "backend", "API", "PostgreSQL"],
    "soft_skills": ["Communication", "Teamwork"],
    "technologies": ["FastAPI", "PostgreSQL", "Docker"],
    "match_score": 85.0,
    "raw_text": "Build and maintain backend services.",
}

_MOCK_TAILORED: dict[str, Any] = {
    "summary": "Experienced backend developer with Python expertise.",
    "skills_reordered": ["Python", "FastAPI", "PostgreSQL", "Docker"],
    "projects": [
        {
            "name": "Sample Project",
            "url": "https://github.com/example",
            "tech": "Python, FastAPI",
            "bullets": ["Built RESTful APIs", "Implemented authentication"],
        }
    ],
    "education": [
        {
            "degree": "B.Tech in Computer Science",
            "institution": "Sample University",
            "cgpa": "8.5",
            "expected": "2025",
        }
    ],
    "verifier_score": 100,
    "verifier_issues": [],
}

_MOCK_COVER_LETTER: str = (
    "Hi there,\n\n"
    "I'm a CS student with strong Python and backend skills. "
    "I've worked on several projects using FastAPI and PostgreSQL. "
    "I'd love to bring my experience to this role.\n\n"
    "Would you be available for a quick chat?\n\nBest,\nCandidate"
)

_MOCK_EMAIL_DRAFT: str = (
    "Subject: Application for Intern Position\n\n"
    "Dear Hiring Manager,\n\n"
    "I am writing to express my interest in the internship position. "
    "I have experience with the required tech stack and am eager to contribute.\n\n"
    "Best regards,\nCandidate"
)

_MOCK_EMAIL_CONTACTS: list[dict[str, Any]] = [
    {
        "email": "hr@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "position": "HR Manager",
        "confidence": 95,
        "source": "hunter",
    }
]


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


def _log_stage(state: PipelineState, name: str) -> None:
    """Log that a pipeline stage has started."""
    logger.info("━━━ Stage: {} ━━━", name)


def _log_completion(name: str, start: float, count: int, errors: int = 0) -> None:
    """Log pipeline node completion with timing and item count."""
    elapsed = time.monotonic() - start
    if errors:
        logger.info(
            "Node '{}' finished in {:.2f}s — {} items, {} errors",
            name,
            elapsed,
            count,
            errors,
        )
    else:
        logger.info(
            "Node '{}' finished in {:.2f}s — {} items",
            name,
            elapsed,
            count,
        )


def _serialize_job(job: Any) -> dict[str, Any]:
    """Serialize a ``JobListing`` model (or any job dict) to a plain dict."""
    if hasattr(job, "model_dump"):
        return job.model_dump()
    if isinstance(job, dict):
        return job
    return dict(job)


def _parse_relative_date(value: str | None) -> date | None:
    """Parse a human-readable posting-date string to a :class:`datetime.date`.

    Handles the following formats:

    * ``"Few hours ago"``, ``"Just now"``, ``"Today"``, ``"Actively hiring"``
      → today's date.
    * ``"Yesterday"`` → yesterday.
    * ``"N days ago"`` → N days ago.
    * ``"N weeks ago"`` → N × 7 days ago.
    * ``"N months ago"`` → N × 30 days ago.
    * Any unparseable value → today (conservative fallback).
    * ``None`` / empty → ``None``.
    """
    if not value:
        return None

    today_d = date.today()
    lower = value.strip().lower()

    # Immediate / today
    if lower in ("few hours ago", "just now", "today", "actively hiring"):
        return today_d

    # Yesterday
    if lower == "yesterday":
        return today_d - timedelta(days=1)

    # N days ago
    m = re.search(r"(\d+)\s+days?\s+ago", lower)
    if m:
        return today_d - timedelta(days=int(m.group(1)))

    # N weeks ago
    m = re.search(r"(\d+)\s+weeks?\s+ago", lower)
    if m:
        return today_d - timedelta(weeks=int(m.group(1)))

    # N months ago
    m = re.search(r"(\d+)\s+months?\s+ago", lower)
    if m:
        return today_d - timedelta(days=int(m.group(1)) * 30)

    # Unparseable → today (conservative)
    return today_d


def _recency_sort_key(job: dict[str, Any]) -> date:
    """Return a sort key for newest-first ordering by ``posted_at_date``.

    If the job dict already has a ``posted_at_date`` key (a ``date`` object)
    that is used directly.  Otherwise the raw ``posted_at`` string is parsed
    via :func:`_parse_relative_date`.  Jobs with no date at all sort to
    today (most recent / default).
    """
    d = job.get("posted_at_date")
    if d is None:
        posted_at = job.get("posted_at")
        if posted_at:
            d = _parse_relative_date(posted_at)
    return d or date.today()


def _app_dir(company: str, title: str) -> Path:
    """Return the applications sub-directory for a given company + title."""
    from internapply.resume.tailor import _sanitize_path_component

    safe_company = _sanitize_path_component(company)
    safe_title = _sanitize_path_component(title)
    return (Path("applications") / f"{safe_company}_{safe_title}").resolve()


# ---------------------------------------------------------------------------
# Node: discover_jobs
# ---------------------------------------------------------------------------


async def discover_jobs(state: PipelineState) -> dict[str, Any]:
    """Discover internship listings from configured sources.

    In ``dry_run`` mode returns a set of mock jobs.  Otherwise delegates
    to :class:`~internapply.discovery.internshala.InternshalaScraper` and
    :class:`~internapply.discovery.naukri.NaukriScraper`.
    """
    _log_stage(state, "discover")
    start = time.monotonic()

    if state["dry_run"]:
        logger.info("[DRY RUN] Would scrape Internshala & Naukri for jobs")
        mock = copy.deepcopy(_MOCK_JOBS)
        _log_completion("discover", start, len(mock))
        return {
            "jobs": mock,
            "raw_jobs_count": len(mock),
            "stage": "discover",
            "filtered_jobs_count": 0,
        }

    try:
        from internapply.config import get_config
        from internapply.discovery.internshala import InternshalaScraper

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

        _log_completion("discover", start, len(all_jobs))
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
    """Apply post-filters, deduplicate, and sort by recency.

    Filters applied:
    * Exclude unpaid jobs (``is_paid == False``).
    * Exclude jobs below ``MIN_STIPEND_INR``.
    * Deduplicate by URL (keeps first occurrence).
    * Optionally location filter (case-insensitive substring).
    * Skip jobs whose URL already exists in the database.
    * Skip jobs whose URL already has an application.
    * Sort remaining jobs by posting recency (newest first).
    """
    _log_stage(state, "filter")
    start = time.monotonic()

    raw_jobs = state.get("jobs", [])
    if not raw_jobs:
        logger.info("No jobs to filter")
        _log_completion("filter", start, 0)
        return {"jobs": [], "filtered_jobs_count": 0, "stage": "filter"}

    if state["dry_run"]:
        logger.info(
            "[DRY RUN] Would filter {} jobs (paid, stipend ≥{}, location match)",
            len(raw_jobs),
            state.get("config", {}).get("MIN_STIPEND_INR", 5000),
        )
        _log_completion("filter", start, len(raw_jobs))
        return {
            "filtered_jobs_count": len(raw_jobs),
            "stage": "filter",
        }

    try:
        cfg = state.get("config", {})
        min_stipend = cfg.get("MIN_STIPEND_INR", 5000)
        target_locations = [loc.lower() for loc in cfg.get("SEARCH_LOCATIONS", [])]

        # ── Load DB state for dedup & already-applied check ──────────
        existing_urls: set[str] = set()
        applied_urls: set[str] = set()
        try:
            from internapply.database import (
                ORMJobListing,
                get_job_applied_urls,
                get_session,
                init_db,
            )
            from sqlalchemy import select

            db_path = cfg.get("DATABASE_PATH")
            await init_db(db_path)
            async with get_session() as session:
                result = await session.execute(select(ORMJobListing.url))
                existing_urls = {row[0] for row in result.fetchall() if row[0]}
                applied_urls = await get_job_applied_urls(session)
        except Exception as exc:
            logger.warning("Could not load DB state for dedup: {}", exc)

        seen_urls: set[str] = set()
        filtered: list[dict[str, Any]] = []

        for job in raw_jobs:
            # In-memory dedup by URL
            url = job.get("url", "")
            if url:
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # DB dedup: skip only if already APPLIED (not just discovered)
                if url in applied_urls:
                    logger.debug("Skipping {} — already applied", url)
                    continue

                # Already-applied check (legacy, kept for safety)
                if url in applied_urls:
                    logger.debug("Skipping {} — already applied", url)
                    continue

            # Paid check
            if not job.get("is_paid", False):
                continue

            # Stipend threshold
            stipend_min = job.get("stipend_min") or 0
            if stipend_min < min_stipend:
                continue

            # Location check
            if target_locations:
                loc_lower = (job.get("location") or "").lower()
                is_remote = "remote" in loc_lower or "work from home" in loc_lower
                if not is_remote and not any(
                    tloc in loc_lower for tloc in target_locations
                ):
                    continue

            # Parse relative date for recency sorting
            if "posted_at_date" not in job or job["posted_at_date"] is None:
                job["posted_at_date"] = _parse_relative_date(job.get("posted_at"))

            filtered.append(job)

        # Sort by recency (newest first)
        filtered.sort(key=_recency_sort_key, reverse=True)

        logger.info(
            "Filtered: {} → {} jobs ({} removed)",
            len(raw_jobs),
            len(filtered),
            len(raw_jobs) - len(filtered),
        )
        _log_completion("filter", start, len(filtered))
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
# Node: analyze_job
# ---------------------------------------------------------------------------


async def analyze_job(state: PipelineState) -> dict[str, Any]:
    """Analyse all job descriptions using :class:`JDAnalyzer`.

    Uses the LLM-based JD analyser to extract structured requirements,
    skills, responsibilities, and compute a match score against the
    candidate's master resume.  Each job's ``analysis`` field is updated.

    Rate-limited to 30 LLM calls per minute globally across the pipeline.
    """
    _log_stage(state, "analyze")
    start = time.monotonic()
    errors: list[str] = []

    jobs = state.get("jobs", [])
    if not jobs:
        logger.info("No jobs to analyze")
        _log_completion("analyze", start, 0)
        return {"stage": "analyze"}

    if state["dry_run"]:
        logger.info("[DRY RUN] Would analyze {} job descriptions with JDAnalyzer", len(jobs))
        for job in jobs:
            job["analysis"] = copy.deepcopy(_MOCK_ANALYSIS)
            job["analysis"]["match_score"] = random.uniform(60, 95)
        _log_completion("analyze", start, len(jobs))
        return {"jobs": jobs, "stage": "analyze"}

    try:
        from internapply.models import JobListing
        from internapply.resume.analyzer import JDAnalyzer

        analyzer = JDAnalyzer()
        analyzed_count = 0
        skipped_count = 0

        for idx, job in enumerate(jobs):
            title = job.get("title", "?")
            company = job.get("company", "?")

            # Skip already-analyzed jobs
            if job.get("analysis"):
                logger.debug("Job {} already analyzed — skipping", job.get("id"))
                skipped_count += 1
                continue

            description = job.get("description", "")
            if not description or not description.strip():
                logger.info("Job {} ({}) has empty description — skipping analysis", job.get("id"), title)
                skipped_count += 1
                continue

            logger.info("Analyzing job {}/{}: {} @ {}", idx + 1, len(jobs), title, company)

            try:
                # Convert dict → JobListing model
                job_model = JobListing(**job)

                # Acquire rate limiter token before LLM call
                await _llm_rate_limiter.acquire()

                # Run analysis (LLM with deterministic fallback)
                await analyzer.analyze(job_model)

                # Store analysis back in the dict
                if job_model.analysis:
                    job["analysis"] = job_model.analysis
                analyzed_count += 1

            except Exception as exc:
                msg = f"Analysis failed for '{title}' @ {company}: {exc}"
                logger.warning(msg)
                errors.append(msg)
                # Continue with next job
                continue

        logger.info(
            "Analysis complete — {} analyzed, {} skipped",
            analyzed_count,
            skipped_count,
        )
        _log_completion("analyze", start, len(jobs), len(errors))

        result: dict[str, Any] = {
            "jobs": jobs,
            "stage": "analyze",
        }
        if errors:
            result["errors"] = errors
        return result

    except Exception as exc:
        msg = f"analyze_job failed: {exc}"
        logger.error(msg)
        return {"errors": [msg], "stage": "analyze"}


# ---------------------------------------------------------------------------
# Node: tailor_resume
# ---------------------------------------------------------------------------


async def tailor_resume(state: PipelineState) -> dict[str, Any]:
    """Tailor the master resume for each job with verifier gate.

    For every job:
    1. Load master resume.
    2. Build a :class:`JDAnalysis` from the job's stored analysis dict.
    3. Call :class:`ResumeTailor` to generate a tailored resume.
    4. Run :class:`ResumeVerifier` to check for hallucination.
    5. If verifier score < 60, retry (up to 2 additional attempts).
    6. Save the tailored resume and verifier report on the job dict.
    """
    _log_stage(state, "tailor")
    start = time.monotonic()
    errors: list[str] = []

    jobs = state.get("jobs", [])
    if not jobs:
        logger.info("No jobs to tailor for")
        _log_completion("tailor", start, 0)
        return {"stage": "tailor"}

    master = state.get("master_resume")
    if master is None and not state["dry_run"]:
        logger.warning("No master resume in state — loading from disk")
        try:
            from internapply.resume.parser import load_resume_json

            master = load_resume_json()
            if master is None:
                logger.error("Master resume not found — tailoring will be skipped")
        except Exception as exc:
            logger.error("Failed to load master resume: {}", exc)

    if state["dry_run"]:
        logger.info("[DRY RUN] Would tailor resume for {} jobs", len(jobs))
        for job in jobs:
            job["tailored_resume"] = copy.deepcopy(_MOCK_TAILORED)
            job["verifier_report"] = {"passed": True, "score": 100, "violations": [], "warnings": []}
            job["verifier_score"] = 100
        _log_completion("tailor", start, len(jobs))
        return {"jobs": jobs, "stage": "tailor"}

    try:
        from internapply.models import JobListing
        from internapply.resume.analyzer import JDAnalysis
        from internapply.resume.tailor import ResumeTailor
        from internapply.resume.verifier import ResumeVerifier

        tailor = ResumeTailor()
        verifier = ResumeVerifier()
        tailored_count = 0
        skipped_count = 0

        for idx, job in enumerate(jobs):
            title = job.get("title", "?")
            company = job.get("company", "?")

            analysis_dict = job.get("analysis")
            if not analysis_dict:
                logger.info("Job {} ({}) has no analysis — skipping tailoring", job.get("id"), title)
                skipped_count += 1
                continue

            description = job.get("description", "")
            if not description:
                description = analysis_dict.get("raw_text", "")

            logger.info("Tailoring resume {}/{}: {} @ {}", idx + 1, len(jobs), title, company)

            # Reconstruct JDAnalysis from stored dict
            jd_analysis = JDAnalysis(**analysis_dict)

            # Retry loop: up to 3 attempts (1 initial + 2 retries)
            best_result: dict[str, Any] | None = None
            best_score = 0

            for attempt in range(3):
                try:
                    # Acquire rate limiter token
                    await _llm_rate_limiter.acquire()

                    # Generate tailored resume
                    result = await tailor.tailor(
                        job_title=title,
                        company=company,
                        job_description=description,
                        jd_analysis=jd_analysis,
                    )
                except Exception as exc:
                    msg = f"Tailor attempt {attempt + 1}/3 failed for '{title}' @ {company}: {exc}"
                    logger.warning(msg)
                    if attempt < 2:
                        await asyncio.sleep(1.0)
                        continue
                    errors.append(msg)
                    break

                # Run ResumeVerifier
                try:
                    report = verifier.verify(
                        tailored_resume=result,
                        source_resume=master,
                    )
                    score = report.score
                    result["verifier_score"] = score
                    result["verifier_issues"] = [v.claimed_value for v in report.violations]
                except Exception as exc:
                    logger.warning("Verifier failed for '{}' @ {}: {}", title, company, exc)
                    score = 0
                    result["verifier_score"] = 0
                    result["verifier_issues"] = [str(exc)]

                # Track best
                if score > best_score:
                    best_result = result
                    best_score = score

                if score >= 60:
                    logger.info(
                        "Verifier passed for '{}' @ {} — score {}/100 (attempt {})",
                        title,
                        company,
                        score,
                        attempt + 1,
                    )
                    break

                logger.warning(
                    "Verifier score {}/100 for '{}' @ {} (attempt {}/3) — retrying...",
                    score,
                    title,
                    company,
                    attempt + 1,
                )

                if attempt < 2:
                    await asyncio.sleep(1.0)

            if best_result:
                job["tailored_resume"] = best_result
                job["verifier_score"] = best_score
                job["verifier_report"] = {
                    "score": best_score,
                    "issues": best_result.get("verifier_issues", []),
                }
                tailored_count += 1
                logger.info(
                    "Tailored resume for '{}' @ {} — verifier score {}/100",
                    title,
                    company,
                    best_score,
                )
            else:
                skipped_count += 1

        logger.info(
            "Tailoring complete — {} tailored, {} skipped/errored",
            tailored_count,
            skipped_count,
        )
        _log_completion("tailor", start, len(jobs), len(errors))

        result: dict[str, Any] = {
            "jobs": jobs,
            "stage": "tailor",
        }
        if errors:
            result["errors"] = errors
        return result

    except Exception as exc:
        msg = f"tailor_resume failed: {exc}"
        logger.error(msg)
        return {"errors": [msg], "stage": "tailor"}


# ---------------------------------------------------------------------------
# Node: generate_cover_letter
# ---------------------------------------------------------------------------


async def generate_cover_letter(state: PipelineState) -> dict[str, Any]:
    """Generate a cover letter for each job.

    Uses :class:`CoverLetterGen` which runs a two-pass draft+humanisation
    pipeline with scoring and regeneration.  The cover letter text is stored
    on each job dict and saved to ``applications/{company}_{title}/cover_letter.md``.
    """
    _log_stage(state, "cover_letter")
    start = time.monotonic()
    errors: list[str] = []

    jobs = state.get("jobs", [])
    if not jobs:
        logger.info("No jobs to generate cover letters for")
        _log_completion("cover_letter", start, 0)
        return {"stage": "cover_letter"}

    master = state.get("master_resume")
    candidate_summary = (master or {}).get("summary", "")
    candidate_name = (master or {}).get("name", "")

    if state["dry_run"]:
        logger.info("[DRY RUN] Would generate cover letters for {} jobs", len(jobs))
        for job in jobs:
            job["cover_letter"] = _MOCK_COVER_LETTER
            job["humanization_score"] = 95
        _log_completion("cover_letter", start, len(jobs))
        return {"jobs": jobs, "stage": "cover_letter"}

    try:
        from internapply.resume.cover_letter import CoverLetterGen

        cl_gen = CoverLetterGen()
        generated_count = 0
        skipped_count = 0

        for idx, job in enumerate(jobs):
            title = job.get("title", "?")
            company = job.get("company", "?")
            analysis = job.get("analysis") or {}

            # Build inputs for CoverLetterGen
            required_skills = analysis.get("required_skills", []) if analysis else []
            top_skills = required_skills[:5] if required_skills else job.get("skills", [])
            jd_summary = (analysis.get("raw_text") if analysis else "") or job.get("description", "")
            jd_summary = jd_summary[:500] if jd_summary else ""

            logger.info("Cover letter {}/{}: {} @ {}", idx + 1, len(jobs), title, company)

            try:
                # Acquire rate limiter token
                await _llm_rate_limiter.acquire()

                letter, h_score = await cl_gen.generate(
                    title=title,
                    company=company,
                    jd_summary=jd_summary,
                    top_skills=top_skills,
                    summary=candidate_summary,
                    name=candidate_name or None,
                )

                job["cover_letter"] = letter
                job["humanization_score"] = h_score
                generated_count += 1

                logger.info(
                    "Cover letter for '{}' @ {} — humanisation score {}/100",
                    title,
                    company,
                    h_score,
                )

            except Exception as exc:
                msg = f"Cover letter failed for '{title}' @ {company}: {exc}"
                logger.warning(msg)
                errors.append(msg)
                skipped_count += 1
                continue

        logger.info(
            "Cover letter generation complete — {} generated, {} skipped",
            generated_count,
            skipped_count,
        )
        _log_completion("cover_letter", start, len(jobs), len(errors))

        result: dict[str, Any] = {
            "jobs": jobs,
            "stage": "cover_letter",
        }
        if errors:
            result["errors"] = errors
        return result

    except Exception as exc:
        msg = f"generate_cover_letter failed: {exc}"
        logger.error(msg)
        return {"errors": [msg], "stage": "cover_letter"}


# ---------------------------------------------------------------------------
# Node: prepare_email
# ---------------------------------------------------------------------------


async def prepare_email(state: PipelineState) -> dict[str, Any]:
    """Find email contacts and draft a cold email for each job.

    1. Use :class:`EmailFinder` (Hunter.io) to discover hiring-manager contacts
       for the company domain.
    2. Generate a personalised cold-email draft via :class:`CoverLetterGen`
       (which includes LLM generation + humanisation scoring).
    3. Save the draft to ``applications/{company}_{title}/email_draft.md``.
    """
    _log_stage(state, "email")
    start = time.monotonic()
    errors: list[str] = []

    jobs = state.get("jobs", [])
    if not jobs:
        logger.info("No jobs to prepare emails for")
        _log_completion("email", start, 0)
        return {"stage": "email"}

    master = state.get("master_resume")
    candidate_summary = (master or {}).get("summary", "")
    candidate_name = (master or {}).get("name", "")

    if state["dry_run"]:
        logger.info("[DRY RUN] Would look up company emails and draft cold emails for {} jobs", len(jobs))
        for job in jobs:
            job["email_contacts"] = copy.deepcopy(_MOCK_EMAIL_CONTACTS)
            job["email_draft"] = _MOCK_EMAIL_DRAFT
        _log_completion("email", start, len(jobs))
        return {"jobs": jobs, "stage": "email"}

    try:
        from internapply.outreach.email_finder import EmailFinder
        from internapply.resume.cover_letter import CoverLetterGen

        finder = EmailFinder()
        cl_gen = CoverLetterGen()
        prepared_count = 0
        skipped_count = 0

        for idx, job in enumerate(jobs):
            title = job.get("title", "?")
            company = job.get("company", "?")
            url = job.get("url", "")
            analysis = job.get("analysis") or {}

            logger.info("Email {}/{}: {} @ {}", idx + 1, len(jobs), title, company)

            # ── Step 1: Find email contacts ──────────────────────────────
            contacts: list[Any] = []
            try:
                contacts = await finder.find_contacts(
                    job_url=url,
                    company_name=company,
                )
                job["email_contacts"] = [
                    {
                        "email": c.email,
                        "first_name": c.first_name,
                        "last_name": c.last_name,
                        "position": c.position,
                        "confidence": c.confidence,
                        "source": c.source,
                    }
                    for c in contacts
                ]
                if contacts:
                    logger.info(
                        "Found {} contact(s) for {}",
                        len(contacts),
                        company,
                    )
                else:
                    logger.info("No email contacts found for {}", company)
            except Exception as exc:
                msg = f"Email lookup failed for '{company}': {exc}"
                logger.warning(msg)
                errors.append(msg)
                job["email_contacts"] = []

            # ── Step 2: Generate cold email draft ────────────────────────
            try:
                required_skills = analysis.get("required_skills", [])
                top_skills = required_skills[:5] if required_skills else job.get("skills", [])
                jd_summary = analysis.get("raw_text", job.get("description", ""))[:500]

                # Acquire rate limiter token
                await _llm_rate_limiter.acquire()

                draft, h_score = await cl_gen.generate(
                    title=title,
                    company=company,
                    jd_summary=jd_summary,
                    top_skills=top_skills,
                    summary=candidate_summary,
                    name=candidate_name or None,
                )

                job["email_draft"] = draft
                job["humanization_score"] = h_score
                prepared_count += 1

                # ── Step 3: Save draft to disk ────────────────────────────
                try:
                    app_dir = _app_dir(company, title)
                    app_dir.mkdir(parents=True, exist_ok=True)
                    draft_path = app_dir / "email_draft.md"
                    draft_path.write_text(draft, encoding="utf-8")
                    logger.debug("Email draft saved to {}", draft_path)
                except OSError as exc:
                    logger.warning("Could not save email draft: {}", exc)

                # Save to DB for email send command to find
                if job.get("email_contacts"):
                    try:
                        from internapply.database import ORMApplication, get_session
                        from sqlalchemy import select
                        async with get_session() as session:
                            result = await session.execute(
                                select(ORMApplication).where(ORMApplication.job_id == job.get("id"))
                            )
                            app = result.scalar_one_or_none()
                            if app is None:
                                from internapply.database import ORMJobListing
                                from sqlalchemy import select as sel2
                                j_result = await session.execute(
                                    sel2(ORMJobListing).where(ORMJobListing.url == job.get("url", ""))
                                )
                                job_row = j_result.scalar_one_or_none()
                                if job_row:
                                    app = ORMApplication(
                                        job_id=job_row.id,
                                        status="email_drafted",
                                        email_contacts_json=json.dumps(job["email_contacts"]),
                                        email_draft_path=str(draft_path),
                                    )
                                    session.add(app)
                            else:
                                app.email_contacts_json = json.dumps(job["email_contacts"])
                                app.email_draft_path = str(draft_path)
                                app.status = "email_drafted"
                            await session.commit()
                    except Exception as db_exc:
                        logger.debug("Could not save email state to DB: {}", db_exc)

                logger.info(
                    "Email draft for '{}' @ {} — humanisation score {}/100",
                    title,
                    company,
                    h_score,
                )

            except Exception as exc:
                msg = f"Email draft failed for '{title}' @ {company}: {exc}"
                logger.warning(msg)
                errors.append(msg)
                skipped_count += 1
                continue

        logger.info(
            "Email preparation complete — {} prepared, {} skipped",
            prepared_count,
            skipped_count,
        )
        _log_completion("email", start, len(jobs), len(errors))

        result: dict[str, Any] = {
            "jobs": jobs,
            "stage": "email",
        }
        if errors:
            result["errors"] = errors
        return result

    except Exception as exc:
        msg = f"prepare_email failed: {exc}"
        logger.error(msg)
        return {"errors": [msg], "stage": "email"}


# ---------------------------------------------------------------------------
# Node: apply_to_job
# ---------------------------------------------------------------------------


async def apply_to_job(state: PipelineState) -> dict[str, Any]:
    """Submit applications via the Internshala portal.

    For each job whose source is ``"internshala"``, delegates to
    :class:`InternshalaSubmitter` to navigate, fill the form, and submit.
    Jobs from other sources are logged and skipped.

    In ``dry_run`` mode records simulated results.
    """
    _log_stage(state, "apply")
    start = time.monotonic()
    errors: list[str] = []
    warnings: list[str] = []

    jobs = state.get("jobs", [])
    if not jobs:
        logger.info("No jobs to apply to")
        _log_completion("apply", start, 0)
        return {"stage": "apply"}

    application_results: list[dict[str, Any]] = list(state.get("application_results", []))

    if state["dry_run"]:
        logger.info("[DRY RUN] Would submit {} applications via portal", len(jobs))
        for job in jobs:
            title = job.get("title", "?")
            company = job.get("company", "?")
            source = job.get("source", "?")

            if source != "internshala":
                logger.info("[DRY RUN] Skipping '{}' @ {} — source is '{}' (not internshala)", title, company, source)
                continue

            result: dict[str, Any] = {
                "job_url": job.get("url", ""),
                "title": title,
                "company": company,
                "source": source,
                "status": "simulated",
                "run_id": state.get("run_id", ""),
                "verifier_score": job.get("verifier_score"),
                "humanization_score": job.get("humanization_score"),
            }
            application_results.append(result)

        _log_completion("apply", start, len(application_results))
        return {
            "application_results": application_results,
            "stage": "apply",
        }

    try:
        from internapply.apply.internshala import InternshalaSubmitter
        from internapply.models import JobListing

        submitter = InternshalaSubmitter()
        applied_count = 0
        skipped_count = 0

        try:
            await submitter.start_session()
            logger.info("Browser session started for auto-apply")
        except Exception as exc:
            msg = f"Failed to start browser session: {exc}"
            logger.error(msg)
            return {"errors": [msg], "stage": "apply"}

        try:
            for idx, job in enumerate(jobs):
                title = job.get("title", "?")
                company = job.get("company", "?")
                source = job.get("source", "")
                url = job.get("url", "")

                # Only auto-apply on Internshala
                if source != "internshala":
                    logger.info(
                        "Skipping '{}' @ {} — source is '{}' (not internshala)",
                        title,
                        company,
                        source,
                    )
                    warnings.append(
                        f"Cannot auto-apply to '{title}' @ {company}: "
                        f"source is '{source}' (portal submission only for Internshala)"
                    )
                    application_results.append({
                        "job_url": url,
                        "title": title,
                        "company": company,
                        "source": source,
                        "status": "skipped_unsupported_source",
                        "run_id": state.get("run_id", ""),
                    })
                    skipped_count += 1
                    continue

                # Resolve paths for tailored resume and cover letter
                tailored_data = job.get("tailored_resume")
                tailored_path: str | None = None
                cover_letter_path: str | None = None

                if tailored_data:
                    try:
                        app_dir = _app_dir(company, title)
                        app_dir.mkdir(parents=True, exist_ok=True)
                        tr_path = app_dir / "tailored_resume.json"
                        tr_path.write_text(
                            json.dumps(tailored_data, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                        tailored_path = str(tr_path)
                    except OSError as exc:
                        logger.warning("Could not save tailored resume: {}", exc)

                cover_text = job.get("cover_letter")
                if cover_text:
                    try:
                        app_dir = _app_dir(company, title)
                        app_dir.mkdir(parents=True, exist_ok=True)
                        cl_path = app_dir / "cover_letter.md"
                        cl_path.write_text(cover_text, encoding="utf-8")
                        cover_letter_path = str(cl_path)
                    except OSError as exc:
                        logger.warning("Could not save cover letter: {}", exc)

                logger.info(
                    "Applying {}/{}: {} @ {} via Internshala",
                    idx + 1,
                    len(jobs),
                    title,
                    company,
                )

                try:
                    # Convert dict → JobListing
                    job_model = JobListing(**job)

                    success = await submitter.apply(
                        job=job_model,
                        tailored_resume_path=tailored_path,
                        cover_letter_path=cover_letter_path,
                        dry_run=False,
                    )

                    status = "submitted" if success else "failed"
                    if success:
                        applied_count += 1
                    else:
                        errors.append(f"Application to '{title}' @ {company} failed (submitter returned False)")

                except RuntimeError as exc:
                    # Per-session or daily limit hit
                    logger.warning("Application limit hit: {}", exc)
                    errors.append(str(exc))
                    status = "limit_exceeded"
                    break  # Stop applying — limits are per-session
                except Exception as exc:
                    msg = f"Application to '{title}' @ {company} failed: {exc}"
                    logger.warning(msg)
                    errors.append(msg)
                    status = "error"

                application_results.append({
                    "job_url": url,
                    "title": title,
                    "company": company,
                    "source": source,
                    "status": status,
                    "run_id": state.get("run_id", ""),
                    "verifier_score": job.get("verifier_score"),
                    "humanization_score": job.get("humanization_score"),
                })

        finally:
            await submitter.close_session()
            logger.info("Browser session closed")

        logger.info(
            "Apply complete — {} submitted, {} skipped/errored",
            applied_count,
            skipped_count,
        )
        _log_completion("apply", start, len(application_results), len(errors))

        result: dict[str, Any] = {
            "application_results": application_results,
            "stage": "apply",
        }
        if errors:
            result["errors"] = errors
        if warnings:
            result["warnings"] = warnings
        return result

    except Exception as exc:
        msg = f"apply_to_job failed: {exc}"
        logger.error(msg)
        return {"errors": [msg], "stage": "apply"}


# ---------------------------------------------------------------------------
# Node exports
# ---------------------------------------------------------------------------

__all__ = [
    "analyze_job",
    "apply_to_job",
    "discover_jobs",
    "filter_jobs",
    "generate_cover_letter",
    "prepare_email",
    "tailor_resume",
]
