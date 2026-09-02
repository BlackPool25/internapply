from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from backend.app.database import get_session
from backend.app.models import JobListing, Application, TailoredResume, CoverEmail

router = APIRouter(prefix="/api/v1/opportunities", tags=["opportunities"])

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


def _get_source_type(source: str) -> str:
    return "freelance" if (source or "").lower() in FREELANCE_SOURCES else "internship"


def _stipend_to_salary(job: JobListing) -> str:
    if job.stipend_min and job.stipend_max:
        return f"₹{job.stipend_min:,} - ₹{job.stipend_max:,}/mo"
    if job.stipend_min:
        return f"₹{job.stipend_min:,}/mo"
    if job.stipend_raw:
        return job.stipend_raw
    return "Not disclosed"


def _normalize_stage(status: str | None) -> str:
    if not status:
        return "discovered"
    s = status.strip().lower()
    stage_map = {
        "pending_review": "reviewing",
        "reviewing": "reviewing",
        "saved": "discovered",
        "discovered": "discovered",
        "batch_ready": "applied",
        "applied": "applied",
        "interview_scheduled": "interviewing",
        "interviewing": "interviewing",
        "offer": "offer",
        "accepted": "offer",
        "rejected": "rejected",
        "ongoing": "ongoing",
        "closed": "closed",
        "cancelled": "cancelled",
    }
    return stage_map.get(s, s)


def _to_frontend_opportunity(
    job: JobListing, app: Application | None = None, tr: TailoredResume | None = None
) -> dict[str, Any]:
    source_type = _get_source_type(job.source)
    tier = _get_source_tier(job.source)
    raw_status = app.status if app and app.status else "discovered"
    stage = _normalize_stage(raw_status)

    opp = {
        "id": str(job.id),
        "company": job.company or "Unknown Company",
        "role": job.title or "Untitled Role",
        "source": job.source or "",
        "source_type": source_type,
        "tier": tier,
        "status": stage,
        "stage": stage,
        "contactName": "",
        "contactEmail": "",
        "matchScore": tr.verifier_score if (tr and tr.verifier_score) else (getattr(job, "fit_score", None) or 0),
        "verifier_score": tr.verifier_score if tr else None,
        "date": str(job.created_at) if job.created_at else "",
        "created_at": str(job.created_at) if job.created_at else "",
        "location": job.location or "Remote / Unspecified",
        "salary": _stipend_to_salary(job),
        "stipend_min": job.stipend_min,
        "stipend_max": job.stipend_max,
        "stipend_raw": job.stipend_raw,
        "is_paid": job.is_paid,
        "is_remote": job.is_remote,
        "canonical_id": job.canonical_id or "",
        "jd_hash": job.jd_hash or "",
        "skills": job.skills or [],
        "jobUrl": job.url or "",
        "notes": app.notes if app and app.notes else "",
        "companyDescription": job.description or "",
        "companySize": "",
        "industry": "",
        "researchSummary": tr.resume_data.get("summary", "") if (tr and tr.resume_data) else (job.description or ""),
        "people": [],
    }
    return opp


class UpdateStageRequest(BaseModel):
    stage: str


@router.get("")
async def list_opportunities(
    source_type: str | None = None,
    stage: str | None = None,
    company_id: int | None = None,
    search: str | None = None,
    limit: int = 500,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List all opportunities with stage, source_type, and company filters."""
    stmt = (
        select(JobListing, Application, TailoredResume)
        .outerjoin(Application, Application.job_listing_id == JobListing.id)
        .outerjoin(TailoredResume, TailoredResume.application_id == Application.id)
    )

    if source_type:
        st = source_type.lower().strip()
        if st == "freelance":
            stmt = stmt.where(func.lower(JobListing.source).in_(FREELANCE_SOURCES))
        elif st == "internship":
            stmt = stmt.where(~func.lower(JobListing.source).in_(FREELANCE_SOURCES))

    if stage:
        stg = stage.lower().strip()
        if stg == "discovered":
            stmt = stmt.where(
                (Application.status.is_(None)) |
                (func.lower(Application.status) == "discovered") |
                (func.lower(Application.status) == "saved")
            )
        elif stg in ("reviewing", "pending_review"):
            stmt = stmt.where(func.lower(Application.status).in_(["reviewing", "pending_review"]))
        elif stg in ("applied", "batch_ready"):
            stmt = stmt.where(func.lower(Application.status).in_(["applied", "batch_ready"]))
        elif stg in ("interviewing", "interview_scheduled"):
            stmt = stmt.where(func.lower(Application.status).in_(["interviewing", "interview_scheduled"]))
        elif stg in ("offer", "accepted"):
            stmt = stmt.where(func.lower(Application.status).in_(["offer", "accepted"]))
        else:
            stmt = stmt.where(func.lower(Application.status) == stg)

    if search:
        s_pat = f"%{search.strip()}%"
        stmt = stmt.where(
            JobListing.title.ilike(s_pat) |
            JobListing.company.ilike(s_pat) |
            JobListing.location.ilike(s_pat)
        )

    stmt = stmt.order_by(JobListing.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    rows = result.all()
    return [_to_frontend_opportunity(job, app, tr) for job, app, tr in rows]


@router.patch("/{id}/stage")
async def update_opportunity_stage(
    id: int,
    body: UpdateStageRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update opportunity stage/status (Discovered, Reviewing, Applied, Interviewing, Offer, Rejected, etc.)."""
    job_stmt = select(JobListing).where(JobListing.id == id)
    job = (await session.execute(job_stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    clean_stage = body.stage.strip().lower()
    if not clean_stage:
        raise HTTPException(status_code=422, detail="Stage cannot be empty")

    app_stmt = select(Application).where(Application.job_listing_id == id)
    app = (await session.execute(app_stmt)).scalar_one_or_none()

    if app:
        app.status = clean_stage
    else:
        app = Application(
            job_listing_id=id,
            status=clean_stage,
        )
        session.add(app)

    await session.commit()
    await session.refresh(app)

    tr_stmt = select(TailoredResume).where(TailoredResume.application_id == app.id)
    tr = (await session.execute(tr_stmt)).scalar_one_or_none()

    return _to_frontend_opportunity(job, app, tr)


@router.get("/{id}")
async def get_opportunity(
    id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get single opportunity with full details (frontend shape)."""
    stmt = (
        select(JobListing, Application)
        .outerjoin(Application, Application.job_listing_id == JobListing.id)
        .where(JobListing.id == id)
    )
    row = (await session.execute(stmt)).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    job, app = row
    opp = _to_frontend_opportunity(job, app)

    # Enrich with tailored resume and cover email if available
    if app:
        tr_stmt = select(TailoredResume).where(TailoredResume.application_id == app.id)
        tr = (await session.execute(tr_stmt)).scalar_one_or_none()
        if tr:
            rd = tr.resume_data or {}
            opp["matchScore"] = tr.verifier_score or 0
            opp["verifier_score"] = tr.verifier_score
            opp["researchSummary"] = rd.get("summary", "")
            opp["notes"] = f"Tailored resume v{tr.version} — skills: {len(rd.get('skills_reordered', []))}"

        ce_stmt = select(CoverEmail).where(CoverEmail.application_id == app.id)
        ce = (await session.execute(ce_stmt)).scalar_one_or_none()
        if ce:
            opp["coverEmail"] = {
                "id": str(ce.id),
                "subject": ce.subject or f"Application for {job.title}",
                "body": ce.body,
                "status": "draft",
            }

    return opp
