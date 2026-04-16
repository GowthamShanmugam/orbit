"""restructure skills to plugin registry pattern

Migrates from flat mcp_skills table to the plugin→skills→user_config
pattern inspired by opendatahub-io/skills-registry.

- skill_categories: grouping for plugins
- skill_plugins: catalog entries (replaces mcp_skills)
- plugin_skills: individual skills within a plugin
- user_plugin_configs: per-user install and credentials

Existing mcp_skills rows are migrated into skill_plugins with data preserved.

Revision ID: q4r5s6t7u8v9
Revises: p3q4r5s6t7u8
Create Date: 2026-04-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "q4r5s6t7u8v9"
down_revision: Union[str, None] = "p3q4r5s6t7u8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create new enum types
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE plugin_type AS ENUM ('mcp', 'prompt', 'hybrid');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE plugin_source AS ENUM ('builtin', 'custom', 'github');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    # -- skill_categories --
    op.create_table(
        "skill_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )

    # -- skill_plugins (replaces mcp_skills) --
    op.create_table(
        "skill_plugins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="0.1.0"),
        sa.Column("icon", sa.String(128), nullable=True),
        sa.Column("tags", postgresql.JSONB, nullable=True),
        sa.Column(
            "plugin_type",
            postgresql.ENUM("mcp", "prompt", "hybrid", name="plugin_type", create_type=False),
            nullable=False,
            server_default="mcp",
        ),
        sa.Column(
            "source",
            postgresql.ENUM("builtin", "custom", "github", name="plugin_source", create_type=False),
            nullable=False,
            server_default="builtin",
        ),
        sa.Column("source_repo", sa.String(2048), nullable=True),
        sa.Column("source_ref", sa.String(128), nullable=True),
        # MCP fields
        sa.Column(
            "transport",
            postgresql.ENUM("stdio", "http", name="skill_transport", create_type=False),
            nullable=True,
        ),
        sa.Column("server_command", sa.String(1024), nullable=True),
        sa.Column("server_args", postgresql.JSONB, nullable=True),
        sa.Column("server_url", sa.String(2048), nullable=True),
        sa.Column("config_schema", postgresql.JSONB, nullable=True),
        sa.Column("cached_tools", postgresql.JSONB, nullable=True),
        sa.Column("is_builtin", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="100"),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skill_categories.id"),
            nullable=True,
        ),
        sa.Column("depends_on", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # -- plugin_skills --
    op.create_table(
        "plugin_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "plugin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skill_plugins.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("user_invocable", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("plugin_id", "slug", name="uq_plugin_skill_slug"),
    )

    # -- user_plugin_configs --
    op.create_table(
        "user_plugin_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plugin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skill_plugins.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("config_values", postgresql.JSONB, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "status",
            postgresql.ENUM("available", "configured", "connected", "error", name="skill_status", create_type=False),
            nullable=False,
            server_default="available",
        ),
        sa.Column("status_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "plugin_id", name="uq_user_plugin"),
    )

    # -- Migrate existing mcp_skills data into skill_plugins --
    op.execute("""
        INSERT INTO skill_plugins (
            id, name, slug, description, icon,
            plugin_type, source,
            transport, server_command, server_args, server_url,
            config_schema, cached_tools,
            is_builtin, sort_order,
            created_at, updated_at
        )
        SELECT
            id, name, slug, description, icon,
            'mcp'::plugin_type,
            CASE WHEN is_builtin THEN 'builtin'::plugin_source ELSE 'custom'::plugin_source END,
            transport, server_command, server_args, server_url,
            config_schema, cached_tools,
            is_builtin, 100,
            created_at, updated_at
        FROM mcp_skills
    """)

    # Drop the old table
    op.drop_table("mcp_skills")


def downgrade() -> None:
    # Recreate mcp_skills
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
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Migrate data back
    op.execute("""
        INSERT INTO mcp_skills (
            id, name, slug, description, icon,
            transport, server_command, server_args, server_url,
            config_schema, cached_tools,
            is_builtin,
            status, created_at, updated_at
        )
        SELECT
            id, name, slug, description, icon,
            transport, server_command, server_args, server_url,
            config_schema, cached_tools,
            is_builtin,
            'available'::skill_status, created_at, updated_at
        FROM skill_plugins
        WHERE plugin_type = 'mcp'
    """)

    op.drop_table("user_plugin_configs")
    op.drop_table("plugin_skills")
    op.drop_table("skill_plugins")
    op.drop_table("skill_categories")
    op.execute("DROP TYPE IF EXISTS plugin_type")
    op.execute("DROP TYPE IF EXISTS plugin_source")
