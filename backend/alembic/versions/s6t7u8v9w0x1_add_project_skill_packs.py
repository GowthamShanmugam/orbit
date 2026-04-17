"""add project_skill_packs table

Links skill packs to projects. Built-in packs are auto-available;
custom packs must be explicitly installed per project.

Revision ID: s6t7u8v9w0x1
Revises: r5s6t7u8v9w0
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "s6t7u8v9w0x1"
down_revision = "r5s6t7u8v9w0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_skill_packs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "skill_plugin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skill_plugins.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "installed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "installed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("project_id", "skill_plugin_id", name="uq_project_skill_pack"),
    )


def downgrade() -> None:
    op.drop_table("project_skill_packs")
