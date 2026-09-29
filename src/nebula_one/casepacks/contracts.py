from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..hashing import canonical_json_sha256


SHA256_PATTERN = r"^[0-9a-f]{64}$"
IDENTIFIER_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"
VERSION_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$"
CAPABILITY_PATTERN = r"^[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+$"


def _non_blank(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value cannot be blank")
    return normalized


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VersionedIdentity(StrictContract):
    id: str = Field(pattern=IDENTIFIER_PATTERN)
    version: str = Field(pattern=VERSION_PATTERN)
    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        return _non_blank(value)


class CasePackIdentity(VersionedIdentity):
    lifecycle_status: Literal["draft", "executable"]
    claim_level: Literal[
        "demonstration",
        "research_reference",
        "business_assurance",
    ]


class EnginePin(StrictContract):
    provider: Literal["nebula-lca"]
    api_contract: Literal["provider.v1"]
    project_id: str = Field(min_length=1, max_length=255)
    version: int = Field(gt=0)
    expected_graph_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("project_id")
    @classmethod
    def strip_project_id(cls, value: str) -> str:
        return _non_blank(value)


class InlineEnginePin(StrictContract):
    provider: Literal["nebula-lca"]
    api_contract: Literal["provider.v1"]
    snapshot_path: str = Field(min_length=1, max_length=512)
    source_id: str = Field(min_length=1, max_length=255)
    source_version: int = Field(gt=0)
    expected_graph_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("snapshot_path", "source_id")
    @classmethod
    def strip_inline_pin_text(cls, value: str) -> str:
        return _non_blank(value)


class SharedReleases(StrictContract):
    foreground_data: str | None = Field(default=None, max_length=255)
    entity_registry: str | None = Field(default=None, max_length=255)
    evidence_index: str | None = Field(default=None, max_length=255)

    @field_validator("foreground_data", "entity_registry", "evidence_index")
    @classmethod
    def strip_optional_release(cls, value: str | None) -> str | None:
        return _non_blank(value) if value is not None else None

    def missing_release_names(self) -> list[str]:
        return [
            name
            for name in ("foreground_data", "entity_registry", "evidence_index")
            if getattr(self, name) is None
        ]


class LicenseManifestRef(StrictContract):
    manifest: str = Field(min_length=1, max_length=512)

    @field_validator("manifest")
    @classmethod
    def strip_manifest(cls, value: str) -> str:
        return _non_blank(value)


class VersionedDocumentRef(StrictContract):
    path: str = Field(min_length=1, max_length=512)
    id: str = Field(pattern=IDENTIFIER_PATTERN)
    version: str = Field(pattern=VERSION_PATTERN)

    @field_validator("path")
    @classmethod
    def strip_path(cls, value: str) -> str:
        return _non_blank(value)


class CasePackShowcaseModule(StrictContract):
    key: str = Field(pattern=IDENTIFIER_PATTERN)
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=320)
    application_case_id: str = Field(pattern=IDENTIFIER_PATTERN)
    capability_keys: tuple[str, ...] = Field(min_length=1)

    @field_validator("title", "description")
    @classmethod
    def strip_showcase_text(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("capability_keys")
    @classmethod
    def validate_showcase_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_non_blank(value) for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("showcase capability_keys must be unique")
        if any(re.fullmatch(CAPABILITY_PATTERN, value) is None for value in normalized):
            raise ValueError("showcase capability_keys contain an invalid key")
        return normalized


class CasePackShowcase(StrictContract):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=600)
    modules: tuple[CasePackShowcaseModule, ...] = Field(min_length=1)

    @field_validator("title", "description")
    @classmethod
    def strip_showcase_copy(cls, value: str) -> str:
        return _non_blank(value)

    @model_validator(mode="after")
    def validate_showcase_modules(self):
        keys = [item.key for item in self.modules]
        if len(keys) != len(set(keys)):
            raise ValueError("showcase module keys must be unique")
        return self


class CasePackDocument(StrictContract):
    schema_version: Literal["nebula.casepack.v1"]
    case_pack: CasePackIdentity
    engine: EnginePin | InlineEnginePin | None
    shared_releases: SharedReleases
    licenses: LicenseManifestRef
    supporting_file_refs: tuple[str, ...] = ()
    application_case_refs: tuple[VersionedDocumentRef, ...] = Field(min_length=1)
    showcase: CasePackShowcase | None = None

    @field_validator("supporting_file_refs")
    @classmethod
    def validate_supporting_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_non_blank(value) for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("supporting_file_refs must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_application_refs(self):
        paths = [item.path for item in self.application_case_refs]
        identities = [(item.id, item.version) for item in self.application_case_refs]
        if len(paths) != len(set(paths)):
            raise ValueError("application_case_refs paths must be unique")
        if len(identities) != len(set(identities)):
            raise ValueError("application_case_refs identities must be unique")
        if self.showcase is not None:
            application_ids = {item.id for item in self.application_case_refs}
            missing = sorted(
                {
                    item.application_case_id
                    for item in self.showcase.modules
                    if item.application_case_id not in application_ids
                }
            )
            if missing:
                raise ValueError(
                    "showcase modules reference unknown application cases: "
                    + ", ".join(missing)
                )
        return self

    @model_validator(mode="after")
    def enforce_executable_pins(self):
        if self.case_pack.lifecycle_status != "executable":
            return self
        missing: list[str] = []
        if self.engine is None:
            missing.append("engine")
        missing.extend(
            f"shared_releases.{name}"
            for name in self.shared_releases.missing_release_names()
        )
        if missing:
            raise ValueError(
                "executable CasePack requires exact pins: " + ", ".join(missing)
            )
        return self


class DemandItem(StrictContract):
    flow_source_namespace: str = Field(min_length=1, max_length=255)
    reference_flow_uuid: str = Field(min_length=1, max_length=255)
    reference_flow_version: str = Field(min_length=1, max_length=128)
    reference_exchange_id: str | None = Field(default=None, max_length=255)
    amount: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=128)
    unit_group_source_namespace: str = Field(min_length=1, max_length=255)
    unit_group_uuid: str = Field(min_length=1, max_length=255)
    unit_group_version: str = Field(min_length=1, max_length=128)

    @field_validator(
        "flow_source_namespace",
        "reference_flow_uuid",
        "reference_flow_version",
        "reference_exchange_id",
        "unit",
        "unit_group_source_namespace",
        "unit_group_uuid",
        "unit_group_version",
    )
    @classmethod
    def strip_demand_text(cls, value: str | None) -> str | None:
        return _non_blank(value) if value is not None else None

    @field_validator("amount")
    @classmethod
    def require_finite_amount(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("amount must be finite")
        return value


class DemandDefinitionDocument(StrictContract):
    schema_version: Literal["nebula.demand-definition.v1"]
    demand_definition: VersionedIdentity
    demand_type: Literal[
        "single_reference_product",
        "scaled_reference_product",
        "annual_production",
        "portfolio_demand",
        "project_lifetime_demand",
    ]
    execution_status: Literal["supported", "planned"]
    demands: tuple[DemandItem, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_demand_shape_and_status(self):
        if self.demand_type in {
            "single_reference_product",
            "scaled_reference_product",
            "annual_production",
        } and len(self.demands) != 1:
            raise ValueError(f"{self.demand_type} requires exactly one demand item")
        supported = {
            "single_reference_product",
            "scaled_reference_product",
            "annual_production",
        }
        expected_status = "supported" if self.demand_type in supported else "planned"
        if self.execution_status != expected_status:
            raise ValueError(
                f"{self.demand_type} execution_status must be {expected_status} in v0.4a"
            )
        return self


class StudyFrameIdentity(VersionedIdentity):
    lifecycle_status: Literal["draft", "frozen"]


class ReportingPeriodIdentity(VersionedIdentity):
    lifecycle_status: Literal["frozen"]


class ReportingPeriodDocument(StrictContract):
    schema_version: Literal["nebula.reporting-period.v1"]
    reporting_period: ReportingPeriodIdentity
    period_kind: Literal["representative_year"]
    start_date: date
    end_date: date
    claim_level: Literal["demonstration", "measured"]

    @model_validator(mode="after")
    def validate_period_order(self):
        if self.end_date < self.start_date:
            raise ValueError("reporting period end_date cannot precede start_date")
        return self


class StudyFrameDocument(StrictContract):
    schema_version: Literal["nebula.study-frame.v1"]
    study_frame: StudyFrameIdentity
    base_revision_ref: str
    calculation_boundary_ref: str
    reporting_boundary_ref: str
    demand_definition_ref: VersionedDocumentRef
    reporting_period_ref: VersionedDocumentRef
    entity_scope_ref: str
    inventory_snapshot_ref: str | None = None
    provider_contract_version: Literal["provider.v1"]
    data_release_ref: str | None = None

    @field_validator(
        "base_revision_ref",
        "calculation_boundary_ref",
        "reporting_boundary_ref",
        "entity_scope_ref",
        "inventory_snapshot_ref",
        "data_release_ref",
    )
    @classmethod
    def strip_study_ref(cls, value: str | None) -> str | None:
        return _non_blank(value) if value is not None else None

    @model_validator(mode="after")
    def enforce_frozen_inputs(self):
        if self.study_frame.lifecycle_status == "frozen" and self.data_release_ref is None:
            raise ValueError("frozen StudyFrame requires data_release_ref")
        return self


class ApplicationCaseIdentity(VersionedIdentity):
    case_type: Literal["golden", "integration", "assurance"]
    lifecycle_status: Literal["draft", "executable"]


class ScenarioBinding(StrictContract):
    parameter_set_refs: tuple[VersionedDocumentRef, ...] = ()
    parameter_binding_ref: VersionedDocumentRef | None = None

    @model_validator(mode="after")
    def validate_parameter_refs(self):
        identities = [
            (item.path, item.id, item.version) for item in self.parameter_set_refs
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("parameter_set_refs must be unique")
        if self.parameter_set_refs and self.parameter_binding_ref is None:
            raise ValueError("parameter_set_refs require parameter_binding_ref")
        return self


class AnalysisPlan(StrictContract):
    capabilities: tuple[str, ...] = Field(min_length=1)
    method_package_refs: tuple[VersionedDocumentRef, ...] = ()

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_non_blank(value) for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("capabilities must be unique")
        for value in normalized:
            if re.fullmatch(CAPABILITY_PATTERN, value) is None:
                raise ValueError(f"invalid capability key: {value}")
        return normalized

    @model_validator(mode="after")
    def validate_method_package_refs(self):
        identities = [
            (item.path, item.id, item.version) for item in self.method_package_refs
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("method_package_refs must be unique")
        return self


class ApplicationCaseDocument(StrictContract):
    schema_version: Literal["nebula.application-case.v1"]
    application_case: ApplicationCaseIdentity
    study_frame: StudyFrameDocument
    scenario: ScenarioBinding
    analysis_plan: AnalysisPlan

    @model_validator(mode="after")
    def enforce_executable_study_frame(self):
        if (
            self.application_case.lifecycle_status == "executable"
            and self.study_frame.study_frame.lifecycle_status != "frozen"
        ):
            raise ValueError("executable ApplicationCase requires a frozen StudyFrame")
        return self


ContractDocument = (
    CasePackDocument
    | ApplicationCaseDocument
    | StudyFrameDocument
    | DemandDefinitionDocument
)


def canonical_contract_sha256(document: BaseModel) -> str:
    return canonical_json_sha256(document.model_dump(mode="json", exclude_none=False))


def parse_casepack(payload: Any) -> CasePackDocument:
    return CasePackDocument.model_validate(payload)


def parse_application_case(payload: Any) -> ApplicationCaseDocument:
    return ApplicationCaseDocument.model_validate(payload)


def parse_study_frame(payload: Any) -> StudyFrameDocument:
    return StudyFrameDocument.model_validate(payload)


def parse_demand_definition(payload: Any) -> DemandDefinitionDocument:
    return DemandDefinitionDocument.model_validate(payload)


def parse_reporting_period(payload: Any) -> ReportingPeriodDocument:
    return ReportingPeriodDocument.model_validate(payload)


def contract_json_schemas() -> dict[str, dict[str, Any]]:
    from .bindings import (
        CaseParameterSetDocument,
        ParameterBindingDocument,
        ResolvedOperationSet,
    )
    from .licenses import LicenseManifestDocument
    from .provider_candidates import ProviderCandidateManifest
    from .physical_properties import (
        PhysicalPropertySetDocument,
        PublishedPhysicalPropertySourceRecord,
    )
    from .quantity_conversions import QuantityConversionReceipt
    from .runs import CaseRunManifest, ResolvedCase
    from .spatial import EntityRegistryDocument
    from ..analysis.energy_carrier import EnergyCarrierSolved
    from ..analysis.energy_scenarios import EnergyScenarioComparison
    from ..runtime_schemas import (
        CarbonManagementOut,
        CbamComplexTrialOut,
        CbamTrialOut,
        PeriodEnergyComparisonOut,
        PeriodEnergyTrendOut,
        PeriodEnergyTotalOut,
        ProvinceElectricityOut,
        EnergyFlowOut,
        WaterBalanceOut,
        SpatialAggregateOut,
        SpatialDistributionOut,
        SpatialEnergyOut,
        SpatialEnergyFlowOut,
    )

    models: dict[str, type[BaseModel]] = {
        "nebula.casepack.v1.schema.json": CasePackDocument,
        "nebula.application-case.v1.schema.json": ApplicationCaseDocument,
        "nebula.study-frame.v1.schema.json": StudyFrameDocument,
        "nebula.demand-definition.v1.schema.json": DemandDefinitionDocument,
        "nebula.reporting-period.v1.schema.json": ReportingPeriodDocument,
        "nebula.parameter-binding.v1.schema.json": ParameterBindingDocument,
        "nebula.case-parameter-set.v1.schema.json": CaseParameterSetDocument,
        "nebula.resolved-operation-set.v1.schema.json": ResolvedOperationSet,
        "nebula.casepack-licenses.v1.schema.json": LicenseManifestDocument,
        "nebula.provider-candidate-manifest.v1.schema.json": ProviderCandidateManifest,
        "nebula.physical-property-set.v1.schema.json": PhysicalPropertySetDocument,
        "nebula.published-physical-property-source.v1.schema.json": (
            PublishedPhysicalPropertySourceRecord
        ),
        "nebula.quantity-conversion-receipt.v1.schema.json": QuantityConversionReceipt,
        "nebula.energy.carrier.solved.v1.schema.json": EnergyCarrierSolved,
        "nebula.energy-scenario-comparison.v1.schema.json": EnergyScenarioComparison,
        "nebula-one.carbon-management.v1.schema.json": CarbonManagementOut,
        "nebula-one.cbam-complex-trial.v1.schema.json": CbamComplexTrialOut,
        "nebula-one.cbam-trial.v1.schema.json": CbamTrialOut,
        "nebula-one.period-energy-scenario-comparison.v1.schema.json": (
            PeriodEnergyComparisonOut
        ),
        "nebula-one.period-energy-trend.v1.schema.json": PeriodEnergyTrendOut,
        "nebula-one.period-energy-total.v1.schema.json": PeriodEnergyTotalOut,
        "nebula-one.province-electricity-scenario.v1.schema.json": (
            ProvinceElectricityOut
        ),
        "nebula-one.energy-flow.solved.v1.schema.json": EnergyFlowOut,
        "nebula-one.water-balance.solved.v1.schema.json": WaterBalanceOut,
        "nebula.entity-registry.v2.schema.json": EntityRegistryDocument,
        "nebula-one.spatial-aggregate.v1.schema.json": SpatialAggregateOut,
        "nebula-one.spatial-energy.v1.schema.json": SpatialEnergyOut,
        "nebula-one.spatial-energy-flow.v1.schema.json": SpatialEnergyFlowOut,
        "nebula-one.spatial-distribution.v1.schema.json": SpatialDistributionOut,
        "nebula.resolved-case.v1.schema.json": ResolvedCase,
        "nebula.case-run-manifest.v1.schema.json": CaseRunManifest,
    }
    return {
        filename: model.model_json_schema(
            ref_template=f"{filename}#/$defs/{{model}}",
            mode="validation",
        )
        for filename, model in models.items()
    }
