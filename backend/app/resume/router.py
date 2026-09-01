"""Resume API router — FastAPI endpoints wrapping ``internapply.resume`` classes.

Each endpoint delegates to the existing internapply classes without
rewriting their logic.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so ``internapply`` is importable.
# ``backend/app/resume/router.py`` →
#   ``resume/`` → ``app/`` → ``backend/`` → project root
# ---------------------------------------------------------------------------
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ---------------------------------------------------------------------------
# Import existing classes — do NOT rewrite the logic
# ---------------------------------------------------------------------------
from internapply.llm import LLMClient  # noqa: E402
from internapply.models import JobListing  # noqa: E402
from internapply.resume.analyzer import JDAnalysis, JDAnalyzer  # noqa: E402
from internapply.resume.cover_letter import CoverLetterGen  # noqa: E402
from internapply.resume.parser import load_resume_json, save_resume_json  # noqa: E402
from internapply.resume.renderer import render_resume  # noqa: E402
from internapply.resume.tailor import ResumeTailor  # noqa: E402
from internapply.resume.verifier import ResumeVerifier, VerifierReport, _CLICHE_PATTERNS  # noqa: E402
from loguru import logger  # noqa: E402

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/resume", tags=["resume"])

# ── Request / Response models ────────────────────────────────────────────


class TailorRequest(BaseModel):
    """Request body for ``POST /api/v1/resume/tailor``."""

    job_title: str
    company: str
    job_description: str
    jd_analysis: dict | None = None


class TailorResponse(BaseModel):
    """Response body for ``POST /api/v1/resume/tailor``."""

    summary: str
    skills_reordered: list[str]
    projects: list[dict[str, Any]]
    education: list[dict[str, Any]]
    verifier_score: int | None = None


class VerifyRequest(BaseModel):
    """Request body for ``POST /api/v1/resume/verify``."""

    tailored_resume: dict[str, Any]
    source_resume: dict[str, Any] | None = None


class CoverLetterRequest(BaseModel):
    """Request body for ``POST /api/v1/resume/cover-letter``."""

    title: str
    company: str
    jd_summary: str
    top_skills: list[str]
    summary: str
    name: str | None = None


class CoverLetterResponse(BaseModel):
    """Response body for ``POST /api/v1/resume/cover-letter``."""

    letter: str
    humanization_score: int


class AnalyzeRequest(BaseModel):
    """Request body for ``POST /api/v1/resume/analyze``."""

    description: str
    title: str = ""
    company: str = ""
    source: str = "api"
    url: str = ""


class UpdateMasterRequest(BaseModel):
    """Request body for ``PUT /api/v1/resume/master``."""

    resume: dict[str, Any]


class RenderRequest(BaseModel):
    """Request body for ``POST /api/v1/resume/render``."""

    resume_data: dict[str, Any]
    company: str = ""
    job_title: str = ""
    output_format: str = "docx"


class QualityCheckRequest(BaseModel):
    """Request body for ``POST /api/v1/resume/quality-check``."""

    tailored_resume: dict[str, Any]


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/tailor", response_model=TailorResponse)
async def tailor_resume(request: TailorRequest) -> TailorResponse:
    """Tailor the master resume for a specific job, with verifier gate.

    If ``jd_analysis`` is provided as a dict it is converted to a
    :class:`JDAnalysis` model.  Otherwise the job description is analysed
    first using :class:`JDAnalyzer`.

    Internally uses :meth:`ResumeTailor.tailor_with_verification` which runs
    the verifier gate and retries up to 2 times if the score is below 100.
    """
    try:
        # Resolve jd_analysis: dict → JDAnalysis model if provided,
        # otherwise run the analyzer first.
        if request.jd_analysis:
            jd_analysis = JDAnalysis(**request.jd_analysis)
            logger.debug("Using provided JD analysis ({} required skills)", len(jd_analysis.required_skills))
        else:
            logger.info("No JD analysis provided — running JDAnalyzer")
            analyzer = JDAnalyzer()
            listing = JobListing(
                title=request.job_title or "Job Listing",
                company=request.company or "Company",
                description=request.job_description,
                source="api",
                url="",
            )
            jd_analysis = await analyzer.analyze(listing)

        tailor = ResumeTailor()
        result = await tailor.tailor_with_verification(
            job_title=request.job_title,
            company=request.company,
            job_description=request.job_description,
            jd_analysis=jd_analysis,
        )

        return TailorResponse(
            summary=result["summary"],
            skills_reordered=result["skills_reordered"],
            projects=result["projects"],
            education=result["education"],
            verifier_score=result.get("verifier_score"),
        )

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.error("Unexpected error in tailor_resume: {}", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/verify")
async def verify_resume(request: VerifyRequest) -> dict[str, Any]:
    """Run the deterministic verifier gate on a tailored resume.

    Checks for hallucinated skills, projects, dates, metrics, and education
    entries.  Also flags AI-cliché phrases as warnings.

    Returns a :class:`VerifierReport` dict with keys ``passed``, ``violations``,
    ``warnings``, and ``score``.
    """
    try:
        verifier = ResumeVerifier()
        report: VerifierReport = verifier.verify(
            tailored_resume=request.tailored_resume,
            source_resume=request.source_resume,
        )
        return report.model_dump()
    except Exception as exc:
        logger.error("Unexpected error in verify_resume: {}", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/cover-letter", response_model=CoverLetterResponse)
async def generate_cover_letter(request: CoverLetterRequest) -> CoverLetterResponse:
    """Generate a cover letter with two-pass humanisation.

    The LLM drafts a cold-email, then the deterministic humanisation pipeline
    strips clichés, robotic phrasing, and hedging.  If the humanisation score
    is below 80 the draft is regenerated with feedback (up to 3 attempts).
    """
    try:
        gen = CoverLetterGen()
        letter, score = await gen.generate(
            title=request.title,
            company=request.company,
            jd_summary=request.jd_summary,
            top_skills=request.top_skills,
            summary=request.summary,
            name=request.name,
        )
        return CoverLetterResponse(letter=letter, humanization_score=score)
    except Exception as exc:
        logger.error("Unexpected error in generate_cover_letter: {}", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/analyze")
async def analyze_jd(request: AnalyzeRequest) -> dict[str, Any]:
    """Analyse a job description and return structured insights.

    Uses the LLM as the primary extraction path with a deterministic
    keyword-frequency fallback.  Returns required/nice-to-have skills,
    responsibilities, experience level, education requirements, top keywords,
    soft skills, technologies, and a match score against the master resume.
    """
    try:
        analyzer = JDAnalyzer()
        listing = JobListing(
            title=request.title or "Job Listing",
            company=request.company or "Company",
            description=request.description,
            source=request.source,
            url=request.url,
        )
        analysis: JDAnalysis = await analyzer.analyze(listing)
        return analysis.model_dump()
    except Exception as exc:
        logger.error("Unexpected error in analyze_jd: {}", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/master")
async def get_master_resume() -> dict[str, Any]:
    """Return the current master resume from ``profile/resume.json``."""
    try:
        resume = load_resume_json()
        if resume is None:
            raise HTTPException(
                status_code=404,
                detail="Master resume not found at profile/resume.json. "
                "Run 'internapply resume init' to create it first.",
            )
        return resume
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Unexpected error in get_master_resume: {}", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/master")
async def update_master_resume(request: UpdateMasterRequest) -> dict[str, Any]:
    """Update the master resume JSON file.

    Accepts the full resume dict and persists it to ``profile/resume.json``.
    """
    try:
        path = save_resume_json(request.resume)
        logger.info("Master resume updated at {}", path)
        return {"status": "ok", "path": path}
    except Exception as exc:
        logger.error("Unexpected error in update_master_resume: {}", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/render")
async def render_resume_endpoint(request: RenderRequest):
    """Generate a professional ATS-optimized DOCX resume (1-page enforced).

    Delegates to ``internapply.resume.renderer.render_resume`` and returns
    the .docx file as a downloadable response.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        path = render_resume(
            data=request.resume_data,
            output_path=tmp_path,
            company=request.company,
            job_title=request.job_title,
        )
        return FileResponse(
            path=str(path),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="resume.docx",
        )
    except Exception as exc:
        logger.error("Unexpected error in render_resume_endpoint: {}", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/quality-check")
async def quality_check(request: QualityCheckRequest) -> dict[str, Any]:
    """Check tailored resume for AI artifacts, length, and one-page compliance.

    Runs five checks:
    1. AI cliché phrases in summary and project descriptions.
    2. Summary length (>200 chars but <500 chars).
    3. Skills reordered (at least 5 skills present).
    4. Projects selected (at least 2 projects).
    5. One-page compliance (max 4 projects, max 2 bullets per project).

    Returns a ``score`` (0-100) and an ``issues`` list.
    """
    issues: list[str] = []
    resume = request.tailored_resume

    summary = resume.get("summary", "")
    projects = resume.get("projects", [])

    cliché_hits: list[str] = []
    for pat in _CLICHE_PATTERNS:
        if summary:
            for m in pat.finditer(summary):
                cliché_hits.append(f"summary: \"{m.group()}\"")
        for proj in projects:
            bullets = proj.get("bullets", proj.get("description", []))
            if isinstance(bullets, str):
                bullets = [bullets]
            for bullet in bullets:
                for m in pat.finditer(bullet):
                    cliché_hits.append(f"project \"{proj.get('name', '')}\": \"{m.group()}\"")

    if cliché_hits:
        issues.append(f"AI cliché phrases found ({len(cliché_hits)}): " + "; ".join(cliché_hits[:5]))

    summary_len = len(summary)
    if summary_len < 200:
        issues.append(f"Summary too short ({summary_len} chars, need >200)")
    elif summary_len > 500:
        issues.append(f"Summary too long ({summary_len} chars, need <500)")

    skills = resume.get("skills_reordered", [])
    if len(skills) < 5:
        issues.append(f"Too few skills ({len(skills)}, need at least 5)")

    if len(projects) < 2:
        issues.append(f"Too few projects ({len(projects)}, need at least 2)")

    if len(projects) > 4:
        issues.append(f"Too many projects ({len(projects)}, max 4)")
    for proj in projects:
        bullets = proj.get("bullets", proj.get("description", []))
        if isinstance(bullets, str):
            bullets = [bullets]
        if len(bullets) > 2:
            issues.append(
                f"Project \"{proj.get('name', '')}\" has {len(bullets)} bullets (max 2)"
            )

    max_checks = 5
    passed = max_checks - len(issues)
    score = max(0, int((passed / max_checks) * 100))

    return {"score": score, "issues": issues, "passed": len(issues) == 0}
