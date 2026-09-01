from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session
from backend.app.models import JobListing, Company, Application

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/stats")
async def dashboard_stats(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return aggregate dashboard statistics."""
    total_opps = await session.execute(select(func.count(JobListing.id)))
    total_companies = await session.execute(select(func.count(Company.id)))
    pending = await session.execute(
        select(func.count(Application.id)).where(Application.status == "pending_review")
    )
    batch_ready = await session.execute(
        select(func.count(Application.id)).where(Application.status == "batch_ready")
    )
    return {
        "total_opportunities": total_opps.scalar() or 0,
        "total_companies": total_companies.scalar() or 0,
        "pending_review": pending.scalar() or 0,
        "batch_ready": batch_ready.scalar() or 0,
    }


@router.get("/activity")
async def dashboard_activity(
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Return recent activity items (frontend Activity shape)."""
    result = await session.execute(
        select(JobListing).order_by(JobListing.created_at.desc()).limit(10)
    )
    jobs = result.scalars().all()
    return [
        {
            "id": f"act-{j.id}",
            "type": "application",
            "message": f"Found: {j.title} @ {j.company}",
            "timestamp": str(j.created_at),
            "opportunityId": str(j.id),
        }
        for j in jobs
    ]
