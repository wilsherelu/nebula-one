"""Finalize a reviewed LCA return as an immutable template for new projects."""
from copy import deepcopy
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..adapters.nebula_lca import same_pinned_model
from ..errors import DomainError
from ..hashing import canonical_content_sha256, canonical_json_sha256
from ..models import Application, AuthoredProjectTemplate, SystemModel, SystemRevision, new_id, utcnow
from ..runtime_models import BoundaryDefinition, MethodPackage, Period
from .returned_projects import reference_demand
from .seed_projects import BOUNDARY_FIELDS, inventory_fields, process_graph_projection
from ..runtime_schemas import CalculationMethodRef
from .template_calculation_methods import freeze_defaults, instantiate_defaults


class MethodPin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PublishAuthoredTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=32)
    source_application_id: str = Field(min_length=1)
    source_model_id: str = Field(min_length=1)
    source_revision_id: str = Field(min_length=1)
    expected_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    methods: list[MethodPin] = Field(default_factory=list)
    user_methods: list[CalculationMethodRef] = Field(default_factory=list)


class CreateAuthoredProject(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    project_key: UUID
    expected_template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def refuse(code, message, status=409):
    raise DomainError(code=code, message=message, status_code=status)


class AuthoredProjectTemplateService:
    def __init__(self, container):
        self.c = container

    @staticmethod
    def _catalog_item(row, graph):
        return {"id": row.id, "title": row.title, "version": row.version,
                "template_sha256": row.content_sha256, "seed_id": "",
                "installed_application_id": row.source_application_id,
                "source_application_id": row.source_application_id,
                "source_model_id": row.source_model_id,
                "source_revision_id": row.source_revision_id,
                "process_count": len(graph.get("nodes", [])),
                "field_count": len(inventory_fields(graph)),
                "capabilities": row.content["capabilities"], "kind": "authored",
                "user_method_count": len(row.content.get("user_methods", []))}

    def catalog(self):
        with self.c.database.session() as db:
            return [self._catalog_item(row, db.get(SystemRevision, row.source_revision_id).graph_snapshot)
                    for row in db.scalars(select(AuthoredProjectTemplate).order_by(AuthoredProjectTemplate.created_at))]

    def publish(self, payload: PublishAuthoredTemplate):
        # Installed seeds are also verified modelling sources; preserve their exact catalog identity.
        from .seed_projects import SeedProjectService
        seed_sources = SeedProjectService(self.c).catalog()["items"]
        installed_item = next((item for item in seed_sources if item["source_application_id"] == payload.source_application_id
            and item["source_model_id"] == payload.source_model_id
            and item["source_revision_id"] == payload.source_revision_id), None)
        installed_source = installed_item is not None
        with self.c.database.session() as db:
            app = db.get(Application, payload.source_application_id)
            model = db.get(SystemModel, payload.source_model_id)
            revision = db.get(SystemRevision, payload.source_revision_id)
            if (not app or not model or not revision or model.application_id != app.id
                    or revision.system_model_id != model.id or revision.revision_kind != "base"
                    or revision.content_sha256 != payload.expected_revision_sha256
                    or not (installed_source or (app.context.get("modeling_template_binding")
                                                and app.context.get("template_locked")))):
                refuse("TEMPLATE_SOURCE_NOT_REVIEWED", "请选择已核验的 LCA 返回模型基础版本。", 422)
            if model.provider_base_url != self.c.client.base_url:
                refuse("TEMPLATE_ENGINE_CHANGED", "模型所属算法服务与当前连接不一致。")
            upstream_source = model
            if installed_source:
                _, upstream_source, _, _, checked_item, _ = SeedProjectService(self.c)._source(db, installed_item["id"])
                if checked_item["template_sha256"] != installed_item["template_sha256"]:
                    refuse("TEMPLATE_SOURCE_CHANGED", "模板来源已变化，请重新选择。")
            exact = self.c.client.get_provider_model_snapshot(upstream_source.upstream_project_id, upstream_source.upstream_version).payload
            if ((not installed_source and exact["graph_hash"] != (model.upstream_receipt or {}).get("upstream_graph_hash"))
                    or not same_pinned_model(upstream_source.graph_snapshot if installed_source else revision.graph_snapshot, exact["graph"])):
                refuse("TEMPLATE_MODEL_CHANGED", "上游精确模型版本与定稿来源不一致。")
            if installed_source:
                from types import SimpleNamespace
                demand = reference_demand(SimpleNamespace(context={
                    **app.context, "modeling_functional_unit": exact["functional_unit"]}), revision)
            else:
                demand = reference_demand(app, revision)
            available = set(app.context.get("method_package_refs") or [])
            pins = []
            selected_kinds = set()
            for pin in payload.methods:
                ref = f"{pin.package_id}@{pin.version}"
                package = db.scalar(select(MethodPackage).where(
                    MethodPackage.package_id == pin.package_id, MethodPackage.version == pin.version))
                if ref not in available or package is None or package.content_sha256 != pin.content_sha256:
                    refuse("TEMPLATE_METHOD_NOT_PINNED", "方法包不属于该模型或内容哈希不匹配。", 422)
                pins.append(pin.model_dump())
                selected_kinds.add(package.package_kind)
            if len({(pin["package_id"], pin["version"]) for pin in pins}) != len(pins):
                refuse("TEMPLATE_METHOD_DUPLICATE", "同一方法版本不能重复选择。", 422)
            user_methods = freeze_defaults(db, app.id, revision.id, payload.user_methods)
            context = deepcopy(app.context)
            if installed_source:
                context["modeling_functional_unit"] = deepcopy(exact["functional_unit"])
            context.pop("project_inputs", None)
            context.pop("project_create_sha256", None)
            context.pop("resource_purpose", None)
            context.pop("modeling_handoff_id", None)
            context["method_package_refs"] = [f"{pin['package_id']}@{pin['version']}" for pin in pins]
            # PCF uses the engine's versioned LCIA climate method, independently of
            # optional regulatory and organization grouping packages.
            capabilities = ["mfa.solved.v1", "pcf.product.v1"]
            for kind, capability in (("product_carbon_footprint", "pcf.product.v1"),
                                     ("cbam_trial", "cbam.trial.v2"),
                                     ("cbam_partial_review", "cbam.trial.v2"),
                                     ("organization_lifecycle_carbon", "organization.lifecycle-carbon.v1")):
                if kind in selected_kinds and capability not in capabilities:
                    capabilities.append(capability)
            context["project_capabilities"] = capabilities
            content = {"title": payload.title, "version": payload.version,
                       "source_application_id": app.id, "source_model_id": model.id,
                       "source_revision_id": revision.id,
                       "source_revision_sha256": revision.content_sha256,
                       "engine_project_id": upstream_source.upstream_project_id,
                       "engine_version": upstream_source.upstream_version,
                       "engine_graph_hash": exact["graph_hash"],
                       "model_graph_sha256": model.graph_sha256,
                       "methods": pins, "demand": demand, "context": context,
                       "capabilities": capabilities}
            if user_methods:
                content["user_methods"] = user_methods
            if installed_source:
                content["upstream_graph_snapshot"] = deepcopy(upstream_source.graph_snapshot)
                content["installed_template_sha256"] = installed_item["template_sha256"]
            digest = canonical_json_sha256(content)
            existing = db.scalar(select(AuthoredProjectTemplate).where(
                AuthoredProjectTemplate.title == payload.title, AuthoredProjectTemplate.version == payload.version))
            if existing:
                if existing.content_sha256 != digest:
                    refuse("TEMPLATE_VERSION_CONFLICT", "同名模板版本已绑定不同模型或方法。")
                return self._catalog_item(existing, revision.graph_snapshot)
            row = AuthoredProjectTemplate(title=payload.title, version=payload.version,
                source_application_id=app.id, source_model_id=model.id,
                source_revision_id=revision.id, content=content, content_sha256=digest)
            db.add(row)
            db.commit()
            return self._catalog_item(row, revision.graph_snapshot)

    def create(self, template_id: str, payload: CreateAuthoredProject):
        with self.c.database.session() as db:
            row = db.get(AuthoredProjectTemplate, template_id)
            if row is None:
                refuse("TEMPLATE_NOT_FOUND", "模板版本不存在。", 404)
            if row.content_sha256 != payload.expected_template_sha256:
                refuse("TEMPLATE_VERSION_CHANGED", "模板内容与创建请求不一致。")
            source = db.get(SystemModel, row.source_model_id)
            revision = db.get(SystemRevision, row.source_revision_id)
            pin = row.content
            if (source is None or revision is None or source.application_id != row.source_application_id
                    or revision.system_model_id != source.id
                    or revision.content_sha256 != pin["source_revision_sha256"]
                    or source.graph_sha256 != pin["model_graph_sha256"]):
                refuse("TEMPLATE_SOURCE_CHANGED", "模板来源模型身份已改变。")
            for method_pin in pin["methods"]:
                package = db.scalar(select(MethodPackage).where(
                    MethodPackage.package_id == method_pin["package_id"],
                    MethodPackage.version == method_pin["version"]))
                if package is None or package.content_sha256 != method_pin["content_sha256"]:
                    refuse("TEMPLATE_METHOD_CHANGED", "定稿方法包的内容身份已改变。")
            app_id = str(uuid5(NAMESPACE_URL, f"nebula-one:authored-project:{row.id}:{payload.project_key}"))
            request_hash = canonical_json_sha256(payload.model_dump(mode="json"))
            existing = db.get(Application, app_id)
            if existing:
                if existing.context.get("project_create_sha256") != request_hash:
                    refuse("TEMPLATE_PROJECT_KEY_CONFLICT", "创建键已用于另一项目。")
                existing_model = db.scalar(select(SystemModel).where(SystemModel.application_id == app_id))
                return {"application_id": app_id, "system_model_id": existing_model.id,
                        "revision_id": existing_model.upstream_receipt["base_revision_id"]}
            exact = self.c.client.get_provider_model_snapshot(pin["engine_project_id"], pin["engine_version"]).payload
            if exact["graph_hash"] != pin["engine_graph_hash"] or not same_pinned_model(pin.get("upstream_graph_snapshot", revision.graph_snapshot), exact["graph"]):
                refuse("TEMPLATE_MODEL_CHANGED", "算法服务的定稿模型版本不再匹配。")
            graph = deepcopy(revision.graph_snapshot)
            model_id, revision_id = new_id(), new_id()
            context = deepcopy(pin["context"])
            context["template_locked"] = True
            context["authored_template"] = {"id": row.id, "title": row.title,
                                            "version": row.version, "content_sha256": row.content_sha256}
            context["project_create_sha256"] = request_hash
            app = Application(id=app_id, name=payload.name, application_type="system_analysis",
                              description=row.title, context=context)
            receipt = {**deepcopy(source.upstream_receipt), "base_revision_id": revision_id,
                       "authored_template_sha256": row.content_sha256}
            model = SystemModel(id=model_id, application_id=app_id, name=source.name,
                provider=source.provider, provider_base_url=source.provider_base_url,
                upstream_project_id=source.upstream_project_id, upstream_version=source.upstream_version,
                graph_sha256=source.graph_sha256, graph_snapshot=graph, upstream_receipt=receipt)
            base = SystemRevision(id=revision_id, system_model_id=model_id, revision_number=1,
                label="模板初始数据", revision_kind="base", graph_sha256=revision.graph_sha256,
                content_sha256=canonical_content_sha256(graph, context), graph_snapshot=graph,
                application_context=deepcopy(context), status="draft")
            db.add(app)
            db.flush()
            db.add(model)
            db.flush()
            db.add(base)
            period_map = {}
            for period in db.scalars(select(Period).where(Period.application_id == row.source_application_id)):
                period_id = new_id()
                period_map[period.id] = period_id
                db.add(Period(id=period_id, application_id=app_id, key=period.key, name=period.name,
                              start_date=period.start_date, end_date=period.end_date, resolution=period.resolution))
            db.flush()
            boundary_map = {}
            for boundary in db.scalars(select(BoundaryDefinition).where(
                    BoundaryDefinition.application_id == row.source_application_id,
                    BoundaryDefinition.status == "frozen")):
                body = {key: deepcopy(getattr(boundary, key)) for key in BOUNDARY_FIELDS}
                body["period_id"] = period_map.get(boundary.period_id)
                if body["geographic_scope"].get("graph_sha256"):
                    body["geographic_scope"]["graph_sha256"] = base.graph_sha256
                boundary_id = new_id()
                boundary_map[boundary.id] = boundary_id
                db.add(BoundaryDefinition(id=boundary_id, application_id=app_id, **body,
                    content_sha256=canonical_json_sha256(body), status="frozen", frozen_at=utcnow()))
            db.flush()
            instantiate_defaults(db, app, base, pin.get("user_methods", []), boundary_map)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                refuse("TEMPLATE_CREATE_CONFLICT", "同一项目正在创建，请重试。")
            return {"application_id": app_id, "system_model_id": model_id, "revision_id": revision_id}
