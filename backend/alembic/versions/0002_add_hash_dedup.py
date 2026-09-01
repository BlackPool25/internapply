"""Add hash/dedup columns + dead_letters, archive batch_queue orphan.

Revision ID: 0002_add_hash_dedup
Revises: 0001_initial_schema
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_add_hash_dedup"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = [c["name"] for c in insp.get_columns(table)]
        return col in cols
    except Exception:
        return False

def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return insp.has_table(table)
    except Exception:
        return False


def upgrade() -> None:
    # offline SQL generation (``--sql``) has no inspector — emit unconditional DDL
    if context.is_offline_mode():
        for col, typ in [
            ("canonical_id", sa.String(length=64)),
            ("jd_hash", sa.String(length=64)),
            ("simhash", sa.BigInteger()),
            ("etag", sa.String(length=255)),
            ("change_log", postgresql.JSONB()),
            ("source_ats", sa.String(length=32)),
            ("last_seen_at", sa.DateTime(timezone=True)),
        ]:
            try:
                op.add_column("job_listings", sa.Column(col, typ, nullable=True))
            except Exception:
                pass
        try:
            op.create_index("ix_job_listings_canonical_id", "job_listings", ["canonical_id"], unique=True)
        except Exception:
            pass
        try:
            op.create_unique_constraint("uq_job_listings_canonical_id", "job_listings", ["canonical_id"])
        except Exception:
            pass
        try:
            op.create_index("ix_job_listings_jd_hash", "job_listings", ["jd_hash"])
        except Exception:
            pass
        try:
            op.create_index("ix_job_listings_last_seen_at", "job_listings", ["last_seen_at"])
        except Exception:
            pass
        op.create_table(
            "dead_letters",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("url", sa.String(length=2048), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source", "url", name="uq_dead_letters_source_url"),
        )
        op.create_index("ix_dead_letters_source", "dead_letters", ["source"])
        op.create_index("ix_dead_letters_next_retry_at", "dead_letters", ["next_retry_at"])
        try:
            op.drop_table("batch_queue")
        except Exception:
            pass
        return

    # online — idempotent adds
    if _table_exists("job_listings"):
        if not _col_exists("job_listings", "canonical_id"):
            op.add_column("job_listings", sa.Column("canonical_id", sa.String(length=64), nullable=True))
        if not _col_exists("job_listings", "jd_hash"):
            op.add_column("job_listings", sa.Column("jd_hash", sa.String(length=64), nullable=True))
        if not _col_exists("job_listings", "simhash"):
            op.add_column("job_listings", sa.Column("simhash", sa.BigInteger(), nullable=True))
        if not _col_exists("job_listings", "etag"):
            op.add_column("job_listings", sa.Column("etag", sa.String(length=255), nullable=True))
        if not _col_exists("job_listings", "change_log"):
            op.add_column("job_listings", sa.Column("change_log", postgresql.JSONB(), nullable=True))
        if not _col_exists("job_listings", "source_ats"):
            op.add_column("job_listings", sa.Column("source_ats", sa.String(length=32), nullable=True))
        if not _col_exists("job_listings", "last_seen_at"):
            op.add_column("job_listings", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))

        # indexes / unique — create if not exists (catch duplicate)
        try:
            op.create_index("ix_job_listings_canonical_id", "job_listings", ["canonical_id"], unique=True)
        except Exception:
            pass
        try:
            op.create_unique_constraint("uq_job_listings_canonical_id", "job_listings", ["canonical_id"])
        except Exception:
            pass
        try:
            op.create_index("ix_job_listings_jd_hash", "job_listings", ["jd_hash"])
        except Exception:
            pass
        try:
            op.create_index("ix_job_listings_last_seen_at", "job_listings", ["last_seen_at"])
        except Exception:
            pass

    # dead_letters
    if not _table_exists("dead_letters"):
        op.create_table(
            "dead_letters",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("url", sa.String(length=2048), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source", "url", name="uq_dead_letters_source_url"),
        )
        op.create_index("ix_dead_letters_source", "dead_letters", ["source"])
        op.create_index("ix_dead_letters_next_retry_at", "dead_letters", ["next_retry_at"])

    # nuke batch_queue orphan — archive/drop if exists, don't fail if missing
    if _table_exists("batch_queue"):
        try:
            op.drop_table("batch_queue")
        except Exception:
            pass
    # pipeline_runs retained for observability; don't drop — but orphan check passes if needed
    # If you want full nuke, uncomment: if _table_exists("pipeline_runs"): op.drop_table("pipeline_runs")


def downgrade() -> None:
    # drop dead_letters
    if _table_exists("dead_letters"):
        try:
            op.drop_index("ix_dead_letters_next_retry_at", table_name="dead_letters")
        except Exception:
            pass
        try:
            op.drop_index("ix_dead_letters_source", table_name="dead_letters")
        except Exception:
            pass
        op.drop_table("dead_letters")

    if _table_exists("job_listings"):
        for idx in ["ix_job_listings_last_seen_at", "ix_job_listings_jd_hash", "ix_job_listings_canonical_id"]:
            try:
                op.drop_index(idx, table_name="job_listings")
            except Exception:
                pass
        try:
            op.drop_constraint("uq_job_listings_canonical_id", "job_listings", type_="unique")
        except Exception:
            pass
        for col in ["last_seen_at", "source_ats", "change_log", "etag", "simhash", "jd_hash", "canonical_id"]:
            if _col_exists("job_listings", col):
                try:
                    op.drop_column("job_listings", col)
                except Exception:
                    pass

    # restore batch_queue (as in 0001)
    if not _table_exists("batch_queue"):
        op.create_table(
            "batch_queue",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("application_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        )
