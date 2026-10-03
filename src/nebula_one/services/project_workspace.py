"""Task-oriented editing over pinned case contracts; no solver or inferred mappings."""
from __future__ import annotations

from typing import Annotated
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..casepacks.bindings import (
    ParentRevisionSnapshot, ParameterSetSnapshot, resolve_parameter_binding,
    to_operation_batch_create,
)
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..schemas import ModelOperationBatchCreate, ModelOperationItem
from ..runtime_schemas import ProviderBackgroundProcessPin, ProviderProjectBackgroundPin
from ..model_processing_contract import PackageRef
from ..mapped_background_schemas import ProviderMappedBackgroundProcessPin
from .seed_projects import process_graph_projection
from ..models import SystemModel
from ..runtime_models import MethodPackage


class ProjectInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    revision_id: str
    expected_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    amounts: list[Annotated[float, Field(gt=0, allow_inf_nan=False)]] = Field(min_length=1)
    demand_mode: str = Field(default="explicit", pattern=r"^(explicit|reference_output)$")
    values: dict[str, Annotated[float, Field(ge=0, allow_inf_nan=False)]] = Field(default_factory=dict)
    source: str = Field(min_length=1, max_length=2000)
    background_process_pins: list[ProviderBackgroundProcessPin] | None = None
    mapped_background_process_pins: list[ProviderMappedBackgroundProcessPin] | None = None
    project_background_pins: list[ProviderProjectBackgroundPin] | None = None
    model_processing_rules_ref: PackageRef | None = None


class ProjectWorkspaceService:
    def __init__(self, container):
        self.c = container

    def _fillable_graph(self, application_id, revision_id):
        """Load the revision for an inventory-editable project, seed instance or professional return.

        A casepack template and a bare unbound return keep their own contracts, so they are refused
        here rather than opened through the generic inventory path they were never reviewed against.
        """
        application = self.c.applications.get(application_id)
        revision = self.c.system_revisions.get(revision_id)
        models = self.c.system_models.list_for_application(application_id)
        if revision.system_model_id not in {model.id for model in models}:
            raise DomainError(code="PROJECT_REVISION_MISMATCH", message="数据版本不属于当前项目。", status_code=409)
        if not (application.context.get('seed_template') or self._fillable_without_casepack(application.context)):
            raise DomainError(code='PROJECT_BACKGROUND_NOT_APPROVED', message='该模板尚未开放背景关联。', status_code=422)
        return application, revision

    def _contract(self, application_id, revision_id):
        application = self.c.applications.get(application_id)
        revision = self.c.system_revisions.get(revision_id)
        models = self.c.system_models.list_for_application(application_id)
        if revision.system_model_id not in {model.id for model in models}:
            raise DomainError(code="PROJECT_REVISION_MISMATCH", message="数据版本不属于当前项目。", status_code=409)
        context = application.context
        if context.get('seed_template'):
            template = context['seed_template']
            return application, revision, SimpleNamespace(demand=template['demand'], capabilities=template['capabilities'], blocked_capabilities=[]), None
        if not context.get("case_pack_id"):
            raise DomainError(code="PROJECT_TEMPLATE_UNAVAILABLE", message="该模型尚未绑定可填报模板。请从工艺模板新建项目；现有结果仍可查看。", status_code=422)
        loaded = self.c.casepacks.load_exact(context["case_pack_id"], context["case_pack_version"])
        if loaded.receipt.case_pack_sha256 != context["case_pack_sha256"]:
            raise DomainError(code="PROJECT_TEMPLATE_CHANGED", message="模板内容与项目保存的版本不一致。", status_code=409)
        case = self.c.casepack_materialization._application_case(loaded, context["application_case_id"], context["application_case_version"])
        from ..casepacks.runs import resolve_case
        resolved = resolve_case(loaded, context["application_case_id"])
        if resolved.content_sha256 != context["resolved_case_sha256"]:
            raise DomainError(code="PROJECT_TEMPLATE_CHANGED", message="模板解析内容已改变。", status_code=409)
        ref = case.scenario.parameter_binding_ref
        binding = next((item for item in loaded.parameter_bindings if ref and item.parameter_binding.id == ref.id and item.parameter_binding.version == ref.version), None)
        return application, revision, resolved, binding

    @staticmethod
    def _fields(revision, binding):
        fields = []
        for item in binding.bindings if binding else []:
            # Other binding operations need their own data-entry contract.
            if item.operation != "set_exchange_amount":
                raise DomainError(code="PROJECT_BINDING_UNSUPPORTED", message="模板包含尚未支持填报的参数操作。", status_code=422)
            target = item.target
            node = next((n for n in revision.graph_snapshot.get("nodes", []) if n["id"] == target.process_id), None)
            port = next((p for group in ("inputs", "outputs", "emissions") for p in (node or {}).get(group, []) if p["id"] == target.port_id), None)
            if port is None:
                raise DomainError(code="PROJECT_FIELD_TARGET_MISSING", message="模板字段对应的生产环节已缺失。", status_code=409)
            fields.append({"key": item.parameter_key, "label": port.get("name") or target.port_id,
                           "process": node.get("name") or target.process_id,
                           "unit": item.parameter_unit_identity.unit, "value": port.get("amount"),
                           "unit_identity": item.parameter_unit_identity.model_dump(mode="json")})
        return fields

    def read(self, application_id, revision_id, language="zh"):
        result = self._read_workspace(application_id, revision_id, language)
        revision = self.c.system_revisions.get(revision_id)
        context = revision.application_context
        refs = context.get("method_package_refs") or []
        with self.c.database.session() as db:
            model = db.get(SystemModel, revision.system_model_id)
            methods = [dict(reference=f"{item.package_id}@{item.version}", content_sha256=item.content_sha256)
                       for item in db.scalars(select(MethodPackage)) if f"{item.package_id}@{item.version}" in refs]
            result["frozen_identity"] = {
                "schema_version": "nebula_one.project-revision-identity.v1",
                "graph_sha256": revision.graph_sha256,
                "source_model": {"project_id": model.upstream_project_id, "version": model.upstream_version,
                                 "graph_sha256": model.graph_sha256, "upstream_receipt": model.upstream_receipt},
                "template": context.get("seed_template") or context.get("modeling_template_binding"),
                "method_packages": methods,
            }
        return result

    def _read_workspace(self, application_id, revision_id, language="zh"):
        if self._is_returned(application_id):
            application, revision = self._fillable_graph(application_id, revision_id)
            from .returned_projects import ReturnedProjectService
            return ReturnedProjectService(self.c).read(application, revision, language)
        application, revision, resolved, binding = self._contract(application_id, revision_id)
        if application.context.get('seed_template'):
            from .seed_projects import SeedProjectService
            return SeedProjectService(self.c).read(application, revision, language=language)
        inputs = revision.application_context.get("project_inputs", {})
        demand = inputs.get("demand", list(resolved.demand))
        return {
            "application_id": application_id, "revision_id": revision.id,
            "content_sha256": revision.content_sha256,
            "template_title": application.description,
            "fields": self._fields(revision, binding), "demand": demand,
            "process_graph": process_graph_projection(revision.graph_snapshot),
            "source": inputs.get("source", "模板示例值（未经实测）"),
            "saved": bool(inputs), "capabilities": list(resolved.capabilities),
            "blocked_capabilities": list(resolved.blocked_capabilities),
            "background_options": [],
            "background_note": "此模板未提供经过兼容性审查的背景过程候选，当前沿用模板数据。需要更换电力或原料数据时，先在专业建模中绑定精确数据版本。",
        }

    @staticmethod
    def _fillable_without_casepack(context):
        # A model returned from professional modelling is filled through the generic inventory
        # contract, not a casepack or a seed instance; lineage alone does not unlock it, so the
        # reviewed template binding and the locked-template flag must both be present.
        return bool(context.get("modeling_template_binding") and context.get("template_locked"))

    def _is_returned(self, application_id):
        return self._fillable_without_casepack(self.c.applications.get(application_id).context)

    def save(self, application_id, payload: ProjectInputs, language="zh"):
        saved = self._save_workspace(application_id, payload, language)
        return self.read(application_id, saved["revision_id"], language)

    def _save_workspace(self, application_id, payload: ProjectInputs, language="zh"):
        if self._is_returned(application_id):
            from .returned_projects import ReturnedProjectService
            application, parent = self._fillable_graph(application_id, payload.revision_id)
            return ReturnedProjectService(self.c).save(application, parent, payload, language)
        application, parent, resolved, binding = self._contract(application_id, payload.revision_id)
        if not application.context.get("template_locked"):
            raise DomainError(code="PROJECT_INSTANCE_REQUIRED", message="示例只供查看，请从模板创建自己的项目。", status_code=409)
        if application.context.get('seed_template'):
            from .seed_projects import SeedProjectService
            return SeedProjectService(self.c).save(application, parent, payload, language)
        if payload.background_process_pins or payload.mapped_background_process_pins or payload.project_background_pins:
            raise DomainError(code='PROJECT_BACKGROUND_NOT_APPROVED', message='该模板尚未开放背景关联。', status_code=422)
        if parent.content_sha256 != payload.expected_content_sha256:
            raise DomainError(code="PROJECT_INPUT_CONFLICT", message="数据版本已改变，请重新加载后保存。", status_code=409)
        fields = self._fields(parent, binding)
        if set(payload.values) != {item["key"] for item in fields}:
            raise DomainError(code="PROJECT_FIELDS_INVALID", message="填报字段与模板声明不一致。", status_code=422)
        if len(payload.amounts) != len(resolved.demand) or not payload.source.strip():
            raise DomainError(code="PROJECT_INPUT_INVALID", message="请完整填写核算规模和数据来源。", status_code=422)
        demand = [{**item, "amount": amount} for item, amount in zip(resolved.demand, payload.amounts)]
        data = {"demand": demand, "values": payload.values, "source": payload.source.strip()}
        operations = []
        if binding:
            values = {item["key"]: {"value": payload.values[item["key"]], "quantity_kind": "amount", "unit_identity": item["unit_identity"]} for item in fields}
            metadata = {"source": data["source"], "claim_level": "user_declared"}
            digest = canonical_json_sha256({"values": values, "metadata": metadata})
            snapshot = ParameterSetSnapshot(schema_version="nebula.parameter-set.snapshot.v1", parameter_set_id=f"project-input:{digest}", status="frozen", content_sha256=digest, values=values, metadata=metadata)
            result = resolve_parameter_binding(binding, snapshot, ParentRevisionSnapshot(revision_id=parent.id, content_sha256=parent.content_sha256, graph=parent.graph_snapshot))
            operations.extend(to_operation_batch_create(result).operations)
            data["parameter_snapshot"] = snapshot.model_dump(mode="json")
        operations.append(ModelOperationItem(operation_type="system.merge_context", payload={"context": {"project_inputs": data}}))
        batch = ModelOperationBatchCreate(parent_revision_id=parent.id, expected_parent_content_sha256=parent.content_sha256,
            idempotency_key="project-input:" + canonical_json_sha256({"parent": parent.id, "data": data}),
            operations=operations, label="生产数据")
        _, revision, _, _ = self.c.system_revisions.apply_batch(parent.system_model_id, batch, template_input=True)
        return self.read(application_id, revision.id, language)
