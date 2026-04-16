"""add visibility to skill_plugins and simplify pack_visibility

- Adds 'visibility' column to skill_plugins (default 'public')
- Adds 'created_by' column to skill_plugins (FK -> users)
- Migrates context_packs.visibility: 'organization' -> 'public', 'personal' -> 'private'
- Updates the pack_visibility enum accordingly

Revision ID: r5s6t7u8v9w0
Revises: q4r5s6t7u8v9
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa

revision = "r5s6t7u8v9w0"
down_revision = "q4r5s6t7u8v9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skill_plugins",
        sa.Column("visibility", sa.String(16), nullable=False, server_default="public"),
    )
    op.add_column(
        "skill_plugins",
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_skill_plugins_created_by",
        "skill_plugins",
        "users",
        ["created_by"],
        ["id"],
    )

    op.execute("ALTER TYPE pack_visibility ADD VALUE IF NOT EXISTS 'private'")
    op.execute("COMMIT")

    op.execute(
        "UPDATE context_packs SET visibility = 'public' WHERE visibility = 'organization'"
    )
    op.execute(
        "UPDATE context_packs SET visibility = 'private' WHERE visibility = 'personal'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE context_packs SET visibility = 'public' WHERE visibility = 'private'"
    )

    op.drop_constraint("fk_skill_plugins_created_by", "skill_plugins", type_="foreignkey")
    op.drop_column("skill_plugins", "created_by")
    op.drop_column("skill_plugins", "visibility")
