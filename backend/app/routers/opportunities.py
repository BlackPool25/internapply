from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, outerjoin

from backend.app.database import get_session
from backend.app.models import JobListing, Application, TailoredResume, CoverEmail

router = APIRouter(prefix="/api/v1/opportunities", tags=["opportunities"])


def _stipend_to_salary(job: JobListing) -> str:
    if job.stipend_min and job.stipend_max:
        return f"₹{job.stipend_min}-{job.stipend_max}/mo"
    if job.stipend_min:
        return f"₹{job.stipend_min}/mo"
    return ""


def _to_frontend_opportunity(
    job: JobListing, app: Application | None = None, tr: TailoredResume | None = None
) -> dict:
    opp = {
        "id": str(job.id),
        "company": job.company,
        "role": job.title or "",
        "source": job.source or "",
        "status": app.status if app else "discovered",
        "contactName": "",
        "contactEmail": "",
        "matchScore": tr.verifier_score if (tr and tr.verifier_score) else 0,
        "date": str(job.created_at) if job.created_at else "",
        "location": job.location or "",
        "salary": _stipend_to_salary(job),
        "jobUrl": job.url or "",
        "notes": "",
        "companyDescription": job.description or "",
        "companySize": "",
        "industry": "",
        "researchSummary": tr.resume_data.get("summary", "") if (tr and tr.resume_data) else (job.description or ""),
        "people": [],
    }
    return opp


@router.get("")
async def list_opportunities(
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """List all opportunities (job listings) with application status."""
    stmt = (
        select(JobListing, Application, TailoredResume)
        .outerjoin(Application, Application.job_listing_id == JobListing.id)
        .outerjoin(TailoredResume, TailoredResume.application_id == Application.id)
        .order_by(JobListing.created_at.desc())
        .limit(100)
    )
    result = await session.execute(stmt)
    rows = result.all()
    return [_to_frontend_opportunity(job, app, tr) for job, app, tr in rows]


@router.get("/{id}")
async def get_opportunity(
    id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
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
