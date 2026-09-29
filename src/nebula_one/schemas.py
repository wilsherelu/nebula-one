from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .casepacks.bindings import ParameterBindingDocument, ResolvedOperationSet


class ApplicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    application_type: str = Field(min_length=1, max_length=80)
    description: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "application_type")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    application_type: str
    description: str | None
    context: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


class SystemModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    upstream_project_id: str = Field(min_length=1, max_length=255)
    upstream_version: int = Field(gt=0)
    provider: str = "nebula_lca"

    @field_validator("name", "upstream_project_id", "provider")
    @classmethod
    def strip_model_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class InlineSystemModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_id: str = Field(min_length=1, max_length=255)
    source_version: int = Field(gt=0)
    expected_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph: dict[str, Any]
    provider: str = "nebula_lca"

    @field_validator("name", "source_id", "provider")
    @classmethod
    def strip_inline_model_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class SystemModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    name: str
    provider: str
    provider_base_url: str
    upstream_project_id: str
    upstream_version: int
    graph_sha256: str
    upstream_receipt: dict[str, Any]
    created_at: datetime


class AnalysisRunCreate(BaseModel):
    capability_key: str = Field(min_length=1, max_length=96)
    parameters: dict[str, Any] = Field(default_factory=dict)
    system_revision_id: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("capability_key", "idempotency_key")
    @classmethod
    def strip_analysis_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("analysis identity cannot be blank")
        return normalized


class AnalysisRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    system_model_id: str
    system_revision_id: str | None
    capability_key: str
    idempotency_key: str
    request_sha256: str
    parameters: dict[str, Any]
    status: str
    model_graph_sha256: str
    provider_receipt: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class OutboxEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    topic: str
    aggregate_type: str
    aggregate_id: str
    payload_sha256: str
    status: str
    attempt_count: int
    max_attempts: int
    available_at: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    last_error: dict[str, Any]
    result_ref: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class NebulaProjectSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    upstream_project_id: str = Field(min_length=1, max_length=255)
    upstream_version: int = Field(gt=0)

    @field_validator("name", "upstream_project_id")
    @classmethod
    def strip_nebula_project_source_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class ModelSourceAttachCreate(BaseModel):
    upstream_project_id: str = Field(min_length=1, max_length=255)
    upstream_version: int = Field(gt=0)

    @field_validator("upstream_project_id")
    @classmethod
    def strip_model_source_project_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class ModelSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    application_id: str
    system_model_id: str | None
    name: str
    source_type: Literal[
        "nebula_project_version", "tidas_bundle", "nebula_native_bundle"
    ]
    provider: str
    provider_base_url: str
    status: str
    file_name: str | None
    file_sha256: str | None
    upstream_project_id: str | None
    upstream_version: int | None
    graph_sha256: str | None
    import_receipt: dict[str, Any]
    candidate_versions: list[dict[str, Any]]
    external_dependencies: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    content_sha256: str
    created_at: datetime
    attached_at: datetime | None


class ModelSourcePreviewOut(BaseModel):
    schema_version: str
    source_type: Literal["tidas_bundle", "nebula_native_bundle"]
    file_name: str
    file_sha256: str
    status: Literal["ready", "blocked"]
    preview_sha256: str
    summary: dict[str, Any]
    external_dependencies: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)


class ModelSourceAttachOut(BaseModel):
    source: ModelSourceOut
    system_model: SystemModelOut
    base_revision: "SystemRevisionOut"


class SystemBindingCreate(BaseModel):
    binding_id: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=96)
    system_model_id: str = Field(min_length=1, max_length=36)
    system_revision_id: str = Field(min_length=1, max_length=36)
    solved_snapshot_id: str = Field(min_length=1, max_length=36)
    study_frame_id: str = Field(min_length=1, max_length=255)
    reporting_period_id: str = Field(min_length=1, max_length=36)
    organizational_boundary_id: str = Field(min_length=1, max_length=36)
    demand: list[dict[str, Any]] = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    status: Literal["draft", "active", "retired"] = "draft"

    @field_validator(
        "binding_id",
        "role",
        "system_model_id",
        "system_revision_id",
        "solved_snapshot_id",
        "study_frame_id",
        "reporting_period_id",
        "organizational_boundary_id",
    )
    @classmethod
    def strip_binding_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("system binding value cannot be blank")
        return normalized

    @field_validator("capabilities", "dependencies")
    @classmethod
    def normalize_binding_identifiers(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("system binding identifiers cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("system binding identifiers must be unique")
        return normalized


class SystemBindingUpdate(BaseModel):
    role: str = Field(min_length=1, max_length=96)
    system_model_id: str = Field(min_length=1, max_length=36)
    system_revision_id: str = Field(min_length=1, max_length=36)
    solved_snapshot_id: str = Field(min_length=1, max_length=36)
    study_frame_id: str = Field(min_length=1, max_length=255)
    reporting_period_id: str = Field(min_length=1, max_length=36)
    organizational_boundary_id: str = Field(min_length=1, max_length=36)
    demand: list[dict[str, Any]] = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    status: Literal["draft", "active", "retired"] = "draft"

    @field_validator(
        "role",
        "system_model_id",
        "system_revision_id",
        "solved_snapshot_id",
        "study_frame_id",
        "reporting_period_id",
        "organizational_boundary_id",
    )
    @classmethod
    def strip_binding_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("system binding value cannot be blank")
        return normalized

    @field_validator("capabilities", "dependencies")
    @classmethod
    def normalize_binding_identifiers(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("system binding identifiers cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("system binding identifiers must be unique")
        return normalized


class SystemBindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    application_id: str
    binding_id: str
    role: str
    system_model_id: str
    system_revision_id: str | None
    solved_snapshot_id: str | None
    study_frame_id: str
    reporting_period_id: str
    organizational_boundary_id: str
    demand: list[dict[str, Any]]
    capabilities: list[str]
    dependencies: list[str]
    content_sha256: str
    status: str
    created_at: datetime
    updated_at: datetime


class CasePackMaterializeCreate(BaseModel):
    expected_case_pack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_resolved_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_name: str | None = Field(default=None, min_length=1, max_length=255)
    project_key: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")

    @model_validator(mode="after")
    def require_project_identity(self):
        if (self.project_name is None) != (self.project_key is None):
            raise ValueError("project name and key must be supplied together")
        if self.project_name is not None:
            self.project_name = self.project_name.strip()
            if not self.project_name:
                raise ValueError("project name cannot be blank")
        return self


class CasePackMaterializeOut(BaseModel):
    status: Literal["created", "existing"]
    application: ApplicationOut
    system_model: "SystemModelOut"
    base_revision: "SystemRevisionOut"
    demand: list[dict[str, Any]]
    capabilities: list[str]
    blocked_capabilities: list[dict[str, str]]
    method_packages: list[dict[str, str]]
    case_pack_sha256: str
    resolved_case_sha256: str


class QueuedAnalysisRunOut(BaseModel):
    run: AnalysisRunOut
    task: OutboxEventOut


class SystemRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    system_model_id: str
    parent_revision_id: str | None
    revision_number: int
    label: str | None
    revision_kind: str
    graph_sha256: str
    content_sha256: str
    graph_snapshot: dict[str, Any]
    application_context: dict[str, Any]
    status: str
    publish_receipt: dict[str, Any]
    created_at: datetime
    published_at: datetime | None


class ModelOperationCreate(BaseModel):
    parent_revision_id: str
    operation_type: str = Field(min_length=1, max_length=96)
    payload: dict[str, Any] = Field(default_factory=dict)
    label: str | None = Field(default=None, max_length=255)

    @field_validator("parent_revision_id", "operation_type")
    @classmethod
    def strip_operation_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class ModelOperationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    system_revision_id: str
    operation_batch_id: str | None
    batch_sequence: int
    operation_type: str
    target_kind: str
    target_id: str | None
    payload: dict[str, Any]
    before_content_sha256: str
    after_content_sha256: str
    created_at: datetime


class OperationApplyOut(BaseModel):
    revision: SystemRevisionOut
    operation: ModelOperationOut


class ModelOperationItem(BaseModel):
    operation_type: str = Field(min_length=1, max_length=96)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("operation_type")
    @classmethod
    def strip_operation_type(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("operation_type cannot be blank")
        return normalized


class ModelOperationBatchCreate(BaseModel):
    parent_revision_id: str
    expected_parent_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=128)
    operations: list[ModelOperationItem] = Field(min_length=1, max_length=100)
    label: str | None = Field(default=None, max_length=255)

    @field_validator("parent_revision_id", "idempotency_key")
    @classmethod
    def strip_batch_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class OperationBatchOut(BaseModel):
    batch_id: str
    idempotency_key: str
    idempotent_replay: bool
    revision: SystemRevisionOut
    operations: list[ModelOperationOut]


class ParameterBindingApplyCreate(BaseModel):
    parent_revision_id: str = Field(min_length=1, max_length=255)
    expected_parent_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameter_set_id: str = Field(min_length=1, max_length=255)
    binding: ParameterBindingDocument
    label: str | None = Field(default=None, max_length=255)


class ParameterBindingApplyOut(BaseModel):
    resolved_operation_set: ResolvedOperationSet
    operation_batch: OperationBatchOut


class PublishRevisionRequest(BaseModel):
    confirm_upstream_write: bool = False
    compile_pts_on_save: bool = True


class PublishRevisionOut(BaseModel):
    revision_id: str
    status: str
    publish_receipt: dict[str, Any]


class ErrorEnvelope(BaseModel):
    error: dict[str, Any]
