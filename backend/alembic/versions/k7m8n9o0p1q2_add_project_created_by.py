"""add created_by_id to projects

Revision ID: k7m8n9o0p1q2
Revises: j6k7l8m9n0o1
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "k7m8n9o0p1q2"
down_revision = "j6k7l8m9n0o1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_projects_created_by_id_users",
        "projects",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_projects_created_by_id", "projects", ["created_by_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_created_by_id", table_name="projects")
    op.drop_constraint("fk_projects_created_by_id_users", "projects", type_="foreignkey")
    op.drop_column("projects", "created_by_id")
