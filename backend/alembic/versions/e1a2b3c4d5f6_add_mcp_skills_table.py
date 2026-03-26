"""add mcp skills table

Revision ID: e1a2b3c4d5f6
Revises: d9f1a2b34c56
Create Date: 2026-03-26 23:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1a2b3c4d5f6"
down_revision: Union[str, None] = "d9f1a2b34c56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE skill_transport AS ENUM ('stdio', 'http');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE skill_status AS ENUM ('available', 'configured', 'connected', 'error');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    op.create_table(
        "mcp_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("icon", sa.String(128), nullable=True),
        sa.Column(
            "transport",
            postgresql.ENUM("stdio", "http", name="skill_transport", create_type=False),
            nullable=False,
            server_default="stdio",
        ),
        sa.Column("server_command", sa.String(1024), nullable=False),
        sa.Column("server_args", postgresql.JSONB, nullable=True),
        sa.Column("server_url", sa.String(2048), nullable=True),
        sa.Column("config_schema", postgresql.JSONB, nullable=True),
        sa.Column("config_values", postgresql.JSONB, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_builtin", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "status",
            postgresql.ENUM("available", "configured", "connected", "error", name="skill_status", create_type=False),
            nullable=False,
            server_default="available",
        ),
        sa.Column("status_message", sa.Text, nullable=True),
        sa.Column("cached_tools", postgresql.JSONB, nullable=True),
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


def downgrade() -> None:
    op.drop_table("mcp_skills")
    op.execute("DROP TYPE IF EXISTS skill_status")
    op.execute("DROP TYPE IF EXISTS skill_transport")
