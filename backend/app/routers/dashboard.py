from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.models import JobListing, Company, Application

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

FREELANCE_SOURCES = {"freelance", "freelancer", "internshala_freelance", "upwork"}


def _get_source_tier(source: str) -> str:
    s = (source or "").lower()
    if s in ("ashby", "greenhouse", "lever", "smartrecruiters"):
        return "Tier 0 (ATS)"
    if s in ("hirist", "unstop", "internshala"):
        return "Tier 1 (Portals)"
    if s in ("jobspy", "jobspy_linkedin", "linkedin", "indeed", "glassdoor", "ziprecruiter"):
        return "Tier 2 (Aggregators)"
    return "Tier 3 (APIs & RSS)"


@router.get("/stats")
async def dashboard_stats(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return aggregate dashboard statistics including stage and tier breakdowns."""
    total_opps_res = await session.execute(select(func.count(JobListing.id)))
    total_opps = total_opps_res.scalar() or 0

    total_companies_res = await session.execute(select(func.count(Company.id)))
    total_companies = total_companies_res.scalar() or 0

    # Aggregate applications by status
    apps_stmt = select(Application.status, func.count(Application.id)).group_by(Application.status)
    apps_res = await session.execute(apps_stmt)
    raw_stage_counts: dict[str, int] = {}
    for row in apps_res.all():
        if row[0]:
            k = row[0].lower().strip()
            raw_stage_counts[k] = raw_stage_counts.get(k, 0) + row[1]

    # Total assigned vs unassigned (unassigned are considered 'discovered')
    assigned_count = sum(raw_stage_counts.values())
    unassigned_count = max(0, total_opps - assigned_count)

    by_stage = {
        "discovered": unassigned_count + raw_stage_counts.get("discovered", 0) + raw_stage_counts.get("saved", 0),
        "reviewing": raw_stage_counts.get("reviewing", 0) + raw_stage_counts.get("pending_review", 0),
        "applied": raw_stage_counts.get("applied", 0) + raw_stage_counts.get("batch_ready", 0),
        "interviewing": raw_stage_counts.get("interviewing", 0) + raw_stage_counts.get("interview_scheduled", 0),
        "offer": raw_stage_counts.get("offer", 0) + raw_stage_counts.get("accepted", 0),
        "rejected": raw_stage_counts.get("rejected", 0),
    }

    # Aggregate source counts and source tier breakdown
    sources_stmt = select(JobListing.source, func.count(JobListing.id)).group_by(JobListing.source)
    sources_res = await session.execute(sources_stmt)
    source_counts: dict[str, int] = {}
    for row in sources_res.all():
        if row[0]:
            source_counts[row[0]] = row[1]

    tier_counts = {
        "Tier 0 (ATS)": 0,
        "Tier 1 (Portals)": 0,
        "Tier 2 (Aggregators)": 0,
        "Tier 3 (APIs & RSS)": 0,
    }

    freelance_count = 0
    internship_count = 0

    for src, cnt in source_counts.items():
        s = (src or "").lower()
        if s in FREELANCE_SOURCES:
            freelance_count += cnt
        else:
            internship_count += cnt

        tier = _get_source_tier(s)
        if tier in tier_counts:
            tier_counts[tier] += cnt

    return {
        "total_opportunities": total_opps,
        "totalOpportunities": total_opps,
        "total_companies": total_companies,
        "totalCompanies": total_companies,
        "pending_review": by_stage["reviewing"],
        "pendingReview": by_stage["reviewing"],
        "batch_ready": by_stage["applied"],
        "batchReady": by_stage["applied"],
        "total_internships": internship_count,
        "total_freelance": freelance_count,
        "by_stage": by_stage,
        "by_source_tier": tier_counts,
        "by_source": source_counts,
    }


@router.get("/activity")
async def dashboard_activity(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Return recent activity items with rich event tags."""
    result = await session.execute(
        select(JobListing, Application)
        .outerjoin(Application, Application.job_listing_id == JobListing.id)
        .order_by(JobListing.created_at.desc())
        .limit(15)
    )
    rows = result.all()
    activities: list[dict[str, Any]] = []

    for job, app in rows:
        stage = (app.status if app and app.status else "discovered").lower()
        event_type = "application"
        if stage == "reviewing":
            event_type = "status_change"
        elif stage == "applied":
            event_type = "email"

        activities.append({
            "id": f"act-{job.id}",
            "type": event_type,
            "stage": stage,
            "message": f"{job.title} @ {job.company}",
            "source": job.source or "unknown",
            "timestamp": str(job.created_at) if job.created_at else "",
            "opportunityId": str(job.id),
        })

    return activities
