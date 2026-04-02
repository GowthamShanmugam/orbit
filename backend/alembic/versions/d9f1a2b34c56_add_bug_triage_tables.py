"""add bug triage tables

Revision ID: d9f1a2b34c56
Revises: c8d4e5f67a23
Create Date: 2026-03-26 22:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d9f1a2b34c56"
down_revision: Union[str, None] = "c8d4e5f67a23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE bug_source AS ENUM ('jira', 'github');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE bug_priority AS ENUM ('critical', 'high', 'medium', 'low', 'unknown');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE bug_status AS ENUM (
                'imported', 'triaging', 'triaged', 'fix_generated',
                'branch_created', 'resolved', 'dismissed'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE triage_confidence AS ENUM ('high', 'medium', 'low');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    op.create_table(
        "bug_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "source",
            postgresql.ENUM("jira", "github", name="bug_source", create_type=False),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("external_url", sa.String(2048), nullable=True),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "priority",
            postgresql.ENUM(
                "critical", "high", "medium", "low", "unknown",
                name="bug_priority", create_type=False,
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "imported", "triaging", "triaged", "fix_generated",
                "branch_created", "resolved", "dismissed",
                name="bug_status", create_type=False,
            ),
            nullable=False,
            server_default="imported",
        ),
        sa.Column("assignee", sa.String(255), nullable=True),
        sa.Column("labels", postgresql.JSONB, nullable=True),
        sa.Column("raw_data", postgresql.JSONB, nullable=True),
        sa.Column(
            "imported_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "triage_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "bug_report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bug_reports.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("root_cause", sa.Text, nullable=True),
        sa.Column("affected_files", postgresql.JSONB, nullable=True),
        sa.Column("risk_level", sa.String(32), nullable=True),
        sa.Column(
            "confidence",
            postgresql.ENUM("high", "medium", "low", name="triage_confidence", create_type=False),
            nullable=False,
            server_default="medium",
        ),
        sa.Column("suggested_fix", sa.Text, nullable=True),
        sa.Column("fix_diff", sa.Text, nullable=True),
        sa.Column("branch_name", sa.String(512), nullable=True),
        sa.Column("branch_created", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("report_markdown", sa.Text, nullable=True),
        sa.Column("ai_model", sa.String(128), nullable=True),
        sa.Column("token_usage", postgresql.JSONB, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("triage_reports")
    op.drop_table("bug_reports")
    op.execute("DROP TYPE IF EXISTS triage_confidence")
    op.execute("DROP TYPE IF EXISTS bug_status")
    op.execute("DROP TYPE IF EXISTS bug_priority")
    op.execute("DROP TYPE IF EXISTS bug_source")
