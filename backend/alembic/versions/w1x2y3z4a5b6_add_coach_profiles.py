"""add coach_profiles for Daily Coach Today

Revision ID: w1x2y3z4a5b6
Revises: d4e5f6g7h8i9
Create Date: 2026-11-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "w1x2y3z4a5b6"
down_revision: Union[str, None] = "d4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coach_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "watchlists",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "reminder_prefs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(
                "'{\"enabled\": true, \"standup_minutes_before\": 15}'::jsonb"
            ),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_coach_profiles_user_id"),
    )
    op.create_index("ix_coach_profiles_user_id", "coach_profiles", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_coach_profiles_user_id", table_name="coach_profiles")
    op.drop_table("coach_profiles")
