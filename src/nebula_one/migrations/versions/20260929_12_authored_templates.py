"""Pin authored project templates to exact reviewed model versions."""
from alembic import op
import sqlalchemy as sa

revision = "20260929_12"
down_revision = "20260925_11"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "authored_project_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("source_application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("source_model_id", sa.String(36), sa.ForeignKey("system_models.id"), nullable=False),
        sa.Column("source_revision_id", sa.String(36), sa.ForeignKey("system_revisions.id"), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("title", "version", name="uq_authored_template_title_version"),
    )


def downgrade():
    op.drop_table("authored_project_templates")
