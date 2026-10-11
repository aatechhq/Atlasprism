"""link Neon Auth identities

Revision ID: 35b92a7f0d11
Revises: 87a0656e38b2
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "35b92a7f0d11"
down_revision = "87a0656e38b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("auth_subject", sa.String(length=255), nullable=True))
    op.create_index("ix_users_auth_subject", "users", ["auth_subject"], unique=True)
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM users WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=False)
    op.drop_index("ix_users_auth_subject", table_name="users")
    op.drop_column("users", "auth_subject")
