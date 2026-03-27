"""add project_shares for workspace sharing

Revision ID: h4e5f6a7b8c9
Revises: g3c4d5e6f7b8
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "h4e5f6a7b8c9"
down_revision = "g3c4d5e6f7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum types idempotent (handles re-run after a failed migration left types in DB).
    # Table columns use create_type=False so create_table never calls CREATE TYPE again.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE project_share_subject AS ENUM ('user', 'group');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE project_share_role AS ENUM ('view', 'edit', 'admin');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    subj_type = postgresql.ENUM(
        "user", "group", name="project_share_subject", create_type=False
    )
    role_type = postgresql.ENUM(
        "view", "edit", "admin", name="project_share_role", create_type=False
    )

    op.create_table(
        "project_shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_type", subj_type, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("group_name", sa.String(255), nullable=True),
        sa.Column("role", role_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_project_shares_project_id", "project_shares", ["project_id"])
    op.create_index("ix_project_shares_user_id", "project_shares", ["user_id"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_project_shares_project_user
        ON project_shares (project_id, user_id)
        WHERE user_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_project_shares_project_group
        ON project_shares (project_id, lower(group_name))
        WHERE group_name IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_project_shares_project_group")
    op.execute("DROP INDEX IF EXISTS uq_project_shares_project_user")
    op.drop_index("ix_project_shares_user_id", table_name="project_shares")
    op.drop_index("ix_project_shares_project_id", table_name="project_shares")
    op.drop_table("project_shares")
    op.execute("DROP TYPE IF EXISTS project_share_role")
    op.execute("DROP TYPE IF EXISTS project_share_subject")
