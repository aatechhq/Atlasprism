"""release gate thresholds

Adds the project's own release policy: a minimum pass rate and a maximum number
of critical Shield findings. Declared before a run so an approval record can
state which standard was applied.

Both nullable with no default. With neither set the gate reports
`not_configured` rather than a quiet pass, so adding this migration changes no
existing behaviour.

Revision ID: 4c1f8a37bd90
Revises: 352ab2015e2c
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "4c1f8a37bd90"
down_revision = "352ab2015e2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("gate_min_pass_rate", sa.Float(), nullable=True))
    op.add_column("projects", sa.Column("gate_max_critical_findings", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "gate_max_critical_findings")
    op.drop_column("projects", "gate_min_pass_rate")
