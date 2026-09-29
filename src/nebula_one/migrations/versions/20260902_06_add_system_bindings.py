"""add application system bindings

Revision ID: 20260902_06
Revises: 20260831_05
Create Date: 2026-09-02 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_06"
down_revision: Union[str, Sequence[str], None] = "20260831_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=96), nullable=False),
        sa.Column("system_model_id", sa.String(length=36), nullable=False),
        sa.Column("system_revision_id", sa.String(length=36), nullable=True),
        sa.Column("solved_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("study_frame_id", sa.String(length=255), nullable=False),
        sa.Column("reporting_period_id", sa.String(length=36), nullable=False),
        sa.Column(
            "organizational_boundary_id", sa.String(length=36), nullable=False
        ),
        sa.Column("demand", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["system_model_id"], ["system_models.id"]),
        sa.ForeignKeyConstraint(["system_revision_id"], ["system_revisions.id"]),
        sa.ForeignKeyConstraint(
            ["solved_snapshot_id"], ["solved_system_snapshots.id"]
        ),
        sa.ForeignKeyConstraint(["reporting_period_id"], ["periods.id"]),
        sa.ForeignKeyConstraint(
            ["organizational_boundary_id"], ["boundary_definitions.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "application_id", "binding_id", name="uq_system_binding_identity"
        ),
        sa.UniqueConstraint(
            "application_id", "role", name="uq_system_binding_role"
        ),
    )
    op.create_index(
        op.f("ix_system_bindings_application_id"),
        "system_bindings",
        ["application_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_system_bindings_system_model_id"),
        "system_bindings",
        ["system_model_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_system_bindings_system_revision_id"),
        "system_bindings",
        ["system_revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_system_bindings_solved_snapshot_id"),
        "system_bindings",
        ["solved_snapshot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_system_bindings_reporting_period_id"),
        "system_bindings",
        ["reporting_period_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_system_bindings_organizational_boundary_id"),
        "system_bindings",
        ["organizational_boundary_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_system_bindings_organizational_boundary_id"),
        table_name="system_bindings",
    )
    op.drop_index(
        op.f("ix_system_bindings_reporting_period_id"),
        table_name="system_bindings",
    )
    op.drop_index(
        op.f("ix_system_bindings_system_model_id"),
        table_name="system_bindings",
    )
    op.drop_index(
        op.f("ix_system_bindings_solved_snapshot_id"),
        table_name="system_bindings",
    )
    op.drop_index(
        op.f("ix_system_bindings_system_revision_id"),
        table_name="system_bindings",
    )
    op.drop_index(
        op.f("ix_system_bindings_application_id"),
        table_name="system_bindings",
    )
    op.drop_table("system_bindings")
