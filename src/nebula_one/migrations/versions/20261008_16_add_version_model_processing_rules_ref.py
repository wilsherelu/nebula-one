"""Bind an exact model-processing package to a user variant method version.

A variant that narrows a CBAM result by per-exchange include/exclude must state which reviewed
processing package it narrows, so the same selection, not the newest published one, is what a
frozen run re-derives. The column is nullable and the reference folds into the version content hash
only when present, so every historical version keeps its byte-for-byte hash and stays on the
automatic official selection until a user explicitly binds a package.
"""
from alembic import op
import sqlalchemy as sa


revision = "20261008_16"
down_revision = "20261007_15"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("calculation_method_versions") as batch:
        batch.add_column(sa.Column("model_processing_rules_ref", sa.JSON(), nullable=True))


def downgrade():
    # A native DROP COLUMN rather than a batch recreate: batch re-creates the whole table and
    # re-emits reporting_dimensions' non-constant JSON default, which SQLite rejects. The column is
    # plain JSON with no index or foreign key, so a direct drop is safe on both SQLite and Postgres.
    op.drop_column("calculation_method_versions", "model_processing_rules_ref")
