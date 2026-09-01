import sys

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# structlog + correlation id (optional deps, ponytail: reuse if installed)
try:
    from asgi_correlation_id import CorrelationIdMiddleware  # type: ignore

    _has_corr = True
except Exception:
    CorrelationIdMiddleware = None  # type: ignore
    _has_corr = False

try:
    import structlog  # type: ignore

    _has_structlog = True
except Exception:
    _has_structlog = False

# Configure loguru
logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("logs/backend.log", rotation="10 MB", level="DEBUG")

app = FastAPI(
    title="InternApply API",
    version="0.2.0",
    description="Semi-automatic internship/opportunity research and outreach system",
)

# CORS - allow Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if _has_corr and CorrelationIdMiddleware is not None:
    app.add_middleware(CorrelationIdMiddleware)
if _has_structlog:
    try:
        from structlog.contextvars import StructlogContextVarsMiddleware  # type: ignore

        app.add_middleware(StructlogContextVarsMiddleware)
    except Exception:
        try:
            import structlog

            structlog.configure(
                processors=[
                    structlog.contextvars.merge_contextvars,
                    structlog.processors.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.JSONRenderer(),
                ]
            )
        except Exception:
            pass

# API v1 prefix
API_PREFIX = "/api/v1"


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0", "service": "internapply-api"}


@app.get("/health/discovery")
async def health_discovery():
    try:
        from backend.app.observability.metrics import get_health_state
        from backend.app.discovery.circuit import get_dead_letters, CircuitBreaker

        state = get_health_state()
        sources = []
        # ensure at least known sources appear even if no runs yet
        for src in ["greenhouse", "lever", "ashby", "smartrecruiters", "hirist", "unstop", "internshala", "free_apis", "jobspy", "freelance"]:
            entry = state.get(src, {})
            sources.append(
                {
                    "source": src,
                    "last_run": entry.get("last_run"),
                    "latency_p50": entry.get("latency_p50", 0.0),
                    "breaker_open": CircuitBreaker.is_open(src) if src not in entry else entry.get("breaker_open", CircuitBreaker.is_open(src)),
                    "dead_letters": len(get_dead_letters(src)),
                }
            )
        return {"sources": sources}
    except Exception as e:
        return {"sources": [], "error": str(e)}


@app.get("/metrics")
async def metrics():
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except Exception as e:
        return Response(f"# metrics unavailable: {e}", media_type="text/plain")


@app.on_event("startup")
async def startup():
    from backend.app.config import settings
    from backend.app.database import init_db

    logger.info("InternApply API starting up...")
    try:
        await init_db(settings.database_url)
        logger.info("Database engine initialised")
    except Exception as exc:
        logger.warning(f"Database not available — DB routes will return 500: {exc}")
    logger.info("InternApply API started")


@app.on_event("shutdown")
async def shutdown():
    from backend.app.database import close_db

    logger.info("InternApply API shutting down...")
    await close_db()


# Register routers
from backend.app.resume.router import router as resume_router
from backend.app.routers.opportunities import router as opportunities_router
from backend.app.routers.companies import router as companies_router
from backend.app.routers.dashboard import router as dashboard_router
from backend.app.routers.pipeline import router as pipeline_router

app.include_router(resume_router)
app.include_router(opportunities_router)
app.include_router(companies_router)
app.include_router(dashboard_router)
app.include_router(pipeline_router)
