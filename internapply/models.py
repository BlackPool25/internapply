"""Pydantic v2 data models for InternApply.

Each model uses ``from_attributes=True`` so SQLAlchemy ORM rows can be
converted via ``model_validate(row)``.  The helper functions at the bottom of
this module handle JSON-column deserialisation that Pydantic cannot do
automatically.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# JobListing
# ---------------------------------------------------------------------------

class JobListing(BaseModel):
    """A discovered internship job listing."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    title: str
    company: str
    location: str | None = None
    stipend_min: int | None = None
    stipend_max: int | None = None
    stipend_raw: str | None = None
    skills: list[str] = Field(default_factory=list)
    analysis: dict[str, Any] | None = None
    description: str | None = None
    source: str
    url: str
    posted_at: str | None = None
    posted_at_date: date | None = None
    is_paid: bool = False
    is_remote: bool = False
    created_at: str | None = None


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class Application(BaseModel):
    """An application to a specific job listing."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    job_id: int
    status: str = "discovered"
    tailored_resume_path: str | None = None
    cover_letter_path: str | None = None
    email_sent: bool = False
    email_sent_at: str | None = None
    email_contacts: list[dict[str, Any]] = Field(default_factory=list)
    email_draft_path: str | None = None
    portal_submitted: bool = False
    portal_submitted_at: str | None = None
    verifier_score: int | None = None
    humanization_score: int | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

class Resume(BaseModel):
    """A candidate resume."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str
    email: str
    phone: str | None = None
    location: str | None = None
    summary: str
    education: list[dict[str, Any]] = Field(default_factory=list)
    skills: dict[str, Any] | list = Field(default_factory=dict)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    additional: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True


# ---------------------------------------------------------------------------
# EmailLookup
# ---------------------------------------------------------------------------

class EmailLookup(BaseModel):
    """Cached email lookups for a domain."""

    model_config = ConfigDict(from_attributes=True)

    domain: str
    emails: list[dict[str, Any]] = Field(default_factory=list)
    cached_at: str | None = None


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def job_listing_to_model(row: Any) -> JobListing:
    """Convert a SQLAlchemy ``job_listings`` row to a :class:`JobListing` model.

    Handles deserialisation of JSON-text columns (``skills_json``,
    ``analysis_json``) and ``created_at`` datetime-to-str conversion.
    """
    return JobListing(
        id=row.id,
        title=row.title,
        company=row.company,
        location=row.location,
        stipend_min=row.stipend_min,
        stipend_max=row.stipend_max,
        stipend_raw=row.stipend_raw,
        skills=json.loads(row.skills_json) if row.skills_json else [],
        analysis=json.loads(row.analysis_json) if row.analysis_json else None,
        description=row.description,
        source=row.source,
        url=row.url,
        posted_at=row.posted_at,
        posted_at_date=row.posted_at_date,
        is_paid=row.is_paid,
        is_remote=row.is_remote,
        created_at=str(row.created_at) if row.created_at else None,
    )


def application_to_model(row: Any) -> Application:
    """Convert a SQLAlchemy ``applications`` row to an :class:`Application` model.

    Handles deserialisation of ``email_contacts_json`` and datetime-to-str
    conversions for timestamp columns.
    """
    return Application(
        id=row.id,
        job_id=row.job_id,
        status=row.status,
        tailored_resume_path=row.tailored_resume_path,
        cover_letter_path=row.cover_letter_path,
        email_sent=row.email_sent,
        email_sent_at=str(row.email_sent_at) if row.email_sent_at else None,
        email_contacts=json.loads(row.email_contacts_json) if row.email_contacts_json else [],
        email_draft_path=row.email_draft_path,
        portal_submitted=row.portal_submitted,
        portal_submitted_at=str(row.portal_submitted_at) if row.portal_submitted_at else None,
        verifier_score=row.verifier_score,
        humanization_score=row.humanization_score,
        notes=row.notes,
    )


def resume_to_model(row: Any) -> Resume:
    """Convert a SQLAlchemy ``resumes`` row to a :class:`Resume` model.

    Handles deserialisation of the JSON-text columns (``education_json``,
    ``skills_json``, ``projects_json``, ``additional_json``).
    """
    return Resume(
        id=row.id,
        name=row.name,
        email=row.email,
        phone=row.phone,
        location=row.location,
        summary=row.summary,
        education=json.loads(row.education_json) if row.education_json else [],
        skills=json.loads(row.skills_json) if row.skills_json else {},
        projects=json.loads(row.projects_json) if row.projects_json else [],
        additional=json.loads(row.additional_json) if row.additional_json else [],
        is_active=row.is_active,
    )
