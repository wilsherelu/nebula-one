"""Bind a returned graph to an already reviewed CBAM boundary after checking its identity."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from sqlalchemy import select

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..emission_selectors import selector_matches
from ..models import Application, SystemModel, SystemRevision, new_id, utcnow
from ..runtime_models import BoundaryDefinition, MethodPackage, Period
from ..runtime_schemas import MethodPackageCreate
from .model_processing_runtime import _resolve_rules, resolve_purpose_derivation
from .seed_projects import BOUNDARY_FIELDS


def _refuse(code: str, message: str, **details) -> None:
    raise DomainError(code=code, message=message, status_code=409, details=details)


def _reviewed_seed(db, application):
    """Follow only server-written, content-pinned handoff lineage to the installed template."""
    binding = (application.context or {}).get("modeling_template_binding")
    profile = (binding or {}).get("profile")
    seen = set()
    while isinstance(binding, dict):
        revision_id = binding.get("bound_revision_id")
        if not revision_id or revision_id in seen:
            break
        seen.add(revision_id)
        revision = db.get(SystemRevision, revision_id)
        model = db.get(SystemModel, binding.get("bound_model_id"))
        if (revision is None or model is None or revision.system_model_id != model.id
                or revision.content_sha256 != binding.get("bound_content_sha256")):
            break
        owner = db.get(Application, model.application_id)
        if owner is None:
            break
        template = (owner.context or {}).get("seed_template")
        if isinstance(template, dict):
            if template.get("profile") != profile:
                break
            return owner, revision, template
        binding = (owner.context or {}).get("modeling_template_binding")
        if (binding or {}).get("profile") != profile:
            break
    _refuse("CBAM_REVIEWED_SOURCE_UNAVAILABLE", "返回模型找不到内容固定的已审钢铁模板来源。")


def _identity_graph(graph):
    """Allow quantities and display names to change, while retaining every process/port/link identity."""
    nodes = []
    for node in graph.get("nodes", []):
        item = {key: deepcopy(value) for key, value in node.items()
                if key not in ("name", "inputs", "outputs")}
        for side in ("inputs", "outputs"):
            ports = []
            for port in node.get(side, []):
                identity = {key: deepcopy(value) for key, value in port.items()
                            if key not in ("amount", "name", "display_name_en", "sourceProcessName",
                                           "product_name", "product_name_en", "externalSaleAmount")}
                sale = port.get("externalSaleAmount")
                if sale not in (None, 0, 0.0):
                    identity["externalSaleAmount"] = sale
                ports.append(identity)
            item[side] = sorted(ports, key=lambda value: str(value.get("id")))
        nodes.append(item)
    links = []
    node_modes = {node.get("id"): node.get("mode") for node in graph.get("nodes", [])}
    for edge in graph.get("exchanges", []):
        identity = {key: deepcopy(value) for key, value in edge.items()
                    if key not in ("amount", "providerAmount", "consumerAmount")}
        # The engine derives this mode from the endpoints when loading legacy graphs.
        # Preserve explicit modes on balanced links, where they carry different semantics.
        if any(node_modes.get(edge.get(side)) == "normalized" for side in ("fromNode", "toNode")):
            identity["quantityMode"] = "dual"
        if identity.get("sourceHandle") in (None, f"out:{edge.get('sourcePortId')}"):
            identity.pop("sourceHandle", None)
        if identity.get("targetHandle") in (None, f"in:{edge.get('targetPortId')}"):
            identity.pop("targetHandle", None)
        links.append(identity)
    return {"nodes": sorted(nodes, key=lambda value: str(value.get("id"))),
            "exchanges": sorted(links, key=lambda value: str(value.get("id")))}


def _first_difference(expected, actual, path="graph"):
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(expected.keys() | actual.keys()):
            if key not in expected or key not in actual:
                return f"{path}.{key}"
            found = _first_difference(expected[key], actual[key], f"{path}.{key}")
            if found:
                return found
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return f"{path}.length"
        for index, (left, right) in enumerate(zip(expected, actual)):
            found = _first_difference(left, right, f"{path}[{index}]")
            if found:
                return found
    elif expected != actual:
        return path
    return None


def _reviewed_selector_additions(source_graph, returned_graph, selectors, in_boundary):
    """Accept additive reviewed emissions; keep local exchange ids only in the frozen receipt."""
    source_nodes = {node["id"]: node for node in source_graph.get("nodes", [])}
    reduced = deepcopy(returned_graph)
    additions = []
    outside = set()
    for node in reduced.get("nodes", []):
        original = source_nodes.get(node["id"])
        if original is None:
            if node.get("process_uuid") in in_boundary:
                _refuse("CBAM_REVIEWED_GRAPH_CHANGED", "新增的边界内过程尚无 CBAM 复核规则。",
                        node_id=node.get("id"))
            outside.add(node["id"])
            continue
        old_ports = {port["id"] for port in original.get("outputs", [])}
        retained = []
        for port in node.get("outputs", []):
            if port.get("id") in old_ports:
                retained.append(port)
                continue
            matched = [selector for selector in selectors
                       if selector_matches(selector.get("identity") or {}, node, port)]
            if len(matched) != 1:
                _refuse("CBAM_EMISSION_ROLE_REVIEW_REQUIRED",
                        "新增排放流没有唯一的已审过程、流身份和方向归属；已知分项仍可单独查看。",
                        exchange_id=f"{node['id']}::{port.get('id')}", matches=len(matched))
            additions.append((f"{node['id']}::{port['id']}", node, matched[0]))
        node["outputs"] = retained
    reduced["nodes"] = [node for node in reduced["nodes"] if node["id"] not in outside]
    reduced["exchanges"] = [edge for edge in reduced.get("exchanges", [])
                            if edge.get("fromNode") not in outside and edge.get("toNode") not in outside]
    difference = _first_difference(_identity_graph(source_graph), _identity_graph(reduced))
    if difference:
        _refuse("CBAM_REVIEWED_GRAPH_CHANGED",
                "返回图还有未审阅的过程、流或连接身份变化。", difference=difference)
    return additions


def reviewed_cbam_content(db, application, revision, demand, inputs):
    source, source_revision, template = _reviewed_seed(db, application)
    expected = _identity_graph(source_revision.graph_snapshot)
    actual = _identity_graph(revision.graph_snapshot)
    profile = (application.context.get("modeling_template_binding") or {}).get("profile")
    rules = _resolve_rules(profile, inputs.get("model_processing_rules_ref"),
                           canonical_json_sha256(actual), revision.graph_snapshot)
    extension = rules.reviewed_returned_graph
    difference = _first_difference(expected, actual)
    selector_review = rules.reviewed_returned_selector
    if difference and selector_review is None and not (extension is not None
                           and extension["source_graph_identity_sha256"] == canonical_json_sha256(expected)
                           and extension["accepted_graph_identity_sha256"] == canonical_json_sha256(actual)):
        _refuse("CBAM_REVIEWED_GRAPH_CHANGED", "返回图的过程、流或连接身份已变，须重新审阅 CBAM 方法边界。",
                difference=difference, reviewed_revision_id=source_revision.id,
                current_revision_id=revision.id)
    derivation = resolve_purpose_derivation(
        db, revision=revision, application=application, purpose="cbam", demand=deepcopy(demand),
        background_process_pins=inputs.get("background_process_pins", []),
        mapped_background_process_pins=inputs.get("mapped_background_process_pins", []),
        project_background_pins=inputs.get("project_background_pins", []),
    )
    cited = [item for item in derivation.basis["method_packages"] if
             (package := db.scalar(select(MethodPackage).where(
                 MethodPackage.package_id == item["package_id"],
                 MethodPackage.version == item["version"]))) is not None
             and package.package_kind == "cbam_trial" and package.content_sha256 == item["content_sha256"]]
    if len(cited) != 1:
        _refuse("CBAM_REVIEWED_METHOD_UNAVAILABLE", "已审规则没有唯一、精确的 CBAM 方法包。")
    method_ref = f"{cited[0]['package_id']}@{cited[0]['version']}"
    source_method = rules.reviewed_source_method_package
    source_method_ref = (f"{source_method.package_id}@{source_method.version}"
                         if source_method is not None else method_ref)
    if source_method is not None:
        registered_source = db.scalar(select(MethodPackage).where(
            MethodPackage.package_id == source_method.package_id,
            MethodPackage.version == source_method.version))
        if registered_source is None or registered_source.content_sha256 != source_method.content_sha256:
            _refuse("CBAM_REVIEWED_SOURCE_METHOD_CHANGED", "已审来源方法包的内容身份不一致。")
    boundaries = list(db.scalars(select(BoundaryDefinition).where(
        BoundaryDefinition.application_id == source.id,
        BoundaryDefinition.id.in_(template.get("boundary_ids") or []),
        BoundaryDefinition.boundary_type == "cbam_trial",
        BoundaryDefinition.method_package_ref == source_method_ref,
        BoundaryDefinition.status == "frozen")))
    if len(boundaries) != 1:
        _refuse("CBAM_REVIEWED_BOUNDARY_UNAVAILABLE", "模板没有唯一的已冻结 CBAM 边界。",
                method_package_ref=method_ref)
    original = boundaries[0]
    original_content = {key: deepcopy(getattr(original, key)) for key in BOUNDARY_FIELDS}
    if canonical_json_sha256(original_content) != original.content_sha256:
        _refuse("CBAM_REVIEWED_BOUNDARY_CHANGED", "已审边界内容与其冻结哈希不一致。")
    content = deepcopy(original_content)
    content["name"] = f"{original.name} / {revision.id}"
    if selector_review is not None:
        manifest = cited[0]
        method = db.scalar(select(MethodPackage).where(
            MethodPackage.package_id == manifest["package_id"],
            MethodPackage.version == manifest["version"]))
        selectors = (method.manifest.get("classification_rules") or {}).get(
            "additional_direct_emission_selectors")
        if not isinstance(selectors, list) or not selectors:
            _refuse("CBAM_REVIEWED_METHOD_CHANGED", "版本化方法没有声明新增直接排放选择器。")
        in_boundary = set((method.manifest.get("boundary_schema") or {}).get(
            "production_process_boundary", {}).get("in_boundary_process_uuids") or [])
        additions = _reviewed_selector_additions(source_revision.graph_snapshot,
                                                  revision.graph_snapshot, selectors, in_boundary)
        content["method_package_ref"] = method_ref
        direct = content["included_flow_rules"]
        existing_ids = {item.get("exchange_id") for item in direct}
        for exchange_id, node, selector in additions:
            if exchange_id in existing_ids:
                _refuse("CBAM_REVIEWED_EXCHANGE_DUPLICATE", "新增直接排放已存在于来源边界。")
            rule = deepcopy(selector["boundary_rule"])
            rule.update(exchange_id=exchange_id, process_uuid=node["process_uuid"])
            direct.append(rule)
        content["geographic_scope"]["selected_additional_exchange_ids"] = sorted(
            item[0] for item in additions)
    if extension is not None:
        content["method_package_ref"] = method_ref
        direct = content["included_flow_rules"]
        if any(item.get("exchange_id") == extension["added_exchange_id"] for item in direct):
            _refuse("CBAM_REVIEWED_EXCHANGE_DUPLICATE", "新增直接排放已存在于来源边界。")
        processes = [node["process_uuid"] for node in revision.graph_snapshot["nodes"]
                     for port in node.get("outputs", [])
                     if f"{node['id']}::{port['id']}" == extension["added_exchange_id"]]
        if len(processes) != 1 or processes[0] != extension["boundary_rule"]["process_uuid"]:
            _refuse("CBAM_REVIEWED_EXCHANGE_MISSING", "新增直接排放端口未唯一对应到已审过程。")
        direct.append(deepcopy(extension["boundary_rule"]))
    content["geographic_scope"]["graph_sha256"] = revision.graph_sha256
    content["geographic_scope"]["source_system_revision_id"] = revision.id
    content["geographic_scope"]["source_revision_content_sha256"] = revision.content_sha256
    content["geographic_scope"]["reviewed_boundary_id"] = original.id
    content["geographic_scope"]["reviewed_boundary_sha256"] = original.content_sha256
    content["geographic_scope"]["reviewed_graph_identity_sha256"] = canonical_json_sha256(expected)
    return source, original, method_ref, content


def register_reviewed_cbam_extension(db, application, revision) -> None:
    """Register the additive direct method only for its exact reviewed graph identity."""
    profile = (application.context.get("modeling_template_binding") or {}).get("profile")
    if not isinstance(profile, dict):
        return
    rules = _resolve_rules(profile,
                           (revision.application_context or {}).get("project_inputs", {}).get("model_processing_rules_ref"),
                           canonical_json_sha256(_identity_graph(revision.graph_snapshot)),
                           revision.graph_snapshot)
    extension = rules.reviewed_returned_graph
    selector_review = rules.reviewed_returned_selector
    if extension is None and selector_review is None:
        return
    source, source_revision, _ = _reviewed_seed(db, application)
    if (extension is not None and
            canonical_json_sha256(_identity_graph(source_revision.graph_snapshot))
            != extension["source_graph_identity_sha256"]):
        _refuse("CBAM_REVIEWED_SOURCE_CHANGED", "已审来源图身份与新版本规则不一致。")
    method = rules.purpose("cbam").process_selection.method_package
    directory = Path(__file__).resolve().parents[1] / "resources/official_methods"
    matches = []
    for path in directory.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (payload.get("package_id"), payload.get("version")) == (method.package_id, method.version):
            matches.append(MethodPackageCreate.model_validate(payload))
    if len(matches) != 1:
        _refuse("CBAM_REVIEWED_METHOD_UNAVAILABLE", "已审规则没有唯一、精确的本地 CBAM 方法包。")
    package = matches[0]
    if package.package_kind != "cbam_trial" or (extension is not None and
            package.manifest.get("reviewed_returned_graph") != extension) or (selector_review is not None and
            package.manifest.get("reviewed_returned_selector", {}).get("source_template")
            != profile or package.manifest["classification_rules"].get(
                "additional_direct_emission_selectors", [{}])[0].get("identity")
            != selector_review.get("identity") or
            package.manifest["boundary_schema"]["production_process_boundary"].get(
                "in_boundary_process_uuids") != selector_review.get("in_boundary_process_uuids")):
        _refuse("CBAM_REVIEWED_METHOD_CHANGED", "新增直接排放方法与精确图审查不一致。")
    digest = canonical_json_sha256(package.model_dump(mode="json"))
    if (package.package_id, package.version, digest) != (method.package_id, method.version, method.content_sha256):
        _refuse("CBAM_REVIEWED_METHOD_CHANGED", "新增直接排放方法哈希与处理规则不一致。")
    existing = db.scalar(select(MethodPackage).where(
        MethodPackage.package_id == package.package_id, MethodPackage.version == package.version))
    if existing is not None and existing.content_sha256 != digest:
        _refuse("CBAM_REVIEWED_METHOD_CHANGED", "已注册的新版本方法内容不同。")
    if existing is None:
        db.add(MethodPackage(**package.model_dump(mode="python"), content_sha256=digest, status="registered"))
        db.flush()


def bind_reviewed_cbam(db, application, revision, demand, inputs) -> str:
    """Create an immutable boundary for this graph and bind its exact method, idempotently."""
    source, original, method_ref, content = reviewed_cbam_content(
        db, application, revision, demand, inputs)
    period_map = {}
    for period in db.scalars(select(Period).where(Period.application_id == source.id)):
        target = db.scalar(select(Period).where(
            Period.application_id == application.id, Period.key == period.key))
        if target is None:
            target = Period(id=new_id(), application_id=application.id, key=period.key,
                            name=period.name, start_date=period.start_date,
                            end_date=period.end_date, resolution=period.resolution)
            db.add(target)
            db.flush()
        elif (target.start_date, target.end_date, target.resolution) != (
                period.start_date, period.end_date, period.resolution):
            _refuse("CBAM_REPORTING_PERIOD_CHANGED", "返回项目的同名报告期与已审来源不一致。")
        period_map[period.id] = target.id
    content["period_id"] = period_map.get(original.period_id)
    digest = canonical_json_sha256(content)
    existing = db.scalar(select(BoundaryDefinition).where(
        BoundaryDefinition.application_id == application.id,
        BoundaryDefinition.name == content["name"]))
    if existing is not None:
        legacy_content = deepcopy(content)
        legacy_content["geographic_scope"].pop("source_system_revision_id", None)
        legacy_content["geographic_scope"].pop("source_revision_content_sha256", None)
        if (existing.status != "frozen" or existing.content_sha256 not in {
                digest, canonical_json_sha256(legacy_content)}):
            _refuse("CBAM_RETURNED_BOUNDARY_CONFLICT", "当前版本已有内容不同的 CBAM 边界。")
        boundary_id = existing.id
    else:
        boundary_id = new_id()
        db.add(BoundaryDefinition(id=boundary_id, application_id=application.id, **content,
                                  content_sha256=digest, status="frozen", frozen_at=utcnow()))
    context = deepcopy(application.context)
    refs = list(context.get("method_package_refs") or [])
    capabilities = list(context.get("project_capabilities") or [])
    if "cbam.trial.v2" not in capabilities:
        capabilities.append("cbam.trial.v2")
        context["project_capabilities"] = capabilities
    if method_ref not in refs:
        refs.append(method_ref)
        context["method_package_refs"] = refs
    if context != application.context:
        application.context = context
    db.flush()
    return boundary_id
