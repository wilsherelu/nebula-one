"""Record the exact source version and content hash a cloned method variant was copied from.

``origin_method_id`` alone cannot pin a variant's identity: the source method moves as its
owner edits new versions, and a frozen CBAM variant must trace its exclusions to the specific
immutable version it was copied from, not to whatever the source head happens to be now.
"""
from alembic import op
import sqlalchemy as sa


revision = "20261006_14"
down_revision = "20261005_13"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("calculation_methods") as batch:
        batch.add_column(sa.Column("origin_method_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("origin_content_sha256", sa.String(64), nullable=True))


def downgrade():
    with op.batch_alter_table("calculation_methods") as batch:
        batch.drop_column("origin_content_sha256")
        batch.drop_column("origin_method_version")
