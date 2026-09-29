"""add durable outbox runtime

Revision ID: 20260831_03
Revises: 20260831_02
Create Date: 2026-08-31 05:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260831_03"
down_revision: Union[str, Sequence[str], None] = "20260831_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("topic", sa.String(length=96), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "topic",
            "aggregate_id",
            name="uq_outbox_topic_aggregate",
        ),
    )
    op.create_index(
        op.f("ix_outbox_events_topic"),
        "outbox_events",
        ["topic"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbox_events_aggregate_id"),
        "outbox_events",
        ["aggregate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbox_events_status"),
        "outbox_events",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbox_events_available_at"),
        "outbox_events",
        ["available_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbox_events_lease_expires_at"),
        "outbox_events",
        ["lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_outbox_events_lease_expires_at"),
        table_name="outbox_events",
    )
    op.drop_index(
        op.f("ix_outbox_events_available_at"),
        table_name="outbox_events",
    )
    op.drop_index(op.f("ix_outbox_events_status"), table_name="outbox_events")
    op.drop_index(
        op.f("ix_outbox_events_aggregate_id"),
        table_name="outbox_events",
    )
    op.drop_index(op.f("ix_outbox_events_topic"), table_name="outbox_events")
    op.drop_table("outbox_events")
