"""SQLAlchemy 2.0 ORM models for InternApply PostgreSQL schema.

All tables use declarative mapping with ``Mapped[]`` notation and PostgreSQL-
specific types (JSONB, etc.).  Every table includes ``created_at`` and
``updated_at`` timestamps with server-side defaults.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    Index,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


# ---------------------------------------------------------------------------
# Track A — Job Listings
# ---------------------------------------------------------------------------

class JobListing(Base):
    """A discovered internship / job listing scraped from job boards."""

    __tablename__ = "job_listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stipend_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stipend_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stipend_raw: Mapped[str | None] = mapped_column(String(100), nullable=True)
    skills: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50))
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    posted_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    posted_at_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)
    # hash/dedup fields — 64 hex (sha256), not 128
    canonical_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    jd_hash: Mapped[str | None] = mapped_column(
        String(64), index=True, nullable=True
    )
    simhash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    change_log: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    source_ats: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # relationships
    applications: Mapped[list["Application"]] = relationship(
        back_populates="job_listing", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_job_listings_source", "source"),
    )

    @property
    def cursor_value(self) -> datetime | date | None:
        """updated_after cursor fallback: updated_at → last_seen_at → posted_at_date."""
        return self.updated_at or self.last_seen_at or self.posted_at_date  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Track B — Companies & Contacts
# ---------------------------------------------------------------------------

class Company(Base):
    """A company discovered as a potential internship target (Track B lead gen)."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tech_stack: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    funding_stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    funding_total: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recent_news: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    culture_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    research_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    discovery_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # relationships
    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="company", passive_deletes=True
    )
    applications: Mapped[list["Application"]] = relationship(
        back_populates="company", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_companies_name", "name"),
    )


class Contact(Base):
    """A person found at a target company (potential outreach recipient)."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_confidence: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # "verified", "guessed", "user_filled"
    linkedin_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source: Mapped[str] = mapped_column(
        String(50)
    )  # "google_dorking", "github_api", "team_page", "crunchbase", "user_added"
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # relationships
    company: Mapped["Company"] = relationship(back_populates="contacts")
    applications: Mapped[list["Application"]] = relationship(
        back_populates="contact", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_contacts_company_id", "company_id"),
    )


# ---------------------------------------------------------------------------
# Applications — connects both tracks
# ---------------------------------------------------------------------------

class Application(Base):
    """An application or opportunity research record.

    Links together a job listing (Track A) and/or a company/contact (Track B)
    with the generated outreach materials.
    """

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_listing_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_listings.id", ondelete="SET NULL"), nullable=True
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True
    )
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="discovered",
        index=True,
    )
    fit_analysis: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    tailored_resume_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
        # NOTE: logical FK to tailored_resumes.id — applied as a real constraint
        # in the migration to avoid circular DDL dependency since
        # tailored_resumes.application_id also references applications.id.
    )
    cover_email_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
        # NOTE: logical FK to cover_emails.id — same circular-dependency reason.
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # relationships
    job_listing: Mapped["JobListing | None"] = relationship(back_populates="applications")
    company: Mapped["Company | None"] = relationship(back_populates="applications")
    contact: Mapped["Contact | None"] = relationship(back_populates="applications")
    tailored_resumes: Mapped[list["TailoredResume"]] = relationship(
        back_populates="application", passive_deletes=True
    )
    cover_emails: Mapped[list["CoverEmail"]] = relationship(
        back_populates="application", passive_deletes=True
    )
    email_drafts: Mapped[list["EmailDraft"]] = relationship(
        back_populates="application", passive_deletes=True
    )


# ---------------------------------------------------------------------------
# Tailored Resumes
# ---------------------------------------------------------------------------

class TailoredResume(Base):
    """A resume tailored to a specific application."""

    __tablename__ = "tailored_resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    resume_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    verifier_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verifier_report: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # relationships
    application: Mapped["Application"] = relationship(back_populates="tailored_resumes")


# ---------------------------------------------------------------------------
# Cover Emails
# ---------------------------------------------------------------------------

class CoverEmail(Base):
    """A cover email / letter generated for a specific application."""

    __tablename__ = "cover_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    humanization_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # relationships
    application: Mapped["Application"] = relationship(back_populates="cover_emails")


# ---------------------------------------------------------------------------
# Email Drafts (outreach)
# ---------------------------------------------------------------------------

class EmailDraft(Base):
    """An outreach email draft ready for review or sending."""

    __tablename__ = "email_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="draft"
    )  # "draft", "ready", "sent", "manual_copy"
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # relationships
    application: Mapped["Application"] = relationship(back_populates="email_drafts")


# ---------------------------------------------------------------------------
# Pipeline Runs — retained for run observability
# ---------------------------------------------------------------------------

class PipelineRun(Base):
    """A record of a pipeline execution (Track A, Track B, or full)."""

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_type: Mapped[str] = mapped_column(
        String(20)
    )  # "track_a", "track_b", "full"
    status: Mapped[str] = mapped_column(
        String(20), default="running"
    )  # "running", "completed", "failed"
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    companies_found: Mapped[int] = mapped_column(Integer, default=0)
    contacts_found: Mapped[int] = mapped_column(Integer, default=0)
    outreach_generated: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Dead Letters — failed scrape/sync rows for retry/backoff
# ---------------------------------------------------------------------------

class DeadLetter(Base):
    """Dead-letter queue for sources that hit errors (retry with backoff)."""

    __tablename__ = "dead_letters"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("source", "url", name="uq_dead_letters_source_url"),
        Index("ix_dead_letters_source", "source"),
        Index("ix_dead_letters_next_retry_at", "next_retry_at"),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def get_job_by_canonical_id(
    session: AsyncSession, canonical_id: str
) -> "JobListing | None":
    """Return job listing by canonical_id (64 hex) or None."""
    result = await session.execute(
        select(JobListing).where(JobListing.canonical_id == canonical_id)
    )
    return result.scalar_one_or_none()
