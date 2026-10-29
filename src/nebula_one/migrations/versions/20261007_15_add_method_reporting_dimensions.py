"""Persist a method version's own reporting dimensions so a user can group by non-Scope categories.

The engine still owns every number; this only records the version's declared dimension tree
(LC-Scope is one such tree, ``plant_split`` = onsite/purchased-energy/upstream-materials is
another). Empty for every historical version, so existing hashes and the legacy Scope path are
byte-for-byte unchanged until a method declares its own categories.
"""
from alembic import op
import sqlalchemy as sa


revision = "20261007_15"
down_revision = "20261006_14"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("calculation_method_versions") as batch:
        batch.add_column(
            sa.Column(
                "reporting_dimensions",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("[]"),
            )
        )


def downgrade():
    with op.batch_alter_table("calculation_method_versions") as batch:
        batch.drop_column("reporting_dimensions")
