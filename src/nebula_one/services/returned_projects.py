"""Production data entry for a model that came back from professional modelling.

A returned project is not an instance of an installed template record: the editor returns a graph,
not a seed definition, so the workbench contract is computed from what that project itself proves -
the generic inventory over the returned exchanges, the exact reference-product identity the returned
graph carries, and the derivation each accounting purpose actually performs under the reviewed rules
the model descends from. Template lineage says where the structure came from; it never approves what
the editor added, so a purpose the current model cannot answer for is reported with its own reason
instead of the project being refused as having no template at all.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from sqlalchemy import select

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..model_processing_contract import load_model_processing_rules_for_template, load_model_processing_rules_by_reference, TemplateRef
from ..release_resources import display_labels
from ..models import SystemRevision
from ..runtime_models import BoundaryDefinition, MethodPackage
from .model_processing_runtime import resolve_purpose_derivation
from .returned_cbam_binding import _identity_graph, bind_reviewed_cbam, register_reviewed_cbam_extension, reviewed_cbam_content
from .official_product_method import bind_official_product_method, bind_official_organization_method, bind_official_cbam_partial_method, bind_official_organization_lifecycle_method
from .project_background import list_background_ports
from .seed_projects import SeedProjectService, apply_inventory_inputs

# Which workbench task one reviewed accounting purpose turns into. A purpose with no entry here is
# not offered at all rather than offered under a guessed capability.
PURPOSE_TASKS = {"lca": "solve.nebula.v1", "cbam": "cbam.trial.v2", "pcf": "pcf.product.v1"}


def _refuse(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=409, details=details)


def reference_demand(application, revision, *, reference_output=False) -> list[dict[str, Any]]:
    """The calculation demand the returned model proves, from its own reference product port.

    The editor's functional unit names a flow, an amount and a unit; the precise unit-group identity
    comes from the single output port in the returned graph that carries that flow, so a model that
    lost or duplicated its reference product is refused by name instead of being solved against an
    assumed unit.
    """
    unit = application.context.get("modeling_functional_unit") or {}
    missing = sorted(key for key in ("flow_uuid", "amount", "unit") if not unit.get(key))
    products = [
        port
        for node in revision.graph_snapshot.get("nodes", [])
        for port in node.get("outputs", [])
        if port.get("isProduct") and port.get("flowUuid") == unit.get("flow_uuid")
        and port.get("unit") == unit.get("unit")
    ]
    if missing or len(products) != 1 or not all(
        products[0].get(key) for key in ("unitGroupUuid", "unitGroupVersion")
    ):
        _refuse(
            "MODELING_FUNCTIONAL_UNIT_INCOMPLETE",
            "this returned model cannot be filled in yet: its reference product, its exact unit"
            " identity or the amount to compute against is missing or ambiguous in the returned"
            " graph, and nothing here may be assumed",
            missing_functional_unit_keys=missing,
            reference_product_ports=len(products),
        )
    port = products[0]
    amount = port.get("amount") if reference_output else unit["amount"]
    if not isinstance(amount, (int, float)) or amount <= 0:
        _refuse("PROJECT_REFERENCE_AMOUNT_INVALID", "目标产品产出必须大于零。")
    return [
        {
            "reference_flow_uuid": unit["flow_uuid"],
            "amount": float(amount),
            "unit": unit["unit"],
            "unit_group_uuid": port["unitGroupUuid"],
            "unit_group_version": port["unitGroupVersion"],
        }
    ]


class ReturnedProjectService:
    def __init__(self, container):
        self.c = container

    def _display_labels(self, application, language: str) -> dict[str, str]:
        """The template's own pinned projection, for the ports that came from that template.

        The extension the editor added has no reviewed projection, so it keeps the names its own
        graph carries rather than being labelled by a template that never described it.
        """
        binding = application.context.get("modeling_template_binding") or {}
        installed_labels = binding.get("display_metadata")
        if installed_labels is not None:
            return display_labels(installed_labels, language)
        bound_id = binding.get("bound_revision_id")
        if not bound_id:
            return {}
        with self.c.database.session() as db:
            bound = db.get(SystemRevision, bound_id)
        template = (bound.application_context or {}).get("seed_template") if bound else None
        content = (template or {}).get("identity_revision", {}).get("content", {})
        return display_labels(content.get("display_metadata", []), language)

    def _tasks(self, application, revision, demand, inputs):
        """Offer a task only when this exact model derives under the reviewed rules it descends from."""
        profile = (application.context.get("modeling_template_binding") or {}).get("profile") or {}
        try:
            exact = inputs.get("model_processing_rules_ref")
            graph_identity = canonical_json_sha256(_identity_graph(revision.graph_snapshot))
            if exact:
                rules = load_model_processing_rules_by_reference(**exact)
                if (rules.applicable_template != TemplateRef.model_validate(profile) or
                        rules.reviewed_returned_graph is not None and
                        rules.reviewed_returned_graph["accepted_graph_identity_sha256"] != graph_identity):
                    raise DomainError(code="MODEL_PROCESSING_RULES_MISMATCH",
                                      message="模型处理规则包不属于此模板和图版本。", status_code=409)
            else:
                rules = load_model_processing_rules_for_template(
                    profile, graph_identity_sha256=graph_identity, graph=revision.graph_snapshot)
        except DomainError as error:
            return ["mfa.solved.v1"], [
                {"capability": "model_processing_rules", "code": error.code, "reason": error.message}
            ]
        capabilities, blocked = ["mfa.solved.v1"], []
        with self.c.database.session() as db:
            for purpose in rules.purposes:
                capability = PURPOSE_TASKS.get(purpose)
                if capability is None:
                    continue
                try:
                    resolve_purpose_derivation(
                        db,
                        revision=revision,
                        application=application,
                        purpose=purpose,
                        demand=deepcopy(demand),
                        background_process_pins=inputs.get("background_process_pins", []),
                        mapped_background_process_pins=inputs.get(
                            "mapped_background_process_pins", []
                        ),
                        project_background_pins=inputs.get("project_background_pins", []),
                    )
                except DomainError as error:
                    blocked.append(
                        {"capability": capability, "code": error.code, "reason": error.message}
                    )
                else:
                    if purpose == "cbam":
                        try:
                            _, original, method_ref, content = reviewed_cbam_content(
                                db, application, revision, demand, inputs)
                        except DomainError as error:
                            blocked.append({"capability": capability, "code": error.code,
                                            "reason": error.message})
                        else:
                            matching = any(
                                b.name == content["name"]
                                and b.method_package_ref == method_ref
                                and b.geographic_scope.get("graph_sha256") == revision.graph_sha256
                                and b.geographic_scope.get("reviewed_boundary_sha256") == original.content_sha256
                                for b in db.query(BoundaryDefinition).filter(
                                    BoundaryDefinition.application_id == application.id,
                                    BoundaryDefinition.boundary_type == "cbam_trial",
                                    BoundaryDefinition.status == "frozen",
                                )
                            )
                            if matching:
                                capabilities.append(capability)
                            else:
                                blocked.append({"capability": capability, "code": "CBAM_BOUNDARY_REQUIRED",
                                                "reason": "当前模型版本尚未绑定经审阅的 CBAM 边界。"})
                    else:
                        capabilities.append(capability)
            method_refs = set((application.context or {}).get("method_package_refs") or [])
            native_products = list(db.scalars(select(MethodPackage).where(
                MethodPackage.package_kind == "product_carbon_footprint")))
            if "pcf.product.v1" not in capabilities and any(f"{package.package_id}@{package.version}" in method_refs
                   and (package.manifest.get("formula_graph") or {}).get("source_contract")
                   == "provider.native-background-climate-total.response.v1"
                   for package in native_products):
                capabilities.append("pcf.product.v1")
        return capabilities, blocked

    def read(self, application, revision, language="zh"):
        inputs = revision.application_context.get("project_inputs", {})
        # A fresh inventory editor saves in reference_output mode; preview that same batch.
        # Already saved explicit demands remain pinned to their original values.
        demand = inputs.get("demand") or reference_demand(application, revision, reference_output=True)
        capabilities, blocked = self._tasks(application, revision, demand, inputs)
        template = {
            "title": (
                (application.context.get("modeling_template_binding") or {}).get("profile") or {}
            ).get("id")
            or "专业建模返回的模型",
            "demand": demand,
            "capabilities": capabilities,
            "blocked_capabilities": blocked,
            "source_default": "建模返回的示例值（未经实测）",
        }
        view = SeedProjectService(self.c).read(application, revision, template=template, language=language)
        if not inputs:
            view["demand_mode"] = "reference_output"
        labels = self._display_labels(application, language)
        for field in view["fields"]:
            key = f"{field['process_id']}::{field['port_id']}"
            if key in labels:
                field["label"] = labels[key]
        for port in view["background_ports"]:
            if port["exchange_id"] in labels:
                port["label"] = labels[port["exchange_id"]]
        return view

    def save(self, application, parent, payload, language="zh"):
        demand = reference_demand(application, parent)
        revision = apply_inventory_inputs(
            self.c, parent, payload, demand, idempotency_prefix="returned-input", label="实景清单"
        )
        with self.c.database.session() as db:
            current = db.get(type(application), application.id)
            saved = db.get(SystemRevision, revision.id)
            bind_official_product_method(db, current)
            bind_official_organization_method(db, current)
            bind_official_cbam_partial_method(db, current, revision=saved)
            bind_official_organization_lifecycle_method(db, current)
            try:
                with db.begin_nested():
                    register_reviewed_cbam_extension(db, current, saved)
                    bind_reviewed_cbam(db, current, saved, demand,
                                       saved.application_context.get("project_inputs", {}))
            except DomainError:
                # An edited graph can remain a valid inventory while its CBAM classification
                # needs review. _tasks reports the exact reason for that data version.
                pass
            db.commit()
        return self.read(self.c.applications.get(application.id), revision, language)

    def refresh_cbam_review(self, application, revision, language: str = "zh"):
        """Apply an installed exact-graph review to an already saved returned data version."""
        if not (application.context or {}).get("modeling_template_binding"):
            _refuse("CBAM_RETURNED_MODEL_REQUIRED", "只有专业建模返回的项目可更新此复核边界。")
        with self.c.database.session() as db:
            current = db.get(type(application), application.id)
            saved = db.get(SystemRevision, revision.id)
            inputs = saved.application_context.get("project_inputs") or {}
            demand = inputs.get("demand") or reference_demand(current, saved)
            with db.begin_nested():
                register_reviewed_cbam_extension(db, current, saved)
                bind_official_cbam_partial_method(db, current, revision=saved)
                bind_reviewed_cbam(db, current, saved, demand, inputs)
            db.commit()
        return self.read(self.c.applications.get(application.id), revision, language)
