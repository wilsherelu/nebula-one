"""Add versioned user calculation methods bound to an exact model revision.

Stores the user's declared CBAM boundary, Scope 1/2/3 and onsite/purchased-energy/
upstream grouping as immutable versions; the engine still owns every emission number.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261005_13"
down_revision = "20260929_12"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "calculation_methods",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False
        ),
        sa.Column(
            "model_revision_id",
            sa.String(36),
            sa.ForeignKey("system_revisions.id"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "origin_method_id",
            sa.String(36),
            sa.ForeignKey("calculation_methods.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "application_id", "model_revision_id", "name", name="uq_calculation_method_name"
        ),
    )
    op.create_index(
        op.f("ix_calculation_methods_application_id"),
        "calculation_methods",
        ["application_id"],
    )
    op.create_index(
        op.f("ix_calculation_methods_model_revision_id"),
        "calculation_methods",
        ["model_revision_id"],
    )
    op.create_index(op.f("ix_calculation_methods_purpose"), "calculation_methods", ["purpose"])
    op.create_index(
        op.f("ix_calculation_methods_origin_method_id"),
        "calculation_methods",
        ["origin_method_id"],
    )

    op.create_table(
        "calculation_method_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "method_id", sa.String(36), sa.ForeignKey("calculation_methods.id"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column(
            "cbam_boundary_ref",
            sa.String(36),
            sa.ForeignKey("boundary_definitions.id"),
            nullable=True,
        ),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "method_id", "version", name="uq_calculation_method_version"
        ),
    )
    op.create_index(
        op.f("ix_calculation_method_versions_method_id"),
        "calculation_method_versions",
        ["method_id"],
    )
    op.create_index(
        op.f("ix_calculation_method_versions_cbam_boundary_ref"),
        "calculation_method_versions",
        ["cbam_boundary_ref"],
    )


def downgrade():
    op.drop_index(
        op.f("ix_calculation_method_versions_cbam_boundary_ref"),
        table_name="calculation_method_versions",
    )
    op.drop_index(
        op.f("ix_calculation_method_versions_method_id"),
        table_name="calculation_method_versions",
    )
    op.drop_table("calculation_method_versions")
    op.drop_index(op.f("ix_calculation_methods_origin_method_id"), table_name="calculation_methods")
    op.drop_index(op.f("ix_calculation_methods_purpose"), table_name="calculation_methods")
    op.drop_index(
        op.f("ix_calculation_methods_model_revision_id"), table_name="calculation_methods"
    )
    op.drop_index(op.f("ix_calculation_methods_application_id"), table_name="calculation_methods")
    op.drop_table("calculation_methods")
