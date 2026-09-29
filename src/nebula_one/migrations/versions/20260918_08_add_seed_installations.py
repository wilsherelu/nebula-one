"""add standard LCA seed installation receipts

Revision ID: 20260918_08
Revises: 20260902_07
Create Date: 2026-09-18 22:10:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260918_08"
down_revision: Union[str, Sequence[str], None] = "20260902_07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seed_installations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("seed_id", sa.String(length=128), nullable=False),
        sa.Column("seed_version", sa.String(length=32), nullable=False),
        sa.Column("install_key", sa.String(length=64), nullable=False),
        sa.Column("bundle_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("engine_base_url", sa.String(length=512), nullable=False),
        sa.Column("engine_db_digest", sa.String(length=64), nullable=False),
        sa.Column("engine_openapi_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage_receipts", sa.JSON(), nullable=False),
        sa.Column("zip_path", sa.String(length=512), nullable=True),
        sa.Column("zip_sha256", sa.String(length=64), nullable=True),
        sa.Column("engine_project_id", sa.String(length=36), nullable=True),
        sa.Column("engine_model_version", sa.Integer(), nullable=True),
        sa.Column("engine_graph_hash", sa.String(length=64), nullable=True),
        sa.Column("role_instance_map", sa.JSON(), nullable=False),
        sa.Column("verification", sa.JSON(), nullable=False),
        sa.Column("import_receipt", sa.JSON(), nullable=False),
        sa.Column("failure", sa.JSON(), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=True),
        sa.Column("system_model_id", sa.String(length=36), nullable=True),
        sa.Column("system_revision_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["system_model_id"], ["system_models.id"]),
        sa.ForeignKeyConstraint(["system_revision_id"], ["system_revisions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("install_key", name="uq_seed_installation_key"),
        sa.UniqueConstraint(
            "seed_id",
            "seed_version",
            "engine_db_digest",
            name="uq_seed_installation_engine_version",
        ),
    )
    op.create_index(op.f("ix_seed_installations_seed_id"), "seed_installations", ["seed_id"])
    op.create_index(
        op.f("ix_seed_installations_bundle_content_sha256"),
        "seed_installations",
        ["bundle_content_sha256"],
    )
    op.create_index(
        op.f("ix_seed_installations_engine_project_id"), "seed_installations", ["engine_project_id"]
    )
    op.create_index(op.f("ix_seed_installations_status"), "seed_installations", ["status"])
    op.create_index(
        op.f("ix_seed_installations_application_id"), "seed_installations", ["application_id"]
    )
    op.create_index(
        op.f("ix_seed_installations_system_model_id"), "seed_installations", ["system_model_id"]
    )
    op.create_index(
        op.f("ix_seed_installations_system_revision_id"), "seed_installations", ["system_revision_id"]
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_seed_installations_system_revision_id"), table_name="seed_installations"
    )
    op.drop_index(op.f("ix_seed_installations_system_model_id"), table_name="seed_installations")
    op.drop_index(op.f("ix_seed_installations_application_id"), table_name="seed_installations")
    op.drop_index(op.f("ix_seed_installations_status"), table_name="seed_installations")
    op.drop_index(
        op.f("ix_seed_installations_engine_project_id"), table_name="seed_installations"
    )
    op.drop_index(
        op.f("ix_seed_installations_bundle_content_sha256"), table_name="seed_installations"
    )
    op.drop_index(op.f("ix_seed_installations_seed_id"), table_name="seed_installations")
    op.drop_table("seed_installations")
