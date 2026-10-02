from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .analysis.energy_carrier import EnergyCarrierSolved
from .casepacks.quantity_conversions import QuantityConversionReceipt
from .schemas import OutboxEventOut
from .mapped_background_schemas import ProviderMappedBackgroundProcessPin


SHA256_PATTERN = r"^[0-9a-f]{64}$"


def _strip(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value cannot be blank")
    return normalized


class EntityCreate(BaseModel):
    entity_type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    parent_id: str | None = None
    external_id: str | None = Field(default=None, max_length=255)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entity_type", "name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip(value)


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    parent_id: str | None
    entity_type: str
    name: str
    external_id: str | None
    attributes: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


class PeriodCreate(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    start_date: date
    end_date: date
    resolution: str = Field(min_length=1, max_length=32)

    @field_validator("key", "name", "resolution")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip(value)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        return self


class PeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    key: str
    name: str
    start_date: date
    end_date: date
    resolution: str
    created_at: datetime


class MethodPackageCreate(BaseModel):
    package_id: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=64)
    package_kind: str = Field(min_length=1, max_length=64)
    jurisdiction: str | None = Field(default=None, max_length=128)
    valid_from: date | None = None
    valid_to: date | None = None
    manifest: dict[str, Any]

    @field_validator("package_id", "version", "package_kind")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip(value)

    @model_validator(mode="after")
    def validate_manifest(self):
        required = {
            "required_entity_types",
            "required_data_fields",
            "accepted_units",
            "boundary_schema",
            "formula_graph",
            "classification_rules",
            "default_value_rules",
            "validation_rules",
            "output_schema",
            "report_mapping",
            "test_cases",
            "provenance",
            "assurance_level",
        }
        missing = sorted(required.difference(self.manifest))
        if missing:
            raise ValueError(f"method package manifest is missing fields: {missing}")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot be earlier than valid_from")
        return self


class MethodPackageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    package_id: str
    version: str
    package_kind: str
    jurisdiction: str | None
    valid_from: date | None
    valid_to: date | None
    manifest: dict[str, Any]
    content_sha256: str
    status: str
    created_at: datetime


class BoundaryDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    boundary_type: str = Field(min_length=1, max_length=64)
    included_entity_ids: list[str] = Field(default_factory=list)
    included_process_ids: list[str] = Field(default_factory=list)
    included_flow_rules: list[dict[str, Any]] = Field(default_factory=list)
    excluded_items: list[dict[str, Any]] = Field(default_factory=list)
    consolidation_policy: dict[str, Any] = Field(default_factory=dict)
    period_id: str | None = None
    geographic_scope: dict[str, Any] = Field(default_factory=dict)
    method_package_ref: str | None = Field(default=None, max_length=320)

    @field_validator("name", "boundary_type")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip(value)


class BoundaryDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    name: str
    boundary_type: str
    included_entity_ids: list[str]
    included_process_ids: list[str]
    included_flow_rules: list[dict[str, Any]]
    excluded_items: list[dict[str, Any]]
    consolidation_policy: dict[str, Any]
    period_id: str | None
    geographic_scope: dict[str, Any]
    method_package_ref: str | None
    content_sha256: str | None
    status: str
    created_at: datetime
    frozen_at: datetime | None


class EntityModelBindingCreate(BaseModel):
    entity_id: str
    system_revision_id: str
    process_ids: list[str] = Field(default_factory=list)
    flow_selectors: list[dict[str, Any]] = Field(default_factory=list)
    period_id: str | None = None
    allocation_rule_ref: str | None = Field(default=None, max_length=320)


class EntityModelBindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    entity_id: str
    system_revision_id: str
    process_ids: list[str]
    flow_selectors: list[dict[str, Any]]
    period_id: str | None
    allocation_rule_ref: str | None
    content_sha256: str
    created_at: datetime


class EvidenceItemCreate(BaseModel):
    evidence_type: str = Field(min_length=1, max_length=64)
    source_name: str = Field(min_length=1, max_length=255)
    source_ref: str = Field(min_length=1)
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_type", "source_name", "source_ref")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip(value)


class EvidenceItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    application_id: str
    evidence_type: str
    source_name: str
    source_ref: str
    content_sha256: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    created_at: datetime


class InventorySnapshotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    system_revision_id: str
    boundary_id: str
    period_id: str

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip(value)


class InventorySnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    name: str
    system_revision_id: str
    boundary_id: str
    period_id: str
    status: str
    content_sha256: str | None
    created_at: datetime
    frozen_at: datetime | None


class InventoryDataPointCreate(BaseModel):
    entity_id: str | None = None
    process_id: str | None = Field(default=None, max_length=255)
    flow_uuid: str | None = Field(default=None, max_length=255)
    metric_key: str = Field(min_length=1, max_length=255)
    quantity: float = Field(ge=0)
    unit: str = Field(min_length=1, max_length=128)
    source_type: str = Field(min_length=1, max_length=64)
    evidence_id: str
    mapping_target: dict[str, Any] = Field(default_factory=dict)
    quality_status: str = Field(min_length=1, max_length=32)
    review_status: str = Field(min_length=1, max_length=32)
    uncertainty: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metric_key", "unit", "source_type", "quality_status", "review_status")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip(value)

    @model_validator(mode="after")
    def validate_mapping_target(self):
        if not any((self.entity_id, self.process_id, self.flow_uuid, self.mapping_target)):
            raise ValueError("data point requires an entity or model mapping target")
        return self


class InventoryDataPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    inventory_snapshot_id: str
    entity_id: str | None
    process_id: str | None
    flow_uuid: str | None
    metric_key: str
    quantity: float
    unit: str
    source_type: str
    evidence_id: str
    mapping_target: dict[str, Any]
    quality_status: str
    review_status: str
    uncertainty: dict[str, Any]
    created_at: datetime


class ParameterSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    values: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip(value)


class ParameterSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    application_id: str
    name: str
    values: dict[str, Any]
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    status: str
    content_sha256: str | None
    created_at: datetime
    frozen_at: datetime | None


class ScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    base_revision_id: str
    system_revision_id: str
    inventory_snapshot_id: str | None = None
    parameter_set_id: str | None = None
    method_package_refs: list[str] = Field(default_factory=list)
    assumptions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip(value)


class ScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    name: str
    base_revision_id: str
    system_revision_id: str
    inventory_snapshot_id: str | None
    parameter_set_id: str | None
    method_package_refs: list[str]
    assumptions: dict[str, Any]
    status: str
    content_sha256: str | None
    created_at: datetime
    frozen_at: datetime | None


class AnalysisPlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scenario_id: str
    capability_keys: list[str] = Field(min_length=1)
    configuration: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip(value)

    @field_validator("capability_keys")
    @classmethod
    def validate_capability_keys(cls, values: list[str]) -> list[str]:
        normalized = [_strip(value) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("capability_keys cannot contain duplicates")
        return normalized


class AnalysisPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    scenario_id: str
    name: str
    capability_keys: list[str]
    configuration: dict[str, Any]
    status: str
    content_sha256: str | None
    created_at: datetime
    frozen_at: datetime | None


class ComparisonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scenario_ids: list[str] = Field(min_length=2)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip(value)

    @field_validator("scenario_ids")
    @classmethod
    def unique_scenarios(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("scenario_ids cannot contain duplicates")
        return values


class ComparisonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    name: str
    scenario_ids: list[str]
    comparability: dict[str, Any]
    content_sha256: str
    created_at: datetime


class ScenarioComparisonDeltaOut(BaseModel):
    absolute: float
    relative: float | None


class ScenarioComparisonMetricOut(BaseModel):
    metric_key: str
    metric_kind: Literal["boundary_flow", "lcia_indicator", "pcf_total"] = (
        "boundary_flow"
    )
    subject_id: str | None = None
    subject_name: str | None = None
    series_id: str
    flow_uuid: str | None = None
    flow_name: str | None = None
    indicator_key: str | None = None
    method: str | None = None
    database_release: str | None = None
    indicator_metadata_hash: str | None = None
    direction: str | None = None
    exchange_type: str | None = None
    unit_group: str
    unit_group_label: str | None = None
    unit: str
    baseline_value: float
    scenario_values: dict[str, float]
    deltas: dict[str, ScenarioComparisonDeltaOut]


class ScenarioComparisonResultOut(BaseModel):
    scenario_id: str
    scenario_name: str
    scenario_hash: str
    system_revision_id: str
    solved_snapshot_id: str
    solved_snapshot_hash: str
    solve_hash: str
    provider_receipt: dict[str, Any]
    lcia_results: dict[str, Any] = Field(default_factory=dict)
    pcf_result: dict[str, Any] = Field(default_factory=dict)
    pcf_result_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    elementary_flow_receipts: list[dict[str, Any]] = Field(default_factory=list)
    technosphere_flow_receipts: list[dict[str, Any]] = Field(default_factory=list)
    mfa_audit: dict[str, Any]
    mfa_series: list[dict[str, Any]]
    sankey_url: str


class ScenarioComparisonRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    application_id: str
    comparison_id: str
    baseline_scenario_id: str
    idempotency_key: str
    request_sha256: str
    status: str
    request: dict[str, Any] = Field(validation_alias="request_json")
    scenario_results: list[ScenarioComparisonResultOut]
    metrics: list[ScenarioComparisonMetricOut]
    audit: dict[str, Any]
    error: dict[str, Any]
    content_sha256: str | None
    created_at: datetime
    completed_at: datetime | None


class QueuedScenarioComparisonRunOut(BaseModel):
    run: ScenarioComparisonRunOut
    task: OutboxEventOut


class SolvedActivityValue(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    process_id: str = Field(min_length=1, max_length=255)
    value: float
    unit: str = Field(min_length=1, max_length=128)


class SolvedExchangeValue(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    exchange_id: str = Field(min_length=1, max_length=255)
    process_id: str = Field(min_length=1, max_length=255)
    counterparty_process_id: str | None = Field(default=None, max_length=255)
    flow_uuid: str = Field(min_length=1, max_length=255)
    amount: float
    unit: str = Field(min_length=1, max_length=128)
    unit_group: str = Field(min_length=1, max_length=128)
    direction: str = Field(pattern=r"^(input|output)$")
    exchange_type: str = Field(min_length=1, max_length=64)


class ProcessBalanceResidual(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    process_id: str = Field(min_length=1, max_length=255)
    quantity_kind: str = Field(min_length=1, max_length=128)
    residual: float
    unit: str = Field(min_length=1, max_length=128)
    tolerance: float = Field(ge=0)
    status: str = Field(pattern=r"^(balanced|accumulation|deficit)$")


class ProviderDemandItem(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    process_uuid: str | None = Field(default=None, min_length=1, max_length=255)
    reference_exchange_id: str | None = Field(
        default=None, min_length=1, max_length=255
    )
    reference_flow_uuid: str | None = Field(
        default=None, min_length=1, max_length=255
    )
    amount: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=128)
    unit_group_uuid: str | None = Field(default=None, min_length=1, max_length=255)
    unit_group_version: str | None = Field(
        default=None, min_length=1, max_length=255
    )

    @model_validator(mode="after")
    def require_one_selector(self) -> "ProviderDemandItem":
        selectors = (
            self.process_uuid,
            self.reference_exchange_id,
            self.reference_flow_uuid,
        )
        if sum(value is not None for value in selectors) != 1:
            raise ValueError(
                "exactly one of process_uuid, reference_exchange_id, or reference_flow_uuid is required"
            )
        return self


class ProviderBackgroundProcessPin(BaseModel):
    schema_version: Literal["provider.background-process-pin.v1"] = (
        "provider.background-process-pin.v1"
    )
    consumer_exchange_id: str = Field(min_length=1, max_length=255)
    source_namespace: Literal["tiangong_open_data"] = "tiangong_open_data"
    process_uuid: str = Field(
        pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"
    )
    version: str = Field(pattern=r"^[0-9]{2}\.[0-9]{2}\.[0-9]{3}$")
    expected_process_content_hash: str = Field(pattern=SHA256_PATTERN)
    expected_process_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    quantitative_reference_exchange_internal_id: str = Field(
        min_length=1,
        max_length=255,
    )
    claim_role: Literal["partial_background_leaf"] = "partial_background_leaf"

    @field_validator(
        "consumer_exchange_id",
        "process_uuid",
        "version",
        "quantitative_reference_exchange_internal_id",
    )
    @classmethod
    def strip_background_pin_text(cls, value: str) -> str:
        return _strip(value)


class ProviderProjectBackgroundPin(BaseModel):
    schema_version: Literal["provider.project-background-pin.v1"] = "provider.project-background-pin.v1"
    consumer_exchange_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    expected_graph_hash: str = Field(pattern=SHA256_PATTERN)
    source_node_id: str = Field(min_length=1)
    reference_port_id: str = Field(min_length=1)
    provider_amount_per_consumer_unit: float = Field(gt=0, allow_inf_nan=False)
    claim_role: Literal["user_declared_partial_background_leaf"] = "user_declared_partial_background_leaf"


class ScenarioComparisonExecuteCreate(BaseModel):
    mapped_background_process_pins: list[ProviderMappedBackgroundProcessPin] = Field(default_factory=list)
    baseline_scenario_id: str
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    demand: list[ProviderDemandItem] = Field(min_length=1)
    lcia_methods: list[str] | None = None
    pcf_method_package_ref: str | None = Field(
        default=None, min_length=3, max_length=320
    )
    background_process_pins: list[ProviderBackgroundProcessPin] = Field(
        default_factory=list
    )

    @field_validator(
        "baseline_scenario_id", "idempotency_key", "pcf_method_package_ref"
    )
    @classmethod
    def strip_comparison_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _strip(value)

    @field_validator("lcia_methods")
    @classmethod
    def normalize_comparison_methods(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if value is None:
            return None
        normalized = [_strip(item) for item in value]
        if not normalized:
            raise ValueError("lcia_methods cannot be empty")
        return normalized

    @model_validator(mode="after")
    def require_unique_background_consumers(self) -> "ScenarioComparisonExecuteCreate":
        consumer_ids = [
            item.consumer_exchange_id for item in [*self.background_process_pins, *self.mapped_background_process_pins]
        ]
        if len(consumer_ids) != len(set(consumer_ids)):
            raise ValueError(
                "background_process_pins must target unique consumer exchanges"
            )
        return self


class ProviderSolveAndFreezeCreate(BaseModel):
    mapped_background_process_pins: list[ProviderMappedBackgroundProcessPin] = Field(default_factory=list)
    project_background_pins: list[ProviderProjectBackgroundPin] = Field(default_factory=list)
    demand: list[ProviderDemandItem] = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    scenario_id: str | None = Field(default=None, max_length=36)
    lcia_methods: list[str] | None = None
    background_process_pins: list[ProviderBackgroundProcessPin] = Field(
        default_factory=list
    )
    native_background_climate: bool = False
    native_background_inventory: bool = False
    climate_default: bool = False
    # Names the accounting purpose this solve answers, never the rules that implement it: which
    # processes, associations and emissions a purpose keeps is decided by the versioned model
    # processing package bound to this model's template.
    calculation_purpose: str | None = Field(default=None, min_length=1, max_length=64)
    analysis_task: Literal["mfa", "pcf", "cbam", "organization"] | None = None

    @model_validator(mode="after")
    def require_native_climate_scope(self) -> "ProviderSolveAndFreezeCreate":
        if self.analysis_task == "cbam" and self.calculation_purpose != "cbam":
            raise ValueError("CBAM task requires the reviewed CBAM calculation purpose")
        if self.analysis_task in ("pcf", "organization") and not (self.climate_default or self.native_background_climate or self.lcia_methods):
            raise ValueError("a climate task requires a characterized method")
        if self.analysis_task == "mfa" and (self.climate_default or self.native_background_climate or self.lcia_methods):
            raise ValueError("MFA task cannot claim a climate answer")
        if self.native_background_inventory:
            providers = {item.process_uuid for item in self.mapped_background_process_pins}
            if (self.native_background_climate or self.climate_default or self.lcia_methods is not None
                    or self.scenario_id is not None or self.background_process_pins or self.project_background_pins or len(providers) != 1):
                raise ValueError("native background inventory requires one shared mapped provider and no climate or LCIA method")
        if self.climate_default and (self.native_background_climate or self.lcia_methods is not None):
            raise ValueError("climate_default selects its versioned method on the server")
        if not self.native_background_climate:
            return self
        if self.scenario_id is not None or self.background_process_pins or self.project_background_pins:
            raise ValueError(
                "native background climate total cannot be combined with a scenario or a bare provider pin"
            )
        # Mirrors the scope guard Nebula LCA applies to the same request at the pinned commit
        # (`NATIVE_CLIMATE_UNSUPPORTED_SCOPE`): mapped providers and no other pins.
        # A scenario is refused here too because the native answer characterises the solved
        # exchanges only, so a scenario-labelled climate total would claim a binding it never used.
        # The method selection is not a caller choice: it is part of the versioned contract, which
        # is why a supplied list is refused rather than compared against a literal here.
        providers = {item.process_uuid for item in self.mapped_background_process_pins}
        if self.lcia_methods is not None or not providers:
            raise ValueError(
                "native background climate total fixes its method through the versioned contract"
                " and requires a mapped provider"
            )
        return self

    @field_validator("idempotency_key")
    @classmethod
    def normalize_solve_idempotency_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _strip(value)

    @field_validator("calculation_purpose")
    @classmethod
    def normalize_calculation_purpose(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _strip(value)

    @field_validator("lcia_methods")
    @classmethod
    def normalize_methods(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [_strip(item) for item in value]
        if not normalized:
            raise ValueError("lcia_methods cannot be empty")
        return normalized

    @model_validator(mode="after")
    def require_unique_background_consumers(self) -> "ProviderSolveAndFreezeCreate":
        consumer_ids = [
            item.consumer_exchange_id for item in [*self.background_process_pins, *self.mapped_background_process_pins, *self.project_background_pins]
        ]
        if len(consumer_ids) != len(set(consumer_ids)):
            raise ValueError(
                "background_process_pins must target unique consumer exchanges"
            )
        return self


class SolvedSystemSnapshotCreate(BaseModel):
    system_revision_id: str
    inventory_snapshot_id: str | None = None
    parameter_set_id: str | None = None
    provider: str = Field(min_length=1, max_length=64)
    provider_receipt: dict[str, Any]
    functional_unit: Any
    database_release: str = Field(min_length=1, max_length=255)
    solver_version: str = Field(min_length=1, max_length=128)
    activity_vector: list[SolvedActivityValue]
    scaled_technosphere_exchanges: list[SolvedExchangeValue]
    scaled_elementary_exchanges: list[SolvedExchangeValue]
    internal_transfers: list[SolvedExchangeValue]
    boundary_flows: list[SolvedExchangeValue]
    process_balance_residuals: list[ProcessBalanceResidual]
    contribution_graph: dict[str, Any] = Field(default_factory=dict)
    lcia_results: dict[str, Any] = Field(default_factory=dict)
    native_background_climate: dict[str, Any] | None = None

    @field_validator("provider", "database_release", "solver_version")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip(value)


class SolvedSystemSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    system_revision_id: str
    inventory_snapshot_id: str | None
    parameter_set_id: str | None
    solve_hash: str
    provider: str
    provider_receipt: dict[str, Any]
    functional_unit: Any
    database_release: str
    solver_version: str
    activity_vector: list[dict[str, Any]]
    scaled_technosphere_exchanges: list[dict[str, Any]]
    scaled_elementary_exchanges: list[dict[str, Any]]
    internal_transfers: list[dict[str, Any]]
    boundary_flows: list[dict[str, Any]]
    process_balance_residuals: list[dict[str, Any]]
    contribution_graph: dict[str, Any]
    lcia_results: dict[str, Any]
    native_background_climate: dict[str, Any] | None
    content_sha256: str
    created_at: datetime


class ClimateMethodIdentityOut(BaseModel):
    lcia_method: str
    total_indicator_key: str
    result_unit: str
    source_contract: str | None
    source_method: dict[str, str] | None


class ClimateMethodResolutionOut(BaseModel):
    schema_version: Literal["nebula_one.climate-method-resolution.v1"]
    status: Literal["ready", "unavailable"]
    reference: str | None
    content_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    reason_code: str | None
    method: ClimateMethodIdentityOut | None


class ProductCarbonFootprintCreate(BaseModel):
    method_package_ref: str = Field(min_length=3, max_length=320)

    @field_validator("method_package_ref")
    @classmethod
    def strip_method_package_ref(cls, value: str) -> str:
        return _strip(value)


class ProductCarbonFootprintOut(BaseModel):
    schema_version: Literal["nebula_one.pcf.product.v1"]
    capability_key: Literal["pcf.product.v1"]
    method_package: dict[str, Any]
    source_snapshot: dict[str, Any]
    functional_unit: dict[str, Any]
    total_footprint: dict[str, Any]
    component_results: list[dict[str, Any]]
    contribution_analysis: dict[str, Any]
    boundary_claim: dict[str, Any]
    data_quality: dict[str, Any]
    audit: dict[str, Any]
    provenance: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class CarbonManagementCreate(BaseModel):
    method_package_ref: str = Field(min_length=3, max_length=320)
    energy_carrier_result_id: str = Field(min_length=1, max_length=255)

    @field_validator("method_package_ref", "energy_carrier_result_id")
    @classmethod
    def strip_carbon_management_refs(cls, value: str) -> str:
        return _strip(value)


class CarbonManagementOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.carbon.management.v1"]
    capability_key: Literal["carbon.management.v1"]
    method_package: dict[str, Any]
    source_snapshot: dict[str, Any]
    reporting_period: dict[str, Any]
    energy_result: dict[str, Any]
    direct_emission_inventory: list[dict[str, Any]]
    climate_change_total: dict[str, Any] | None
    carbon_attribution: dict[str, Any]
    audit: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class CbamTrialPrecursorCreate(BaseModel):
    solved_snapshot_id: str = Field(min_length=1, max_length=36)
    boundary_definition_id: str = Field(min_length=1, max_length=36)

    @field_validator("solved_snapshot_id", "boundary_definition_id")
    @classmethod
    def strip_cbam_trial_precursor_refs(cls, value: str) -> str:
        return _strip(value)


class CbamTrialCreate(BaseModel):
    method_package_ref: str = Field(min_length=3, max_length=320)
    reporting_period_id: str = Field(min_length=1, max_length=255)
    boundary_definition_id: str | None = Field(
        default=None, min_length=1, max_length=36
    )
    end_use_declaration: str | None = Field(default=None, min_length=1, max_length=64)
    precursors: list[CbamTrialPrecursorCreate] | None = Field(
        default=None, min_length=1, max_length=1
    )

    @field_validator(
        "method_package_ref",
        "reporting_period_id",
        "boundary_definition_id",
        "end_use_declaration",
    )
    @classmethod
    def strip_cbam_trial_refs(cls, value: str | None) -> str | None:
        return None if value is None else _strip(value)


class CbamPartialReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method_package_ref: str = Field(min_length=3, max_length=320)
    reporting_period_id: str = Field(min_length=1, max_length=255)
    boundary_definition_id: str = Field(min_length=1, max_length=36)
    eligible_electricity_factor_ref: str | None = Field(default=None, min_length=3, max_length=320)
    condition_declarations: dict[str, dict[str, str]] = Field(default_factory=dict)


class CbamTrialOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.cbam.trial.v1"]
    capability_key: Literal["cbam.trial.v1"]
    method_package: dict[str, Any]
    source_snapshot: dict[str, Any]
    reporting_period: dict[str, Any]
    goods: dict[str, Any]
    activity_level: dict[str, Any]
    attributed_emissions: dict[str, Any]
    specific_embedded_emissions: dict[str, Any]
    status: Literal["trial_passed"]
    audit: dict[str, Any]
    claim_boundary: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class CbamTrialV2Out(CbamTrialOut):
    model_config = ConfigDict(extra="forbid")

    status: Literal["trial_passed", "partial_calculated"]

    schema_version: Literal["nebula_one.cbam.trial.v2"]
    capability_key: Literal["cbam.trial.v2"]
    coverage: dict[str, Any]
    # a three-component result carries A-C18's second denominator beside the per-tonne indicator;
    # a direct-only good has none, and the analyzed content_sha256 does not contain this key either
    nitrogen_basis: dict[str, Any] | None = None


class CbamComplexPrecursorCreate(BaseModel):
    solved_snapshot_id: str = Field(min_length=1, max_length=255)
    method_package_ref: str = Field(min_length=3, max_length=320)

    @field_validator("solved_snapshot_id", "method_package_ref")
    @classmethod
    def strip_cbam_complex_precursor_refs(cls, value: str) -> str:
        return _strip(value)


class CbamComplexTrialCreate(BaseModel):
    method_package_ref: str = Field(min_length=3, max_length=320)
    reporting_period_id: str = Field(min_length=1, max_length=255)
    precursors: list[CbamComplexPrecursorCreate] = Field(
        min_length=1, max_length=1
    )

    @field_validator("method_package_ref", "reporting_period_id")
    @classmethod
    def strip_cbam_complex_refs(cls, value: str) -> str:
        return _strip(value)

    @model_validator(mode="after")
    def unique_precursor_methods(self) -> "CbamComplexTrialCreate":
        refs = [item.method_package_ref for item in self.precursors]
        if len(refs) != len(set(refs)):
            raise ValueError("precursor method_package_ref values must be unique")
        return self


class CbamComplexTrialOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.cbam.complex-trial.v1"]
    capability_key: Literal["cbam.complex-trial.v1"]
    method_package: dict[str, Any]
    source_snapshot: dict[str, Any]
    reporting_period: dict[str, Any]
    goods: dict[str, Any]
    activity_level: dict[str, Any]
    attributed_emissions: dict[str, Any]
    precursors: list[dict[str, Any]]
    specific_embedded_emissions: dict[str, Any]
    status: Literal["trial_passed"]
    audit: dict[str, Any]
    claim_boundary: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class SpatialAggregateCreate(BaseModel):
    boundary_id: str = Field(min_length=1, max_length=255)
    series_id: str | None = Field(default=None, min_length=1, max_length=512)
    tolerance: float = Field(default=1e-9, ge=0)

    @field_validator("boundary_id", "series_id")
    @classmethod
    def strip_spatial_refs(cls, value: str | None) -> str | None:
        return _strip(value) if value is not None else None


class SpatialAggregateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.spatial.aggregate.v1"]
    capability_key: Literal["spatial.aggregate.v1"]
    source_snapshot: dict[str, Any]
    park: dict[str, Any]
    facilities: list[dict[str, Any]]
    series: list[dict[str, Any]]
    audit: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class SpatialEnergyCreate(BaseModel):
    boundary_id: str = Field(min_length=1, max_length=255)
    energy_carrier_result_id: str = Field(min_length=1, max_length=255)
    series_id: str | None = Field(default=None, min_length=1, max_length=512)
    tolerance: float = Field(default=1e-9, ge=0)

    @field_validator("boundary_id", "energy_carrier_result_id", "series_id")
    @classmethod
    def strip_spatial_energy_refs(cls, value: str | None) -> str | None:
        return _strip(value) if value is not None else None


class SpatialEnergyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.spatial.energy.v1"]
    capability_key: Literal["spatial.energy.v1"]
    source_snapshot: dict[str, Any]
    source_energy_result: dict[str, Any]
    source_spatial_result: dict[str, Any]
    park: dict[str, Any]
    facilities: list[dict[str, Any]]
    series: list[dict[str, Any]]
    audit: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class PeriodEnergyComparisonCreate(BaseModel):
    energy_result_ids: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("energy_result_ids")
    @classmethod
    def normalize_energy_result_ids(cls, value: list[str]) -> list[str]:
        normalized = [_strip(item) for item in value]
        if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("energy_result_ids must be non-empty and unique")
        return normalized


class PeriodEnergyComparisonOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[
        "nebula_one.period-energy-scenario-comparison.v1"
    ]
    capability_key: Literal["energy.scenario-comparison.v1"]
    reporting_period: dict[str, Any]
    source_comparison_run: dict[str, Any]
    comparison: dict[str, Any]
    audit: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class PeriodEnergyTrendObservationCreate(BaseModel):
    period_id: str = Field(min_length=1, max_length=128)
    energy_result_id: str = Field(min_length=1, max_length=128)

    @field_validator("period_id", "energy_result_id")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip(value)


class PeriodEnergyTrendCreate(BaseModel):
    observations: list[PeriodEnergyTrendObservationCreate] = Field(
        min_length=2,
        max_length=24,
    )
    baseline_period_id: str | None = Field(default=None, max_length=128)

    @field_validator("baseline_period_id")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        return _strip(value) if value is not None else None

    @model_validator(mode="after")
    def validate_unique_bindings(self):
        period_ids = [item.period_id for item in self.observations]
        result_ids = [item.energy_result_id for item in self.observations]
        if len(period_ids) != len(set(period_ids)):
            raise ValueError("period observations must use unique period ids")
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("period observations must use unique energy result ids")
        if self.baseline_period_id and self.baseline_period_id not in period_ids:
            raise ValueError("baseline_period_id must be included in observations")
        return self


class PeriodEnergyTrendOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.period-energy-trend.v1"]
    capability_key: Literal["energy.period-trend.v1"]
    application_id: str
    system_model_id: str
    value_semantics: dict[str, Any]
    baseline_period_id: str
    observations: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    status: str
    audit: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class PeriodEnergyTotalObservationCreate(PeriodEnergyTrendObservationCreate):
    inventory_snapshot_id: str = Field(min_length=1, max_length=128)
    production_data_point_id: str = Field(min_length=1, max_length=128)

    @field_validator("inventory_snapshot_id", "production_data_point_id")
    @classmethod
    def strip_activity_identity(cls, value: str) -> str:
        return _strip(value)


class PeriodEnergyTotalCreate(BaseModel):
    observations: list[PeriodEnergyTotalObservationCreate] = Field(
        min_length=2,
        max_length=24,
    )
    baseline_period_id: str | None = Field(default=None, max_length=128)

    @field_validator("baseline_period_id")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        return _strip(value) if value is not None else None

    @model_validator(mode="after")
    def validate_unique_bindings(self):
        fields = (
            "period_id",
            "energy_result_id",
            "inventory_snapshot_id",
            "production_data_point_id",
        )
        for field in fields:
            values = [getattr(item, field) for item in self.observations]
            if len(values) != len(set(values)):
                raise ValueError(f"period total observations must use unique {field} values")
        period_ids = [item.period_id for item in self.observations]
        if self.baseline_period_id and self.baseline_period_id not in period_ids:
            raise ValueError("baseline_period_id must be included in observations")
        return self


class PeriodEnergyTotalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.period-energy-total.v1"]
    capability_key: Literal["energy.period-total.v1"]
    application_id: str
    system_model_id: str
    source_intensity_trend: dict[str, Any]
    value_semantics: dict[str, Any]
    baseline_period_id: str
    observations: list[dict[str, Any]]
    activities: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    status: Literal["passed", "passed_with_warnings"]
    audit: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class ProvinceElectricityCreate(BaseModel):
    method_package_ref: str = Field(min_length=3, max_length=260)
    period_energy_total: PeriodEnergyTotalCreate

    @field_validator("method_package_ref")
    @classmethod
    def strip_method_ref(cls, value: str) -> str:
        return _strip(value)


class ProvinceElectricityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.province-electricity-scenario.v1"]
    capability_key: Literal["electricity.province-scenario.v1"]
    application_id: str
    system_model_id: str
    source_period_energy_total: dict[str, Any]
    source_binding: dict[str, Any]
    method_package: dict[str, Any]
    value_semantics: dict[str, Any]
    electricity_activity: dict[str, Any]
    factor_source: dict[str, Any]
    baseline_scenario_id: str
    scenarios: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    status: Literal["passed", "passed_with_warnings"]
    audit: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class OrganizationGhgInventoryCreate(BaseModel):
    method_package_ref: str = Field(min_length=3, max_length=320)
    carbon_method_package_ref: str = Field(min_length=3, max_length=320)
    province_electricity: ProvinceElectricityCreate
    scope_2_scenario_id: str = Field(min_length=1, max_length=128)

    @field_validator(
        "method_package_ref", "carbon_method_package_ref", "scope_2_scenario_id"
    )
    @classmethod
    def strip_ghg_inventory_refs(cls, value: str) -> str:
        return _strip(value)


class OrganizationGhgInventoryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.organization-ghg-inventory-trial.v1"]
    capability_key: Literal["ghg.inventory.trial.v1"]
    application_id: str
    method_package: dict[str, Any]
    source_period_energy_total: dict[str, Any]
    reporting_period: dict[str, Any]
    inventory_boundary: dict[str, Any]
    scopes: list[dict[str, Any]]
    combined_total: None
    issues: list[dict[str, Any]]
    status: Literal["passed_with_warnings"]
    audit: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class OrganizationGhgInventoryV1Create(BaseModel):
    method_package_ref: str = Field(min_length=3, max_length=320)
    pcf_method_package_ref: str = Field(min_length=3, max_length=320)
    binding_ids: list[str] = Field(min_length=1)

    @field_validator("method_package_ref", "pcf_method_package_ref")
    @classmethod
    def strip_organization_method_refs(cls, value: str) -> str:
        return _strip(value)

    @field_validator("binding_ids")
    @classmethod
    def normalize_organization_binding_ids(cls, values: list[str]) -> list[str]:
        normalized = [_strip(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("binding_ids must be unique")
        return normalized


class OrganizationGhgInventoryV1Out(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.organization-ghg-inventory.v1"]
    capability_key: Literal["organization.ghg-inventory.v1"]
    application_id: str
    reporting_period_id: str
    organizational_boundary_id: str
    method_package: dict[str, Any]
    comparability: dict[str, Any]
    scopes: list[dict[str, Any]]
    total: dict[str, Any]
    audit: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class OrganizationSupplierActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activity_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    consumer_exchange_id: str = Field(min_length=1)
    quantity: float = Field(gt=0, allow_inf_nan=False)
    activity_unit: str = Field(min_length=1)
    factor_value: float = Field(gt=0, allow_inf_nan=False)
    factor_unit: str = Field(min_length=1)
    factor_version: str = Field(min_length=1)
    factor_source: str = Field(min_length=1)
    factor_boundary: str = Field(min_length=1)
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    evidence_role: Literal["supplier_specific", "demonstration_proxy"]
    outside_model: bool


class OrganizationPeriodCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    solved_snapshot_id: str = Field(min_length=1)
    method_package_ref: str = Field(min_length=3, max_length=320)
    reporting_period_id: str = Field(min_length=1)
    facility: str = Field(min_length=1)
    controlled_process_ids: list[str] = Field(min_length=1)
    period_product_output: float = Field(gt=0, allow_inf_nan=False)
    scope3_activities: list[OrganizationSupplierActivity] = Field(default_factory=list)
    category_statuses: dict[str, Literal["missing_activity", "not_applicable", "excluded_by_boundary"]] = Field(default_factory=dict)


class OrganizationLifecycleActivity(OrganizationSupplierActivity):
    factor_package_ref: str | None = Field(default=None, min_length=3, max_length=320)
    factor_method_id: str | None = None
    factor_method_version: str | None = None
    factor_method_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    factor_reference_product: str | None = None


class OrganizationLifecycleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    solved_snapshot_id: str = Field(min_length=1)
    method_package_ref: str = Field(min_length=3, max_length=320)
    reporting_period_id: str = Field(min_length=1)
    facility: str = Field(min_length=1)
    controlled_process_ids: list[str] = Field(min_length=1)
    input_basis: Literal["per_unit_product", "annual_total"]
    period_product_output: float = Field(gt=0, allow_inf_nan=False)
    other_activities: list[OrganizationLifecycleActivity] = Field(default_factory=list)


class OrganizationPeriodOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    application_id: str
    system_revision_id: str
    solved_snapshot_id: str
    period_id: str
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    result: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    created_at: datetime


class EnergyCarrierResultCreate(BaseModel):
    direct_exchange_ids: tuple[str, ...] = ()
    conversions: tuple[QuantityConversionReceipt, ...] = ()

    @field_validator("direct_exchange_ids")
    @classmethod
    def normalize_direct_exchange_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_strip(item) for item in value)


class EnergyCarrierResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    solved_snapshot_id: str
    request_sha256: str
    result: EnergyCarrierSolved = Field(validation_alias="result_json")
    content_sha256: str
    created_at: datetime


class EnergyFlowInternalLinkCreate(BaseModel):
    source_exchange_id: str = Field(min_length=1, max_length=255)
    target_exchange_id: str = Field(min_length=1, max_length=255)

    @field_validator("source_exchange_id", "target_exchange_id")
    @classmethod
    def strip_exchange_ids(cls, value: str) -> str:
        return _strip(value)


class EnergyFlowConversionCreate(BaseModel):
    process_node_id: str = Field(min_length=1, max_length=255)
    input_energy_entry_ids: list[str] = Field(min_length=1)
    useful_internal_links: list[EnergyFlowInternalLinkCreate] = Field(min_length=1)
    loss_output_exchange_ids: list[str] = Field(min_length=1)

    @field_validator("process_node_id")
    @classmethod
    def strip_process_node_id(cls, value: str) -> str:
        return _strip(value)

    @field_validator("input_energy_entry_ids", "loss_output_exchange_ids")
    @classmethod
    def normalize_id_lists(cls, values: list[str]) -> list[str]:
        normalized = [_strip(item) for item in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("energy flow identifiers must be unique")
        return normalized


class EnergyFlowCreate(BaseModel):
    energy_carrier_result_id: str = Field(min_length=1, max_length=255)
    conversions: list[EnergyFlowConversionCreate] = Field(min_length=1)
    series_id: str | None = Field(default=None, min_length=1, max_length=255)
    tolerance: float = Field(default=1e-9, ge=0)

    @field_validator("energy_carrier_result_id", "series_id")
    @classmethod
    def strip_energy_flow_refs(cls, value: str | None) -> str | None:
        return _strip(value) if value is not None else None

    @model_validator(mode="after")
    def unique_conversion_processes(self):
        process_ids = [item.process_node_id for item in self.conversions]
        if len(process_ids) != len(set(process_ids)):
            raise ValueError("energy flow conversion process_node_id values must be unique")
        return self


class EnergyFlowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.energy-flow.solved.v1"]
    capability_key: Literal["energy.flow.solved.v1"]
    source_snapshot: dict[str, Any]
    source_energy_result: dict[str, Any]
    series: list[dict[str, Any]]
    audit: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class WaterBalanceInternalLinkCreate(BaseModel):
    source_exchange_id: str = Field(min_length=1, max_length=255)
    target_exchange_id: str = Field(min_length=1, max_length=255)

    @field_validator("source_exchange_id", "target_exchange_id")
    @classmethod
    def strip_exchange_ids(cls, value: str) -> str:
        return _strip(value)


class WaterBalanceSeriesCreate(BaseModel):
    series_id: str = Field(min_length=1, max_length=255)
    unit_group_uuid: str = Field(min_length=1, max_length=255)
    unit: str = Field(min_length=1, max_length=64)
    withdrawal_exchange_ids: list[str] = Field(min_length=1)
    wastewater_links: list[WaterBalanceInternalLinkCreate] = Field(min_length=1)
    reuse_links: list[WaterBalanceInternalLinkCreate] = Field(min_length=1)
    discharge_exchange_ids: list[str] = Field(min_length=1)
    consumptive_output_exchange_ids: list[str] = Field(min_length=1)

    @field_validator("series_id", "unit_group_uuid", "unit")
    @classmethod
    def strip_series_identity(cls, value: str) -> str:
        return _strip(value)

    @field_validator(
        "withdrawal_exchange_ids",
        "discharge_exchange_ids",
        "consumptive_output_exchange_ids",
    )
    @classmethod
    def normalize_exchange_ids(cls, values: list[str]) -> list[str]:
        normalized = [_strip(item) for item in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("water balance exchange identifiers must be unique")
        return normalized


class WaterBalanceCreate(BaseModel):
    series: list[WaterBalanceSeriesCreate] = Field(min_length=1)
    series_id: str | None = Field(default=None, min_length=1, max_length=255)
    tolerance: float = Field(default=1e-9, ge=0)

    @field_validator("series_id")
    @classmethod
    def strip_series_id(cls, value: str | None) -> str | None:
        return _strip(value) if value is not None else None

    @model_validator(mode="after")
    def unique_series_ids(self):
        ids = [item.series_id for item in self.series]
        if len(ids) != len(set(ids)):
            raise ValueError("water balance series_id values must be unique")
        return self


class WaterBalanceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.water-balance.solved.v1"]
    capability_key: Literal["water.balance.solved.v1"]
    source_snapshot: dict[str, Any]
    series: list[dict[str, Any]]
    audit: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class SpatialEnergyFlowCreate(EnergyFlowCreate):
    boundary_id: str = Field(min_length=1, max_length=255)

    @field_validator("boundary_id")
    @classmethod
    def strip_boundary_id(cls, value: str) -> str:
        return _strip(value)


class SpatialEnergyFlowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.spatial.energy-flow.v1"]
    capability_key: Literal["spatial.energy-flow.v1"]
    source_snapshot: dict[str, Any]
    source_energy_flow: dict[str, Any]
    source_spatial_result: dict[str, Any]
    park: dict[str, Any]
    facilities: list[dict[str, Any]]
    series: list[dict[str, Any]]
    audit: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class SpatialDistributionCreate(BaseModel):
    method_package_ref: str = Field(min_length=3, max_length=320)
    scenario_id: str | None = Field(default=None, min_length=1, max_length=128)
    tolerance: float = Field(default=1e-9, ge=0)

    @field_validator("method_package_ref")
    @classmethod
    def strip_method_ref(cls, value: str) -> str:
        return _strip(value)


class SpatialDistributionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["nebula_one.spatial.distribution.v1"]
    capability_key: Literal["spatial.distribution.v1"]
    source_snapshot: dict[str, Any]
    method_package: dict[str, Any]
    source_flow: dict[str, Any]
    destination: dict[str, Any]
    baseline_scenario_id: str
    scenarios: list[dict[str, Any]]
    audit: dict[str, Any]
    content_sha256: str = Field(pattern=SHA256_PATTERN)


class ResultSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scenario_id: str
    analysis_plan_id: str | None = None
    solved_snapshot_id: str | None = None
    dimensions: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    units: dict[str, Any]
    aggregation_rules: dict[str, Any] = Field(default_factory=dict)
    source_run_ids: list[str] = Field(default_factory=list)
    method_package_refs: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip(value)

    @model_validator(mode="after")
    def require_provenance_source(self):
        if not self.source_run_ids and self.solved_snapshot_id is None:
            raise ValueError("result set requires source runs or a solved snapshot")
        return self


class ResultSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    scenario_id: str
    analysis_plan_id: str | None
    solved_snapshot_id: str | None
    name: str
    dimensions: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    units: dict[str, Any]
    aggregation_rules: dict[str, Any]
    source_run_ids: list[str]
    method_package_refs: list[str]
    result_hash: str
    created_at: datetime


class EvidencePackCreate(BaseModel):
    result_set_id: str
    evidence_item_ids: list[str] = Field(default_factory=list)


class EvidencePackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    result_set_id: str
    evidence_item_ids: list[str]
    lineage: dict[str, Any]
    completeness: dict[str, Any]
    content_sha256: str
    created_at: datetime
