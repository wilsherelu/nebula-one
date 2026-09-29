"""add model source provenance

Revision ID: 20260902_07
Revises: 20260902_06
Create Date: 2026-09-02 16:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_07"
down_revision: Union[str, Sequence[str], None] = "20260902_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("system_model_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=48), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_base_url", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("upstream_project_id", sa.String(length=255), nullable=True),
        sa.Column("upstream_version", sa.Integer(), nullable=True),
        sa.Column("graph_sha256", sa.String(length=64), nullable=True),
        sa.Column("import_receipt", sa.JSON(), nullable=False),
        sa.Column("candidate_versions", sa.JSON(), nullable=False),
        sa.Column("external_dependencies", sa.JSON(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attached_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["system_model_id"], ["system_models.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("system_model_id", name="uq_model_source_system_model"),
    )
    op.create_index(op.f("ix_model_sources_application_id"), "model_sources", ["application_id"])
    op.create_index(op.f("ix_model_sources_system_model_id"), "model_sources", ["system_model_id"])
    op.create_index(op.f("ix_model_sources_source_type"), "model_sources", ["source_type"])
    op.create_index(op.f("ix_model_sources_status"), "model_sources", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_model_sources_status"), table_name="model_sources")
    op.drop_index(op.f("ix_model_sources_source_type"), table_name="model_sources")
    op.drop_index(op.f("ix_model_sources_system_model_id"), table_name="model_sources")
    op.drop_index(op.f("ix_model_sources_application_id"), table_name="model_sources")
    op.drop_table("model_sources")
