"""add cluster tables

Revision ID: c8d4e5f67a23
Revises: b5e8d3f42c17
Create Date: 2026-03-26 21:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8d4e5f67a23"
down_revision: Union[str, None] = "b5e8d3f42c17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE cluster_role AS ENUM ('context', 'test');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE cluster_auth_method AS ENUM ('kubeconfig', 'token');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE cluster_status AS ENUM ('pending', 'connected', 'error', 'syncing');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE test_run_status AS ENUM ('pending', 'running', 'passed', 'failed', 'error', 'cancelled');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    op.create_table(
        "project_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("context", "test", name="cluster_role", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "auth_method",
            postgresql.ENUM("kubeconfig", "token", name="cluster_auth_method", create_type=False),
            nullable=False,
        ),
        sa.Column("api_server_url", sa.String(2048), nullable=True),
        sa.Column("encrypted_credentials", sa.LargeBinary, nullable=False),
        sa.Column("credentials_nonce", sa.LargeBinary, nullable=False),
        sa.Column("credentials_tag", sa.LargeBinary, nullable=False),
        sa.Column("namespace_filter", postgresql.JSONB, nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("pending", "connected", "error", "syncing", name="cluster_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("status_message", sa.Text, nullable=True),
        sa.Column("last_synced", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_config", postgresql.JSONB, nullable=True),
        sa.Column("config", postgresql.JSONB, nullable=True),
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
        "test_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cluster_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_clusters.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("run_type", sa.String(64), nullable=False, server_default="command"),
        sa.Column("command", sa.Text, nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending", "running", "passed", "failed", "error", "cancelled",
                name="test_run_status", create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("output", sa.Text, nullable=True),
        sa.Column("exit_code", sa.Integer, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column(
            "triggered_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("config", postgresql.JSONB, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.execute("ALTER TYPE context_source_type ADD VALUE IF NOT EXISTS 'k8s_cluster'")


def downgrade() -> None:
    op.drop_table("test_runs")
    op.drop_table("project_clusters")
    op.execute("DROP TYPE IF EXISTS test_run_status")
    op.execute("DROP TYPE IF EXISTS cluster_status")
    op.execute("DROP TYPE IF EXISTS cluster_auth_method")
    op.execute("DROP TYPE IF EXISTS cluster_role")
