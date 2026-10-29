from __future__ import annotations

import math
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


class MethodPackageBindingCreate(BaseModel):
    reference: str = Field(min_length=3, max_length=320)

    @field_validator("reference")
    @classmethod
    def strip_reference(cls, value: str) -> str:
        return _strip(value)


class MethodPackageBindingOut(BaseModel):
    application_id: str
    method_package_refs: list[str]


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
    claim_role: Literal["user_declared_partial_background_leaf", "user_declared_partial_background_network"] = "user_declared_partial_background_leaf"


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


class CalculationMethodRef(BaseModel):
    """An exact reference to one user calculation method version, by id + version + content hash.

    The hash is what makes the reference precise: the server re-reads the stored version and
    refuses if it no longer matches, so a calculation can never silently follow a moved head.
    """

    model_config = ConfigDict(protected_namespaces=())

    method_id: str = Field(min_length=1, max_length=36)
    version: int = Field(ge=1)
    content_sha256: str = Field(min_length=64, max_length=64)


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
    # The exact user calculation method version this solve follows, when one is used. It names a
    # persisted, validated grouping only; it never carries emission factors or a regulatory answer.
    calculation_method_ref: CalculationMethodRef | None = None

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
    # A read-side display parameter over the frozen solve. `total` re-exports the snapshot
    # unchanged; `per_reference_output` rescales every line by T*b/Q. It is never a new solve.
    result_basis: Literal["total", "per_reference_output"] = "total"
    base_amount: float | None = Field(default=None, gt=0)
    base_unit: str | None = None

    @field_validator("method_package_ref")
    @classmethod
    def strip_method_package_ref(cls, value: str) -> str:
        return _strip(value)

    @field_validator("base_amount")
    @classmethod
    def base_amount_finite(cls, value: float | None) -> float | None:
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)
                                  or not math.isfinite(float(value))):
            raise ValueError("base_amount must be a finite number greater than zero")
        return value

    @field_validator("base_unit")
    @classmethod
    def base_unit_supported(cls, value: str | None) -> str | None:
        if value is not None:
            normalized = _strip(value)
            if normalized not in ("kg", "t"):
                raise ValueError("base_unit must be a supported product mass unit (kg or t)")
            return normalized
        return value

    @model_validator(mode="after")
    def require_base_for_intensity(self) -> "ProductCarbonFootprintCreate":
        if self.result_basis == "per_reference_output":
            if self.base_amount is None or not self.base_unit:
                raise ValueError("per_reference_output requires an exact base amount and unit")
        return self


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
    result_basis: dict[str, Any] | None = None
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
    user_declared_counted_ledger: dict[str, Any] | None = None


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
    attribution: dict[str, Any]
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


class OrganizationCurrentModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    solved_snapshot_id: str = Field(min_length=1)
    method_package_ref: str = Field(min_length=3, max_length=320)


class OrganizationLifecycleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    solved_snapshot_id: str = Field(min_length=1)
    method_package_ref: str = Field(min_length=3, max_length=320)
    reporting_period_id: str = Field(min_length=1)
    facility: str = Field(min_length=1)
    controlled_process_ids: list[str] = Field(min_length=1)
    input_basis: Literal["per_unit_product", "annual_total", "current_model_total"]
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


MethodPurpose = Literal["cbam", "organization", "pcf", "custom"]
# Explicit method-version semantics. Absent keeps the legacy boundary/Scope/dimension reading.
# `flow_tag.v1` is the historical presence/pending tag scheme and stays replayable as-is;
# `result_category.v1` is a caliber whose only entry is a valid leaf category assignment.
MethodSemantics = Literal["flow_tag.v1", "result_category.v1"]
RuleDirection = Literal["input", "output", "emission", "resource"]
BoundaryStatus = Literal["selected", "excluded", "pending"]
LocationRole = Literal["onsite", "purchased_energy", "upstream_supply", "other"]
ScopeValue = Literal["scope_1", "scope_2", "scope_3"]
ClassificationBasis = Literal["user", "package", "unclassified"]
MethodStatus = Literal["draft", "ready", "retired"]
# The frozen core's single accounting-boundary decision. "inherit" means the target
# carries no override and defers to the process/method default (see the compiler); it is
# deliberately not a fourth resolved state. "include"/"exclude"/"pending" are decided.
AccountingBoundary = Literal["include", "exclude", "pending", "inherit"]


class MethodCategorySpec(BaseModel):
    """One report category declared by a method's reporting dimension.

    A category is a leaf unless it names a ``parent_id``; parents only roll their leaves up.
    ``is_leaf`` is derived from the parent link when it is omitted, so a caller that lists a
    flat category set does not have to mark every row. Ids are stable keys — renaming a
    ``name`` never renumbers the category a rule already points at.
    """

    model_config = ConfigDict(protected_namespaces=())

    id: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=255)
    name_zh: str | None = Field(default=None, max_length=255)
    name_en: str | None = Field(default=None, max_length=255)
    parent_id: str | None = Field(default=None, max_length=128)
    is_leaf: bool | None = None

    @field_validator("id", "parent_id")
    @classmethod
    def strip_required(cls, value: str | None) -> str | None:
        return _strip(value) if value is not None else None


class MethodDimensionSpec(BaseModel):
    """A user- or package-declared reporting dimension: stable id plus its category tree.

    LC-Scope 1-3 is only one such dimension; a method may instead declare, say,
    ``plant_split`` with onsite-production / purchased-energy / upstream-materials leaves.
    The generic kernel is the input-driven consumer of these definitions, so adding a
    non-Scope grouping needs no new calculation code branch.
    """

    model_config = ConfigDict(protected_namespaces=())

    id: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=255)
    source: str = Field(default="user", min_length=1, max_length=32)
    mutually_exclusive: bool = True
    requires_full_coverage: bool = False
    categories: list[MethodCategorySpec] = Field(default_factory=list)

    @field_validator("id", "source")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip(value)

    @model_validator(mode="after")
    def validate_categories(self):
        seen: set[str] = set()
        for category in self.categories:
            if category.id in seen:
                raise ValueError(f"dimension {self.id} has a duplicate category id {category.id}")
            seen.add(category.id)
        for category in self.categories:
            if category.parent_id is not None and category.parent_id not in seen:
                raise ValueError(
                    f"category {category.id} names an unknown parent {category.parent_id}"
                )
        return self


class ModelProcessingRulesRef(BaseModel):
    """The exact model-processing package a variant binds, in the shape a derivation pin reads.

    Only the three identity fields are carried: the package's own content hash is re-checked when it
    is loaded by reference, so a tampered reference never resolves to different rules.
    """

    model_config = ConfigDict(extra="forbid")

    package_id: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=64)
    content_sha256: str = Field(min_length=64, max_length=64)

    @field_validator("package_id", "version")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip(value)


class ProcessingPackageOptionOut(BaseModel):
    """One explicitly selectable processing package for a method's bound base and purpose.

    Business identity (package id + version) and the exact content hash are shown together with the
    applicability facts a user needs to choose: how this purpose handles emissions, so a variant that
    must narrow per-exchange can tell an explicit package from a template-prelimited one.
    """

    package_id: str
    version: str
    content_sha256: str
    selection_mode: str
    purpose_declared: bool
    elementary_flows_mode: str | None


class MethodCapabilityReasonOut(BaseModel):
    """Why a capability is or is not available, as a stable code plus a readable message."""

    code: str
    message: str


class CalculationMethodCapabilitiesOut(BaseModel):
    """What this method version can actually do, so the UI never asks for an unrelated package.

    ``processing_package_selection`` is true only when the method's own base and purpose can offer a
    package. A missing template binding is reported as a reason here instead of surfacing as a 409
    from a selection endpoint the reader never needed.
    """

    method_id: str
    method_name: str
    semantics: str | None
    latest_version: int | None = None
    latest_status: str | None = None
    content_sha256: str | None = None
    purpose: str
    tag_scheme: bool
    tag_grouping: bool
    # Result-category calibers are read-only groupings over a frozen pool, and a legacy tag scheme
    # can be converted into one; both need no processing package.
    result_category: bool = False
    legacy_tag_scheme: bool = False
    # A pre-caliber custom method is legacy too: its Scope/boundary rules stay readable and can be
    # converted, but are never edited in place.
    legacy_method: bool = False
    conversion_available: bool = False
    dedicated_strategy: str | None = None
    processing_package_selection: bool
    processing_package_reason: MethodCapabilityReasonOut | None = None


class TagSchemeRef(BaseModel):
    """One exact tag-scheme version, cited by identity rather than by name or latest."""

    model_config = ConfigDict(extra="forbid")

    method_id: str = Field(min_length=1, max_length=255)
    version: int = Field(ge=1)
    content_sha256: str = Field(min_length=64, max_length=64)


class TagGroupingRequest(BaseModel):
    """Group an existing frozen contribution pool by one or more exact tag-scheme versions."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1, max_length=255)
    indicator_key: str = Field(min_length=1, max_length=255)
    schemes: list[TagSchemeRef] = Field(min_length=1)
    # Separate shows each scheme on its own; intersection/union compute one deduplicated total.
    mode: Literal["separate", "intersection", "union"] = "separate"


class TagCategoryRowOut(BaseModel):
    id: str
    name: str | None = None
    parent_id: str | None = None
    is_leaf: bool
    subtotal: float | None
    unit: str | None
    term_count: int
    missing_count: int


class TagSchemeGroupingOut(BaseModel):
    scheme: dict[str, Any]
    semantics: str | None = None
    dimension: dict[str, Any]
    tag_total: dict[str, Any]
    uncategorized: dict[str, Any] = Field(default_factory=dict)
    matched: dict[str, Any] = Field(default_factory=dict)
    matched_exchange_ids: list[str] = Field(default_factory=list)
    unmatched: dict[str, Any]
    pending: dict[str, Any]
    missing: dict[str, Any]
    real_zero: dict[str, Any]
    coverage: dict[str, Any]
    # False when no flow carries a relation in this caliber; never rendered as a zero total.
    populated: bool = False
    reconciled: bool
    problems: list[dict[str, Any]] = Field(default_factory=list)


class TagGroupingOut(BaseModel):
    result_id: str | None = None
    created_at: datetime | None = None
    application_id: str
    snapshot_id: str
    snapshot_content_sha256: str
    indicator_key: str
    indicator_unit: str | None = None
    mode: str
    semantics: str
    available: bool
    reason: str | None = None
    schemes: list[TagSchemeGroupingOut] = Field(default_factory=list)
    union: dict[str, Any] | None = None
    intersection: dict[str, Any] | None = None
    overlap: dict[str, Any] = Field(default_factory=dict)
    reconciled: bool = False
    problems: list[dict[str, Any]] = Field(default_factory=list)
    content_sha256: str


class ResultCategoryConversionResolution(BaseModel):
    """One explicit mapping decision for a legacy rule the copy cannot carry as-is.

    ``category=None`` is the reader actively choosing “无”, not an unresolved default: a rule with a
    missing or invalid legacy category never becomes “无” unless it is spelled out here.
    """

    model_config = ConfigDict(extra="forbid")

    rule_index: int = Field(ge=0)
    category: str | None = Field(default=None, max_length=128)

    @field_validator("category")
    @classmethod
    def strip_category(cls, value: str | None) -> str | None:
        return _strip(value) if value is not None else None


class ResultCategoryConversionOptions(BaseModel):
    """The mapping a conversion preview and apply share; both reject the same unmapped rules."""

    model_config = ConfigDict(extra="forbid")

    source_dimension_id: str | None = Field(default=None, max_length=128)
    # Only needed when the legacy version declares no category tree: the reader names the target
    # categories explicitly instead of accepting a guessed one.
    target_dimension: MethodDimensionSpec | None = None
    resolutions: list[ResultCategoryConversionResolution] = Field(default_factory=list)


class ResultCategoryConversionRuleOut(BaseModel):
    """One legacy rule as the conversion would carry it into the new caliber."""

    rule_index: int = Field(ge=0)
    process_instance_id: str
    exchange_id: str | None = None
    flow_uuid: str | None = None
    old_category: str | None = None
    new_category: str | None = None
    outcome: Literal["assigned", "unassigned", "invalid_category"]
    needs_resolution: bool = False
    resolved: bool = False


class ResultCategoryConversionSourceDimensionOut(BaseModel):
    id: str
    name: str | None = None
    category_count: int = 0
    rule_count: int = 0


class ResultCategoryConversionPreviewOut(BaseModel):
    """What converting a legacy method version would do, counted before anything is written."""

    source_method_id: str
    source_method_name: str
    source_version: int
    source_semantics: str | None = None
    source_content_sha256: str
    source_dimensions: list[ResultCategoryConversionSourceDimensionOut] = Field(default_factory=list)
    source_dimension_id: str | None = None
    target_semantics: str
    target_dimension_id: str | None = None
    dimension: dict[str, Any] | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    rules: list[ResultCategoryConversionRuleOut] = Field(default_factory=list)
    problems: list[dict[str, Any]] = Field(default_factory=list)
    can_convert: bool
    reason: MethodCapabilityReasonOut | None = None
    mapping_sha256: str


class ResultCategoryConversionCreate(ResultCategoryConversionOptions):
    name: str = Field(min_length=1, max_length=255)
    expected_mapping_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return _strip(value)


class CalculationMethodRule(BaseModel):
    """One per-exchange classification, keyed to stable model identities, not display names.

    Schema v1 (``schema_version == 1``) expresses the three frozen-core layers through the
    legacy fields: ``boundary_status`` (selected/excluded/pending), ``scope`` (LC-Scope 1-3)
    and the ``cbam_relevant`` flag. Schema v2 rules carry them directly and independently via
    ``boundary`` (accounting scope) and ``categories`` (per-dimension contribution
    attribution). Both are persisted in the same immutable version list; the adapter in
    ``analysis.method_rule_adapter`` reconciles them so a caller always sees one shape.
    """

    process_instance_id: str = Field(min_length=1, max_length=255)
    exchange_id: str | None = Field(default=None, max_length=255)
    flow_uuid: str | None = Field(default=None, max_length=255)
    direction: RuleDirection
    boundary_status: BoundaryStatus = "pending"
    location_role: LocationRole = "other"
    scope: ScopeValue | None = None
    cbam_relevant: bool = False
    classification_basis: ClassificationBasis = "user"
    # Additive frozen-core fields; the defaults keep every pre-existing v1 rule valid, and
    # old persisted JSON (which lacks these keys) still validates without rewriting history.
    schema_version: int = Field(default=1, ge=1, le=2)
    contribution_target: str = Field(default="direct", min_length=1, max_length=64)
    boundary: AccountingBoundary | None = None
    categories: dict[str, str] = Field(default_factory=dict)
    base_method_ref: str | None = Field(default=None, max_length=255)

    @field_validator("process_instance_id")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip(value)

    @field_validator("categories")
    @classmethod
    def strip_categories(cls, value: dict[str, str]) -> dict[str, str]:
        return {str(dim): _strip(cat) for dim, cat in value.items()}

    @model_validator(mode="after")
    def validate_scope(self):
        # Inclusion and result-grouping are two independent settings: an excluded rule may retain the
        # Scope it carried so the reader can still track its original classification. Both grouping
        # kernels bucket `excluded` before any Scope, so a retained Scope never re-enters a total.
        return self


class CalculationMethodCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(min_length=1, max_length=255)
    purpose: MethodPurpose
    model_revision_id: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)
    cbam_boundary_ref: str | None = Field(default=None, max_length=255)
    rules: list[CalculationMethodRule] = Field(default_factory=list)
    # The method's own reporting dimensions. Empty keeps the legacy LC-Scope-only behavior so
    # every pre-existing method and hash is unchanged; a non-Scope grouping declares its tree here.
    reporting_dimensions: list[MethodDimensionSpec] = Field(default_factory=list)
    # The exact processing package a variant narrows against. Absent keeps the automatic official
    # selection, so every pre-existing create and its hash is unchanged.
    model_processing_rules_ref: ModelProcessingRulesRef | None = None
    # Absent keeps the legacy reading. A tag scheme declares its semantics explicitly.
    semantics: MethodSemantics | None = None

    @field_validator("name", "model_revision_id")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip(value)


class CalculationMethodRuleOut(BaseModel):
    process_instance_id: str
    exchange_id: str | None
    flow_uuid: str | None
    direction: str
    boundary_status: str
    location_role: str
    scope: str | None
    cbam_relevant: bool
    classification_basis: str
    # Additive v2 fields; defaulted so a pre-migration stored rule (which lacks them)
    # still validates into this shape without rewriting historical JSON.
    schema_version: int = 1
    contribution_target: str = "direct"
    boundary: str | None = None
    categories: dict[str, str] = Field(default_factory=dict)
    base_method_ref: str | None = None


class CalculationMethodVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    method_id: str
    version: int
    cbam_boundary_ref: str | None
    content_sha256: str | None
    status: str
    created_at: datetime
    validated_at: datetime | None
    rules: list[CalculationMethodRuleOut]
    reporting_dimensions: list[dict[str, Any]] = Field(default_factory=list)
    model_processing_rules_ref: dict[str, Any] | None = None
    semantics: str | None = None


class CalculationMethodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    application_id: str
    model_revision_id: str
    purpose: str
    name: str
    description: str | None
    origin_method_id: str | None
    origin_method_version: int | None
    origin_content_sha256: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    # Optional head facts so a list row can show what the latest version declares without a
    # per-row detail request. Detail responses keep them null when they were not computed.
    semantics: str | None = None
    latest_version: int | None = None
    latest_content_sha256: str | None = None
    latest_status: str | None = None
    category_summary: list[str] = Field(default_factory=list)


class CalculationMethodDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    method: CalculationMethodOut
    latest_version: int
    versions: list[CalculationMethodVersionOut]


class CalculationMethodSave(BaseModel):
    """A full replacement of the rule set, guarded by the version hash the editor loaded from."""

    model_config = ConfigDict(protected_namespaces=())

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)
    cbam_boundary_ref: str | None = Field(default=None, max_length=255)
    rules: list[CalculationMethodRule] = Field(default_factory=list)
    reporting_dimensions: list[MethodDimensionSpec] = Field(default_factory=list)
    # Binding a variant to an exact processing package; omitted keeps it on the automatic selection.
    model_processing_rules_ref: ModelProcessingRulesRef | None = None
    # A tag scheme always states its semantics; omitted keeps the legacy reading.
    semantics: MethodSemantics | None = None
    expected_content_sha256: str = Field(min_length=64, max_length=64)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        return _strip(value) if value is not None else None


class CalculationMethodClone(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(min_length=1, max_length=255)
    purpose: MethodPurpose
    model_revision_id: str = Field(min_length=1, max_length=255)
    # The processing binding is copied from the source version when omitted; supplying it re-binds the
    # clone to a different package, which is then validated against the target revision's base.
    model_processing_rules_ref: ModelProcessingRulesRef | None = None
    # Absent inherits the source version's semantics, so cloning a tag scheme stays one.
    semantics: MethodSemantics | None = None

    @field_validator("name", "model_revision_id")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return _strip(value)


class CalculationMethodValidationProblemOut(BaseModel):
    """One structural problem located to a rule (process/exchange) when possible."""

    code: str
    message: str
    rule_index: int | None = None
    process_instance_id: str | None = None
    exchange_id: str | None = None
    unmatched_count: int | None = None
    exchange_ids: list[str] = Field(default_factory=list)


class CalculationMethodValidationOut(BaseModel):
    """The result of validating an exact method version against its bound model revision.

    ``valid`` is True only when ``problems`` is empty; ``status`` reflects the persisted
    version state after the check (``ready`` when valid, ``draft`` when not).
    """

    model_config = ConfigDict(protected_namespaces=())

    method_id: str
    version: int
    model_revision_id: str
    content_sha256: str | None
    valid: bool
    status: str
    validated_at: datetime
    problems: list[CalculationMethodValidationProblemOut] = Field(default_factory=list)


class ClassificationSuggestedRuleOut(BaseModel):
    """The rule a confirmed suggestion would write: a boundary, a location role and a Scope.

    ``scope`` is None for a port kept pending on insufficient evidence, so applying it never invents
    a classification the evidence did not support.
    """

    model_config = ConfigDict(extra="forbid")

    boundary_status: BoundaryStatus
    location_role: LocationRole
    scope: ScopeValue | None = None


class ClassificationSuggestionOut(BaseModel):
    """One located, previewable suggestion for a single model port.

    ``status`` separates an actionable suggestion from a port the reader already decided
    (``already_classified``), one that carries no Scope by construction (``not_applicable``), and one
    kept pending for want of evidence (``pending_evidence``). ``rationale`` and ``basis`` are stable
    code strings the frontend translates; they are never a flow name, a business UUID, or a factor.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    exchange_id: str
    process_id: str | None = None
    process_name: str | None = None
    flow_name: str | None = None
    unit: str = ""
    direction: str
    status: Literal["suggested", "already_classified", "not_applicable", "pending_evidence"]
    rationale: str
    confidence: Literal["high", "medium", "insufficient", "none"]
    basis: list[str] = Field(default_factory=list)
    suggested: ClassificationSuggestedRuleOut | None = None
    current: ClassificationSuggestedRuleOut | None = None


class ClassificationEnergyPackageOut(BaseModel):
    """One bound method package that declared purchased-energy exchanges, cited by exact identity."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    package_id: str
    version: str
    content_sha256: str
    declared_energy_exchange_ids: list[str] = Field(default_factory=list)


class ClassificationSuggestionsOut(BaseModel):
    """The full preview for one method version, with the evidence source it was derived from.

    ``graph_content_sha256`` fingerprints the exact model graph the suggestions read, and
    ``energy_packages`` lists the versioned package declarations behind any Scope 2/3 choice, so a
    reader can trace a suggestion back to its source instead of trusting an opaque recommendation.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    strategy_version: str
    method_id: str
    version: int
    model_revision_id: str
    graph_content_sha256: str
    energy_packages: list[ClassificationEnergyPackageOut] = Field(default_factory=list)
    suggestions: list[ClassificationSuggestionOut] = Field(default_factory=list)
