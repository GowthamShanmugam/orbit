"""add context hub tables

Revision ID: a3f7c2d91b04
Revises: e64cad834ec1
Create Date: 2026-03-26 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "a3f7c2d91b04"
down_revision: Union[str, None] = "e64cad834ec1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        "CREATE TYPE pack_visibility AS ENUM ('public', 'organization', 'personal')"
    )
    op.execute(
        "CREATE TYPE context_source_type AS ENUM ("
        "'github_repo', 'gitlab_repo', 'jira_project', 'confluence_space', "
        "'google_doc', 'google_drive_folder', 'file_pin', 'code_snippet')"
    )
    op.execute(
        "CREATE TYPE session_layer_type AS ENUM ("
        "'pull_request', 'jira_ticket', 'google_doc', 'google_drive_folder', "
        "'file_pin', 'code_snippet', 'past_session')"
    )

    pack_vis = postgresql.ENUM(
        "public", "organization", "personal",
        name="pack_visibility", create_type=False,
    )
    ctx_src = postgresql.ENUM(
        "github_repo", "gitlab_repo", "jira_project", "confluence_space",
        "google_doc", "google_drive_folder", "file_pin", "code_snippet",
        name="context_source_type", create_type=False,
    )
    sess_layer = postgresql.ENUM(
        "pull_request", "jira_ticket", "google_doc", "google_drive_folder",
        "file_pin", "code_snippet", "past_session",
        name="session_layer_type", create_type=False,
    )

    op.create_table(
        "context_packs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("icon", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("visibility", pack_vis, nullable=False),
        sa.Column(
            "dependencies",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("maintainer_team", sa.String(length=255), nullable=True),
        sa.Column("org_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("repo_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_context_packs_org_id"), "context_packs", ["org_id"])

    op.create_table(
        "pack_context_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("pack_id", sa.UUID(), nullable=False),
        sa.Column("type", ctx_src, nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pack_id"], ["context_packs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pack_context_sources_pack_id"),
        "pack_context_sources",
        ["pack_id"],
    )

    op.create_table(
        "installed_packs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("pack_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("auto_update", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "installed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pack_id"], ["context_packs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_installed_packs_project_id"), "installed_packs", ["project_id"]
    )
    op.create_index(
        op.f("ix_installed_packs_pack_id"), "installed_packs", ["pack_id"]
    )

    op.create_table(
        "context_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("type", ctx_src, nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("auto_attach", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_indexed", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_context_sources_project_id"), "context_sources", ["project_id"]
    )

    op.create_table(
        "session_layers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("type", sess_layer, nullable=False),
        sa.Column("reference_url", sa.String(length=2048), nullable=True),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column(
            "cached_content",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_session_layers_session_id"), "session_layers", ["session_id"]
    )

    op.create_table(
        "indexed_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("file_path", sa.String(length=2048), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("chunk_type", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["context_sources.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_indexed_chunks_source_id"), "indexed_chunks", ["source_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_indexed_chunks_source_id"), table_name="indexed_chunks")
    op.drop_table("indexed_chunks")

    op.drop_index(op.f("ix_session_layers_session_id"), table_name="session_layers")
    op.drop_table("session_layers")

    op.drop_index(op.f("ix_context_sources_project_id"), table_name="context_sources")
    op.drop_table("context_sources")

    op.drop_index(op.f("ix_installed_packs_pack_id"), table_name="installed_packs")
    op.drop_index(
        op.f("ix_installed_packs_project_id"), table_name="installed_packs"
    )
    op.drop_table("installed_packs")

    op.drop_index(
        op.f("ix_pack_context_sources_pack_id"), table_name="pack_context_sources"
    )
    op.drop_table("pack_context_sources")

    op.drop_index(op.f("ix_context_packs_org_id"), table_name="context_packs")
    op.drop_table("context_packs")

    op.execute("DROP TYPE IF EXISTS session_layer_type")
    op.execute("DROP TYPE IF EXISTS context_source_type")
    op.execute("DROP TYPE IF EXISTS pack_visibility")
