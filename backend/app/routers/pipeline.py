from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_session

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


class RunPipelineRequest(BaseModel):
    dry_run: bool = True


@router.post("/run")
async def run_pipeline(body: RunPipelineRequest) -> dict:
    """Trigger the LangGraph discovery pipeline.

    When ``dry_run=True`` (the default) the pipeline uses mock data and skips
    real API calls and database writes.  Set ``dry_run=false`` to execute real
    scrapers and persist results.
    """
    from backend.app.pipeline.orchestrator import create_pipeline
    from backend.app.pipeline.state import initial_state

    graph = create_pipeline()
    state = initial_state(config={}, dry_run=body.dry_run)
    config_obj = {"configurable": {"thread_id": "api-trigger"}}
    result = await graph.ainvoke(state, config=config_obj)
    return {
        "status": "completed",
        "stage": result.get("stage"),
        "jobs_found": len(result.get("job_listings", [])),
        "companies_found": len(result.get("companies", [])),
        "errors": len(result.get("errors", [])),
    }


@router.post("/clear")
async def clear_pipeline_data(session: AsyncSession = Depends(get_session)):
    from backend.app.models import (
        Application,
        BatchQueue,
        Company,
        Contact,
        CoverEmail,
        EmailDraft,
        JobListing,
        TailoredResume,
    )

    tables = [BatchQueue, EmailDraft, CoverEmail, TailoredResume, Application, Contact, Company, JobListing]
    for table in tables:
        await session.execute(delete(table))
    await session.commit()
    return {"status": "cleared", "tables": len(tables)}


@router.post("/rerun")
async def rerun_pipeline(session: AsyncSession = Depends(get_session)):
    from backend.app.models import Application

    result = await session.execute(
        select(Application).where(Application.status.in_(["discovered", "researching", "research_complete"]))
    )
    unapproved = result.scalars().all()

    from backend.app.pipeline.orchestrator import create_pipeline
    from backend.app.pipeline.state import initial_state

    graph = create_pipeline()
    state = initial_state(config={}, dry_run=False)
    config_obj = {"configurable": {"thread_id": "rerun-" + str(uuid4())[:8]}}
    result = await graph.ainvoke(state, config=config_obj)

    return {"status": "rerun_completed", "items_rerun": len(unapproved), "stage": result.get("stage")}
