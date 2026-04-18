"""add_session_summary_and_tags

Revision ID: 95c3e2ce7172
Revises: s6t7u8v9w0x1
Create Date: 2026-04-18 11:59:31.587856

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '95c3e2ce7172'
down_revision: Union[str, None] = 's6t7u8v9w0x1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("tags", sa.ARRAY(sa.String(64)), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "tags")
    op.drop_column("sessions", "summary")
