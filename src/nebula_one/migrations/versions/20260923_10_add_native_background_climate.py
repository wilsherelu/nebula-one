"""Give a solved snapshot its own column for a pinned native climate answer.

Nullable on purpose: a snapshot frozen before the source contract existed has no native answer, and
an empty object would read back as evidence that one was produced.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260923_10"
down_revision: Union[str, Sequence[str], None] = "20260922_09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "solved_system_snapshots",
        sa.Column("native_background_climate", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("solved_system_snapshots", "native_background_climate")
