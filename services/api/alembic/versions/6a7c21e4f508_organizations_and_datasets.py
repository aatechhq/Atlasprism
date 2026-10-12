"""organizations, memberships, datasets and dataset versions

Two V0.5 capabilities.

TEAM ACCESS. A project may belong to an organisation; membership then grants
access according to a role. `projects.organization_id` is nullable, so every
existing project keeps owner-only access and the isolation behaviour is
unchanged until someone deliberately attaches a project to an organisation.

DATASETS. A reusable, versioned library of cases that does not belong to a
single project, so a Shield library can be authored once and instantiated into
many projects. Versions are immutable: a change creates the next version, the
same reasoning as the per-run case snapshot.

Revision ID: 6a7c21e4f508
Revises: 5d3e9b17ca42
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "6a7c21e4f508"
down_revision = "5d3e9b17ca42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "memberships",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
        sa.CheckConstraint("role IN ('owner','admin','member','viewer')",
                           name="ck_membership_role"),
    )
    op.create_index("ix_memberships_organization_id", "memberships", ["organization_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.add_column("projects", sa.Column("organization_id", sa.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_projects_organization", "projects", "organizations",
                          ["organization_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])

    op.create_table(
        "datasets",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", sa.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("engine", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("engine IN ('guard','shield')", name="ck_dataset_engine"),
    )
    op.create_index("ix_datasets_owner_id", "datasets", ["owner_id"])
    op.create_index("ix_datasets_organization_id", "datasets", ["organization_id"])

    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("dataset_id", sa.UUID(as_uuid=True),
                  sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("cases", postgresql.JSONB(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("dataset_id", "version", name="uq_dataset_version"),
    )
    op.create_index("ix_dataset_versions_dataset_id", "dataset_versions", ["dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_dataset_versions_dataset_id", table_name="dataset_versions")
    op.drop_table("dataset_versions")
    op.drop_index("ix_datasets_organization_id", table_name="datasets")
    op.drop_index("ix_datasets_owner_id", table_name="datasets")
    op.drop_table("datasets")
    op.drop_index("ix_projects_organization_id", table_name="projects")
    op.drop_constraint("fk_projects_organization", "projects", type_="foreignkey")
    op.drop_column("projects", "organization_id")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_memberships_organization_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("organizations")
