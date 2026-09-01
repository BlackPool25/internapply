"""Deterministic resume hallucination verifier.

Verifies that a tailored resume contains only content derived from the
candidate's source resume — no fabricated projects, inflated skills,
or hallucinated metrics.  Uses **set-based string matching only** —
never an LLM call.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Report & Violation models
# ---------------------------------------------------------------------------


class Violation(BaseModel):
    """A single verification violation."""

    field: str
    claimed_value: str
    source_value: str | None
    severity: str  # "error" | "warning"


class VerifierReport(BaseModel):
    """Result of verifying a tailored resume against the source resume."""

    passed: bool
    violations: list[Violation]
    warnings: list[str]
    score: int  # 0-100, 100 = perfect


# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

_DEFAULT_PROFILE_DIR = Path("profile")
_DEFAULT_RESUME_PATH = _DEFAULT_PROFILE_DIR / "resume.json"


# ---------------------------------------------------------------------------
# AI cliché patterns (word-boundary anchored)
# ---------------------------------------------------------------------------

_CLICHE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bproven track record\b", re.IGNORECASE),
    re.compile(r"\bpassionate about\b", re.IGNORECASE),
    re.compile(r"\bresults.driven\b", re.IGNORECASE),
    re.compile(r"\bteam player\b", re.IGNORECASE),
    re.compile(r"\bsynergy\b", re.IGNORECASE),
    re.compile(r"\bleverage\b", re.IGNORECASE),
    re.compile(r"\butilize\b", re.IGNORECASE),
    re.compile(r"\brockstar\b", re.IGNORECASE),
    re.compile(r"\bninja\b", re.IGNORECASE),
    re.compile(r"\bdeep dive\b", re.IGNORECASE),
    re.compile(r"\bI am writing to apply\b", re.IGNORECASE),
    re.compile(r"\bkeen interest\b", re.IGNORECASE),
    re.compile(r"\bstate.of.the.art\b", re.IGNORECASE),
    re.compile(r"\bcutting.edge\b", re.IGNORECASE),
    re.compile(r"\bthink outside the box\b", re.IGNORECASE),
    re.compile(r"\bgo.getter\b", re.IGNORECASE),
    re.compile(r"\bhardworking\b", re.IGNORECASE),
    re.compile(r"\bresponsible for\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Date normalisation
# ---------------------------------------------------------------------------

_MONTH_MAP: dict[str, str] = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}

_MONTH_PATTERN = r"(?:" + "|".join(_MONTH_MAP) + r")\s+\d{4}"
_DATE_SUBSTRING = re.compile(_MONTH_PATTERN, re.IGNORECASE)


def _normalize_date(date_str: str) -> str | None:
    """Normalise a date string to ``YYYY-MM`` format.

    Handles:
    - ``"January 2023"`` / ``"Jan 2023"``  → ``"2023-01"``
    - ``"2023"``                            → ``"2023-01"``
    """
    stripped = date_str.strip()
    # Month-name + year (e.g. "January 2023", "May 2027")
    m = _DATE_SUBSTRING.search(stripped)
    if m:
        month_name, year = _parse_month_year(m.group(0))
        return f"{year}-{_MONTH_MAP[month_name]}"
    # Standalone 4-digit year
    if re.match(r"^\d{4}$", stripped):
        return f"{stripped}-01"
    return None


def _parse_month_year(text: str) -> tuple[str, str]:
    """Split a ``"Month 2024"`` string into ``(month_name, year)``."""
    parts = text.strip().split()
    if len(parts) >= 2:
        return parts[0].lower(), parts[-1]
    return text.lower(), "0000"


def _extract_date_strings(text: str) -> set[str]:
    """Extract all date-like substrings from *text*.

    Returns month+year phrases and standalone 4-digit years.
    """
    dates: set[str] = set()
    for m in _DATE_SUBSTRING.finditer(text):
        dates.add(m.group(0).strip())
    # Standalone bare years (entire text is just "2023")
    stripped = text.strip()
    if re.match(r"^\d{4}$", stripped):
        dates.add(stripped)
    return dates


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------

_METRIC_PATTERN = re.compile(
    r"(?:\d+(?:,\d{3})*(?:\.\d+)?\s*%"              # percentages: 40%, 99.5%
    r"|\$\s*\d+(?:,\d{3})*(?:\.\d+)?[KMB]?"          # dollar amounts: $2M, $50k
    r"|\d+(?:,\d{3})*(?:\.\d+)?\s*[x\u00d7]"         # multipliers: 3.87×, 10x
    r"|\d+(?:,\d{3})*\+)"                             # counts with +: 1000+
)


def _extract_metrics(text: str) -> set[str]:
    """Extract normalised numeric metric strings from *text*."""
    return {m.group(0).strip().lower() for m in _METRIC_PATTERN.finditer(text)}


# ---------------------------------------------------------------------------
# Skill flattening
# ---------------------------------------------------------------------------


def _flatten_skills(skills_data: dict[str, Any] | list) -> set[str]:
    """Flatten source resume skills into a set of normalised lower-case strings.

    Handles dict format (``{"Languages": "Python, Java", ...}``) and list
    format (``["Python", "Java"]`` or ``[{"name": "Python"}, ...]``).
    """
    result: set[str] = set()
    if isinstance(skills_data, dict):
        for value in skills_data.values():
            if isinstance(value, str):
                for part in value.split(","):
                    part_clean = part.strip().lower()
                    if part_clean:
                        result.add(part_clean)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        item_clean = item.strip().lower()
                        if item_clean:
                            result.add(item_clean)
    elif isinstance(skills_data, list):
        for item in skills_data:
            if isinstance(item, str):
                item_clean = item.strip().lower()
                if item_clean:
                    result.add(item_clean)
            elif isinstance(item, dict) and "name" in item:
                item_clean = item["name"].strip().lower()
                if item_clean:
                    result.add(item_clean)
    return result


# ---------------------------------------------------------------------------
# ResumeVerifier
# ---------------------------------------------------------------------------


class ResumeVerifier:
    """Deterministic verifier that checks a tailored resume against the source.

    Uses **set-based string matching only** — never calls an LLM for
    verification.
    """

    def __init__(self, source_path: str | Path | None = None) -> None:
        """Initialise with an optional custom path to the source resume JSON.

        Args:
            source_path: Path to the source resume JSON.  Defaults to
                ``profile/resume.json`` relative to the project root.
        """
        self._source_path = Path(source_path) if source_path else _DEFAULT_RESUME_PATH

    # ── Public API ────────────────────────────────────────────────────

    def verify(
        self,
        tailored_resume: dict[str, Any],
        source_resume: dict[str, Any] | None = None,
    ) -> VerifierReport:
        """Verify *tailored_resume* against *source_resume*.

        If *source_resume* is ``None`` the verifier loads it from the
        default profile path (``profile/resume.json``).

        Args:
            tailored_resume: The LLM-generated tailored resume dict.
            source_resume: The source resume dict to verify against.
                If ``None``, loaded from the configured source path.

        Returns:
            A :class:`VerifierReport` with the verification result.
        """
        source = source_resume if source_resume is not None else self._load_source()
        violations: list[Violation] = []
        warnings_list: list[str] = []

        self._check_project_names(tailored_resume, source, violations)
        self._check_skills(tailored_resume, source, violations)
        self._check_dates(tailored_resume, source, violations)
        self._check_metrics(tailored_resume, source, violations)
        self._check_education(tailored_resume, source, violations)
        self._check_cliches(tailored_resume, warnings_list)

        error_count = sum(1 for v in violations if v.severity == "error")
        score = max(0, 100 - error_count * 20)
        # WARN@80: >80 green pass, 70-80 yellow WARN (pass during calibration, hard 422 after 30), <70 red fail
        if score > 80:
            passed = True
        elif score >= 70:
            passed = _is_calibration_mode()
            if passed:
                warnings_list.append(f"WARN yellow (score {score}): below 80 but within calibration window (<{_CALIBRATION_THRESHOLD} JDs)")
        else:
            passed = False

        return VerifierReport(
            passed=passed,
            violations=violations,
            warnings=warnings_list,
            score=score,
        )

    # ── Source loading ────────────────────────────────────────────────

    def _load_source(self) -> dict[str, Any]:
        """Load the source resume JSON from the configured path."""
        path = self._source_path.resolve()
        if not path.exists():
            return {"projects": [], "skills": {}, "education": [], "additional": []}
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)

    # ── Individual check methods ──────────────────────────────────────

    @staticmethod
    def _check_project_names(
        tailored: dict[str, Any],
        source: dict[str, Any],
        violations: list[Violation],
    ) -> None:
        """Check that every project name in *tailored* exists in *source*."""
        source_projects = source.get("projects", []) or []
        source_names = {
            p.get("name", "").strip().lower()
            for p in source_projects
            if p.get("name")
        }

        for proj in tailored.get("projects", []) or []:
            name = (proj.get("name") or "").strip()
            if not name:
                continue

            name_lower = name.lower()
            found = any(
                name_lower in src_name or src_name in name_lower
                for src_name in source_names
            )
            if not found:
                violations.append(
                    Violation(
                        field="project.name",
                        claimed_value=name,
                        source_value=None,
                        severity="error",
                    ),
                )

    @staticmethod
    def _check_skills(
        tailored: dict[str, Any],
        source: dict[str, Any],
        violations: list[Violation],
    ) -> None:
        """Check that every skill in *tailored* exists in *source*."""
        source_skills = _flatten_skills(source.get("skills", {}))

        for skill in tailored.get("skills_reordered", []) or []:
            if not isinstance(skill, str):
                continue
            skill_clean = skill.strip().lower()
            if not skill_clean:
                continue

            found = any(
                skill_clean == src or skill_clean in src or src in skill_clean
                for src in source_skills
            )
            if not found:
                violations.append(
                    Violation(
                        field="skills_reordered",
                        claimed_value=skill.strip(),
                        source_value=None,
                        severity="error",
                    ),
                )

    @staticmethod
    def _check_dates(
        tailored: dict[str, Any],
        source: dict[str, Any],
        violations: list[Violation],
    ) -> None:
        """Check that every normalised date in *tailored* exists in *source*."""
        source_normalized = _collect_normalized_dates(source)
        tailored_normalized = _collect_normalized_dates(tailored)

        for norm_date in tailored_normalized:
            if norm_date not in source_normalized:
                violations.append(
                    Violation(
                        field="date",
                        claimed_value=norm_date,
                        source_value=None,
                        severity="error",
                    ),
                )

    @staticmethod
    def _check_metrics(
        tailored: dict[str, Any],
        source: dict[str, Any],
        violations: list[Violation],
    ) -> None:
        """Check that every numeric metric in *tailored* exists in *source* (via normalize_metric)."""
        source_text = _collect_all_text(source)
        source_metrics = _extract_metrics(source_text)
        source_norm = {normalize_metric(m) for m in source_metrics}

        tailored_text = _collect_all_text(tailored)
        tailored_metrics = _extract_metrics(tailored_text)
        tailored_norm = {normalize_metric(m): m for m in tailored_metrics}

        for norm, raw in tailored_norm.items():
            # also consider full-text normalized comparison for synonym phrases:
            # if tailored_norm metric not in source_norm, check if the surrounding phrase normalized matches
            if norm not in source_norm:
                # secondary check: see if tailored_text normalized contains source-like metric phrase
                # we use strict metric set; if not found, check via full text synonym-aware containment
                tailored_full_norm = normalize_metric(tailored_text)
                source_full_norm = normalize_metric(source_text)
                # if raw metric (like "40 percent") appears in normalized source text, don't flag
                if norm in source_full_norm:
                    continue
                # if normalized full phrases share same metric token, don't flag when only verb differs
                # e.g. source has "cut latency 40 percent" -> normalize_metric(source_text) contains "reduce latency 40 percent"
                # and tailored is "reduce latency 40 percent" -> would be covered above.
                violations.append(
                    Violation(
                        field="metric",
                        claimed_value=raw,
                        source_value=None,
                        severity="error",
                    ),
                )
                continue
                # unreachable

    @staticmethod
    def _check_education(
        tailored: dict[str, Any],
        source: dict[str, Any],
        violations: list[Violation],
    ) -> None:
        """Check that each education entry in *tailored* is grounded in *source*."""
        source_edu = source.get("education", []) or []

        for entry in tailored.get("education", []) or []:
            if not isinstance(entry, dict):
                continue

            _check_edu_field(
                entry,
                "degree_name",
                source_edu,
                ["degree_name", "degree"],
                "education.degree",
                violations,
            )
            _check_edu_field(
                entry,
                "field_of_study",
                source_edu,
                None,
                "education.field_of_study",
                violations,
            )
            _check_edu_field(
                entry,
                "institution",
                source_edu,
                ["institution"],
                "education.institution",
                violations,
            )

            # GPA — check both "gpa" and "cgpa" keys
            gpa = (entry.get("gpa") or entry.get("cgpa") or "").strip()
            if gpa:
                found = _any_value_contains(source_edu, gpa)
                if not found:
                    violations.append(
                        Violation(
                            field="education.gpa",
                            claimed_value=gpa,
                            source_value=None,
                            severity="error",
                        ),
                    )

    @staticmethod
    def _check_cliches(
        tailored: dict[str, Any],
        warnings_list: list[str],
    ) -> None:
        """Scan the entire tailored resume for AI-cliché phrases (warnings only)."""
        text = _collect_all_text(tailored).lower()
        for pat in _CLICHE_PATTERNS:
            m = pat.search(text)
            if m:
                warnings_list.append(f'AI cliché detected: "{m.group(0).strip()}"')


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _collect_normalized_dates(obj: dict[str, Any]) -> set[str]:
    """Collect all date strings from *obj* and normalise them to ``YYYY-MM``."""
    raw: set[str] = set()
    _collect_date_strings(obj, raw)
    normalized: set[str] = set()
    for ds in raw:
        norm = _normalize_date(ds)
        if norm:
            normalized.add(norm)
    return normalized


def _collect_date_strings(obj: Any, out: set[str], depth: int = 0) -> None:
    """Recursively collect date-like substrings from a nested structure."""
    if depth > 10:
        return
    if isinstance(obj, dict):
        for value in obj.values():
            _collect_date_strings(value, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _collect_date_strings(item, out, depth + 1)
    elif isinstance(obj, str):
        out.update(_extract_date_strings(obj))


def _collect_all_text(obj: Any, depth: int = 0) -> str:
    """Recursively collect all string values from a nested dict/list structure.

    Reaches at most 10 levels deep to avoid infinite recursion on circular
    references.
    """
    if depth > 10:
        return ""
    parts: list[str] = []
    if isinstance(obj, dict):
        for value in obj.values():
            part = _collect_all_text(value, depth + 1)
            if part:
                parts.append(part)
    elif isinstance(obj, list):
        for item in obj:
            part = _collect_all_text(item, depth + 1)
            if part:
                parts.append(part)
    elif isinstance(obj, str):
        return obj
    return " ".join(parts)


def _check_edu_field(
    entry: dict[str, Any],
    key: str,
    source_edu: list[dict[str, Any]],
    source_fields: list[str] | None,
    violation_field: str,
    violations: list[Violation],
) -> None:
    """Check one education field against source entries.

    If *source_fields* is ``None``, searches all values in each source
    education entry (broad match).  Otherwise restricts the search to
    the specified keys.
    """
    value = (entry.get(key) or "").strip()
    if not value:
        return
    if source_fields is not None:
        found = _edu_field_exists(source_edu, value, source_fields)
    else:
        found = _any_value_contains(source_edu, value)
    if not found:
        violations.append(
            Violation(
                field=violation_field,
                claimed_value=value,
                source_value=None,
                severity="error",
            ),
        )


def _edu_field_exists(
    source_edu: list[dict[str, Any]],
    value: str,
    fields: list[str],
) -> bool:
    """Check if *value* (case-insensitive) exists in any of *fields* across source education entries.

    Uses substring matching (either direction) for flexibility.
    """
    value_lower = value.lower()
    for entry in source_edu:
        if not isinstance(entry, dict):
            continue
        for field in fields:
            entry_val = (entry.get(field) or "").strip().lower()
            if entry_val and (value_lower in entry_val or entry_val in value_lower):
                return True
    return False


def _any_value_contains(source_edu: list[dict[str, Any]], value: str) -> bool:
    """Check if *value* appears as a substring in any field of any source education entry."""
    value_lower = value.lower()
    for entry in source_edu:
        if not isinstance(entry, dict):
            continue
        for entry_val in entry.values():
            if isinstance(entry_val, str) and value_lower in entry_val.strip().lower():
                return True
    return False


# ── WARN@80 + calibration + normalize_metric ─────────────────────────
_CALIBRATION_THRESHOLD = 30
_CACHE_PATH = Path("data/tailor_cache.json")

# synonym map for metric normalization: cut/reduced/etc → reduce, latency/time → latency
_SYNONYM_MAP: dict[str, str] = {
    "cut": "reduce",
    "cuts": "reduce",
    "cutting": "reduce",
    "reduced": "reduce",
    "reduce": "reduce",
    "reduces": "reduce",
    "reducing": "reduce",
    "decreased": "reduce",
    "decrease": "reduce",
    "decreases": "reduce",
    "decreasing": "reduce",
    "improved": "reduce",
    "improve": "reduce",
    "improves": "reduce",
    "lowered": "reduce",
    "lower": "reduce",
    "time": "latency",
    "latency": "latency",
    "times": "latency",
}
_STOPWORDS = {"by", "the", "a", "an", "of", "to", "for", "in", "on", "at"}

_PERCENT_RE_V = re.compile(r"(\d+)\s*%")
_PERCENT_WORD_RE_V = re.compile(r"(\d+)\s+percent", re.IGNORECASE)


def normalize_metric(s: str) -> str:
    """Normalize metric strings: 40% == 40 percent, cut/reduced synonyms unified.

    Ensures ``normalize_metric('cut latency 40%') == normalize_metric('reduced time by 40 percent')``.
    Lowercases, unifies ``%`` → ``percent``, maps verbs/nouns via synonym dict, drops stopwords.
    """
    if not s:
        return ""
    t = s.lower().strip()
    # 40% → 40 percent
    t = _PERCENT_RE_V.sub(r"\1 percent", t)
    t = _PERCENT_WORD_RE_V.sub(lambda m: f"{m.group(1)} percent", t)
    # tokenise alphanumeric + percent already expanded
    tokens = re.findall(r"[a-z0-9]+", t)
    normed: list[str] = []
    for tok in tokens:
        if tok in _STOPWORDS:
            continue
        normed.append(_SYNONYM_MAP.get(tok, tok))
    # collapse percent duplication already handled; join
    return " ".join(normed).strip()


def _is_calibration_mode() -> bool:
    """True if still within first 30 JDs (WARN yellow not 422)."""
    try:
        p = _CACHE_PATH
        if not p.exists():
            return True
        data = json.loads(p.read_text(encoding="utf-8"))
        # count real jd_hash entries (exclude metadata keys starting with _)
        n = len([k for k in data.keys() if not str(k).startswith("_")])
        return n < _CALIBRATION_THRESHOLD
    except Exception:
        return True


def get_verifier_badge(score: int) -> str:
    """Return badge color for *score*: green >80, yellow 70-80, red <70."""
    if score > 80:
        return "green"
    if score >= 70:
        return "yellow"
    return "red"


__all__ = [
    "ResumeVerifier",
    "VerifierReport",
    "Violation",
    "normalize_metric",
    "get_verifier_badge",
]
