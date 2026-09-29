"""add durable run idempotency

Revision ID: 20260831_02
Revises: 20260831_01
Create Date: 2026-08-31 05:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260831_02"
down_revision: Union[str, Sequence[str], None] = "20260831_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_run_identity(table_name: str) -> None:
    table = sa.table(
        table_name,
        sa.column("id", sa.String(length=36)),
        sa.column("idempotency_key", sa.String(length=128)),
        sa.column("request_sha256", sa.String(length=64)),
    )
    compact_id = sa.func.replace(table.c.id, "-", "")
    legacy_key = sa.literal("legacy:").op("||")(table.c.id)
    legacy_request_hash = compact_id.op("||")(compact_id)
    op.get_bind().execute(
        table.update()
        .where(table.c.idempotency_key.is_(None))
        .values(
            idempotency_key=legacy_key,
            request_sha256=legacy_request_hash,
        )
    )


def upgrade() -> None:
    with op.batch_alter_table("analysis_runs") as batch:
        batch.add_column(
            sa.Column("idempotency_key", sa.String(length=128), nullable=True)
        )
        batch.add_column(
            sa.Column("request_sha256", sa.String(length=64), nullable=True)
        )
    with op.batch_alter_table("scenario_comparison_runs") as batch:
        batch.add_column(
            sa.Column("idempotency_key", sa.String(length=128), nullable=True)
        )
        batch.add_column(
            sa.Column("request_sha256", sa.String(length=64), nullable=True)
        )

    _backfill_run_identity("analysis_runs")
    _backfill_run_identity("scenario_comparison_runs")

    with op.batch_alter_table("analysis_runs") as batch:
        batch.alter_column("idempotency_key", nullable=False)
        batch.alter_column("request_sha256", nullable=False)
        batch.create_unique_constraint(
            "uq_analysis_run_idempotency",
            ["system_model_id", "idempotency_key"],
        )
    with op.batch_alter_table("scenario_comparison_runs") as batch:
        batch.alter_column("idempotency_key", nullable=False)
        batch.alter_column("request_sha256", nullable=False)
        batch.create_unique_constraint(
            "uq_scenario_comparison_run_idempotency",
            ["comparison_id", "idempotency_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("scenario_comparison_runs") as batch:
        batch.drop_constraint(
            "uq_scenario_comparison_run_idempotency", type_="unique"
        )
        batch.drop_column("request_sha256")
        batch.drop_column("idempotency_key")
    with op.batch_alter_table("analysis_runs") as batch:
        batch.drop_constraint("uq_analysis_run_idempotency", type_="unique")
        batch.drop_column("request_sha256")
        batch.drop_column("idempotency_key")
