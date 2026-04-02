"""add visibility to projects (private | public)

Revision ID: m9n0o1p2q3r4
Revises: k7m8n9o0p1q2
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa

revision = "m9n0o1p2q3r4"
down_revision = "k7m8n9o0p1q2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "visibility",
            sa.String(16),
            nullable=False,
            server_default="private",
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "visibility")
