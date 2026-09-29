"""add persisted energy carrier results

Revision ID: 20260831_05
Revises: 20260831_04
Create Date: 2026-08-31 18:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260831_05"
down_revision: Union[str, Sequence[str], None] = "20260831_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "energy_carrier_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("solved_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(
            ["solved_snapshot_id"], ["solved_system_snapshots.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "solved_snapshot_id",
            "request_sha256",
            name="uq_energy_carrier_result_request",
        ),
    )
    op.create_index(
        op.f("ix_energy_carrier_results_application_id"),
        "energy_carrier_results",
        ["application_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_energy_carrier_results_solved_snapshot_id"),
        "energy_carrier_results",
        ["solved_snapshot_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_energy_carrier_results_solved_snapshot_id"),
        table_name="energy_carrier_results",
    )
    op.drop_index(
        op.f("ix_energy_carrier_results_application_id"),
        table_name="energy_carrier_results",
    )
    op.drop_table("energy_carrier_results")
