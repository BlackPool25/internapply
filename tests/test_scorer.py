"""Tests for ATSScorer — deterministic ATS keyword and format scoring.

Tests cover determinism (same input → same output), keyword presence/absence,
and format scoring differentiation.
"""

from __future__ import annotations

import pytest

from internapply.resume.scorer import ATSScorer, ATSScore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def scorer() -> ATSScorer:
    """Return a fresh ATSScorer instance (stateless, so reused)."""
    return ATSScorer()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestATSScorer:
    """3+ tests for deterministic ATS scoring."""

    def test_deterministic(self, scorer):
        """Same input produces identical score every time."""
        resume_text = (
            "Experienced Python developer with Django and PostgreSQL skills. "
            "Built RESTful APIs and worked with Docker containers."
        )
        jd_skills = {
            "required_skills": ["Python", "Django", "PostgreSQL"],
            "nice_to_have_skills": ["Docker", "FastAPI"],
        }
        job_title = "Python Backend Developer"

        result1 = scorer.score(resume_text, jd_skills, job_title)
        result2 = scorer.score(resume_text, jd_skills, job_title)

        assert result1.total == result2.total
        assert result1.keyword_match == result2.keyword_match
        assert result1.nice_to_have_match == result2.nice_to_have_match
        assert result1.format_score == result2.format_score
        assert result1.title_match == result2.title_match
        assert result1.skills_density == result2.skills_density

        # Keyword-level entries should also match
        for e1, e2 in zip(result1.keywords_table, result2.keywords_table):
            assert e1.present == e2.present

    def test_keyword_match(self, scorer):
        """Skills present in text get credit; missing skills do not."""
        resume_text = (
            "Python developer experienced with FastAPI and PostgreSQL. "
            "Familiar with Git and Linux. Proficient in Java."
        )
        jd_skills = {
            "required_skills": ["Python", "Java", "Go"],
            "nice_to_have_skills": ["Rust", "Kubernetes"],
        }

        result = scorer.score(resume_text, jd_skills, "Developer")

        # Build lookup from keyword table
        kw_map = {e.keyword: e.present for e in result.keywords_table}

        # Required skills
        assert kw_map.get("Python") is True, "Python should be found"
        assert kw_map.get("Java") is True, "Java should be found"
        assert kw_map.get("Go") is False, "Go should NOT be found (not in text)"

        # Nice-to-have skills
        assert kw_map.get("Rust") is False, "Rust should NOT be found"
        assert kw_map.get("Kubernetes") is False, "Kubernetes should NOT be found"

        # Verify keyword_match is proportional
        assert result.keyword_match == 6, (
            f"Expected keyword_match=6 (2/3 required matched × 3 pts each) "
            f"but got {result.keyword_match}"
        )

    def test_format_scoring(self, scorer):
        """Well-structured resume scores higher format points than plain text."""
        jd_skills: dict = {"required_skills": [], "nice_to_have_skills": []}

        # A well-formatted resume with section headers, bullets, single-column
        good_resume = (
            "Professional Summary\n"
            "Experienced developer with 5+ years building backend systems.\n"
            "\n"
            "Education\n"
            "Bachelor of Technology in Computer Science from IIT Bombay\n"
            "\n"
            "Skills\n"
            "Python, Java, JavaScript, Django, FastAPI, PostgreSQL, Docker\n"
            "\n"
            "Experience\n"
            "- Built and deployed RESTful APIs serving 10k+ requests per day\n"
            "- Designed database schemas for multi-tenant SaaS applications\n"
            "- Implemented CI/CD pipelines using GitHub Actions and Docker\n"
            "- Led migration of legacy monolith to microservices architecture\n"
        )

        # A poorly formatted resume with no structure
        bad_resume = (
            "Just a plain block of text with no section headers "
            "and no bullet points whatsoever. It's a single paragraph "
            "that would be very hard for an ATS to parse correctly."
        )

        good_result = scorer.score(good_resume, jd_skills, "Developer")
        bad_result = scorer.score(bad_resume, jd_skills, "Developer")

        assert good_result.format_score > bad_result.format_score, (
            f"Expected well-formatted resume ({good_result.format_score}) to "
            f"score higher than plain text ({bad_result.format_score})"
        )
        # A well-formatted resume should have at least some format points
        assert good_result.format_score >= 5, (
            f"Expected format_score >= 5 for well-formatted resume "
            f"but got {good_result.format_score}"
        )

    def test_title_match_affects_score(self, scorer):
        """Job title keywords in resume boost title_match score."""
        jd_skills: dict = {"required_skills": [], "nice_to_have_skills": []}

        resume_with_title = (
            "Backend software engineer passionate about Python development. "
            "Worked on multiple backend projects."
        )
        resume_without_title = (
            "Software enthusiast with experience in various technologies. "
            "Enjoy building things."
        )

        result_with = scorer.score(
            resume_with_title,
            jd_skills,
            "Backend Engineer Intern",
        )
        result_without = scorer.score(
            resume_without_title,
            jd_skills,
            "Backend Engineer Intern",
        )

        assert result_with.title_match > result_without.title_match, (
            f"Title match should be higher when keywords are in resume "
            f"(with={result_with.title_match}, without={result_without.title_match})"
        )

    def test_suggestions_for_missing_skills(self, scorer):
        """Missing required skills generate actionable suggestions."""
        resume_text = "I like writing code."
        jd_skills = {
            "required_skills": ["Python", "Django", "PostgreSQL", "Redis", "Docker"],
            "nice_to_have_skills": ["Kubernetes", "GraphQL"],
        }

        result = scorer.score(resume_text, jd_skills, "Developer")

        assert len(result.suggestions) > 0, "Expected suggestions for missing skills"
        # At least one suggestion should mention adding skills
        skill_suggestions = [s for s in result.suggestions if "skill" in s.lower() or "Skill" in s]
        assert len(skill_suggestions) >= 1, (
            f"Expected at least one skill-related suggestion but got: {result.suggestions}"
        )
