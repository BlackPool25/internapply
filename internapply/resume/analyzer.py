"""JD Analyzer — extracts structured requirements and keywords from job descriptions.

Uses the OpenCode Go LLM (via :class:`LLMClient`) as the primary extraction
path, with a deterministic TF-IDF/count-based fallback for when the LLM is
unavailable.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from loguru import logger
from openai import APIError as OpenAIAPIError
from pydantic import BaseModel, ConfigDict

from internapply.config import get_config
from internapply.llm import LLMClient
from internapply.models import JobListing
from internapply.resume.parser import load_resume_json

# ──────────────────────────────────────────────────────────────────────────
# Constants — skill dictionary & experience-level keyword sets
# ──────────────────────────────────────────────────────────────────────────

_COMMON_SKILLS: list[str] = [
    # Languages
    "python",
    "java",
    "javascript",
    "typescript",
    "go",
    "golang",
    "rust",
    "c++",
    "c",
    "c#",
    "csharp",
    "ruby",
    "php",
    "swift",
    "kotlin",
    "scala",
    "perl",
    "r",
    "matlab",
    "sql",
    "nosql",
    "html",
    "css",
    "scss",
    "sass",
    "dart",
    "elixir",
    "haskell",
    "clojure",
    "julia",
    # Web frameworks
    "django",
    "flask",
    "fastapi",
    "spring boot",
    "spring",
    "express",
    "express.js",
    "node.js",
    "node",
    "react",
    "react.js",
    "vue",
    "vue.js",
    "angular",
    "next.js",
    "nextjs",
    "nuxt.js",
    "svelte",
    "jquery",
    "bootstrap",
    "tailwind",
    "tailwind css",
    # Backend & databases
    "rest",
    "rest api",
    "graphql",
    "grpc",
    "soap",
    "api",
    "microservices",
    "postgresql",
    "postgres",
    "mysql",
    "mongodb",
    "redis",
    "sqlite",
    "mariadb",
    "elasticsearch",
    "cassandra",
    "dynamodb",
    "firebase",
    "supabase",
    "cockroachdb",
    "couchdb",
    "neo4j",
    # Cloud & DevOps
    "aws",
    "gcp",
    "azure",
    "cloud",
    "docker",
    "kubernetes",
    "k8s",
    "terraform",
    "ansible",
    "jenkins",
    "ci/cd",
    "github actions",
    "gitlab ci",
    "circleci",
    "argocd",
    "helm",
    "prometheus",
    "grafana",
    "istio",
    "envoy",
    # Tools & version control
    "git",
    "linux",
    "unix",
    "bash",
    "shell",
    "make",
    "cmake",
    "vim",
    "neovim",
    "vscode",
    "intellij",
    "pycharm",
    # Data & ML
    "machine learning",
    "deep learning",
    "nlp",
    "tensorflow",
    "pytorch",
    "pandas",
    "numpy",
    "scikit-learn",
    "scipy",
    "opencv",
    "llm",
    "ai",
    "artificial intelligence",
    "rag",
    "langchain",
    "hugging face",
    "transformers",
    "spacy",
    "nltk",
    "airflow",
    "spark",
    "hadoop",
    # Message queues & streaming
    "kafka",
    "rabbitmq",
    "celery",
    "pub/sub",
    "nats",
    "pulsar",
    "amazon sqs",
    # Testing
    "pytest",
    "jest",
    "mocha",
    "selenium",
    "cypress",
    "junit",
    "unittest",
    "playwright",
    "vitest",
    # Auth & security
    "oauth",
    "jwt",
    "sso",
    "ldap",
    "rbac",
    "saml",
    "tls",
    "ssl",
    # Monitoring & logging
    "datadog",
    "sentry",
    "logstash",
    "kibana",
    "new relic",
    "opentelemetry",
    # Mobile
    "android",
    "ios",
    "flutter",
    "react native",
    "dart",
    # Concepts
    "oop",
    "orm",
    "tdd",
    "agile",
    "scrum",
    "design patterns",
    "solid",
    "clean architecture",
    "hexagonal architecture",
    "domain-driven design",
    # Other
    "webpack",
    "vite",
    "babel",
    "eslint",
    "prettier",
    "swagger",
    "openapi",
    "postman",
    "insomnia",
    "docker compose",
    "nginx",
    "apache",
    "gunicorn",
    "uvicorn",
    "wsgi",
    "asgi",
]

_ENTRY_KEYWORDS: set[str] = {
    "entry",
    "entry-level",
    "entry level",
    "fresher",
    "trainee",
    "intern",
    "internship",
    "0-1 year",
    "0 to 1 year",
}
_JUNIOR_KEYWORDS: set[str] = {
    "junior",
    "jr",
    "jr.",
    "junior-level",
    "junior level",
    "1-3 year",
    "1 to 3 year",
}
_MID_KEYWORDS: set[str] = {
    "mid",
    "mid-level",
    "mid level",
    "intermediate",
    "3-5 year",
    "3 to 5 year",
    "mid-senior",
}
_SENIOR_KEYWORDS: set[str] = {
    "senior",
    "sr",
    "sr.",
    "senior-level",
    "senior level",
    "staff",
    "principal",
    "5-8 year",
    "5 to 8 year",
}
_LEAD_KEYWORDS: set[str] = {
    "lead",
    "manager",
    "head",
    "director",
    "architect",
    "vp",
    "vice president",
    "8+ year",
    "8+ years",
}

_SOFT_SKILLS_KEYWORDS: list[str] = [
    r"communication",
    r"teamwork",
    r"leadership",
    r"problem.solving",
    r"critical thinking",
    r"time management",
    r"adaptability",
    r"collaboration",
    r"creativity",
    r"analytical",
    r"interpersonal",
    r"organizational",
    r"detail.orient",
    r"self.motivat",
    r"fast learner",
    r"proactive",
    r"flexible",
    r"mentorship",
    r"presentation",
    r"negotiation",
    r"conflict resolution",
    r"decision.making",
    r"multitasking",
    r"curiosity",
    r"growth mindset",
    r"ownership",
    r"accountability",
]

# ──────────────────────────────────────────────────────────────────────────
# JDAnalysis model
# ──────────────────────────────────────────────────────────────────────────


class JDAnalysis(BaseModel):
    """Structured analysis of a job description.

    Fields correspond to the output of both the LLM and deterministic
    extraction paths.  ``match_score`` is computed against the candidate's
    resume.
    """

    model_config = ConfigDict(from_attributes=True)

    required_skills: list[str]
    """Must-have technical skills explicitly mentioned in the JD."""

    nice_to_have_skills: list[str]
    """Preferred or optional skills (e.g. flagged as 'nice to have')."""

    responsibilities: list[str]
    """Key duties and responsibilities extracted from the description."""

    experience_level: str | None
    """One of ``entry``, ``junior``, ``mid``, ``senior``, ``lead``, or ``None``."""

    education_requirements: list[str]
    """Degrees, certifications, or other education prerequisites."""

    top_keywords: list[str]
    """Top 15 keywords for ATS matching, ranked by importance."""

    soft_skills: list[str]
    """Soft skills or interpersonal qualities mentioned in the JD."""

    technologies: list[str]
    """Specific tools, platforms, or frameworks referenced."""

    match_score: float | None
    """Keyword-overlap score (0–100) vs the candidate's resume, or ``None``."""

    raw_text: str
    """Original description text (truncated to 2000 characters)."""


# ──────────────────────────────────────────────────────────────────────────
# JDAnalyzer
# ──────────────────────────────────────────────────────────────────────────


class JDAnalyzer:
    """Analyzes job descriptions to extract structured requirements and keywords.

    Usage::

        from internapply.resume.analyzer import JDAnalyzer

        analyzer = JDAnalyzer()
        analysis = await analyzer.analyze(job_listing)

    The primary path uses :class:`LLMClient` (OpenCode Go API).  If the LLM
    call fails a deterministic fallback based on keyword frequency and a
    built-in skills dictionary is used instead.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()
        self._cfg = get_config()

    # ── Public API ─────────────────────────────────────────────────────

    async def analyze(self, job_listing: JobListing) -> JDAnalysis:
        """Analyze a *job_listing*'s description and return structured data.

        Tries the LLM path first.  If it fails (network error, JSON parse
        error, etc.) the deterministic fallback is used.  The analysis is
        also stored back on ``job_listing.analysis`` as a dict, ready for
        the caller to persist to the database.
        """
        description = job_listing.description or ""
        if not description.strip():
            logger.warning(
                "Empty description for listing {} ({}) — returning empty analysis",
                job_listing.id,
                job_listing.title,
            )
            return self._empty_analysis(description)

        # 1. Attempt LLM extraction
        try:
            analysis = await self._llm_analyze(description)
            logger.debug(
                "LLM analysis succeeded for listing {} — {} required skills, {} responsibilities",
                job_listing.id,
                len(analysis.required_skills),
                len(analysis.responsibilities),
            )
        except (RuntimeError, OpenAIAPIError, json.JSONDecodeError) as exc:
            logger.warning(
                "LLM analysis failed for listing {}: {} — falling back to deterministic",
                job_listing.id,
                exc,
            )
            analysis = self.analyze_deterministic(description)

        # 2. Compute match score against the candidate's resume
        jd_skill_set = list(
            set(analysis.required_skills)
            | set(analysis.nice_to_have_skills)
            | set(analysis.technologies)
        )
        analysis.match_score = self._compute_match_score(jd_skill_set)

        # 3. Update the listing's in-memory analysis field for persistence
        job_listing.analysis = analysis.model_dump()

        return analysis

    async def analyze_batch(
        self,
        listings: list[JobListing],
        *,
        max_concurrent: int = 5,
    ) -> list[JDAnalysis]:
        """Analyze multiple job listings sequentially (respects rate limits).

        Parameters
        ----------
        listings:
            The job listings to analyze.
        max_concurrent:
            **Reserved** for future concurrent-batch use.  Currently processes
            sequentially to avoid overwhelming the LLM API.

        Returns
        -------
        A list of :class:`JDAnalysis` objects in the same order as *listings*.
        """
        # TODO: implement concurrent batch via asyncio.gather with a semaphore
        results: list[JDAnalysis] = []
        for idx, listing in enumerate(listings):
            analysis = await self.analyze(listing)
            results.append(analysis)
            if (idx + 1) % 10 == 0:
                logger.info("Batch progress: {}/{} listings analyzed", idx + 1, len(listings))
        return results

    def analyze_deterministic(self, description: str) -> JDAnalysis:
        """Fallback: extract keywords using count-based approach without LLM.

        Uses a built-in skills dictionary (``~100 skills), frequency analysis,
        and simple heuristics for experience level and education detection.
        No external API calls are made.
        """
        if not description.strip():
            return self._empty_analysis(description)

        lower = description.lower()
        words = re.findall(r"[a-zA-Z+#.]+(?:\s[a-zA-Z+#.]+)*", lower)

        # ── 1. Skills (dictionary-based) ──────────────────────────────
        matched_skills: set[str] = set()
        for skill in _COMMON_SKILLS:
            if skill in lower:
                matched_skills.add(skill)

        required_skills: list[str] = []
        nice_to_have_skills: list[str] = []

        for skill in matched_skills:
            idx = lower.find(skill)
            # Inspect context around the skill mention
            start = max(0, idx - 80)
            end = min(len(lower), idx + len(skill) + 80)
            context = lower[start:end]
            if any(
                marker in context
                for marker in ("nice", "preferred", "plus", "bonus", "good to have", "optional")
            ):
                nice_to_have_skills.append(skill)
            else:
                # If the skill ALSO appears alone without the "nice" context,
                # classify as required; otherwise nice-to-have
                required_skills.append(skill)

        # Deduplicate while preserving insertion order
        required_skills = list(dict.fromkeys(required_skills))
        nice_to_have_skills = list(dict.fromkeys(nice_to_have_skills))

        # ── 2. Technologies (tools / platforms) ───────────────────────
        tech_set: set[str] = {
            "docker",
            "kubernetes",
            "k8s",
            "terraform",
            "ansible",
            "jenkins",
            "grafana",
            "prometheus",
            "git",
            "linux",
            "postman",
            "swagger",
            "openapi",
            "kafka",
            "rabbitmq",
            "celery",
            "redis",
            "elasticsearch",
            "datadog",
            "sentry",
            "webpack",
            "vite",
            "babel",
            "nginx",
            "apache",
            "gunicorn",
            "uvicorn",
            "docker compose",
            "helm",
            "argocd",
            "circleci",
            "github actions",
            "gitlab ci",
            "airflow",
            "spark",
            "hadoop",
        }
        technologies = sorted(matched_skills & tech_set)

        # ── 3. Responsibilities ───────────────────────────────────────
        responsibilities = self._extract_responsibilities(description)

        # ── 4. Experience level ───────────────────────────────────────
        experience_level = self._detect_experience_level(lower)

        # ── 5. Education requirements ─────────────────────────────────
        education_requirements = self._detect_education(lower)

        # ── 6. Soft skills ────────────────────────────────────────────
        soft_skills = self._detect_soft_skills(lower)

        # ── 7. Top keywords (TF-IDF-like frequency) ───────────────────
        top_keywords = self._extract_top_keywords(words, matched_skills)

        return JDAnalysis(
            required_skills=required_skills,
            nice_to_have_skills=nice_to_have_skills,
            responsibilities=responsibilities,
            experience_level=experience_level,
            education_requirements=education_requirements,
            top_keywords=top_keywords,
            soft_skills=soft_skills,
            technologies=technologies,
            match_score=None,  # computed by the caller
            raw_text=description[:2000],
        )

    # ── Private: LLM path ─────────────────────────────────────────────

    async def _llm_analyze(self, description: str) -> JDAnalysis:
        """Use the LLM to extract structured data from *description*."""
        prompt = self._build_llm_prompt(description)

        try:
            data = await self._llm.async_complete_json(
                messages=[{"role": "user", "content": prompt}],
            )
            return self._parse_llm_response(data, description)
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "LLM JSON parse failed: {} — retrying with simpler prompt", exc
            )
            # Retry with a minimal prompt (no response_format dependency)
            simple_prompt = (
                "Extract the following from this job description and return as JSON:\n"
                "1) required_skills (array of must-have technical skills)\n"
                "2) nice_to_have_skills (preferred/optional skills)\n"
                "3) responsibilities (array of key duties)\n"
                "4) experience_level (entry/junior/mid/senior/lead or null)\n"
                "5) education_requirements (array)\n"
                "6) top_keywords (top 15 keywords for ATS matching, ranked)\n"
                "7) soft_skills (array)\n"
                "8) technologies (specific tools/frameworks)\n\n"
                f"Job description:\n{description}\n\n"
                "Return ONLY valid JSON."
            )
            data = await self._llm.async_complete_json(
                messages=[{"role": "user", "content": simple_prompt}],
            )
            return self._parse_llm_response(data, description)

    @staticmethod
    def _build_llm_prompt(description: str) -> str:
        """Build the structured-extraction prompt for the LLM."""
        return (
            "You are a job description analyzer. Extract structured information "
            "from the following job description and return ONLY valid JSON "
            "(no markdown formatting, no code fences).\n\n"
            "Extract these fields:\n"
            "1) required_skills: array of must-have technical skills explicitly mentioned\n"
            "2) nice_to_have_skills: array of preferred or optional skills\n"
            "3) responsibilities: array of key duties and responsibilities\n"
            "4) experience_level: one of \"entry\", \"junior\", \"mid\", \"senior\", "
            "\"lead\", or null if unclear\n"
            "5) education_requirements: array of required degrees or certifications\n"
            "6) top_keywords: array of top 15 keywords for ATS matching, "
            "ranked by importance\n"
            "7) soft_skills: array of soft skills or interpersonal skills mentioned\n"
            "8) technologies: array of specific tools, platforms, or frameworks mentioned\n\n"
            "Job description:\n"
            f"{description}\n\n"
            "Return ONLY valid JSON. No explanation."
        )

    @staticmethod
    def _parse_llm_response(
        data: dict[str, Any],
        description: str,
    ) -> JDAnalysis:
        """Parse the LLM JSON response into a :class:`JDAnalysis` instance."""
        return JDAnalysis(
            required_skills=data.get("required_skills", []),
            nice_to_have_skills=data.get("nice_to_have_skills", []),
            responsibilities=data.get("responsibilities", []),
            experience_level=data.get("experience_level") or None,
            education_requirements=data.get("education_requirements", []),
            top_keywords=data.get("top_keywords", [])[:15],
            soft_skills=data.get("soft_skills", []),
            technologies=data.get("technologies", []),
            match_score=None,  # computed externally
            raw_text=description[:2000],
        )

    # ── Private: Match score ──────────────────────────────────────────

    def _compute_match_score(self, jd_skills: list[str]) -> float | None:
        """Compute simple keyword overlap score between JD and resume skills.

        Returns a float 0–100, or ``None`` if no resume data is available
        or *jd_skills* is empty.
        """
        resume_skills = self._load_resume_skills()
        if not resume_skills or not jd_skills:
            return None

        norm_jd = {s.strip().lower() for s in jd_skills if s.strip()}
        norm_resume = {s.strip().lower() for s in resume_skills if s.strip()}

        if not norm_jd:
            return None

        matched = norm_jd & norm_resume
        score = (len(matched) / len(norm_jd)) * 100.0
        return round(score, 1)

    @staticmethod
    def _load_resume_skills() -> list[str]:
        """Load all individual skill strings from the resume JSON file.

        The resume stores skills as a dictionary mapping categories to
        comma-separated strings (e.g. ``{"Languages": "Python, SQL"}``).
        This method flattens all categories into a single list.
        """
        data = load_resume_json()
        if data is None:
            logger.debug("No resume JSON file found — skipping match score")
            return []

        skills_raw = data.get("skills", {})
        if isinstance(skills_raw, dict):
            result: list[str] = []
            for cat_value in skills_raw.values():
                if isinstance(cat_value, str):
                    for part in re.split(r"[,;]\s*", cat_value):
                        part = part.strip()
                        if part and len(part) > 1:
                            result.append(part)
                elif isinstance(cat_value, list):
                    for item in cat_value:
                        s = str(item).strip()
                        if s:
                            result.append(s)
            return result

        if isinstance(skills_raw, list):
            return [str(s).strip() for s in skills_raw if str(s).strip()]

        return []

    # ── Private: Deterministic helpers ────────────────────────────────

    @staticmethod
    def _empty_analysis(description: str) -> JDAnalysis:
        """Return a skeleton analysis for empty descriptions."""
        return JDAnalysis(
            required_skills=[],
            nice_to_have_skills=[],
            responsibilities=[],
            experience_level=None,
            education_requirements=[],
            top_keywords=[],
            soft_skills=[],
            technologies=[],
            match_score=None,
            raw_text=description[:2000],
        )

    @staticmethod
    def _extract_responsibilities(description: str) -> list[str]:
        """Extract responsibility statements from *description*.

        Handles bullet-point lists and sentences starting with action verbs.
        """
        responsibilities: list[str] = []
        lines = description.split("\n")

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Bullet-point or numbered list items
            if re.match(r"^\s*[-*•‣◦⁃▶→]\s+", stripped):
                cleaned = re.sub(r"^\s*[-*•‣◦⁃▶→]\s+", "", stripped)
                if cleaned:
                    responsibilities.append(cleaned)
            elif re.match(r"^\s*\d+[.)]\s+", stripped):
                cleaned = re.sub(r"^\s*\d+[.)]\s+", "", stripped)
                if cleaned:
                    responsibilities.append(cleaned)
            # Section headers to skip
            elif re.match(
                r"^(responsibilit|what you.ll do|key duties|"
                r"role & responsibilit|about the role|job description|"
                r"what you will do|the role)",
                stripped,
                re.IGNORECASE,
            ):
                continue

        # If no bullet points found, extract sentences with action verbs
        if not responsibilities:
            action_verbs: list[str] = [
                "develop",
                "design",
                "implement",
                "build",
                "create",
                "manage",
                "maintain",
                "write",
                "test",
                "deploy",
                "analyze",
                "optimize",
                "improve",
                "lead",
                "coordinate",
                "collaborate",
                "support",
                "troubleshoot",
                "debug",
                "refactor",
                "integrate",
                "migrate",
                "automate",
                "monitor",
                "review",
                "document",
                "participate",
                "contribute",
            ]
            sentences = re.split(r"(?<=[.!?])\s+", description)
            for sent in sentences:
                ts = sent.strip()
                if not ts:
                    continue
                lower_sent = ts.lower()
                if any(lower_sent.startswith(v) for v in action_verbs):
                    responsibilities.append(ts)

        return responsibilities

    @staticmethod
    def _detect_experience_level(lower: str) -> str | None:
        """Detect experience level from the lowercased description text."""
        # Check for explicit years-of-experience patterns
        yr_match = re.search(r"(\d+)\s*\+?\s*years?\s*(?:of)?\s*experience", lower)
        if yr_match:
            years = int(yr_match.group(1))
            if years <= 1:
                return "entry"
            if years <= 3:
                return "junior"
            if years <= 5:
                return "mid"
            if years <= 8:
                return "senior"
            return "lead"

        # Fall back to keyword matching
        words_set = set(re.findall(r"[a-zA-Z][a-zA-Z0-9.-]*", lower))

        if words_set & _LEAD_KEYWORDS:
            return "lead"
        if words_set & _SENIOR_KEYWORDS:
            return "senior"
        if words_set & _MID_KEYWORDS:
            return "mid"
        if words_set & _JUNIOR_KEYWORDS:
            return "junior"
        if words_set & _ENTRY_KEYWORDS:
            return "entry"

        return None

    @staticmethod
    def _detect_education(lower: str) -> list[str]:
        """Extract education / certification requirements from lowercased text."""
        found: list[str] = []
        patterns: list[tuple[str, str]] = [
            (r"bachelor[^a-z]?s?\b|b\.?tech|b\.?e\b|b\.?s\b|b\.?a\b|undergraduate", "Bachelor's degree"),
            (r"master[^a-z]?s?\b|m\.?tech|m\.?e\b|m\.?s\b|m\.?b\.?a\b|graduate|postgraduate|post.graduate", "Master's degree"),
            (r"ph\.?d\b|doctorate|doctoral", "PhD"),
            (r"b\.?com\b|bachelor of commerce", "Bachelor's degree"),
            (r"m\.?com\b|master of commerce", "Master's degree"),
            (r"associate[^a-z]?s?\b|associate degree|diploma", "Associate/Diploma"),
        ]
        for pattern, label in patterns:
            if re.search(pattern, lower) and label not in found:
                found.append(label)

        # Check for specific certifications
        certs: list[str] = [
            "aws certified",
            "azure certified",
            "gcp certified",
            "google cloud certified",
            "pmp",
            "scrum master",
            "cfa",
            "cpa",
            "ceh",
            "oscp",
            "ccna",
            "tensorflow developer",
            "kubernetes administrator",
            "cka",
            "ckad",
        ]
        for cert in certs:
            if cert in lower:
                found.append(cert.title())

        return found

    @staticmethod
    def _detect_soft_skills(lower: str) -> list[str]:
        """Extract soft skills from lowercased text via regex patterns."""
        soft: list[str] = []
        for pattern in _SOFT_SKILLS_KEYWORDS:
            m = re.search(pattern, lower)
            if m:
                # Normalise the matched text: replace dots with hyphens
                text = m.group(0).replace(".", "-")
                # Title-case each word for a clean presentation
                text = text.replace("-", " ").title()
                if text not in soft:
                    soft.append(text)
        return soft

    @staticmethod
    def _extract_top_keywords(words: list[str], matched_skills: set[str]) -> list[str]:
        """Rank top keywords using a TF-IDF-like frequency approach.

        Prioritises matched skills, then fills with important frequent terms.
        """
        stop_words: set[str] = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "as", "is", "are", "was", "were", "be",
            "been", "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can", "need",
            "this", "that", "these", "those", "it", "its", "we", "our", "you",
            "your", "they", "them", "their", "who", "whom", "which", "what",
            "when", "where", "why", "how", "all", "each", "every", "both",
            "few", "more", "most", "other", "some", "such", "no", "nor", "not",
            "only", "own", "same", "so", "than", "too", "very", "just", "about",
            "if", "then", "else", "also", "well", "here", "there", "now",
            "up", "down", "out", "off", "over", "under", "again", "further",
            "above", "below", "any", "into", "like", "much", "must",
        }

        word_freq = Counter(words)
        important_words: list[str] = [
            w for w, _ in word_freq.most_common(60)
            if w not in stop_words and len(w) > 2
        ]

        # Prioritise matched skills, then fill with frequency-ranked terms
        ranked: list[str] = list(matched_skills)
        for w in important_words:
            if w not in ranked:
                ranked.append(w)
            if len(ranked) >= 15:
                break

        return ranked[:15]


__all__ = ["JDAnalysis", "JDAnalyzer"]
