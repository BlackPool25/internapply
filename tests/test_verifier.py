"""Tests for ResumeVerifier — deterministic hallucination gate.

Verifies that tailored resumes only contain content derived from the
candidate's source resume — no fabricated projects, inflated skills,
hallucinated metrics, or date mismatches.
"""

from __future__ import annotations

import pytest

from internapply.resume.verifier import ResumeVerifier


# ---------------------------------------------------------------------------
# Fixtures — reusable test data
# ---------------------------------------------------------------------------

@pytest.fixture
def verifier() -> ResumeVerifier:
    """Return a bare ResumeVerifier (no source path needed when passing dicts)."""
    return ResumeVerifier(source_path="/dev/null/non-existent")


@pytest.fixture
def source_resume() -> dict:
    """Standard source resume used across most verifier tests."""
    return {
        "name": "John Doe",
        "email": "john@example.com",
        "summary": "CS student with Python and Django experience.",
        "skills": {
            "Languages": "Python, Java, JavaScript",
            "Frameworks": "Django, React",
        },
        "projects": [
            {
                "name": "E-commerce Platform",
                "tech": "Python, Django",
                "date": "Jan 2023",
                "bullets": [
                    "Built RESTful APIs handling 1000+ requests/day",
                    "Implemented payment gateway integration",
                ],
            },
            {
                "name": "Chat Application",
                "tech": "React, Node.js",
                "date": "Jun 2022",
                "bullets": ["Designed real-time messaging system"],
            },
        ],
        "education": [
            {
                "degree_name": "B.Tech",
                "institution": "IIT Bombay",
                "cgpa": "8.5",
                "dates": "2020-2024",
            },
        ],
        "additional": [
            {"title": "Open Source Contributor", "org": "Hacktoberfest"},
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVerifierGate:
    """8+ tests covering all ResumeVerifier check methods."""

    def test_clean_resume_passes(self, verifier, source_resume):
        """Resume with all real data should pass (score=100)."""
        tailored = {
            "summary": "CS student with Python and Django experience.",
            "skills_reordered": ["Python", "Java", "JavaScript", "Django", "React"],
            "projects": [
                {
                    "name": "E-commerce Platform",
                    "tech": "Python, Django",
                    "date": "Jan 2023",
                    "bullets": [
                        "Built RESTful APIs handling 1000+ requests/day",
                        "Implemented payment gateway integration",
                    ],
                },
                {
                    "name": "Chat Application",
                    "tech": "React, Node.js",
                    "date": "Jun 2022",
                    "bullets": ["Designed real-time messaging system"],
                },
            ],
            "education": [
                {
                    "degree_name": "B.Tech",
                    "institution": "IIT Bombay",
                    "cgpa": "8.5",
                },
            ],
        }
        report = verifier.verify(
            tailored_resume=tailored,
            source_resume=source_resume,
        )
        assert report.passed, f"Expected passed=True but got score={report.score}"
        assert report.score == 100, f"Expected score=100 but got {report.score}"
        assert len(report.violations) == 0, f"Expected 0 violations but got {len(report.violations)}: {report.violations}"

    def test_hallucinated_project_detected(self, verifier, source_resume):
        """Fake project name not in source should be detected as violation."""
        tailored = {
            "projects": [
                {"name": "E-commerce Platform"},  # real
                {"name": "Fake Quantum AI Project"},  # hallucinated
                {"name": "Nonexistent Blockchain App"},  # hallucinated
            ],
        }
        report = verifier.verify(
            tailored_resume=tailored,
            source_resume=source_resume,
        )
        project_violations = [
            v for v in report.violations
            if v.field == "project.name"
        ]
        assert len(project_violations) >= 2, (
            f"Expected at least 2 project violations but got {len(project_violations)}"
        )
        claimed = {v.claimed_value for v in project_violations}
        assert "Fake Quantum AI Project" in claimed
        assert "Nonexistent Blockchain App" in claimed

    def test_hallucinated_skill_detected(self, verifier, source_resume):
        """Skill not present in source resume should be flagged."""
        tailored = {
            "skills_reordered": [
                "Python",  # real
                "COBOL",  # hallucinated
                "React",  # real
                "Fortran",  # hallucinated
            ],
        }
        report = verifier.verify(
            tailored_resume=tailored,
            source_resume=source_resume,
        )
        skill_violations = [
            v for v in report.violations
            if v.field == "skills_reordered"
        ]
        # Each hallucinated skill is one violation; score drops below 60
        # with enough violations (100 - 2*20 = 60 still passes, but we
        # just verify detection, not necessarily failure)
        assert len(skill_violations) == 2, (
            f"Expected 2 skill violations but got {len(skill_violations)}"
        )
        claimed = {v.claimed_value for v in skill_violations}
        assert "COBOL" in claimed
        assert "Fortran" in claimed

    def test_date_normalization(self, verifier):
        """'January 2023' should match 'Jan 2023' after normalization to YYYY-MM."""
        source = {
            "projects": [
                {"name": "Platform", "date": "Jan 2023"},
            ],
        }
        tailored = {
            "projects": [
                {"name": "Platform", "date": "January 2023"},
            ],
        }
        report = verifier.verify(
            tailored_resume=tailored,
            source_resume=source,
        )
        # Both normalize to "2023-01" — no violation expected
        date_violations = [v for v in report.violations if v.field == "date"]
        assert len(date_violations) == 0, (
            f"Expected no date violations after normalization but got: {date_violations}"
        )
        assert report.passed

    def test_date_mismatch_detected(self, verifier):
        """A date in tailored that does NOT appear in source should be flagged."""
        source = {
            "projects": [
                {"name": "Platform", "date": "Jan 2023"},
            ],
        }
        tailored = {
            "projects": [
                {"name": "Platform", "date": "December 2024"},
            ],
        }
        report = verifier.verify(
            tailored_resume=tailored,
            source_resume=source,
        )
        date_violations = [v for v in report.violations if v.field == "date"]
        assert len(date_violations) >= 1, "Expected at least 1 date violation"

    def test_education_mismatch(self, verifier, source_resume):
        """Different degree / institution from source should be detected."""
        tailored = {
            "education": [
                {
                    "degree_name": "PhD in Computer Science",
                    "institution": "Harvard University",
                },
                {
                    "degree_name": "MBA",
                    "institution": "Stanford University",
                },
            ],
        }
        report = verifier.verify(
            tailored_resume=tailored,
            source_resume=source_resume,
        )
        edu_violations = [
            v for v in report.violations
            if v.field.startswith("education.")
        ]
        assert len(edu_violations) >= 2, (
            f"Expected at least 2 education violations but got {len(edu_violations)}"
        )
        # Score should now be well below 60 (2 entries × 2 checks = 4 violations → 100 - 4*20 = 20)
        assert not report.passed, (
            f"Expected report to fail but score={report.score} with {len(edu_violations)} edu violations"
        )

    def test_metric_extraction(self, verifier):
        """Numeric metrics preserved from source pass; new metrics flagged."""
        source = {
            "summary": "Improved performance by 40% and reduced costs by $2M",
            "projects": [
                {
                    "name": "Optimization",
                    "bullets": ["Reduced latency by 3.87× for 1000+ users"],
                },
            ],
        }
        tailored = {
            "summary": "Improved performance by 40% and reduced costs by $2M",
            "projects": [
                {
                    "name": "Optimization",
                    "bullets": [
                        "Reduced latency by 3.87× for 1000+ users",
                        "Boosted revenue by $5M",  # hallucinated metric
                    ],
                },
            ],
        }
        report = verifier.verify(
            tailored_resume=tailored,
            source_resume=source,
        )
        metric_violations = [v for v in report.violations if v.field == "metric"]
        # "3.87×", "40%", "$2m" from source should match; "$5m" is new
        assert len(metric_violations) == 1, (
            f"Expected 1 metric violation (for $5M) but got {len(metric_violations)}: {metric_violations}"
        )
        assert "$5m" in metric_violations[0].claimed_value.lower()

    def test_ai_cliche_detected(self, verifier, source_resume):
        """'proven track record' should be flagged as a warning."""
        tailored = {
            "summary": "I have a proven track record of delivering high-quality software. "
                       "I am passionate about technology and a team player.",
        }
        report = verifier.verify(
            tailored_resume=tailored,
            source_resume=source_resume,
        )
        assert len(report.warnings) > 0, f"Expected warnings but got none"
        warning_text = " ".join(report.warnings).lower()
        assert "proven track record" in warning_text or "passionate about" in warning_text, (
            f"Expected cliché warning but got: {report.warnings}"
        )

    def test_ai_cliche_multiple_patterns(self, verifier, source_resume):
        """Multiple AI clichés each produce separate warnings."""
        tailored = {
            "summary": "Results-driven ninja with a proven track record. "
                       "Leverages cutting-edge technology and thinks outside the box.",
        }
        report = verifier.verify(
            tailored_resume=tailored,
            source_resume=source_resume,
        )
        assert len(report.warnings) >= 3, (
            f"Expected at least 3 cliché warnings but got {len(report.warnings)}: {report.warnings}"
        )

    def test_empty_resume(self, verifier):
        """Empty source and empty tailored should pass (score=100)."""
        report = verifier.verify(
            tailored_resume={},
            source_resume={},
        )
        assert report.passed, "Empty resume should pass verification"
        assert report.score == 100, "Empty resume should get score=100"
        assert len(report.violations) == 0

# ── Task-13 additions: WARN@80 + cache + metric synonym ──────────────────
from internapply.resume.verifier import normalize_metric, get_verifier_badge  # noqa: E402
from backend.app.discovery.hash_utils import jd_hash  # noqa: E402


class TestTask13:
    def test_pass_at_80_warn(self, verifier, source_resume):
        """1 error → score 80 should be WARN yellow not block (passed=True) during calibration (<30)."""
        # ensure calibration mode (<30 entries)
        from pathlib import Path
        import json as _json
        p = Path("data/tailor_cache.json")
        # backup
        bak = p.read_text(encoding="utf-8") if p.exists() else None
        try:
            p.write_text("{}", encoding="utf-8")
            # 1 hallucinated skill → 1 error → 80
            tailored = {
                "skills_reordered": ["Python", "COBOL"],  # COBOL not in source → 1 error
                "projects": [],
            }
            report = verifier.verify(tailored_resume=tailored, source_resume=source_resume)
            assert report.score == 80, f"expected 80 got {report.score}"
            assert get_verifier_badge(report.score) == "yellow"
            assert report.passed is True, "WARN yellow during calibration should not block (passed=True)"
        finally:
            if bak is not None:
                p.write_text(bak, encoding="utf-8")
            else:
                p.unlink(missing_ok=True)

    def test_metric_synonym_not_block(self, verifier):
        """cut vs reduced same metric → not violation via normalize_metric."""
        assert normalize_metric("cut latency 40%") == normalize_metric("reduced time by 40 percent")
        assert normalize_metric("40%") == normalize_metric("40 percent")
        source = {"summary": "cut latency 40% improved", "projects": []}
        tailored = {"summary": "reduced time by 40 percent", "projects": []}
        report = verifier.verify(tailored_resume=tailored, source_resume=source)
        metric_violations = [v for v in report.violations if v.field == "metric"]
        assert len(metric_violations) == 0, f"synonym metric should not violate but got {metric_violations}"

    def test_cache_hit_no_llm(self, tmp_path):
        """second call with same jd_hash uses 0 LLM (mock counter)."""
        import scripts.tailor as tailor_mod
        # reset
        from pathlib import Path as P
        cache_p = P("data/tailor_cache.json")
        bak = cache_p.read_text(encoding="utf-8") if cache_p.exists() else None
        try:
            cache_p.write_text("{}", encoding="utf-8")
            # use tmp canonical to avoid polluting applications
            jd = "Unique JD for cache test python backend 9999"
            r1 = tailor_mod.tailor_job("Backend Intern", "CacheCo", jd, canonical_id="cache_test_1")
            assert r1["llm_calls"] == 1 and not r1["cached"]
            r2 = tailor_mod.tailor_job("Backend Intern", "CacheCo", jd, canonical_id="cache_test_1")
            assert r2["cached"] is True and r2["llm_calls"] == 0, "second hit must be 0 LLM"
            # also jd_hash hit via hash_utils
            h = jd_hash(jd)
            assert r2["jd_hash"] == h
        finally:
            if bak is not None:
                cache_p.write_text(bak, encoding="utf-8")
            else:
                cache_p.unlink(missing_ok=True)
            # cleanup docx
            import shutil
            shutil.rmtree("applications/cache_test_1", ignore_errors=True)
