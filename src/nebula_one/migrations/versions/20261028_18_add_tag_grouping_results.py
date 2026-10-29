"""Persist immutable tag grouping results for history and exports."""
from alembic import op
import sqlalchemy as sa

revision = "20261028_18"
down_revision = "20261028_17"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tag_grouping_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("solved_system_snapshots.id"), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("application_id", "request_sha256", name="uq_tag_grouping_request"),
    )
    op.create_index("ix_tag_grouping_results_application_id", "tag_grouping_results", ["application_id"])
    op.create_index("ix_tag_grouping_results_snapshot_id", "tag_grouping_results", ["snapshot_id"])


def downgrade():
    op.drop_table("tag_grouping_results")
