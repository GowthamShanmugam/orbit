"""decouple secrets from projects

Revision ID: t7u8v9w0x1y2
Revises: 95c3e2ce7172
Create Date: 2026-04-16 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "t7u8v9w0x1y2"
down_revision: Union[str, None] = "95c3e2ce7172"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("project_secrets", "project_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column(
        "project_secrets",
        "created_by",
        existing_type=sa.UUID(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "project_secrets",
        "created_by",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.alter_column("project_secrets", "project_id", existing_type=sa.UUID(), nullable=False)
