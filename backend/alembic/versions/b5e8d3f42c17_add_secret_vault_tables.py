"""add secret vault tables

Revision ID: b5e8d3f42c17
Revises: a3f7c2d91b04
Create Date: 2026-03-26 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5e8d3f42c17"
down_revision: Union[str, None] = "a3f7c2d91b04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN CREATE TYPE secret_scope AS ENUM ('personal', 'team', 'project'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute(
        "DO $$ BEGIN CREATE TYPE vault_backend AS ENUM ('builtin', 'hashicorp', 'onepassword'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )

    secret_scope = postgresql.ENUM(
        "personal", "team", "project",
        name="secret_scope", create_type=False,
    )
    vault_be = postgresql.ENUM(
        "builtin", "hashicorp", "onepassword",
        name="vault_backend", create_type=False,
    )

    op.create_table(
        "project_secrets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("scope", secret_scope, nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("tag", sa.LargeBinary(), nullable=False),
        sa.Column("placeholder_key", sa.String(length=255), nullable=False),
        sa.Column("vault_backend", vault_be, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("last_rotated", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("placeholder_key"),
    )
    op.create_index(
        op.f("ix_project_secrets_project_id"), "project_secrets", ["project_id"]
    )

    op.create_table(
        "secret_audit_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("secret_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["secret_id"], ["project_secrets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_secret_audit_logs_secret_id"),
        "secret_audit_logs",
        ["secret_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_secret_audit_logs_secret_id"), table_name="secret_audit_logs"
    )
    op.drop_table("secret_audit_logs")
    op.drop_index(
        op.f("ix_project_secrets_project_id"), table_name="project_secrets"
    )
    op.drop_table("project_secrets")
    op.execute("DROP TYPE IF EXISTS vault_backend")
    op.execute("DROP TYPE IF EXISTS secret_scope")
