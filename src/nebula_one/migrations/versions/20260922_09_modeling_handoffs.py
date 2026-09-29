"""Persist modeling handoffs without changing existing analysis records."""
from alembic import op
import sqlalchemy as sa

revision = "20260922_09"
down_revision = "20260918_08"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "modeling_handoffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state_sha256", sa.String(64), nullable=False),
        sa.Column("confirmation_sha256", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("engine_base_url", sa.String(512), nullable=False),
        sa.Column("base_identity", sa.JSON(), nullable=False),
        sa.Column("candidate", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("modeling_handoffs")
