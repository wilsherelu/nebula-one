"""Declare an explicit semantics marker on a method version.

A flow-tag scheme is a distinct analysis caliber: one category tree over per-exchange matches,
not a Scope/boundary method. It must be stated, never inferred from ``purpose=custom`` or an empty
field, so the marker is persisted. The column is nullable and folds into the version content hash
only when present, leaving every historical version byte-for-byte identical.
"""
from alembic import op
import sqlalchemy as sa


revision = "20261028_17"
down_revision = "20261008_16"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("calculation_method_versions") as batch:
        batch.add_column(sa.Column("semantics", sa.String(length=32), nullable=True))


def downgrade():
    # Direct drop for the same reason as revision 16: a batch recreate re-emits JSON defaults
    # that SQLite rejects. The column carries no index or foreign key.
    op.drop_column("calculation_method_versions", "semantics")
