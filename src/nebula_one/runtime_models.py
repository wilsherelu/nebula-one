from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import new_id, utcnow


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("application_id", "external_id", name="uq_entity_external_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.id"), nullable=True, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class Period(Base):
    __tablename__ = "periods"
    __table_args__ = (
        UniqueConstraint("application_id", "key", name="uq_period_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    resolution: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class MethodPackage(Base):
    __tablename__ = "method_packages"
    __table_args__ = (
        UniqueConstraint("package_id", "version", name="uq_method_package_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    package_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    package_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(128), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="registered")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class OrganizationPeriodInventory(Base):
    __tablename__ = "organization_period_inventories"
    __table_args__ = (UniqueConstraint("application_id", "request_sha256", name="uq_organization_period_request"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    system_revision_id: Mapped[str] = mapped_column(ForeignKey("system_revisions.id"), nullable=False, index=True)
    solved_snapshot_id: Mapped[str] = mapped_column(ForeignKey("solved_system_snapshots.id"), nullable=False, index=True)
    period_id: Mapped[str] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    inputs_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class BoundaryDefinition(Base):
    __tablename__ = "boundary_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    boundary_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    included_entity_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    included_process_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    included_flow_rules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    excluded_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    consolidation_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    period_id: Mapped[str | None] = mapped_column(
        ForeignKey("periods.id"), nullable=True, index=True
    )
    geographic_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    method_package_ref: Mapped[str | None] = mapped_column(String(320), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EntityModelBinding(Base):
    __tablename__ = "entity_model_bindings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.id"), nullable=False, index=True
    )
    system_revision_id: Mapped[str] = mapped_column(
        ForeignKey("system_revisions.id"), nullable=False, index=True
    )
    process_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    flow_selectors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    period_id: Mapped[str | None] = mapped_column(
        ForeignKey("periods.id"), nullable=True, index=True
    )
    allocation_rule_ref: Mapped[str | None] = mapped_column(String(320), nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class SystemBinding(Base):
    __tablename__ = "system_bindings"
    __table_args__ = (
        UniqueConstraint(
            "application_id", "binding_id", name="uq_system_binding_identity"
        ),
        UniqueConstraint("application_id", "role", name="uq_system_binding_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    binding_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(96), nullable=False)
    system_model_id: Mapped[str] = mapped_column(
        ForeignKey("system_models.id"), nullable=False, index=True
    )
    system_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("system_revisions.id"), nullable=True, index=True
    )
    solved_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("solved_system_snapshots.id"), nullable=True, index=True
    )
    study_frame_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reporting_period_id: Mapped[str] = mapped_column(
        ForeignKey("periods.id"), nullable=False, index=True
    )
    organizational_boundary_id: Mapped[str] = mapped_column(
        ForeignKey("boundary_definitions.id"), nullable=False, index=True
    )
    demand: Mapped[list] = mapped_column(JSON, nullable=False)
    capabilities: Mapped[list] = mapped_column(JSON, nullable=False)
    dependencies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    system_revision_id: Mapped[str] = mapped_column(
        ForeignKey("system_revisions.id"), nullable=False, index=True
    )
    boundary_id: Mapped[str] = mapped_column(
        ForeignKey("boundary_definitions.id"), nullable=False, index=True
    )
    period_id: Mapped[str] = mapped_column(
        ForeignKey("periods.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InventoryDataPoint(Base):
    __tablename__ = "inventory_data_points"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    inventory_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("inventory_snapshots.id"), nullable=False, index=True
    )
    entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.id"), nullable=True, index=True
    )
    process_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    flow_uuid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metric_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_items.id"), nullable=False, index=True
    )
    mapping_target: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    uncertainty: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ParameterSet(Base):
    __tablename__ = "parameter_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_revision_id: Mapped[str] = mapped_column(
        ForeignKey("system_revisions.id"), nullable=False, index=True
    )
    system_revision_id: Mapped[str] = mapped_column(
        ForeignKey("system_revisions.id"), nullable=False, index=True
    )
    inventory_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("inventory_snapshots.id"), nullable=True, index=True
    )
    parameter_set_id: Mapped[str | None] = mapped_column(
        ForeignKey("parameter_sets.id"), nullable=True, index=True
    )
    method_package_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    assumptions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisPlan(Base):
    __tablename__ = "analysis_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("scenarios.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    capability_keys: Mapped[list] = mapped_column(JSON, nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Comparison(Base):
    __tablename__ = "comparisons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scenario_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    comparability: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ScenarioComparisonRun(Base):
    __tablename__ = "scenario_comparison_runs"
    __table_args__ = (
        UniqueConstraint(
            "comparison_id",
            "idempotency_key",
            name="uq_scenario_comparison_run_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    comparison_id: Mapped[str] = mapped_column(
        ForeignKey("comparisons.id"), nullable=False, index=True
    )
    baseline_scenario_id: Mapped[str] = mapped_column(
        ForeignKey("scenarios.id"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    request_json: Mapped[dict] = mapped_column("request", JSON, nullable=False)
    scenario_results: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metrics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    audit: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SolvedSystemSnapshot(Base):
    __tablename__ = "solved_system_snapshots"
    __table_args__ = (
        UniqueConstraint("application_id", "solve_hash", name="uq_solved_snapshot_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    system_revision_id: Mapped[str] = mapped_column(
        ForeignKey("system_revisions.id"), nullable=False, index=True
    )
    inventory_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("inventory_snapshots.id"), nullable=True, index=True
    )
    parameter_set_id: Mapped[str | None] = mapped_column(
        ForeignKey("parameter_sets.id"), nullable=True, index=True
    )
    solve_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_receipt: Mapped[dict] = mapped_column(JSON, nullable=False)
    functional_unit: Mapped[dict | str] = mapped_column(JSON, nullable=False)
    database_release: Mapped[str] = mapped_column(String(255), nullable=False)
    solver_version: Mapped[str] = mapped_column(String(128), nullable=False)
    activity_vector: Mapped[list] = mapped_column(JSON, nullable=False)
    scaled_technosphere_exchanges: Mapped[list] = mapped_column(JSON, nullable=False)
    scaled_elementary_exchanges: Mapped[list] = mapped_column(JSON, nullable=False)
    internal_transfers: Mapped[list] = mapped_column(JSON, nullable=False)
    boundary_flows: Mapped[list] = mapped_column(JSON, nullable=False)
    process_balance_residuals: Mapped[list] = mapped_column(JSON, nullable=False)
    contribution_graph: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    lcia_results: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    native_background_climate: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class EnergyCarrierResult(Base):
    __tablename__ = "energy_carrier_results"
    __table_args__ = (
        UniqueConstraint(
            "solved_snapshot_id",
            "request_sha256",
            name="uq_energy_carrier_result_request",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    solved_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("solved_system_snapshots.id"), nullable=False, index=True
    )
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[dict] = mapped_column("result", JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ResultSet(Base):
    __tablename__ = "result_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("scenarios.id"), nullable=False, index=True
    )
    analysis_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_plans.id"), nullable=True, index=True
    )
    solved_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("solved_system_snapshots.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dimensions: Mapped[list] = mapped_column(JSON, nullable=False)
    metrics: Mapped[list] = mapped_column(JSON, nullable=False)
    units: Mapped[dict] = mapped_column(JSON, nullable=False)
    aggregation_rules: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_run_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    method_package_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class EvidencePack(Base):
    __tablename__ = "evidence_packs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    result_set_id: Mapped[str] = mapped_column(
        ForeignKey("result_sets.id"), nullable=False, index=True
    )
    evidence_item_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    lineage: Mapped[dict] = mapped_column(JSON, nullable=False)
    completeness: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class TagGroupingResult(Base):
    """Immutable tag view; independent of later edits or retirement of its schemes."""

    __tablename__ = "tag_grouping_results"
    __table_args__ = (UniqueConstraint("application_id", "request_sha256", name="uq_tag_grouping_request"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("solved_system_snapshots.id"), nullable=False, index=True)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class CalculationMethod(Base):
    """A user-defined calculation method bound to one exact Nebula LCA model revision.

    Identity lives here; the versioned rule content lives in CalculationMethodVersion.
    ``model_revision_id`` is always a concrete revision, never ``latest``.
    """

    __tablename__ = "calculation_methods"
    __table_args__ = (
        UniqueConstraint(
            "application_id", "model_revision_id", "name", name="uq_calculation_method_name"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    model_revision_id: Mapped[str] = mapped_column(
        ForeignKey("system_revisions.id"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_method_id: Mapped[str | None] = mapped_column(
        ForeignKey("calculation_methods.id"), nullable=True, index=True
    )
    origin_method_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin_content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class CalculationMethodVersion(Base):
    """An immutable-by-version snapshot of the user's boundary/Scope/location rules."""

    __tablename__ = "calculation_method_versions"
    __table_args__ = (
        UniqueConstraint("method_id", "version", name="uq_calculation_method_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    method_id: Mapped[str] = mapped_column(
        ForeignKey("calculation_methods.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reporting_dimensions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # The exact model-processing package a user CBAM/variant version narrows against, in the
    # {package_id, version, content_sha256} shape a derivation pin reads. Null keeps the version on
    # the automatic official selection, so a pre-migration snapshot and its content hash are unchanged;
    # only a version that binds a package folds this reference into its identity.
    model_processing_rules_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # The version's explicit semantics. NULL keeps every pre-existing method on the legacy
    # boundary/Scope reading; "flow_tag.v1" declares a flow-tag scheme, where the single declared
    # dimension is the scheme's category set and each rule is one confirmed flow match. The marker
    # is persisted, never inferred from purpose or an empty field, and folds into the content hash
    # only when present so a historical version keeps its byte-for-byte identity.
    semantics: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cbam_boundary_ref: Mapped[str | None] = mapped_column(
        ForeignKey("boundary_definitions.id"), nullable=True, index=True
    )
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
