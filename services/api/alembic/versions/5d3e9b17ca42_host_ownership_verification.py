"""host ownership verification

Proof that a project controls a host before Shield may send adversarial traffic
to it. Containment (netguard) decides whether an address is safe to reach; this
decides whether the caller is permitted to reach it. A checkbox is not
authorisation.

Unique on (project_id, host): one verification record per host per project.

Revision ID: 5d3e9b17ca42
Revises: 4c1f8a37bd90
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "5d3e9b17ca42"
down_revision = "4c1f8a37bd90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "host_verifications",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("token", sa.String(length=100), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("project_id", "host", name="uq_host_verification_project_host"),
    )
    op.create_index("ix_host_verifications_project_id", "host_verifications", ["project_id"])
    op.create_index("ix_host_verifications_host", "host_verifications", ["host"])


def downgrade() -> None:
    op.drop_index("ix_host_verifications_host", table_name="host_verifications")
    op.drop_index("ix_host_verifications_project_id", table_name="host_verifications")
    op.drop_table("host_verifications")
