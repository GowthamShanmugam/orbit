"""add bug triage session link and bug_report layer type

Revision ID: f2b3c4d5e6a7
Revises: e1a2b3c4d5f6
Create Date: 2026-03-26 23:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2b3c4d5e6a7"
down_revision: Union[str, None] = "e1a2b3c4d5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bug_reports",
        sa.Column(
            "triage_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.execute("ALTER TYPE session_layer_type ADD VALUE IF NOT EXISTS 'bug_report'")


def downgrade() -> None:
    op.drop_column("bug_reports", "triage_session_id")
