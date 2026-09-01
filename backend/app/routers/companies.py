from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.database import get_session
from backend.app.models import Company

router = APIRouter(prefix="/api/v1/companies", tags=["companies"])


@router.get("")
async def list_companies(
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """List all companies."""
    result = await session.execute(
        select(Company).order_by(Company.created_at.desc()).limit(100)
    )
    companies = result.scalars().all()
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "domain": c.domain,
            "description": c.description,
            "tech_stack": c.tech_stack,
            "funding_stage": c.funding_stage,
            "source": c.source,
            "created_at": str(c.created_at),
        }
        for c in companies
    ]


@router.get("/{id}")
async def get_company(
    id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get single company with full details."""
    result = await session.execute(
        select(Company).where(Company.id == id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return {
        "id": str(company.id),
        "name": company.name,
        "domain": company.domain,
        "description": company.description,
        "tech_stack": company.tech_stack,
        "funding_stage": company.funding_stage,
        "funding_total": company.funding_total,
        "recent_news": company.recent_news,
        "culture_data": company.culture_data,
        "research_notes": company.research_notes,
        "source": company.source,
        "created_at": str(company.created_at),
    }
