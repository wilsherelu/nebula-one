"""Persist exact organization-period requests and frozen results."""
from alembic import op
import sqlalchemy as sa

revision = "20260925_11"
down_revision = "20260923_10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organization_period_inventories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("system_revision_id", sa.String(36), sa.ForeignKey("system_revisions.id"), nullable=False),
        sa.Column("solved_snapshot_id", sa.String(36), sa.ForeignKey("solved_system_snapshots.id"), nullable=False),
        sa.Column("period_id", sa.String(36), sa.ForeignKey("periods.id"), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("inputs_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("application_id", "request_sha256", name="uq_organization_period_request"),
    )
    for name in ("application_id", "system_revision_id", "solved_snapshot_id", "period_id"):
        op.create_index(f"ix_organization_period_inventories_{name}", "organization_period_inventories", [name])


def downgrade():
    op.drop_table("organization_period_inventories")
