from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    application_type: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    system_models: Mapped[list["SystemModel"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class ModelingHandoff(Base):
    __tablename__ = "modeling_handoffs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    state_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    engine_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    base_identity: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    candidate: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SystemModel(Base):
    __tablename__ = "system_models"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "provider",
            "upstream_project_id",
            "upstream_version",
            name="uq_system_model_exact_pin",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    upstream_project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    upstream_version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    upstream_receipt: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    application: Mapped[Application] = relationship(back_populates="system_models")
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="system_model", cascade="all, delete-orphan"
    )
    revisions: Mapped[list["SystemRevision"]] = relationship(
        back_populates="system_model", cascade="all, delete-orphan"
    )


class ModelSource(Base):
    __tablename__ = "model_sources"
    __table_args__ = (
        UniqueConstraint("system_model_id", name="uq_model_source_system_model"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    system_model_id: Mapped[str | None] = mapped_column(
        ForeignKey("system_models.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="nebula_lca")
    provider_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    upstream_project_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    upstream_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graph_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    import_receipt: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    candidate_versions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    external_dependencies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    issues: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    attached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SystemRevision(Base):
    __tablename__ = "system_revisions"
    __table_args__ = (
        UniqueConstraint(
            "system_model_id", "revision_number", name="uq_system_revision_number"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    system_model_id: Mapped[str] = mapped_column(
        ForeignKey("system_models.id"), nullable=False, index=True
    )
    parent_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("system_revisions.id"), nullable=True, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revision_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="operation")
    graph_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    application_context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    publish_receipt: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    system_model: Mapped[SystemModel] = relationship(back_populates="revisions")
    operations: Mapped[list["ModelOperation"]] = relationship(
        back_populates="revision", cascade="all, delete-orphan"
    )
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="system_revision"
    )


class ModelOperation(Base):
    __tablename__ = "model_operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    system_revision_id: Mapped[str] = mapped_column(
        ForeignKey("system_revisions.id"), nullable=False, index=True
    )
    operation_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("operation_batches.id"), nullable=True, index=True
    )
    batch_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    operation_type: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    before_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    after_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    revision: Mapped[SystemRevision] = relationship(back_populates="operations")


class OperationBatch(Base):
    __tablename__ = "operation_batches"
    __table_args__ = (
        UniqueConstraint(
            "system_model_id", "idempotency_key", name="uq_operation_batch_idempotency"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    system_model_id: Mapped[str] = mapped_column(
        ForeignKey("system_models.id"), nullable=False, index=True
    )
    parent_revision_id: Mapped[str] = mapped_column(
        ForeignKey("system_revisions.id"), nullable=False, index=True
    )
    final_revision_id: Mapped[str] = mapped_column(
        ForeignKey("system_revisions.id"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint(
            "system_model_id",
            "idempotency_key",
            name="uq_analysis_run_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    system_model_id: Mapped[str] = mapped_column(
        ForeignKey("system_models.id"), nullable=False, index=True
    )
    system_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("system_revisions.id"), nullable=True, index=True
    )
    capability_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    model_graph_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_receipt: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    system_model: Mapped[SystemModel] = relationship(back_populates="analysis_runs")
    system_revision: Mapped[SystemRevision | None] = relationship(
        back_populates="analysis_runs"
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint(
            "topic",
            "aggregate_id",
            name="uq_outbox_topic_aggregate",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_error: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_ref: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SeedInstallation(Base):
    """A seed version installed into one engine database, with per-stage receipts."""

    __tablename__ = "seed_installations"
    __table_args__ = (
        UniqueConstraint("install_key", name="uq_seed_installation_key"),
        UniqueConstraint(
            "seed_id",
            "seed_version",
            "engine_db_digest",
            name="uq_seed_installation_engine_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    seed_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    seed_version: Mapped[str] = mapped_column(String(32), nullable=False)
    install_key: Mapped[str] = mapped_column(String(64), nullable=False)
    bundle_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    engine_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    engine_db_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_openapi_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="validated")
    stage_receipts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    zip_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    zip_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engine_project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    engine_model_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine_graph_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role_instance_map: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    verification: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    import_receipt: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    failure: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id"), nullable=True, index=True
    )
    system_model_id: Mapped[str | None] = mapped_column(
        ForeignKey("system_models.id"), nullable=True, index=True
    )
    system_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("system_revisions.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
