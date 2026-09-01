"""Create initial schema for InternApply — all 9 tables.

Tables are created in dependency order to satisfy foreign-key constraints:

1. ``job_listings``, ``companies`` (no FKs → leaf tables)
2. ``contacts`` (FK → companies)
3. ``applications`` (FK → job_listings, companies, contacts)
4. ``tailored_resumes``, ``cover_emails``, ``email_drafts``, ``batch_queue`` (FK → applications)
5. ``pipeline_runs`` (no FKs)

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-07-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_job_listings() -> None:
    op.create_table(
        "job_listings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("stipend_min", sa.Integer(), nullable=True),
        sa.Column("stipend_max", sa.Integer(), nullable=True),
        sa.Column("stipend_raw", sa.String(length=100), nullable=True),
        sa.Column("skills", postgresql.JSONB(), nullable=True),
        sa.Column("analysis", postgresql.JSONB(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("posted_at", sa.String(length=50), nullable=True),
        sa.Column("posted_at_date", sa.Date(), nullable=True),
        sa.Column("is_paid", sa.Boolean(), default=False, nullable=False),
        sa.Column("is_remote", sa.Boolean(), default=False, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", name="uq_job_listings_url"),
    )
    op.create_index("ix_job_listings_source", "job_listings", ["source"])


def _create_companies() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tech_stack", postgresql.JSONB(), nullable=True),
        sa.Column("funding_stage", sa.String(length=100), nullable=True),
        sa.Column("funding_total", sa.String(length=100), nullable=True),
        sa.Column("recent_news", postgresql.JSONB(), nullable=True),
        sa.Column("culture_data", postgresql.JSONB(), nullable=True),
        sa.Column("research_notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("discovery_method", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_companies_name", "companies", ["name"])


def _create_contacts() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("email_confidence", sa.String(length=20), nullable=True),
        sa.Column("linkedin_url", sa.String(length=2048), nullable=True),
        sa.Column("github_url", sa.String(length=2048), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_contacts_company_id", "contacts", ["company_id"])


def _create_applications() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_listing_id", sa.Integer(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), default="discovered", nullable=False),
        sa.Column("fit_analysis", postgresql.JSONB(), nullable=True),
        # tailored_resume_id and cover_email_id are plain Integer columns
        # (logical FKs only) to avoid circular DDL dependency:
        #   tailored_resumes.application_id → applications.id
        #   applications.tailored_resume_id → tailored_resumes.id
        sa.Column("tailored_resume_id", sa.Integer(), nullable=True),
        sa.Column("cover_email_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["job_listing_id"], ["job_listings.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_applications_status", "applications", ["status"])


def _create_tailored_resumes() -> None:
    op.create_table(
        "tailored_resumes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("resume_data", postgresql.JSONB(), nullable=False),
        sa.Column("verifier_score", sa.Integer(), nullable=True),
        sa.Column("verifier_report", postgresql.JSONB(), nullable=True),
        sa.Column("version", sa.Integer(), default=1, nullable=False),
        sa.Column("is_approved", sa.Boolean(), default=False, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
    )


def _create_cover_emails() -> None:
    op.create_table(
        "cover_emails",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("humanization_score", sa.Integer(), nullable=True),
        sa.Column("is_approved", sa.Boolean(), default=False, nullable=False),
        sa.Column("version", sa.Integer(), default=1, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
    )


def _create_email_drafts() -> None:
    op.create_table(
        "email_drafts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("recipient_name", sa.String(length=255), nullable=True),
        sa.Column("recipient_email", sa.String(length=320), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attachment_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), default="draft", nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
    )


def _create_batch_queue() -> None:
    op.create_table(
        "batch_queue",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), default="queued", nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
    )


def _create_pipeline_runs() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_type", sa.String(length=20), nullable=False),
        sa.Column(
            "status", sa.String(length=20), default="running", nullable=False
        ),
        sa.Column("jobs_found", sa.Integer(), default=0, nullable=False),
        sa.Column("companies_found", sa.Integer(), default=0, nullable=False),
        sa.Column("contacts_found", sa.Integer(), default=0, nullable=False),
        sa.Column("outreach_generated", sa.Integer(), default=0, nullable=False),
        sa.Column("errors", postgresql.JSONB(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def upgrade() -> None:
    _create_job_listings()
    _create_companies()
    _create_contacts()
    _create_applications()
    _create_tailored_resumes()
    _create_cover_emails()
    _create_email_drafts()
    _create_batch_queue()
    _create_pipeline_runs()


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    op.drop_table("pipeline_runs")
    op.drop_table("batch_queue")
    op.drop_table("email_drafts")
    op.drop_table("cover_emails")
    op.drop_table("tailored_resumes")
    op.drop_table("applications")
    op.drop_table("contacts")
    op.drop_table("companies")
    op.drop_table("job_listings")
