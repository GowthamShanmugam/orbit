"""add claude_model and ai_config to threads

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b2c3d4e5f6g7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("threads", sa.Column("claude_model", sa.String(128), nullable=True))
    op.add_column("threads", sa.Column("ai_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("threads", "ai_config")
    op.drop_column("threads", "claude_model")
