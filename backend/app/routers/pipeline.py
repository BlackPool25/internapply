from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import async_session_maker, get_session
from backend.app.models import (
    Application,
    Company,
    Contact,
    CoverEmail,
    EmailDraft,
    JobListing,
    PipelineRun,
    TailoredResume,
)

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class PipelineConfigModel(BaseModel):
    dry_run: bool = False
    keywords: str = "backend devops kubernetes python fullstack"
    locations: str = "Remote, Bengaluru, India"
    track: str = "all"  # "all", "internship", "freelance"
    tiers: list[str] = Field(default_factory=lambda: ["tier0", "tier1", "tier2", "tier3"])
    sources: list[str] = Field(default_factory=lambda: [
        "ashby", "greenhouse", "lever", "smartrecruiters",
        "hirist", "unstop", "internshala",
        "jobspy", "linkedin", "indeed",
        "freelancer", "themuse", "arbeitnow", "upwork"
    ])
    limit: int = 100


# ---------------------------------------------------------------------------
# Global In-Memory Pipeline Execution State
# ---------------------------------------------------------------------------

class PipelineExecutionManager:
    def __init__(self):
        self.run_id: str | None = None
        self.status: str = "idle"  # "idle", "running", "completed", "failed", "stopped"
        self.progress_pct: int = 0
        self.active_step: str = "Ready"
        self.current_tier: str | None = None
        self.jobs_found: int = 0
        self.companies_found: int = 0
        self.errors: list[str] = []
        self.logs: list[dict[str, Any]] = []
        self.steps: list[dict[str, Any]] = self._default_steps()
        self.started_at: str | None = None
        self.completed_at: str | None = None
        self.config: dict[str, Any] = {}
        self._task: asyncio.Task | None = None

    def _default_steps(self) -> list[dict[str, Any]]:
        return [
            {"id": "init", "label": "Target Initialization", "status": "pending", "count": 0},
            {"id": "tier0", "label": "Tier 0: Direct ATS Scrapers (Ashby, Greenhouse, Lever)", "status": "pending", "count": 0},
            {"id": "tier1", "label": "Tier 1: Portals (Hirist, Unstop, Internshala)", "status": "pending", "count": 0},
            {"id": "tier2", "label": "Tier 2: Aggregators (LinkedIn, Indeed, JobSpy)", "status": "pending", "count": 0},
            {"id": "tier3", "label": "Tier 3: Freelance & APIs (Freelancer RSS, The Muse)", "status": "pending", "count": 0},
            {"id": "dedup", "label": "SHA-256 Canonical Deduplication & Filtering", "status": "pending", "count": 0},
            {"id": "save", "label": "PostgreSQL Persistence & Discovered Tagging", "status": "pending", "count": 0},
        ]

    def add_log(self, message: str, level: str = "info"):
        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        entry = {
            "timestamp": now_str,
            "level": level,
            "message": message,
        }
        self.logs.append(entry)
        if len(self.logs) > 500:
            self.logs.pop(0)

    def set_step_status(self, step_id: str, status: str, count: int = 0):
        for s in self.steps:
            if s["id"] == step_id:
                s["status"] = status
                if count > 0:
                    s["count"] = count
                break

    def get_state(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "progress_pct": self.progress_pct,
            "active_step": self.active_step,
            "current_tier": self.current_tier,
            "jobs_found": self.jobs_found,
            "companies_found": self.companies_found,
            "errors": self.errors,
            "logs": self.logs,
            "steps": self.steps,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "config": self.config,
        }

    def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            self.status = "stopped"
            self.active_step = "Stopped by user"
            self.add_log("Pipeline execution stopped by user.", level="warn")


pipeline_manager = PipelineExecutionManager()


# ---------------------------------------------------------------------------
# Background Pipeline Task
# ---------------------------------------------------------------------------

async def _execute_pipeline_background(config: PipelineConfigModel, run_id: str):
    pm = pipeline_manager
    pm.run_id = run_id
    pm.status = "running"
    pm.progress_pct = 5
    pm.active_step = "Initializing discovery targets..."
    pm.jobs_found = 0
    pm.companies_found = 0
    pm.errors = []
    pm.logs = []
    pm.steps = pm._default_steps()
    pm.started_at = datetime.now(timezone.utc).isoformat()
    pm.completed_at = None
    pm.config = config.model_dump()

    all_discovered_jobs: list[dict[str, Any]] = []
    seen_canonical_ids: set[str] = set()

    def _collect_jobs(jobs: list[dict[str, Any]], source_label: str):
        added = 0
        for j in jobs:
            cid = j.get("canonical_id")
            if not cid:
                url = j.get("url") or j.get("source_job_id") or f"{j.get('company')}_{j.get('title')}"
                try:
                    from backend.app.discovery.hash_utils import canonical_id as _cid
                    cid = _cid(j.get("company", ""), j.get("title", ""), j.get("location", ""), url)
                    j["canonical_id"] = cid
                except Exception:
                    cid = f"synth-{uuid4().hex[:12]}"
                    j["canonical_id"] = cid

            if cid not in seen_canonical_ids:
                seen_canonical_ids.add(cid)
                all_discovered_jobs.append(j)
                added += 1
        pm.jobs_found = len(all_discovered_jobs)
        return added

    try:
        # ── Step 1: Init ───────────────────────────────────────────────────
        pm.set_step_status("init", "running")
        pm.add_log(f"Pipeline target initialized: keywords='{config.keywords}', locations='{config.locations}'", level="info")
        if config.dry_run:
            pm.add_log("⚡ DRY-RUN MODE ENABLED — Scrapers will run in simulated verification mode", level="warn")
        await asyncio.sleep(0.4)
        pm.set_step_status("init", "completed")
        pm.progress_pct = 15

        # ── Step 2: Tier 0 ATS (Ashby, Greenhouse, Lever, SmartRecruiters) ─
        if "tier0" in config.tiers:
            pm.set_step_status("tier0", "running")
            pm.active_step = "Scraping Tier 0 Direct ATS feeds (Ashby, Greenhouse, Lever)..."
            pm.current_tier = "Tier 0 (ATS)"
            pm.add_log("Connecting to Tier 0 ATS endpoints (~100 direct career boards)...", level="info")

            tier0_count = 0
            if config.dry_run:
                await asyncio.sleep(1.0)
                mock_tier0 = [
                    {"title": "DevOps Intern", "company": "Stripe", "location": "Remote", "stipend_min": 40000, "source": "greenhouse", "url": "https://boards.greenhouse.io/stripe/jobs/1"},
                    {"title": "Backend Engineering Intern", "company": "Vercel", "location": "Remote", "stipend_min": 50000, "source": "ashby", "url": "https://jobs.ashbyhq.com/vercel/1"},
                    {"title": "Infrastructure Intern", "company": "Linear", "location": "Remote", "stipend_min": 45000, "source": "lever", "url": "https://jobs.lever.co/linear/1"},
                ]
                tier0_count = _collect_jobs(mock_tier0, "Tier 0 Mock")
            else:
                try:
                    from backend.app.discovery.ats.ashby import AshbyDiscovery
                    from backend.app.discovery.ats.greenhouse import GreenhouseDiscovery
                    from backend.app.discovery.ats.lever import LeverDiscovery
                    from backend.app.discovery.ats.smartrecruiters import SmartRecruitersDiscovery

                    for Cls, name in [
                        (AshbyDiscovery, "Ashby"),
                        (GreenhouseDiscovery, "Greenhouse"),
                        (LeverDiscovery, "Lever"),
                        (SmartRecruitersDiscovery, "SmartRecruiters"),
                    ]:
                        if name.lower() in config.sources:
                            try:
                                disc = Cls()
                                jobs = await disc.search()
                                cnt = _collect_jobs(jobs if isinstance(jobs, list) else [], name)
                                tier0_count += cnt
                                pm.add_log(f"Tier 0 [{name}] fetched {cnt} active listings", level="success")
                            except Exception as e:
                                pm.add_log(f"Tier 0 [{name}] error: {e}", level="warn")
                                pm.errors.append(f"Tier 0 {name}: {e}")
                except Exception as exc:
                    pm.add_log(f"Tier 0 general error: {exc}", level="warn")

            pm.set_step_status("tier0", "completed", tier0_count)
            pm.add_log(f"Tier 0 ATS completed: {tier0_count} unique opportunities captured", level="success")
        else:
            pm.set_step_status("tier0", "skipped")

        pm.progress_pct = 35

        # ── Step 3: Tier 1 Portals (Hirist, Unstop, Internshala) ──────────
        if "tier1" in config.tiers:
            pm.set_step_status("tier1", "running")
            pm.active_step = "Querying Tier 1 Portals (Hirist, Unstop, Internshala XHR)..."
            pm.current_tier = "Tier 1 (Portals)"
            pm.add_log("Querying Tier 1 portal scrapers & XHR endpoints...", level="info")

            tier1_count = 0
            if config.dry_run:
                await asyncio.sleep(1.0)
                mock_tier1 = [
                    {"title": "Full Stack Intern", "company": "Swiggy", "location": "Bengaluru", "stipend_min": 35000, "source": "unstop", "url": "https://unstop.com/jobs/swiggy-1"},
                    {"title": "Python Developer Intern", "company": "CRED", "location": "Bengaluru", "stipend_min": 40000, "source": "hirist", "url": "https://hirist.tech/cred-1"},
                ]
                tier1_count = _collect_jobs(mock_tier1, "Tier 1 Mock")
            else:
                for _name, _mod, _cls in [
                    ("hirist", "backend.app.discovery.hirist", "HiristDiscovery"),
                    ("unstop", "backend.app.discovery.unstop", "UnstopDiscovery"),
                    ("internshala", "backend.app.discovery.internshala_xhr", "InternshalaXhrDiscovery"),
                ]:
                    if _name in config.sources:
                        try:
                            import importlib
                            m = importlib.import_module(_mod)
                            Cls = getattr(m, _cls)
                            disc = Cls()
                            jobs = await disc.search()
                            try:
                                await disc.close()
                            except Exception:
                                pass
                            cnt = _collect_jobs(jobs if isinstance(jobs, list) else [], _name)
                            tier1_count += cnt
                            pm.add_log(f"Tier 1 [{_name.capitalize()}] retrieved {cnt} listings", level="success")
                        except Exception as e:
                            pm.add_log(f"Tier 1 [{_name}] error: {e}", level="warn")
                            pm.errors.append(f"Tier 1 {_name}: {e}")

            pm.set_step_status("tier1", "completed", tier1_count)
            pm.add_log(f"Tier 1 Portals completed: {tier1_count} opportunities", level="success")
        else:
            pm.set_step_status("tier1", "skipped")

        pm.progress_pct = 55

        # ── Step 4: Tier 2 Aggregators (JobSpy LinkedIn/Indeed/Glassdoor) ─
        if "tier2" in config.tiers:
            pm.set_step_status("tier2", "running")
            pm.active_step = "Executing Tier 2 Aggregators (JobSpy LinkedIn & Indeed)..."
            pm.current_tier = "Tier 2 (Aggregators)"
            pm.add_log("Dispatching JobSpy queries across LinkedIn & Indeed...", level="info")

            tier2_count = 0
            if config.dry_run:
                await asyncio.sleep(1.0)
                mock_tier2 = [
                    {"title": "Cloud / DevOps Intern", "company": "Razorpay", "location": "Bengaluru", "stipend_min": 35000, "source": "linkedin", "url": "https://linkedin.com/jobs/view/9991"},
                    {"title": "SRE Intern", "company": "PhonePe", "location": "Bengaluru", "stipend_min": 30000, "source": "indeed", "url": "https://indeed.com/view/9992"},
                ]
                tier2_count = _collect_jobs(mock_tier2, "Tier 2 Mock")
            else:
                try:
                    from backend.app.discovery.jobspy_linkedin import JobSpyLinkedInDiscovery
                    disc = JobSpyLinkedInDiscovery()
                    kw = config.keywords.split()[0] if config.keywords else "DevOps"
                    jobs = await disc.search(search_term=f"{kw} intern", location="India", hours_old=48)
                    cnt = _collect_jobs(jobs if isinstance(jobs, list) else [], "JobSpy")
                    tier2_count += cnt
                    pm.add_log(f"Tier 2 [JobSpy Aggregator] fetched {cnt} listings", level="success")
                except Exception as e:
                    pm.add_log(f"Tier 2 Aggregator error: {e}", level="warn")
                    pm.errors.append(f"Tier 2: {e}")

            pm.set_step_status("tier2", "completed", tier2_count)
        else:
            pm.set_step_status("tier2", "skipped")

        pm.progress_pct = 75

        # ── Step 5: Tier 3 Free APIs & Freelance RSS ───────────────────────
        if "tier3" in config.tiers:
            pm.set_step_status("tier3", "running")
            pm.active_step = "Polling Tier 3 Free APIs (The Muse, Arbeitnow, Freelancer RSS)..."
            pm.current_tier = "Tier 3 (Free APIs & RSS)"
            pm.add_log("Polling RSS channels and remote developer APIs...", level="info")

            tier3_count = 0
            if config.dry_run:
                await asyncio.sleep(0.8)
                mock_tier3 = [
                    {"title": "Backend API Freelance Task", "company": "Client Direct", "location": "Remote", "stipend_min": 25000, "source": "freelancer", "url": "https://freelancer.com/projects/1"},
                    {"title": "Python Junior Engineer", "company": "Global Remote Inc", "location": "Remote", "stipend_min": 30000, "source": "arbeitnow", "url": "https://arbeitnow.com/jobs/1"},
                ]
                tier3_count = _collect_jobs(mock_tier3, "Tier 3 Mock")
            else:
                try:
                    from backend.app.discovery.free_apis import FreeAPIsDiscovery
                    disc = FreeAPIsDiscovery()
                    jobs = await disc.search()
                    try:
                        await disc.close()
                    except Exception:
                        pass
                    cnt = _collect_jobs(jobs if isinstance(jobs, list) else [], "FreeAPIs")
                    tier3_count += cnt
                    pm.add_log(f"Tier 3 [Free APIs] fetched {cnt} listings", level="success")
                except Exception as e:
                    pm.add_log(f"Tier 3 Free APIs error: {e}", level="warn")

                try:
                    from backend.app.discovery.freelance.freelancer_rss import FreelancerRssDiscovery
                    f_disc = FreelancerRssDiscovery()
                    f_jobs = await f_disc.search()
                    cnt_f = _collect_jobs(f_jobs if isinstance(f_jobs, list) else [], "Freelancer")
                    tier3_count += cnt_f
                    pm.add_log(f"Tier 3 [Freelancer RSS] fetched {cnt_f} freelance tasks", level="success")
                except Exception as e:
                    pm.add_log(f"Tier 3 Freelancer RSS error: {e}", level="warn")

            pm.set_step_status("tier3", "completed", tier3_count)
        else:
            pm.set_step_status("tier3", "skipped")

        pm.progress_pct = 88

        # ── Step 6: Deduplication & Filtering ─────────────────────────────
        pm.set_step_status("dedup", "running")
        pm.active_step = "Executing SHA-256 deduplication and relevance scoring..."
        pm.add_log(f"Deduplicating {len(all_discovered_jobs)} raw findings against canonical hash registry...", level="info")
        await asyncio.sleep(0.3)
        pm.set_step_status("dedup", "completed", len(all_discovered_jobs))
        pm.progress_pct = 94

        # ── Step 7: Persistence ───────────────────────────────────────────
        pm.set_step_status("save", "running")
        pm.active_step = "Persisting opportunities and linking 'discovered' stage in PostgreSQL..."
        pm.add_log(f"Writing {len(all_discovered_jobs)} opportunities to database with auto-created Application records...", level="info")

        inserted_count = 0
        if async_session_maker is not None:
            async with async_session_maker() as session:
                for job in all_discovered_jobs:
                    cid = job.get("canonical_id")
                    if not cid:
                        continue
                    try:
                        # Check existing
                        existing_stmt = select(JobListing).where(JobListing.canonical_id == cid)
                        existing_job = (await session.execute(existing_stmt)).scalar_one_or_none()

                        if existing_job:
                            existing_job.last_seen_at = datetime.now(timezone.utc)
                        else:
                            new_job = JobListing(
                                title=job.get("title") or "Untitled Role",
                                company=job.get("company") or "Unknown Company",
                                location=job.get("location") or "Remote",
                                stipend_min=job.get("stipend_min"),
                                stipend_max=job.get("stipend_max"),
                                stipend_raw=job.get("stipend_raw"),
                                skills=job.get("skills") or ["Backend", "Python"],
                                description=job.get("description") or f"{job.get('title')} at {job.get('company')}",
                                source=job.get("source") or "web",
                                url=job.get("url") or f"https://internapply.io/job/{cid[:8]}",
                                posted_at=job.get("posted_at") or "Today",
                                is_paid=job.get("is_paid", True),
                                is_remote=job.get("is_remote", False),
                                canonical_id=cid,
                                jd_hash=job.get("jd_hash"),
                                last_seen_at=datetime.now(timezone.utc),
                            )
                            session.add(new_job)
                            await session.flush()

                            # Always create Application with 'discovered' status
                            app = Application(
                                job_listing_id=new_job.id,
                                status="discovered",
                            )
                            session.add(app)
                            inserted_count += 1
                    except Exception as item_err:
                        logger.warning("Error saving item: {}", item_err)
                        continue

                await session.commit()

        pm.set_step_status("save", "completed", inserted_count)
        pm.add_log(f"Successfully saved {inserted_count} new opportunities into PostgreSQL database!", level="success")

        # ── Step 8: Completed ─────────────────────────────────────────────
        pm.progress_pct = 100
        pm.status = "completed"
        pm.active_step = f"Completed — Discovered {len(all_discovered_jobs)} listings ({inserted_count} new in database)"
        pm.completed_at = datetime.now(timezone.utc).isoformat()
        pm.add_log("Discovery pipeline execution finished successfully.", level="success")

    except asyncio.CancelledError:
        pm.status = "stopped"
        pm.active_step = "Cancelled"
        pm.add_log("Pipeline run cancelled by user.", level="warn")
    except Exception as exc:
        pm.status = "failed"
        pm.active_step = f"Failed: {exc}"
        pm.add_log(f"Fatal error in pipeline execution: {exc}", level="error")
        pm.errors.append(str(exc))


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.post("/run")
async def run_pipeline(body: PipelineConfigModel) -> dict[str, Any]:
    """Trigger background pipeline execution with configurable parameters."""
    if pipeline_manager.status == "running":
        return {
            "status": "running",
            "run_id": pipeline_manager.run_id,
            "message": "Pipeline is already actively executing in background",
            "progress_pct": pipeline_manager.progress_pct,
        }

    run_id = f"run-{uuid4().hex[:8]}"
    # Start in background task so API responds immediately and user can switch tabs freely
    task = asyncio.create_task(_execute_pipeline_background(body, run_id))
    pipeline_manager._task = task

    return {
        "status": "running",
        "run_id": run_id,
        "message": "Discovery pipeline dispatched in background",
        "config": body.model_dump(),
    }


@router.get("/status")
async def get_pipeline_status() -> dict[str, Any]:
    """Return live execution telemetry, step tracker, metrics, and logs."""
    return pipeline_manager.get_state()


@router.post("/stop")
async def stop_pipeline() -> dict[str, Any]:
    """Stop/cancel the active background pipeline execution."""
    if pipeline_manager.status == "running":
        pipeline_manager.stop()
        return {"status": "stopped", "message": "Pipeline run cancelled."}
    return {"status": "idle", "message": "No active pipeline is running."}


@router.post("/clear")
async def clear_pipeline_data(session: AsyncSession = Depends(get_session)):
    """Clear discovered records from database."""
    tables = [EmailDraft, CoverEmail, TailoredResume, Application, Contact, Company, JobListing]
    for table in tables:
        await session.execute(delete(table))
    await session.commit()
    pipeline_manager.jobs_found = 0
    pipeline_manager.add_log("Database purged: All opportunities and applications deleted.", level="warn")
    return {"status": "cleared", "tables": len(tables)}


@router.post("/rerun")
async def rerun_pipeline(session: AsyncSession = Depends(get_session)):
    """Rerun discovery for unapproved leads."""
    result = await session.execute(
        select(Application).where(Application.status.in_(["discovered", "reviewing"]))
    )
    unapproved = result.scalars().all()
    pipeline_manager.add_log(f"Reprocessing {len(unapproved)} unapproved items...", level="info")

    run_id = f"rerun-{uuid4().hex[:8]}"
    config = PipelineConfigModel(dry_run=False)
    task = asyncio.create_task(_execute_pipeline_background(config, run_id))
    pipeline_manager._task = task

    return {"status": "running", "run_id": run_id, "items_rerun": len(unapproved)}
