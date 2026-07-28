"""Tests for Pydantic v2 data models.

Covers JobListing, Application, and Resume creation, field types,
serialisation, and deserialisation roundtrip.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from internapply.models import (
    Application,
    EmailLookup,
    JobListing,
    Resume,
)


class TestJobListing:
    """JobListing model creation, defaults, and validation."""

    def test_job_listing_creation(self):
        """Create a JobListing with all fields populated."""
        job = JobListing(
            id=1,
            title="Python Backend Intern",
            company="TechCorp",
            location="Remote",
            stipend_min=15000,
            stipend_max=25000,
            stipend_raw="₹15,000-25,000 /month",
            skills=["Python", "FastAPI", "PostgreSQL"],
            analysis={"match_score": 85.0, "required_skills": ["Python"]},
            description="Build and maintain backend services.",
            source="internshala",
            url="https://internshala.com/internship/12345",
            posted_at="3 days ago",
            is_paid=True,
            is_remote=True,
            created_at="2024-01-15 10:30:00",
        )
        assert job.title == "Python Backend Intern"
        assert job.company == "TechCorp"
        assert job.location == "Remote"
        assert job.stipend_min == 15000
        assert job.stipend_max == 25000
        assert job.stipend_raw == "₹15,000-25,000 /month"
        assert job.skills == ["Python", "FastAPI", "PostgreSQL"]
        assert job.analysis == {"match_score": 85.0, "required_skills": ["Python"]}
        assert job.source == "internshala"
        assert job.url == "https://internshala.com/internship/12345"
        assert job.is_paid is True
        assert job.is_remote is True

    def test_job_listing_defaults(self):
        """JobListing fields have correct defaults when omitted."""
        job = JobListing(
            title="Backend Intern",
            company="Startup",
            source="naukri",
            url="https://naukri.com/job/1",
        )
        assert job.id is None
        assert job.location is None
        assert job.stipend_min is None
        assert job.stipend_max is None
        assert job.skills == []
        assert job.analysis is None
        assert job.description is None
        assert job.posted_at is None
        assert job.is_paid is False
        assert job.is_remote is False
        assert job.created_at is None

    def test_job_listing_required_fields(self):
        """Creating a JobListing without required fields raises."""
        with pytest.raises(ValidationError):
            JobListing()  # missing title, company, source, url


class TestApplication:
    """Application model creation, defaults, and validation."""

    def test_application_creation(self):
        """Create an Application with all fields populated."""
        app = Application(
            id=10,
            job_id=5,
            status="applied",
            tailored_resume_path="/path/to/tailored.json",
            cover_letter_path="/path/to/cover.md",
            email_sent=True,
            email_sent_at="2024-02-01 14:00:00",
            email_contacts=[
                {"email": "hr@example.com", "name": "John"},
            ],
            email_draft_path="/path/to/draft.md",
            portal_submitted=True,
            portal_submitted_at="2024-02-01 15:00:00",
            verifier_score=95,
            humanization_score=88,
            notes="Application submitted successfully.",
        )
        assert app.id == 10
        assert app.job_id == 5
        assert app.status == "applied"
        assert app.tailored_resume_path == "/path/to/tailored.json"
        assert app.email_sent is True
        assert len(app.email_contacts) == 1
        assert app.email_contacts[0]["email"] == "hr@example.com"
        assert app.verifier_score == 95
        assert app.humanization_score == 88

    def test_application_defaults(self):
        """Application fields have correct defaults when omitted."""
        app = Application(job_id=42)
        assert app.id is None
        assert app.status == "discovered"
        assert app.tailored_resume_path is None
        assert app.email_sent is False
        assert app.email_contacts == []
        assert app.portal_submitted is False
        assert app.verifier_score is None

    def test_application_missing_job_id(self):
        """Creating an Application without job_id raises."""
        with pytest.raises(ValidationError):
            Application()


class TestResume:
    """Resume model creation and defaults."""

    def test_resume_creation(self):
        """Create a Resume with all fields populated."""
        resume = Resume(
            id=1,
            name="Jane Doe",
            email="jane@example.com",
            phone="+91-9876543210",
            location="Bangalore",
            summary="Experienced Python developer.",
            education=[
                {"degree": "B.Tech", "institution": "IIT Delhi", "cgpa": "9.0"},
            ],
            skills={"Languages": "Python, Java", "Frameworks": "Django"},
            projects=[
                {"name": "Portfolio", "tech": "React", "bullets": ["Built UI"]},
            ],
            additional=[
                {"title": "Certification", "org": "AWS"},
            ],
            is_active=True,
        )
        assert resume.name == "Jane Doe"
        assert resume.email == "jane@example.com"
        assert len(resume.education) == 1
        assert resume.skills["Languages"] == "Python, Java"
        assert len(resume.projects) == 1
        assert len(resume.additional) == 1

    def test_resume_defaults(self):
        """Resume fields have correct defaults."""
        resume = Resume(name="John", email="john@test.com", summary=".")
        assert resume.id is None
        assert resume.phone is None
        assert resume.education == []
        assert resume.skills == {}
        assert resume.projects == []
        assert resume.additional == []
        assert resume.is_active is True


class TestSerialization:
    """Model serialisation and deserialisation roundtrip."""

    def test_model_serialization_roundtrip(self):
        """Model → dict → JSON → dict → Model preserves all fields."""
        original = JobListing(
            id=1,
            title="Python Backend Intern",
            company="TechCorp",
            location="Remote",
            stipend_min=15000,
            stipend_max=25000,
            skills=["Python", "FastAPI"],
            analysis={"match_score": 85.0},
            source="internshala",
            url="https://example.com",
            is_paid=True,
            is_remote=True,
        )

        # Model → dict
        data = original.model_dump()

        # dict → JSON (simulate network transfer)
        json_str = json.dumps(data, default=str)

        # JSON → dict
        restored_data = json.loads(json_str)

        # dict → Model
        restored = JobListing(**restored_data)

        assert restored.title == original.title
        assert restored.company == original.company
        assert restored.stipend_min == original.stipend_min
        assert restored.skills == original.skills
        assert restored.analysis == original.analysis
        assert restored.is_paid == original.is_paid
        assert restored.is_remote == original.is_remote

    def test_application_roundtrip(self):
        """Application → dict → Application preserves fields."""
        original = Application(
            job_id=10,
            status="applied",
            email_contacts=[{"email": "a@b.com"}],
            verifier_score=90,
        )
        data = original.model_dump()
        restored = Application(**data)
        assert restored.job_id == original.job_id
        assert restored.status == original.status
        assert restored.email_contacts == original.email_contacts
        assert restored.verifier_score == original.verifier_score

    def test_email_lookup_creation(self):
        """EmailLookup model works with from_attributes."""
        lookup = EmailLookup(
            domain="example.com",
            emails=[{"email": "info@example.com", "confidence": 95}],
        )
        assert lookup.domain == "example.com"
        assert len(lookup.emails) == 1
        assert lookup.emails[0]["email"] == "info@example.com"
