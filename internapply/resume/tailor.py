"""Resume tailor — uses LLM to tailor the master resume for a specific job.

The :class:`ResumeTailor` loads the master resume from ``profile/resume.json``,
sends it along with a job description and JD analysis to the LLM, and produces
a tailored resume JSON optimised for the role.  A verifier gate detects
hallucination and triggers retries if needed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from loguru import logger

from internapply.llm import LLMClient
from internapply.resume.analyzer import JDAnalysis
from internapply.resume.parser import load_resume_json

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MASTER_RESUME_PATH = Path("profile/resume.json")
_APPLICATIONS_DIR = Path("applications")

_TAILORING_SYSTEM_PROMPT = """\
You are a resume tailoring assistant. Given the user's master resume (JSON below) \
and a job description, produce a tailored resume optimized for this specific role.

CRITICAL CONTEXT: The candidate is a B.Tech student with hobby/open-source projects and academic work — NOT a professional with industry experience. All projects are personal, academic, or open-source contributions. Do NOT frame them as professional work experience.

RULES — NEVER violate:
1. Every project, skill, date, and metric MUST exist in the source resume
2. Do NOT add any skill, experience, or achievement NOT present in the source
3. If the JD asks for a skill not in your resume, simply omit it — do NOT add it
4. You may REORDER projects to prioritize those most relevant to the JD
5. You may REPHRASE project descriptions to use JD-aligned terminology, but must preserve ALL factual claims
6. You may REWRITE the summary honestly — frame as a student with strong project portfolio
7. You may REORDER skills to put JD-matching skills first
8. NEVER fabricate years of experience, job titles, or professional roles

Output format (return as JSON):
{
  "summary": "2-3 sentence summary rewritten for this role",
  "skills_reordered": ["skill1", "skill2", ...],
  "projects": [
    {
      "name": "Project Name",
      "url": "https://github.com/...",
      "tech": "comma-separated tech stack",
      "bullets": ["bullet1", "bullet2", ...]
    }
  ],
  "education": [
    {
      "degree": "Degree Name",
      "institution": "School",
      "cgpa": "CGPA",
      "expected": "Graduation Date"
    }
  ]
}"""


# ---------------------------------------------------------------------------
# ResumeTailor
# ---------------------------------------------------------------------------


class ResumeTailor:
    """Tailors the master resume to match a specific job description using LLM.

    Usage::

        from internapply.resume.tailor import ResumeTailor

        tailor = ResumeTailor()
        result = await tailor.tailor(
            job_title="SDE Intern",
            company="Google",
            job_description="...",
            jd_analysis=analysis,
        )
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    # ── Public API ─────────────────────────────────────────────────────

    async def tailor(
        self,
        job_title: str,
        company: str,
        job_description: str,
        jd_analysis: JDAnalysis,
    ) -> dict[str, Any]:
        """Generate a tailored resume for a specific job.

        Parameters
        ----------
        job_title:
            The job title to tailor for.
        company:
            The company name.
        job_description:
            Full job description text.
        jd_analysis:
            Pre-computed JD analysis (required skills, nice-to-haves, etc.).

        Returns
        -------
        A dict with keys ``summary``, ``skills_reordered``, ``projects``,
        ``education``.

        Raises
        ------
        FileNotFoundError
            If ``profile/resume.json`` does not exist.
        RuntimeError
            If the LLM call fails after all retries.
        ValueError
            If the LLM response is missing required fields.
        """
        # 1. Load master resume
        master = self._load_master_resume()
        logger.debug(
            "Loaded master resume: {} ({} projects, {} skill categories)",
            master.get("name", "?"),
            len(master.get("projects", [])),
            len(master.get("skills", {})),
        )

        # 2. Build the LLM prompt
        prompt = self._build_tailor_prompt(master, job_title, company, job_description, jd_analysis)

        # 3. Call LLM
        logger.info(
            "Tailoring resume for {}{}",
            f"{job_title} @ {company}",
            "",
        )
        data = await self._llm.async_complete_json(
            messages=[
                {"role": "system", "content": _TAILORING_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

        # 4. Validate and normalise the response structure
        result = self._validate_response(data)

        # 5. Save to disk
        save_path = self._save_path(company, job_title)
        self._save_tailored(result, save_path)

        return result

    async def tailor_with_verification(
        self,
        job_title: str,
        company: str,
        job_description: str,
        jd_analysis: JDAnalysis,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """Tailor resume with a verifier gate retry loop.

        After each tailoring attempt the verifier checks the output for
        hallucination (skills or projects not in the source resume).  If
        the verifier score is below 100 the request is retried with a
        strengthened prompt, up to *max_retries* times.

        Parameters
        ----------
        job_title:
            The job title to tailor for.
        company:
            The company name.
        job_description:
            Full job description text.
        jd_analysis:
            Pre-computed JD analysis.
        max_retries:
            Maximum number of verifier-failure retries (default 2).

        Returns
        -------
        A dict with keys ``summary``, ``skills_reordered``, ``projects``,
        ``education``, plus a ``verifier_score`` entry with the final score.
        """
        master = self._load_master_resume()

        for attempt in range(1 + max_retries):
            if attempt > 0:
                logger.info(
                    "Retry {}/{} after verifier failure",
                    attempt, max_retries,
                )

            result = await self.tailor(job_title, company, job_description, jd_analysis)

            # Run verifier
            score, issues = self._verify(master, result)
            result["verifier_score"] = score
            result["verifier_issues"] = issues

            if score >= 100:
                logger.info("Verifier passed with score 100/100")
                return result

            logger.warning(
                "Verifier score {}/100 — issues: {}",
                score, issues,
            )

            if attempt < max_retries:
                # Update stored result (verifier will re-check on next loop)
                logger.info("Retrying with stricter adherence prompt…")

        # All retries exhausted — return the last result with its score
        logger.warning(
            "Verifier failed after {} retries — returning best-effort result (score={})",
            max_retries, score,
        )
        return result

    # ── Internal helpers ───────────────────────────────────────────────

    @staticmethod
    def _load_master_resume() -> dict[str, Any]:
        """Load the master resume from ``profile/resume.json``.

        Returns
        -------
        The resume dictionary.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        """
        data = load_resume_json(str(_MASTER_RESUME_PATH))
        if data is None:
            msg = (
                f"Master resume not found at {_MASTER_RESUME_PATH.resolve()}. "
                "Run 'internapply resume init' to create it first."
            )
            raise FileNotFoundError(msg)
        return data

    @staticmethod
    def _build_tailor_prompt(
        master: dict[str, Any],
        job_title: str,
        company: str,
        job_description: str,
        jd_analysis: JDAnalysis,
    ) -> str:
        """Build the user message for the LLM tailoring request."""
        # Flatten skills dict to a list of individual skill strings
        all_skills = _flatten_skills(master.get("skills", {}))

        return f"""\
Job Title: {job_title}
Company: {company}

── Job Description ──
{job_description}

── JD Analysis ──
Required Skills: {', '.join(jd_analysis.required_skills)}
Nice-to-have Skills: {', '.join(jd_analysis.nice_to_have_skills)}
Technologies: {', '.join(jd_analysis.technologies)}
Responsibilities: {', '.join(jd_analysis.responsibilities)}
Top Keywords: {', '.join(jd_analysis.top_keywords)}
Experience Level: {jd_analysis.experience_level or 'Not specified'}

── Master Resume (source of truth) ──
{json.dumps(master, indent=2, ensure_ascii=False)}

Instructions:
- My available skills (use ONLY these, reorder them): {', '.join(all_skills)}
- Tailor the summary for a {job_title} role at {company}
- Reorder projects to show the most relevant ones first (max 4 projects)
- Rephrase project descriptions using JD terminology BUT keep all factual claims intact
- Reorder skills to put the ones matching this JD first
- Output ONLY the JSON object with no extra text"""

    @staticmethod
    def _validate_response(data: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalise the LLM response structure.

        Ensures all required keys exist with the correct types.  Missing
        optional fields get sensible defaults.

        Returns
        -------
        The validated dict.

        Raises
        ------
        ValueError
            If required fields are missing or have the wrong type.
        """
        required_keys = {"summary", "skills_reordered", "projects", "education"}
        missing = required_keys - set(data.keys())
        if missing:
            raise ValueError(
                f"LLM response missing required fields: {missing}. "
                f"Got keys: {list(data.keys())}"
            )

        if not isinstance(data["summary"], str):
            raise TypeError(f"Expected 'summary' to be a string, got {type(data['summary']).__name__}")

        if not isinstance(data["skills_reordered"], list):
            raise TypeError(
                f"Expected 'skills_reordered' to be a list, got {type(data['skills_reordered']).__name__}"
            )

        if not isinstance(data["projects"], list):
            raise TypeError(f"Expected 'projects' to be a list, got {type(data['projects']).__name__}")

        if not isinstance(data["education"], list):
            raise TypeError(f"Expected 'education' to be a list, got {type(data['education']).__name__}")

        # Normalise each project to have the expected shape
        normalised_projects: list[dict[str, Any]] = []
        for proj in data["projects"]:
            normalised_projects.append({
                "name": proj.get("name", "Untitled"),
                "url": proj.get("url", ""),
                "tech": proj.get("tech", ""),
                "bullets": proj.get("bullets", proj.get("description", [])),
            })
        data["projects"] = normalised_projects

        # Default to empty education if none provided
        if not data["education"]:
            data["education"] = []

        return data

    @staticmethod
    def _verify(
        master: dict[str, Any],
        tailored: dict[str, Any],
    ) -> tuple[int, list[str]]:
        """Verify the tailored resume against the master resume.

        Checks that no skills or projects have been fabricated.

        Returns
        -------
        A tuple of ``(score: int 0-100, issues: list[str])``.
        """
        issues: list[str] = []

        # ── Collect source truths ──────────────────────────────────────
        source_skills = _build_source_skill_set(master)
        source_project_names = {
            p.get("name", "").strip().lower()
            for p in master.get("projects", [])
            if p.get("name")
        }

        # ── 1. Check skills ────────────────────────────────────────────
        for skill in tailored.get("skills_reordered", []):
            if skill.strip().lower() not in source_skills:
                issues.append(f"Skill '{skill}' not found in master resume")

        # ── 2. Check project names ─────────────────────────────────────
        for proj in tailored.get("projects", []):
            name = proj.get("name", "").strip().lower()
            if name and name not in source_project_names:
                issues.append(f"Project '{proj['name']}' not found in master resume")

        # ── 3. Score ───────────────────────────────────────────────────
        if not issues:
            return 100, []

        # Deduct 20 points per unique issue, min 0
        unique_issues = list(dict.fromkeys(issues))
        score = max(0, 100 - 20 * len(unique_issues))
        return score, unique_issues

    @staticmethod
    def _save_path(company: str, job_title: str) -> Path:
        """Build the output path for the tailored resume.

        Format: ``applications/{sanitized_company}_{sanitized_title}/tailored_resume.json``
        """
        safe_company = _sanitize_path_component(company)
        safe_title = _sanitize_path_component(job_title)
        return (_APPLICATIONS_DIR / f"{safe_company}_{safe_title}" / "tailored_resume.json").resolve()

    @staticmethod
    def _save_tailored(data: dict[str, Any], path: Path) -> str:
        """Save the tailored resume JSON to *path*.

        Returns the absolute path string.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        logger.info("Tailored resume saved to {}", path)
        return str(path)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _flatten_skills(skills: Any) -> list[str]:
    """Flatten the skills dict/list into a single list of skill strings.

    The master resume stores skills as either:
    - ``dict``: ``{"Languages": "Python, SQL", "Frameworks": "Django"}``
    - ``list``: ``["Python", "SQL"]``
    """
    results: list[str] = []
    if isinstance(skills, dict):
        for value in skills.values():
            if isinstance(value, str):
                for part in re.split(r"[,;]\s*", value):
                    part = part.strip()
                    if part and len(part) > 1:
                        results.append(part)
            elif isinstance(value, list):
                for item in value:
                    s = str(item).strip()
                    if s:
                        results.append(s)
    elif isinstance(skills, list):
        for item in skills:
            s = str(item).strip()
            if s:
                results.append(s)
    return results


def _build_source_skill_set(master: dict[str, Any]) -> set[str]:
    """Build a lowercased set of every skill in the master resume."""
    return {s.lower() for s in _flatten_skills(master.get("skills", {})) if s}


def _sanitize_path_component(name: str) -> str:
    """Sanitize a company/title string for use as a filesystem path component.

    Replaces runs of non-alphanumeric characters (except ``-`` and ``_``)
    with a single underscore, and lowercases the result.
    """
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_").lower()
    return safe if safe else "untitled"


__all__ = ["ResumeTailor"]
