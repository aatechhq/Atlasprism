"""project application profile

Adds the application under test to a project: the system prompt and rules the
developer's own assistant runs with. Prism layers it beneath every test case,
so Guard measures adherence to those instructions and Shield attempts to
override those rules, rather than evaluating the base model in isolation.

Nullable with no default on purpose. An empty profile changes nothing, so the
committed baseline suites and every historical run behave exactly as before.

Revision ID: 352ab2015e2c
Revises: 35b92a7f0d11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "352ab2015e2c"
down_revision = "35b92a7f0d11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("app_system_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "app_system_prompt")
