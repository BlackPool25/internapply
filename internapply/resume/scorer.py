"""ATS Keyword Scorer — deterministic keyword matching and format scoring.

Provides :class:`ATSScorer` which computes a 0–100 ATS compatibility score
using ONLY keyword matching and format checking — no LLM calls, no API keys.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

# ──────────────────────────────────────────────────────────────────────────
# Data models
# ──────────────────────────────────────────────────────────────────────────


class KeywordEntry(BaseModel):
    """Per-keyword breakdown of the match result."""

    keyword: str
    present: bool
    weight: str  # "required" or "nice_to_have"


class ATSScore(BaseModel):
    """ATS compatibility score with detailed breakdown (0–100)."""

    total: int
    keyword_match: int  # 0-60
    nice_to_have_match: int  # 0-15
    format_score: int  # 0-15
    title_match: int  # 0-15
    skills_density: int  # 0-10
    keywords_table: list[KeywordEntry]
    format_issues: list[str]
    suggestions: list[str]


# ──────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────

_STANDARD_SECTION_HEADERS: set[str] = {
    "education",
    "experience",
    "skills",
    "technical skills",
    "projects",
    "professional summary",
    "summary",
    "work experience",
    "employment",
    "certifications",
    "achievements",
    "publications",
    "honors",
    "awards",
    "leadership",
    "volunteer",
    "languages",
    "interests",
    "additional information",
    "objective",
    "profile",
    "qualifications",
    "technical experience",
    "research",
    "coursework",
    "relevant experience",
}

_TITLE_STOP_WORDS: set[str] = {
    "a", "an", "the", "in", "at", "on", "for", "of", "to", "and", "or",
    "with", "is", "are", "was", "were", "be", "been", "being", "have",
    "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "shall", "can", "need", "this", "that", "these",
    "those", "it", "its", "we", "our", "you", "your", "they", "them",
    "their", "intern", "internship", "developer", "engineer", "role",
    "position", "trainee", "fresher",
}

_BULLET_PATTERN = re.compile(r"^[\s]*[-*•‣◦⁃▶→▪–—›⁃]", re.MULTILINE)


# ──────────────────────────────────────────────────────────────────────────
# ATSScorer
# ──────────────────────────────────────────────────────────────────────────


class ATSScorer:
    """Deterministic ATS keyword scorer.

    Computes a 0–100 compatibility score using ONLY keyword matching and
    format heuristics.  No LLM, no API keys, no external dependencies.

    Usage::

        scorer = ATSScorer()
        result = scorer.score(
            resume_text="...",
            jd_skills={"required_skills": ["Python", "Django"], "nice_to_have_skills": ["FastAPI"]},
            job_title="Python Backend Developer",
        )
        print(result.total)  # 0–100
    """

    # ── Public API ─────────────────────────────────────────────────────

    def score(
        self,
        resume_text: str,
        jd_skills: dict[str, Any],
        job_title: str,
    ) -> ATSScore:
        """Compute a 0–100 ATS compatibility score.

        Parameters
        ----------
        resume_text:
            Full plain text of the tailored resume.
        jd_skills:
            Dictionary with keys ``required_skills`` and ``nice_to_have_skills``,
            each a list of skill strings.
        job_title:
            The job title whose words are matched against the resume summary.

        Returns
        -------
        An :class:`ATSScore` with detailed component breakdown.
        """
        required: list[str] = jd_skills.get("required_skills", []) or []
        nice_have: list[str] = jd_skills.get("nice_to_have_skills", []) or []
        all_jd_skills = list(set(required + nice_have))

        lower_resume = resume_text.lower()

        # ── 1. Keyword Match (60 + 15 points) ─────────────────────────
        kw_score, nh_score, kw_table = self._keyword_match(
            required, nice_have, lower_resume,
        )

        # ── 2. Format Score (15 points) ───────────────────────────────
        fmt_score, fmt_issues = self._format_score(resume_text)

        # ── 3. Title Match (15 points) ────────────────────────────────
        title_score = self._title_match(job_title, lower_resume)

        # ── 4. Skills Density (10 points) ─────────────────────────────
        density_score = self._skills_density(all_jd_skills, lower_resume)

        # ── Total (cap at 100) ────────────────────────────────────────
        total = kw_score + nh_score + fmt_score + title_score + density_score
        total = min(total, 100)

        # ── Suggestions ───────────────────────────────────────────────
        suggestions = self._generate_suggestions(
            kw_table=kw_table,
            format_issues=fmt_issues,
            title_score=title_score,
            density_score=density_score,
        )

        return ATSScore(
            total=total,
            keyword_match=kw_score,
            nice_to_have_match=nh_score,
            format_score=fmt_score,
            title_match=title_score,
            skills_density=density_score,
            keywords_table=kw_table,
            format_issues=fmt_issues,
            suggestions=suggestions,
        )

    # ── Private: Keyword Match ────────────────────────────────────────

    @staticmethod
    def _keyword_match(
        required: list[str],
        nice_have: list[str],
        lower_resume: str,
    ) -> tuple[int, int, list[KeywordEntry]]:
        """Check each skill for presence in the resume text.

        Returns
        -------
        (keyword_score_capped_60, nice_to_have_score_capped_15, keywords_table)
        """
        table: list[KeywordEntry] = []
        kw_score = 0

        for skill in required:
            present = _skill_in_text(skill, lower_resume)
            table.append(KeywordEntry(
                keyword=skill,
                present=present,
                weight="required",
            ))
            if present:
                kw_score += 3

        nh_score = 0
        for skill in nice_have:
            present = _skill_in_text(skill, lower_resume)
            table.append(KeywordEntry(
                keyword=skill,
                present=present,
                weight="nice_to_have",
            ))
            if present:
                nh_score += 1

        return min(kw_score, 60), min(nh_score, 15), table

    # ── Private: Format Score ─────────────────────────────────────────

    @staticmethod
    def _format_score(resume_text: str) -> tuple[int, list[str]]:
        """Evaluate resume formatting quality (max 15).

        +5 Single-column layout
        +5 Standard section headers (>= 3 found)
        +5 Bullet points (>= 5 found)
        """
        score = 0
        issues: list[str] = []

        # ── Single-column layout (+5) ────────────────────────────────
        single_col = _check_single_column(resume_text)
        if single_col:
            score += 5
        else:
            issues.append(
                "Resume appears to use a multi-column layout, "
                "which can confuse ATS parsers — consider a single-column format"
            )

        # ── Standard section headers (+5) ────────────────────────────
        headers_found = _check_section_headers(resume_text)
        if headers_found >= 3:
            score += 5
        elif headers_found >= 1:
            score += 3
            issues.append(
                f"Only {headers_found}/3+ standard section headers detected — "
                "add Education, Skills, and Experience sections"
            )
        else:
            issues.append(
                "No standard section headers detected — "
                "use clear headings like Education, Skills, Experience"
            )

        # ── Bullet points (+5) ────────────────────────────────────────
        bullet_count = _count_bullets(resume_text)
        if bullet_count >= 5:
            score += 5
        elif bullet_count >= 2:
            score += 3
            issues.append(
                f"Only {bullet_count} bullet points found — "
                "ATS prefers bullet-pointed experience listings"
            )
        else:
            issues.append(
                "No bullet points detected — "
                "use bullet points for experience and project descriptions"
            )

        return score, issues

    # ── Private: Title Match ──────────────────────────────────────────

    @staticmethod
    def _title_match(job_title: str, lower_resume: str) -> int:
        """Compute how many meaningful title words appear in the resume (0–15).

        Filters out common stop words from the title, then computes
        (matched / total_meaningful) * 15.
        """
        title_words = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.]*", job_title)
        meaningful = [
            w.lower() for w in title_words
            if w.lower() not in _TITLE_STOP_WORDS and len(w) > 1
        ]

        if not meaningful:
            return 0

        matched = sum(1 for w in meaningful if w in lower_resume)
        score = (matched / len(meaningful)) * 15
        return round(score)

    # ── Private: Skills Density ───────────────────────────────────────

    @staticmethod
    def _skills_density(
        all_jd_skills: list[str],
        lower_resume: str,
    ) -> int:
        """Compute skills density score (0–10).

        Ratio of matched JD keywords to total unique skills mentioned
        in the resume.  A higher ratio indicates a more focused,
        JD-aligned skill set.
        """
        resume_skills = _extract_skills_from_text(lower_resume)

        if not resume_skills:
            return 0

        matched = sum(
            1 for s in all_jd_skills if _skill_in_text(s, lower_resume)
        )

        density = matched / len(resume_skills)
        density = min(density, 1.0)
        return round(density * 10)

    # ── Private: Suggestions ──────────────────────────────────────────

    @staticmethod
    def _generate_suggestions(
        kw_table: list[KeywordEntry],
        format_issues: list[str],
        title_score: int,
        density_score: int,
    ) -> list[str]:
        """Generate actionable improvement suggestions."""
        suggestions: list[str] = []

        # Missing required skills
        missing_required = [
            e.keyword for e in kw_table
            if e.weight == "required" and not e.present
        ]
        if missing_required:
            display = missing_required[:5]
            suffix = "..." if len(missing_required) > 5 else ""
            suggestions.append(
                "Add missing required skill{} to resume: {}{}".format(
                    "s" if len(missing_required) != 1 else "",
                    ", ".join(display),
                    suffix,
                )
            )

        # Missing nice-to-have skills (only if few enough to list)
        missing_nice = [
            e.keyword for e in kw_table
            if e.weight == "nice_to_have" and not e.present
        ]
        if missing_nice and len(missing_nice) <= 8:
            suggestions.append(
                "Consider adding these preferred skills: {}".format(
                    ", ".join(missing_nice)
                )
            )

        # Title match
        if title_score < 10:
            suggestions.append(
                "Incorporate job title keywords into your professional summary"
            )

        # Skills density
        if density_score < 5:
            suggestions.append(
                "Consider trimming less relevant skills to improve keyword density"
            )

        # Format issues (already descriptive)
        suggestions.extend(format_issues)

        return suggestions


# ──────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ──────────────────────────────────────────────────────────────────────────


def _skill_in_text(skill: str, lower_resume: str) -> bool:
    """Check if *skill* appears in *lower_resume* with word-boundary awareness.

    For multi-word skills (e.g. ``"machine learning"``) the full phrase is
    matched as a substring.  For single tokens (e.g. ``"go"``) a word-boundary
    regex is used to avoid false positives like ``"going"`` or ``"mongodb"``.
    """
    skill_lower = skill.strip().lower()
    if not skill_lower:
        return False

    # Multi-word or slash-separated → exact substring check
    if " " in skill_lower or "/" in skill_lower:
        return skill_lower in lower_resume

    # Single token → word-boundary regex to avoid partial matches
    pattern = re.compile(
        r"(?<![a-zA-Z])" + re.escape(skill_lower) + r"(?![a-zA-Z])",
    )
    return bool(pattern.search(lower_resume))


def _check_single_column(resume_text: str) -> bool:
    """Heuristic: detect multi-column layout indicators.

    Returns ``True`` if the resume appears to be single-column (ATS-friendly).
    """
    lines = resume_text.strip().split("\n")
    if not lines:
        return True

    # Many short lines suggests a two-column layout (e.g. skills sidebar)
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return True

    short_lines = sum(1 for l in non_empty if len(l.strip()) < 30)
    if len(non_empty) > 5 and short_lines / len(non_empty) > 0.4:
        return False

    # Lines with words separated by 3+ spaces (tabular alignment)
    sample = non_empty[:30]
    multi_col = sum(1 for l in sample if re.search(r"\w\s{3,}\w", l))
    return not (len(sample) > 0 and multi_col / len(sample) > 0.3)


def _check_section_headers(resume_text: str) -> int:
    """Count how many standard section headers appear as line-level headings."""
    lower = resume_text.lower()
    found = 0
    for header in _STANDARD_SECTION_HEADERS:
        pattern = re.compile(
            r"^" + re.escape(header) + r"[:\s]*$", re.MULTILINE,
        )
        if pattern.search(lower):
            found += 1
    return found


def _count_bullets(resume_text: str) -> int:
    """Count bullet-point lines in the resume."""
    return len(_BULLET_PATTERN.findall(resume_text))


# ──────────────────────────────────────────────────────────────────────────
# Skills dictionary (for density extraction)
# ──────────────────────────────────────────────────────────────────────────

_COMMON_SKILLS_FOR_DENSITY: list[str] = [
    # Languages
    "python", "java", "javascript", "typescript", "go", "golang", "rust",
    "c++", "c", "c#", "csharp", "ruby", "php", "swift", "kotlin", "scala",
    "perl", "r", "matlab", "sql", "nosql", "html", "css", "scss", "sass",
    "dart", "elixir", "haskell", "clojure", "julia",
    # Web frameworks
    "django", "flask", "fastapi", "spring boot", "spring", "express",
    "express.js", "node.js", "node", "react", "react.js", "vue", "vue.js",
    "angular", "next.js", "nextjs", "nuxt.js", "svelte", "jquery",
    "bootstrap", "tailwind", "tailwind css",
    # Backend & databases
    "rest", "rest api", "graphql", "grpc", "api", "microservices",
    "postgresql", "postgres", "mysql", "mongodb", "redis", "sqlite",
    "mariadb", "elasticsearch", "cassandra", "dynamodb", "firebase",
    "supabase", "cockroachdb", "couchdb", "neo4j",
    # Cloud & DevOps
    "aws", "gcp", "azure", "cloud", "docker", "kubernetes", "k8s",
    "terraform", "ansible", "jenkins", "ci/cd", "github actions",
    "gitlab ci", "circleci", "argocd", "helm", "prometheus", "grafana",
    "istio", "envoy",
    # Tools & version control
    "git", "linux", "unix", "bash", "shell", "make", "cmake",
    # Data & ML
    "machine learning", "deep learning", "nlp", "tensorflow", "pytorch",
    "pandas", "numpy", "scikit-learn", "scipy", "opencv",
    "llm", "ai", "artificial intelligence", "rag", "langchain",
    "hugging face", "transformers", "spacy", "nltk",
    "airflow", "spark", "hadoop",
    # Message queues & streaming
    "kafka", "rabbitmq", "celery", "nats", "pulsar", "amazon sqs",
    # Testing
    "pytest", "jest", "mocha", "selenium", "cypress", "junit", "unittest",
    "playwright", "vitest",
    # Auth & security
    "oauth", "jwt", "sso", "rbac", "tls", "ssl",
    # Mobile
    "android", "ios", "flutter", "react native",
    # Concepts
    "oop", "orm", "tdd", "agile", "scrum", "design patterns", "solid",
    # Other
    "docker compose", "nginx", "apache", "gunicorn", "uvicorn",
]


def _extract_skills_from_text(lower_resume: str) -> set[str]:
    """Extract all known skills mentioned in the resume text.

    Used by the skills-density computation.
    """
    found: set[str] = set()
    for skill in _COMMON_SKILLS_FOR_DENSITY:
        if _skill_in_text(skill, lower_resume):
            found.add(skill)
    return found


__all__ = [
    "ATSScore",
    "ATSScorer",
    "KeywordEntry",
]
