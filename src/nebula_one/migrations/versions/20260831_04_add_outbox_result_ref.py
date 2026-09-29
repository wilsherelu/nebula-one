"""add outbox result reference

Revision ID: 20260831_04
Revises: 20260831_03
Create Date: 2026-08-31 06:10:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260831_04"
down_revision: Union[str, Sequence[str], None] = "20260831_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column(
            "result_ref",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("outbox_events", "result_ref")
