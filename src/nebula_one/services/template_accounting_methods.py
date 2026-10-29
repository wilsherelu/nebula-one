"""The accounting methods one exact template version binds, read from their real declarations.

A card in the template workspace has to say where its rules come from, so this read model only
reports what a bound package or a frozen user-method snapshot declares: explicit identities and
versioned structural selectors expand against the exact model, while undeclared ports stay
undeclared instead of being guessed from their flow names. Package limitations, pending rules and refused defaults travel with
the entry verbatim, so a missing official scope shows as a named gap rather than as coverage.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..errors import DomainError
from ..analysis.method_selectors import compile_accounting_selectors, SCHEMA_VERSION as RULE_DEFINITION_SCHEMA
from ..models import AuthoredProjectTemplate, SeedInstallation, SystemRevision
from ..runtime_models import (BoundaryDefinition, CalculationMethod, CalculationMethodVersion,
                              MethodPackage)
from ..runtime_schemas import CalculationMethodCreate, CalculationMethodDetailOut, CalculationMethodRef

SCHEMA_VERSION = "nebula_one.template-accounting-methods.v1"
COPY_SCHEMA_VERSION = "nebula_one.template-method-copy.v1"
SAVE_SCHEMA_VERSION = "nebula_one.template-save.v1"
EXCHANGE_ID = re.compile(r"^[A-Za-z0-9_.\-]+::[A-Za-z0-9_.\-]+$")
# The same three groups the rule editor flattens (web modelFlows), so the counts agree with the UI.
PORT_GROUPS = ("inputs", "outputs", "emissions")
METHOD_GROUPS = {
    "organization_period_inventory": "organization",
    "organization_lifecycle_carbon": "organization",
    "organization_ghg_inventory": "organization",
    "cbam_trial": "cbam",
    "cbam_partial_review": "cbam",
    "product_carbon_footprint": "product",
    # A copied or cloned working method carries one of the four method purposes, not a package kind.
    "cbam": "cbam",
    "organization": "organization",
    "pcf": "product",
    "custom": "user",
}
# A copied method is persisted through the existing user-method contract, whose purpose vocabulary
# is the four-value one; the package kinds map onto it explicitly, never by string similarity.
PURPOSE_BY_KIND = {
    "organization_period_inventory": "organization",
    "organization_lifecycle_carbon": "organization",
    "organization_ghg_inventory": "organization",
    "cbam_trial": "cbam",
    "cbam_partial_review": "cbam",
    "product_carbon_footprint": "pcf",
}
# The three reader-facing accounting tasks and the method group each one owns. A task is the unit the
# template workspace shows; the internal packages that realise it stay behind the task's preset list.
TASK_ROLE_GROUP = {
    "complete_model": "product",
    "cbam": "cbam",
    "scope_classification": "organization",
}


def refuse(code: str, message: str, status: int = 409, **details) -> None:
    raise DomainError(code=code, message=message, status_code=status, details=details)


def port_direction(group: str, port: dict) -> str:
    """The rule direction of one graph port, by the same group/type rule the editor uses.

    Kept identical to `web/src/pages/calculationMethods/flowRows.ts` so a transcribed rule and the
    row the editor draws for that port share one identity.
    """
    port_type = str(port.get("type") or "")
    if port_type in ("biosphere", "elementary") or group == "emissions":
        return "resource" if group == "inputs" else "emission"
    return "input" if group == "inputs" else "output"


def model_ports(graph: dict | None) -> list[dict[str, Any]]:
    """Every selectable port of one engine graph, as `process::port` identities."""
    source = graph or {}
    # An input fed by another modelled process is a foreground transfer, not a purchased background
    # path; the contribution domain of a rule depends on that, so it is read off the graph edges.
    internal = {f"{edge.get('toNode')}::{edge.get('targetPortId')}"
                for edge in source.get("exchanges") or source.get("edges") or []
                if isinstance(edge, dict) and edge.get("toNode") and edge.get("targetPortId")}
    ports: list[dict[str, Any]] = []
    for node in source.get("nodes") or []:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            continue
        for group in PORT_GROUPS:
            for port in node.get(group) or []:
                if not isinstance(port, dict) or port.get("id") is None:
                    continue
                exchange_id = f"{node['id']}::{port['id']}"
                ports.append({
                    "exchange_id": exchange_id,
                    "process_id": node["id"],
                    "process_name": str(node.get("name") or node["id"]),
                    "port_id": str(port["id"]),
                    "name": str(port.get("name") or port.get("id")),
                    "unit": str(port.get("unit") or ""),
                    "port_group": group,
                    "flow_uuid": port.get("flowUuid") if isinstance(port.get("flowUuid"), str) else None,
                    "direction": port_direction(group, port),
                    "internal": exchange_id in internal,
                })
    return ports


def declared_exchanges(rules: Any, path: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Collect the exact exchange identities a declaration names, with the rule path that names them.

    Both positions count: a `process::port` string value, and a `process::port` used as a mapping
    key (`pending_activity_rules` declares its subject that way). Structural only - the pattern is
    an identity shape, never a flow name, so this cannot invent a rule the package did not write.
    """
    found: list[dict[str, Any]] = []
    if isinstance(rules, dict):
        for key, value in rules.items():
            if isinstance(key, str) and EXCHANGE_ID.match(key):
                found.append({"exchange_id": key, "rule_path": ".".join([*path, key])})
            found.extend(declared_exchanges(value, (*path, str(key))))
    elif isinstance(rules, list):
        for index, value in enumerate(rules):
            found.extend(declared_exchanges(value, (*path, str(index))))
    elif isinstance(rules, str) and EXCHANGE_ID.match(rules):
        found.append({"exchange_id": rules, "rule_path": ".".join(path)})
    return found


def group_declarations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    for item in items:
        grouped.setdefault(item["exchange_id"], [])
        if item["rule_path"] not in grouped[item["exchange_id"]]:
            grouped[item["exchange_id"]].append(item["rule_path"])
    return [{"exchange_id": exchange_id, "rule_paths": paths} for exchange_id, paths in sorted(grouped.items())]


def package_provenance(manifest: dict) -> list[dict[str, Any]]:
    """The citations a package carries for its own rules, kept verbatim."""
    out: list[dict[str, Any]] = []

    def walk(node: Any, path: tuple[str, ...]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, (*path, str(key)))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, (*path, str(index)))
        elif isinstance(node, str):
            entry: dict[str, Any] = {"source_path": ".".join(path)}
            if node.startswith("http"):
                entry["url"] = node
            else:
                entry["text"] = node
            out.append(entry)

    walk(manifest.get("provenance") or {}, ())
    return out


def package_gaps(manifest: dict) -> list[dict[str, Any]]:
    """What the package itself says it does not cover. Nothing here is inferred."""
    gaps: list[dict[str, Any]] = []
    limitations = (manifest.get("validation_rules") or {}).get("limitations") or []
    for index, text in enumerate(limitations):
        gaps.append({"code": "PACKAGE_DECLARED_LIMITATION", "message": str(text),
                     "source_path": f"validation_rules.limitations[{index}]"})
    pending = (manifest.get("classification_rules") or {}).get("pending_activity_rules") or {}
    if isinstance(pending, dict):
        for exchange_id, rule in sorted(pending.items()):
            rule = rule if isinstance(rule, dict) else {}
            gaps.append({"code": "PACKAGE_PENDING_RULE", "exchange_id": exchange_id,
                         "clause": rule.get("clause"), "message": str(rule.get("reason") or ""),
                         "source_path": f"classification_rules.pending_activity_rules.{exchange_id}"})
    defaults = manifest.get("default_value_rules") or {}
    if defaults.get("allowed") is False and defaults.get("basis"):
        gaps.append({"code": "PACKAGE_REFUSES_DEFAULT_VALUES", "message": str(defaults["basis"]),
                     "source_path": "default_value_rules.basis"})
    for key, value in sorted((manifest.get("boundary_schema") or {}).items()):
        if value is False:
            gaps.append({"code": "PACKAGE_DECLARED_INCOMPLETE_BOUNDARY", "message": key,
                         "source_path": f"boundary_schema.{key}"})
    return gaps


# Where each package kind writes its per-flow declarations. The mapping is explicit per kind: a kind
# listed here is transcribed from the keys it names, and any other kind yields an empty rule set with
# a note, never a guess. Nothing in this table reads a flow name.
ORGANIZATION_DECLARATIONS = {
    "organization_period_inventory": {
        "purchased_keys": ("scope2_purchase_exchange_ids",),
        "category_key": "scope3_categories",
        "dimension": {"id": "ghg_scope3_category", "name": "范围 3 类别"},
    },
    "organization_lifecycle_carbon": {
        "purchased_keys": ("energy_purchase_exchange_ids",),
        "category_key": "other_value_chain_categories",
        "dimension": {"id": "lc_value_chain", "name": "价值链分项"},
    },
}
COPYABLE_KINDS = ("cbam_trial", "cbam_partial_review", "product_carbon_footprint",
                  *ORGANIZATION_DECLARATIONS)


def contribution_domain(port: dict[str, Any]) -> str:
    """The contribution domain a rule for this port binds to, read off the model graph.

    An input another modelled process feeds is a foreground transfer (`direct`); an input from
    outside the model is a purchased background path (`upstream`). The solver resolves the same
    domain from its receipts, so a copied rule has to declare the one the engine will use.
    """
    return "direct" if port["direction"] != "input" or port["internal"] else "upstream"


def transcribed_rule(port: dict[str, Any], base_ref: str, *, boundary_status: str,
                     scope: str | None = None, location_role: str = "other",
                     cbam_relevant: bool = False, flow_uuid: str | None = None,
                     categories: dict[str, str] | None = None) -> dict[str, Any]:
    match = {"exchange_ids": [port["exchange_id"]], "directions": [port["direction"]]}
    if flow_uuid:
        # A package's exact flow citation must agree with the model, not overwrite it.
        match["flow_uuids"] = [flow_uuid]
    compiled = compile_accounting_selectors({"schema_version": RULE_DEFINITION_SCHEMA,
        "selectors": [{"id": "exact_port", "match": match, "classification": {
            "boundary_status": boundary_status, "location_role": location_role, "scope": scope,
            "cbam_relevant": cbam_relevant, "categories": categories or {}}}]}, [port], base_ref)
    return compiled["rules"][0]


def transcribe_official_rules(kind: str, manifest: dict, ports: list[dict[str, Any]],
                              base_ref: str) -> dict[str, Any]:
    """Write one bound package's own declarations down as user-method rules.

    Exact declarations and controlled-foreground selectors become rules, keyed by `process::port`
    identity. A port outside those declarations gets no rule, so the editor shows that flow as 待确认
    instead of inheriting an invented classification, and everything the package says it cannot do
    travels back as a note: a copy states its own gaps rather than looking complete.
    """
    by_id = {port["exchange_id"]: port for port in ports}
    rules: dict[str, dict[str, Any]] = {}
    dimensions: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    classification = manifest.get("classification_rules") or {}

    definition = manifest.get("accounting_rule_definition")
    if definition is not None:
        compiled = compile_accounting_selectors(definition, ports, base_ref)
        return {**compiled, "notes": [], "reference_product_exchange_id": None,
                "declared_exchange_ids": [rule["exchange_id"] for rule in compiled["rules"]]}

    def absent(exchange_id: Any, path: str) -> None:
        notes.append({"code": "DECLARED_PORT_ABSENT_FROM_MODEL", "exchange_id": exchange_id,
                      "message": "官方声明的端口不在这个模型版本里，未复制为规则。",
                      "source_path": path})

    def place(port: dict[str, Any], rule: dict[str, Any], path: str) -> None:
        existing = rules.get(port["exchange_id"])
        if existing is not None:
            notes.append({"code": "PACKAGE_DECLARATION_CONFLICT", "exchange_id": port["exchange_id"],
                          "message": "同一个端口被官方声明了两次，保留先出现的那条，另一条未复制。",
                          "source_path": path})
            return
        rules[port["exchange_id"]] = rule

    reference_product = None
    if kind == "cbam_trial":
        for index, item in enumerate(classification.get("direct_emissions") or []):
            item = item if isinstance(item, dict) else {}
            port = by_id.get(item.get("exchange_id"))
            path = f"classification_rules.direct_emissions[{index}]"
            if port is None:
                absent(item.get("exchange_id"), path)
                continue
            place(port, transcribed_rule(port, base_ref, boundary_status="selected", scope="scope_1",
                                         location_role="onsite", cbam_relevant=True,
                                         flow_uuid=item.get("flow_uuid")), path)
        product = classification.get("product") or {}
        reference_product = product.get("exchange_id") or product.get("reference_exchange_id")
        if reference_product:
            notes.append({"code": "REFERENCE_PRODUCT_NOT_A_RULE", "exchange_id": reference_product,
                          "message": "参考产品由项目需求给出，不作为流规则复制。",
                          "source_path": "classification_rules.product"})
    elif kind in ORGANIZATION_DECLARATIONS:
        spec = ORGANIZATION_DECLARATIONS[kind]
        control_mode = classification.get("controlled_process_mode")
        if control_mode == "all_solved_foreground_processes":
            # Expand the package's structural declaration with the same generic selector
            # compiler available to new method definitions, never from process/flow names.
            controlled = [port for port in ports if port["direction"] in {"emission", "resource"}]
            if controlled:
                compiled = compile_accounting_selectors({"schema_version": RULE_DEFINITION_SCHEMA,
                    "selectors": [{"id": "controlled_foreground", "match": {
                        "all_model_processes": True, "directions": ["emission", "resource"],
                        "contribution_target": "direct"}, "classification": {
                        "boundary_status": "selected", "scope": "scope_1", "location_role": "onsite"}}]},
                    ports, base_ref)
                for rule in compiled["rules"]:
                    place(by_id[rule["exchange_id"]], rule, "classification_rules.controlled_process_mode")
        elif control_mode is not None:
            notes.append({"code": "PACKAGE_CONTROL_MODE_UNSUPPORTED",
                          "message": "官方受控过程声明尚无可用的身份选择器，未猜测范围 1。",
                          "source_path": "classification_rules.controlled_process_mode"})
        for key in spec["purchased_keys"]:
            for index, exchange_id in enumerate(classification.get(key) or []):
                path = f"classification_rules.{key}[{index}]"
                port = by_id.get(exchange_id)
                if port is None:
                    absent(exchange_id, path)
                    continue
                if contribution_domain(port) != "upstream":
                    notes.append({"code": "PACKAGE_ROLE_CONFLICTS_WITH_MODEL", "exchange_id": exchange_id,
                                  "message": "官方把它声明为购入能源路径，但模型里这个端口由其他过程供给或不是输入；"
                                             "已按模型的实际贡献域复制，请核对。",
                                  "source_path": path})
                place(port, transcribed_rule(port, base_ref, boundary_status="selected", scope="scope_2",
                                             location_role="purchased_energy"), path)
        leaves: list[dict[str, Any]] = []
        for category_id, entry in sorted((classification.get(spec["category_key"]) or {}).items()):
            entry = entry if isinstance(entry, dict) else {}
            eligible = [item for item in entry.get("eligible_consumer_exchange_ids") or []
                        if isinstance(item, str)]
            if entry.get("boundary_status") == "not_in_boundary" or not eligible:
                notes.append({"code": "PACKAGE_CATEGORY_HAS_NO_PORT", "category": category_id,
                              "message": str(entry.get("name") or category_id),
                              "source_path": f"classification_rules.{spec['category_key']}.{category_id}"})
                continue
            leaves.append({"id": category_id, "name": str(entry.get("name") or category_id),
                           "is_leaf": True})
            for index, exchange_id in enumerate(eligible):
                path = (f"classification_rules.{spec['category_key']}.{category_id}"
                        f".eligible_consumer_exchange_ids[{index}]")
                port = by_id.get(exchange_id)
                if port is None:
                    absent(exchange_id, path)
                    continue
                place(port, transcribed_rule(port, base_ref, boundary_status="selected", scope="scope_3",
                                             location_role="upstream_supply",
                                             categories={spec["dimension"]["id"]: category_id}), path)
        if leaves:
            dimensions.append({**spec["dimension"], "source": "package", "categories": leaves})
    # A pending declaration names an applicable port the package still owes a factor for; that is a
    # declaration for every kind, and it stays pending: deciding it here would count a flow the
    # official method does not count.
    for exchange_id, pending in sorted((classification.get("pending_activity_rules") or {}).items()):
        pending = pending if isinstance(pending, dict) else {}
        path = f"classification_rules.pending_activity_rules.{exchange_id}"
        port = by_id.get(exchange_id)
        if port is None:
            absent(exchange_id, path)
            continue
        place(port, transcribed_rule(port, base_ref, boundary_status="pending"), path)
        notes.append({"code": "PACKAGE_PENDING_RULE", "exchange_id": exchange_id,
                      "clause": pending.get("clause"), "message": str(pending.get("reason") or ""),
                      "source_path": path})
    if not rules:
        notes.append({"code": "NO_PER_FLOW_DECLARATION",
                      "message": "该官方包没有可复制到这个模型版本的逐流规则；副本从空规则开始，"
                                 "需要逐个流设置核算范围。",
                      "source_path": "classification_rules"})
    return {
        "rules": list(rules.values()),
        "reporting_dimensions": dimensions,
        "notes": notes,
        "reference_product_exchange_id": reference_product,
        "declared_exchange_ids": sorted(rules),
    }


class TemplateMethodCopy(BaseModel):
    """Which official scheme to copy, named by the aggregation's own `method_key`.

    The caller names the scheme and the new method's display name only: the source application,
    model revision and package identity come from the exact template version, so a reader never
    re-picks them and cannot point a copy at a different model.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    method_key: str = Field(min_length=1, max_length=512)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4096)
    cbam_boundary_ref: str | None = Field(default=None, max_length=255)


class TemplateSave(BaseModel):
    """Save this exact template version as one of the reader's own templates.

    Only the name and the version are the reader's choices; source application, model revision and
    package pins are read from the template being saved, so a save can never quietly re-point it at
    another model or at a moved package head. Each named user method must already be a checked
    version on that same revision - the existing finalize contract enforces that again.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=32)
    user_methods: list[CalculationMethodRef] = Field(default_factory=list)


class TemplateAccountingMethodsService:
    """The template's accounting methods: what it binds, and a user copy of one official scheme.

    Reading aggregates the existing template, package and method services. Copying writes through
    the existing user-method contract (`CalculationMethodService.create_method`), so a copy is an
    ordinary draft method on the template's exact model revision - never an edit of the official
    original, which stays immutable.
    """

    def __init__(self, container):
        self.c = container

    def _context(self, db, template_id: str) -> dict[str, Any]:
        """Resolve one exact template version and everything its schemes are read from."""
        authored = db.get(AuthoredProjectTemplate, template_id)
        if authored is not None:
            identity = self._authored_identity(db, authored)
        else:
            installation = db.get(SeedInstallation, template_id)
            if installation is None:
                refuse("PROJECT_TEMPLATE_NOT_FOUND", "找不到该工艺模板。", 404, template_id=template_id)
            identity = self._seed_identity(db, installation)
        revision = db.get(SystemRevision, identity["source_revision_id"])
        if revision is None:
            refuse("TEMPLATE_METHOD_SOURCE_UNRESOLVED",
                   "模板绑定的模型版本已不可解析，无法列出其核算方案。",
                   template_id=template_id, source_revision_id=identity["source_revision_id"])
        ports = model_ports(revision.graph_snapshot or {})
        packages = self._packages(db, identity["method_package_refs"])
        for reference, expected_hash in (identity.get('method_pins') or {}).items():
            if reference in packages and packages[reference].content_sha256 != expected_hash:
                refuse('TEMPLATE_METHOD_PIN_MISMATCH', '已登记方法内容与模板固定版本不一致。',
                       method_package_ref=reference, expected_content_sha256=expected_hash)
        return {
            "identity": identity,
            "graph_sha256": revision.graph_sha256,
            "graph_snapshot": revision.graph_snapshot,
            "ports": ports,
            "known": {port["exchange_id"] for port in ports},
            "packages": packages,
            # A copy is created on the template's editable source, so the frozen boundaries it may
            # narrow are that source's own: a boundary from another application could never be
            # frozen into a saved template or carried into a project created from it.
            "boundaries": self._frozen_boundaries(db, identity["source_application_id"]),
        }

    def read(self, template_id: str, language: str = "zh") -> dict[str, Any]:
        with self.c.database.session() as db:
            context = self._context(db, template_id)
            identity = context["identity"]
            ports, known, packages = context["ports"], context["known"], context["packages"]
            methods = [self._official_entry(ref, packages[ref], ports, known, context["boundaries"])
                       for ref in identity["method_package_refs"] if ref in packages]
            missing = [ref for ref in identity["method_package_refs"] if ref not in packages]
            methods.extend(self._user_entry(snapshot, ports, known) for snapshot in identity["user_methods"])
            methods.extend(self._source_entries(db, identity, ports, known))
            tasks, other_scheme_keys = self._task_view(methods, self._task_declaration(identity))
        template = {key: value for key, value in identity.items() if key != "user_methods"}
        from .case_display import display_project_graph
        from .flow_display import exact_flow_labels
        labels, display_issues = exact_flow_labels(self.c.client, context["graph_snapshot"], language)
        display_graph, _ = display_project_graph(context["graph_snapshot"], self.c.settings.casepack_roots, language, labels)
        template["model"] = {
            "process_count": len({port["process_id"] for port in ports}),
            "port_count": len(ports),
            "graph_sha256": context["graph_sha256"],
            "graph_basis": "source_revision",
            "graph_snapshot": display_graph,
            "flow_display_issues": display_issues,
        }
        template["unresolved_method_package_refs"] = missing
        return {"schema_version": SCHEMA_VERSION, "template": template, "methods": methods,
                "tasks": tasks, "other_scheme_keys": other_scheme_keys}

    def _task_declaration(self, identity: dict[str, Any]) -> list[dict[str, Any]] | None:
        """The task roles this template version's schemes are grouped into, from its own library.

        A template seeded with a task-declaring library carries it in `accounting_library`; an older
        installation is re-resolved from its structural profile so it still gets the task view as long
        as the current library covers the same exact packages. Resolving the declaration is a
        presentation concern, so any failure falls back to the flat per-package view instead of
        breaking the read model.
        """
        library = identity.get("accounting_library") or {}
        tasks = library.get("tasks")
        if isinstance(tasks, list) and tasks:
            return tasks
        profile = identity.get("template_profile")
        if not isinstance(profile, dict):
            return None
        from .template_method_libraries import load_template_method_library
        try:
            resolved = load_template_method_library(profile)
        except DomainError:
            return None
        if not resolved:
            return None
        declared = resolved[0].get("tasks")
        return declared if isinstance(declared, list) and declared else None

    def _task_view(self, methods: list[dict[str, Any]],
                   declaration: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]] | None, list[str]]:
        """Group the flat scheme list into reader-facing tasks without duplicating entry data.

        Each task names the method keys of its presets (the declared default first) and of the user
        copies that belong to it; the entries themselves stay in `methods`. Any scheme no task claims
        is returned in `other_scheme_keys` so nothing is hidden when a declaration does not cover it.
        """
        if not declaration:
            return None, []
        official_key_by_ref: dict[str, str] = {}
        for entry in methods:
            if entry["origin"] == "official_package" and entry.get("base_method_ref"):
                ref = f"{entry['base_method_ref']['package_id']}@{entry['base_method_ref']['version']}"
                official_key_by_ref[ref] = entry["method_key"]
        tasks: list[dict[str, Any]] = []
        claimed: set[str] = set()
        for task in declaration:
            role = task.get("role")
            group = TASK_ROLE_GROUP.get(role)
            if group is None:
                continue
            refs = list(task.get("refs") or [])
            default_ref = task.get("default_ref")
            if default_ref in refs:
                refs = [default_ref, *(ref for ref in refs if ref != default_ref)]
            preset_keys = [official_key_by_ref[ref] for ref in refs if ref in official_key_by_ref]
            # Only the library's declared choices are user-facing. Bound legacy packages
            # remain addressable in methods for history and exact component references.
            claimed.update(preset_keys)
            user_scheme_keys = [entry["method_key"] for entry in methods
                                if entry["origin"] != "official_package" and entry["method_group"] == group]
            claimed.update(user_scheme_keys)
            tasks.append({"role": role, "default_ref": default_ref,
                          "preset_keys": preset_keys, "user_scheme_keys": user_scheme_keys})
        other_scheme_keys = [entry["method_key"] for entry in methods
                             if entry["origin"] != "official_package" and entry["method_key"] not in claimed]
        return tasks, other_scheme_keys

    def copy_official(self, template_id: str, payload) -> dict[str, Any]:
        """Create the user working copy of one official scheme this template version binds.

        The copy is an ordinary draft method on the template's exact source revision, created
        through the existing user-method contract; the official package is never written to. Its
        rules are exactly the package's own declarations, so the copy starts as a faithful variant
        the reader then narrows - undeclared ports stay undeclared instead of being filled in.
        """
        with self.c.database.session() as db:
            context = self._context(db, template_id)
            identity = context["identity"]
            ref = payload.method_key[len("official:"):] if payload.method_key.startswith("official:") else ""
            package = context["packages"].get(ref)
            if package is None:
                refuse("TEMPLATE_METHOD_COPY_SOURCE_NOT_FOUND",
                       "该模板版本没有绑定这个官方方案，无法复制。", 404,
                       template_id=template_id, method_key=payload.method_key,
                       bound=sorted(context["packages"]))
            kind = package.package_kind
            if kind not in COPYABLE_KINDS:
                refuse("TEMPLATE_METHOD_COPY_UNSUPPORTED",
                       "这个官方方案类型没有可复制的逐流规则声明。",
                       template_id=template_id, method_key=payload.method_key, package_kind=kind)
            base_ref = {"package_id": package.package_id, "version": package.version,
                        "content_sha256": package.content_sha256}
            transcribed = transcribe_official_rules(kind, package.manifest or {}, context["ports"],
                                                    f"{package.package_id}@{package.version}")
            purpose = PURPOSE_BY_KIND[kind]
            boundary_ref = payload.cbam_boundary_ref
            if purpose == "cbam":
                boundary_ref = self._cbam_boundary(context["boundaries"], boundary_ref)
            elif boundary_ref:
                refuse("TEMPLATE_METHOD_COPY_BOUNDARY_NOT_ALLOWED",
                       "只有 CBAM 方案可以绑定冻结边界。", 422,
                       method_key=payload.method_key, package_kind=kind)
            ports, known = context["ports"], context["known"]
            application_id = identity["source_application_id"]
            revision_id = identity["source_revision_id"]
        declared = set(transcribed["declared_exchange_ids"])
        service = self.c.calculation_methods
        method = service.create_method(application_id, CalculationMethodCreate(
            name=payload.name,
            purpose=purpose,
            model_revision_id=revision_id,
            description=payload.description if payload.description is not None
            else f"复制自官方方案 {base_ref['package_id']}@{base_ref['version']}",
            cbam_boundary_ref=boundary_ref,
            rules=transcribed["rules"],
            reporting_dimensions=transcribed["reporting_dimensions"],
        ))
        return {
            "schema_version": COPY_SCHEMA_VERSION,
            # Serialized through the same schema the method detail route uses, so the editor can
            # open the copy straight from this response without a second contract.
            "method": CalculationMethodDetailOut.model_validate(service.build_detail(method)
                                                                ).model_dump(mode="json"),
            "transcription": {
                "template_id": template_id,
                "method_key": payload.method_key,
                "package_kind": kind,
                "purpose": purpose,
                "base_method_ref": base_ref,
                "application_id": application_id,
                "model_revision_id": revision_id,
                "cbam_boundary_ref": boundary_ref,
                "rule_count": len(transcribed["rules"]),
                "port_count": len(ports),
                "undeclared_port_count": len(ports) - len(declared & known),
                "declared_but_absent_from_model": sorted(declared - known),
                "declared_exchange_ids": transcribed["declared_exchange_ids"],
                "reporting_dimensions": transcribed["reporting_dimensions"],
                "reference_product_exchange_id": transcribed["reference_product_exchange_id"],
                "notes": transcribed["notes"],
                "definition_sha256": transcribed.get("definition_sha256"),
                "rule_sources": transcribed.get("rule_sources", []),
            },
        }

    def save_plan(self, template_id: str) -> dict[str, Any]:
        """What saving this template version as the reader's own would freeze, before they choose.

        The plan is the modification summary the workspace shows: the exact package pins, the working
        methods on this revision with their real check status, and the next free version. A method
        that has not passed its check is listed with the reason instead of being offered as ready,
        because the finalize contract would refuse it anyway.
        """
        with self.c.database.session() as db:
            context = self._context(db, template_id)
            identity = context["identity"]
            revision = db.get(SystemRevision, identity["source_revision_id"])
            packages = context["packages"]
            refs = identity["method_package_refs"]
            frozen = {(snapshot.get("reference") or {}).get("method_id")
                      for snapshot in identity["user_methods"]}
            return {
                "schema_version": SAVE_SCHEMA_VERSION,
                "template_id": identity["id"],
                "kind": identity["kind"],
                "official": identity["official"],
                "title": identity["title"],
                "version": identity["version"],
                "template_sha256": identity["template_sha256"],
                "suggested_title": (f"{identity['title']} · 我的模板" if identity["official"]
                                    else identity["title"]),
                "suggested_version": self._next_version(db, identity),
                "source_application_id": identity["source_application_id"],
                "source_model_id": identity["source_model_id"],
                "source_revision_id": identity["source_revision_id"],
                "expected_revision_sha256": revision.content_sha256,
                "method_pins": [{"package_id": packages[ref].package_id, "version": packages[ref].version,
                                 "content_sha256": packages[ref].content_sha256}
                                for ref in refs if ref in packages],
                "unresolved_method_package_refs": [ref for ref in refs if ref not in packages],
                "user_methods": self._save_candidates(db, identity, context["boundaries"], frozen),
            }

    def save_as_template(self, template_id: str, payload: TemplateSave) -> dict[str, Any]:
        """Freeze this template version, plus the reader's checked working methods, as a new template.

        Delegation is the point: the existing finalize service keeps the exact source, the model
        revision hash and the immutable-version rules, so a saved template is the same object a
        reviewed modelling return would have produced - not a second, weaker copy of it.
        """
        with self.c.database.session() as db:
            context = self._context(db, template_id)
            identity = context["identity"]
            revision = db.get(SystemRevision, identity["source_revision_id"])
            packages = context["packages"]
            unresolved = [ref for ref in identity["method_package_refs"] if ref not in packages]
            if unresolved:
                # Dropping a scheme the template binds would silently publish a narrower template.
                refuse("TEMPLATE_SAVE_METHOD_UNRESOLVED",
                       "模板绑定的方案包无法解析，不能保存为我的模板。",
                       template_id=template_id, unresolved=unresolved)
            pins = [{"package_id": packages[ref].package_id, "version": packages[ref].version,
                     "content_sha256": packages[ref].content_sha256}
                    for ref in identity["method_package_refs"]]
            source = {"template_id": identity["id"], "title": identity["title"],
                      "version": identity["version"], "template_sha256": identity["template_sha256"],
                      "source_application_id": identity["source_application_id"],
                      "source_model_id": identity["source_model_id"],
                      "source_revision_id": identity["source_revision_id"]}
        from .authored_project_templates import AuthoredProjectTemplateService, PublishAuthoredTemplate
        saved = AuthoredProjectTemplateService(self.c).publish(PublishAuthoredTemplate(
            title=payload.title, version=payload.version,
            source_application_id=source["source_application_id"],
            source_model_id=source["source_model_id"],
            source_revision_id=source["source_revision_id"],
            expected_revision_sha256=revision.content_sha256,
            methods=pins, user_methods=list(payload.user_methods)))
        return {"schema_version": SAVE_SCHEMA_VERSION, "template": saved, "source_template": source,
                "frozen_user_methods": [ref.model_dump() for ref in payload.user_methods]}

    def _next_version(self, db, identity: dict[str, Any]) -> str:
        """The next free numeric version of the title being saved; never an existing one.

        An official template is saved under a new name, so it starts at 1.0.0; a template of the
        reader's own keeps its title and continues its own numeric line.
        """
        title = identity["title"] if not identity["official"] else f"{identity['title']} · 我的模板"
        numeric = []
        for value in db.scalars(select(AuthoredProjectTemplate.version).where(
                AuthoredProjectTemplate.title == title)):
            parts = str(value).split(".")
            if parts and all(part.isdigit() for part in parts):
                numeric.append(([int(part) for part in parts] + [0, 0, 0])[:3])
        if not numeric:
            return "1.0.0"
        highest = max(numeric)
        return ".".join(str(part) for part in [highest[0], highest[1], highest[2] + 1])

    def _save_candidates(self, db, identity: dict[str, Any], boundaries: list[dict[str, Any]],
                         frozen: set) -> list[dict[str, Any]]:
        """The working methods on this exact revision, each with the reason it can or cannot be frozen."""
        frozen_boundaries = {item["id"] for item in boundaries}
        rows = db.scalars(select(CalculationMethod).where(
            CalculationMethod.application_id == identity["source_application_id"],
            CalculationMethod.model_revision_id == identity["source_revision_id"],
        ).order_by(CalculationMethod.created_at))
        candidates = []
        for method in rows:
            version = db.scalar(select(CalculationMethodVersion)
                                .where(CalculationMethodVersion.method_id == method.id)
                                .order_by(CalculationMethodVersion.version.desc()).limit(1))
            status = str(version.status if version is not None else "draft")
            boundary_ref = version.cbam_boundary_ref if version is not None else None
            already = method.id in frozen
            blocking = None
            if already:
                blocking = "METHOD_ALREADY_IN_TEMPLATE"
            elif method.status == "retired":
                blocking = "METHOD_NOT_VALIDATED"
            elif version is None:
                blocking = "METHOD_HAS_NO_VERSION"
            elif status != "ready":
                blocking = "METHOD_NOT_VALIDATED"
            elif boundary_ref and boundary_ref not in frozen_boundaries:
                blocking = "METHOD_BOUNDARY_NOT_FROZEN_IN_SOURCE"
            purpose = str(method.purpose or "")
            candidates.append({
                "method_id": method.id,
                "name": method.name,
                "purpose": purpose,
                "method_group": METHOD_GROUPS.get(purpose, "user"),
                "version": version.version if version is not None else 0,
                "content_sha256": version.content_sha256 if version is not None else None,
                "status": status,
                "rule_count": len((version.rules if version is not None else None) or []),
                "reporting_dimension_count": len(
                    (version.reporting_dimensions if version is not None else None) or []),
                "semantics": version.semantics if version is not None else None,
                "cbam_boundary_ref": boundary_ref,
                "already_frozen_in_template": already,
                "savable": blocking is None,
                "blocking_reason": blocking,
            })
        return candidates

    def _cbam_boundary(self, boundaries: list[dict[str, Any]], explicit: str | None) -> str:
        """The frozen CBAM boundary a copied CBAM variant has to name - never a guessed one."""
        candidates = [item for item in boundaries if item["boundary_type"] == "cbam_trial"]
        available = [{"id": item["id"], "name": item["name"], "graph_sha256": item["graph_sha256"]}
                     for item in candidates]
        if explicit is not None:
            if not any(item["id"] == explicit for item in candidates):
                refuse("TEMPLATE_METHOD_COPY_BOUNDARY_NOT_FOUND",
                       "指定的冻结 CBAM 边界不属于该模板来源。", 404,
                       cbam_boundary_ref=explicit, available=available)
            return explicit
        if not candidates:
            refuse("TEMPLATE_METHOD_COPY_BOUNDARY_MISSING",
                   "该模板来源没有冻结的 CBAM 边界，复制出的方案无法通过校验；请先冻结边界。",
                   available=available)
        if len(candidates) > 1:
            refuse("TEMPLATE_METHOD_COPY_BOUNDARY_AMBIGUOUS",
                   "该模板来源有多个冻结的 CBAM 边界，请明确选择要复制哪一个。", available=available)
        return candidates[0]["id"]

    def _authored_identity(self, db, row: AuthoredProjectTemplate) -> dict[str, Any]:
        # The frozen template content, not the live source application: publishing rewrites
        # method_package_refs to exactly the pins that version selected.
        content = row.content or {}
        context = content.get("context") or {}
        return {
            "id": row.id, "kind": "authored", "title": row.title, "version": row.version,
            "template_sha256": row.content_sha256, "display_name": None, "official": False,
            "editable": True,
            "source_application_id": row.source_application_id,
            "source_model_id": row.source_model_id,
            "source_revision_id": row.source_revision_id,
            "capabilities": list(content.get("capabilities") or []),
            "template_profile": (context.get("modeling_template_binding") or {}).get("profile"),
            "method_package_refs": list(context.get("method_package_refs") or []),
            "method_pins": {f"{pin['package_id']}@{pin['version']}": pin.get("content_sha256")
                            for pin in content.get("methods") or []},
            "user_methods": [dict(item) for item in content.get("user_methods") or []],
        }

    def _seed_identity(self, db, row: SeedInstallation) -> dict[str, Any]:
        # _source replays the exact template version: profile replacements, method pins and the
        # editor source revision the workspace will actually edit.
        from .seed_projects import SeedProjectService
        _, _, _, content, item, _ = SeedProjectService(self.c)._source(db, row.id)
        source_context = content.get("source_context") or {}
        return {
            "id": item["id"], "kind": "seed", "title": item["title"], "version": item["version"],
            "template_sha256": item["template_sha256"],
            "display_name": item.get("display_name"), "official": True, "editable": False,
            "source_application_id": item["source_application_id"],
            "source_model_id": item["source_model_id"],
            "source_revision_id": item["source_revision_id"],
            "capabilities": list(content.get("capabilities") or []),
            "template_profile": content.get("profile"),
            "accounting_library": content.get("accounting_library"),
            # The installation row is the authority for the bundle identity: the catalog item only
            # carries reader-facing fields, so seed_version and the bundle hash are not on it.
            "seed": {"seed_id": row.seed_id, "seed_version": row.seed_version,
                     "bundle_content_sha256": row.bundle_content_sha256},
            "method_package_refs": list(source_context.get("method_package_refs") or []),
            "method_pins": dict(content.get("method_pins") or {}),
            "boundary_pins": dict(content.get("boundary_pins") or {}),
            "user_methods": [],
            "installed_application_id": item["installed_application_id"],
        }

    def _packages(self, db, refs: list[str]) -> dict[str, MethodPackage]:
        ids = {ref.rsplit("@", 1)[0] for ref in refs}
        if not ids:
            return {}
        rows = db.scalars(select(MethodPackage).where(MethodPackage.package_id.in_(sorted(ids))))
        # Only the pinned versions this template version binds are its methods: another registered
        # version of the same package id is a different scheme and must not be reachable from here.
        return {f"{row.package_id}@{row.version}": row for row in rows
                if f"{row.package_id}@{row.version}" in set(refs)}

    def _frozen_boundaries(self, db, application_id: str) -> list[dict[str, Any]]:
        rows = db.scalars(select(BoundaryDefinition).where(
            BoundaryDefinition.application_id == application_id,
            BoundaryDefinition.status == "frozen").order_by(BoundaryDefinition.created_at))
        return [{"id": row.id, "name": row.name, "boundary_type": row.boundary_type,
                 "status": row.status, "period_id": row.period_id,
                 "method_package_ref": row.method_package_ref,
                 "graph_sha256": (row.geographic_scope or {}).get("graph_sha256"),
                 "included_process_count": len(row.included_process_ids or []),
                 "included_flow_rule_count": len(row.included_flow_rules or []),
                 "excluded_item_count": len(row.excluded_items or [])} for row in rows]

    def _rule_source(self, declared: list[dict[str, Any]], ports: list[dict], known: set[str],
                     kind: str, provenance: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        ids = {item["exchange_id"] for item in declared}
        return {
            "kind": kind,
            "declared": declared,
            "declared_count": len(ids),
            "port_count": len(ports),
            "undeclared_port_count": len(ports) - len(ids & known),
            "declared_but_absent_from_model": sorted(ids - known),
            "provenance": provenance or [],
        }

    def _official_entry(self, ref: str, package: MethodPackage, ports: list[dict], known: set[str],
                        boundaries: list[dict[str, Any]]) -> dict[str, Any]:
        manifest = package.manifest or {}
        declared = group_declarations(declared_exchanges(manifest.get("classification_rules")))
        # Cards and copies must expose the same expanded identity set. Retain legacy
        # declarations (including absent ports/product references) alongside selectors.
        transcribed = transcribe_official_rules(package.package_kind, manifest, ports, ref)
        expanded = [{"exchange_id": rule["exchange_id"],
                     "rule_path": "classification_rules.controlled_process_mode"}
                    for rule in transcribed["rules"]
                    if rule["exchange_id"] not in {item["exchange_id"] for item in declared}]
        if manifest.get("accounting_rule_definition") is not None:
            declared = []
            expanded = [{"exchange_id": item["exchange_id"],
                         "rule_path": f"accounting_rule_definition.selectors.{selector_id}"}
                        for item in transcribed["rule_sources"] for selector_id in item["selector_ids"]]
        declared = group_declarations([
            {"exchange_id": item["exchange_id"], "rule_path": path}
            for item in declared for path in item["rule_paths"]] + expanded)
        gaps = package_gaps(manifest)
        gaps.extend(note for note in transcribed["notes"] if note["code"] == "PACKAGE_CONTROL_MODE_UNSUPPORTED")
        absent = sorted({item["exchange_id"] for item in declared} - known)
        if absent:
            gaps.append({"code": "DECLARED_PORT_ABSENT_FROM_MODEL", "message": ", ".join(absent),
                         "source_path": "classification_rules"})
        if not declared:
            gaps.append({"code": "NO_PER_FLOW_DECLARATION",
                         "message": "该官方包未声明逐流规则，只提供口径与因子边界。",
                         "source_path": "classification_rules"})
        kind = package.package_kind
        entry = {
            "method_key": f"official:{ref}",
            "purpose": kind,
            "method_group": METHOD_GROUPS.get(kind, "other"),
            "origin": "official_package",
            "display_name": None,
            "editable": False,
            "actions": ["view", "copy_and_adjust"],
            "base_method_ref": {"package_id": package.package_id, "version": package.version,
                                "content_sha256": package.content_sha256},
            "rule_source": self._rule_source(declared, ports, known,
                                             "official_package_classification" if declared else "none",
                                             package_provenance(manifest)),
            "coverage_gaps": gaps,
            "user_method": None,
            "check": {"status": "gap" if gaps else "ready", "status_basis": "official_package_declaration",
                      "problem_count": len(gaps), "problems": []},
            "package_detail": {
                "jurisdiction": package.jurisdiction,
                "assurance_level": manifest.get("assurance_level"),
                "boundary_schema": manifest.get("boundary_schema") or {},
                "output_schema": manifest.get("output_schema") or {},
                "accepted_units": manifest.get("accepted_units") or {},
                "formula_graph": manifest.get("formula_graph") or {},
            },
        }
        if entry["method_group"] == "cbam":
            entry["cbam_boundaries"] = boundaries
        return entry

    def _user_entry(self, snapshot: dict[str, Any], ports: list[dict], known: set[str]) -> dict[str, Any]:
        reference = snapshot.get("reference") or {}
        rules = snapshot.get("rules") or []
        declared = group_declarations([
            {"exchange_id": rule.get("exchange_id"), "rule_path": f"rules[{index}]"}
            for index, rule in enumerate(rules)
            if isinstance(rule, dict) and isinstance(rule.get("exchange_id"), str)
        ])
        purpose = str(snapshot.get("purpose") or "")
        return {
            "method_key": f"user:{reference.get('method_id')}@{reference.get('version')}",
            "purpose": purpose,
            "method_group": METHOD_GROUPS.get(purpose, "user"),
            "origin": "template_user_method",
            "display_name": {"zh": snapshot.get("name") or "", "en": snapshot.get("name") or ""},
            "editable": True,
            "actions": ["view", "edit", "save_draft", "check"],
            "base_method_ref": None,
            "rule_source": self._rule_source(declared, ports, known, "user_method_rules"),
            "coverage_gaps": [],
            "user_method": {
                "method_id": reference.get("method_id"),
                "version": reference.get("version"),
                "content_sha256": reference.get("content_sha256"),
                "status": "frozen_snapshot",
                "name": snapshot.get("name"),
                "description": snapshot.get("description"),
                "origin_method_id": None,
                "origin_method_version": None,
                "model_processing_rules_ref": snapshot.get("model_processing_rules_ref"),
                "cbam_boundary_ref": snapshot.get("cbam_boundary_ref"),
                "rule_count": len(rules),
                "reporting_dimension_count": len(snapshot.get("reporting_dimensions") or []),
                "semantics": snapshot.get("semantics"),
                "reporting_dimensions": deepcopy(snapshot.get("reporting_dimensions") or []),
            },
            "check": {"status": "not_validated", "status_basis": "template_snapshot",
                      "problem_count": 0, "problems": []},
        }

    def _source_entries(self, db, identity: dict[str, Any], ports: list[dict], known: set[str]) -> list[dict[str, Any]]:
        """Working methods on this exact template version that are not frozen into the template.

        A copied official scheme is an ordinary draft on the source revision, so without this it
        would be listed only while the copy response is in hand and would vanish from the template
        it was copied into after a refresh.
        """
        frozen = {(snapshot.get("reference") or {}).get("method_id")
                  for snapshot in identity["user_methods"]}
        rows = db.scalars(select(CalculationMethod).where(
            CalculationMethod.application_id == identity["source_application_id"],
            CalculationMethod.model_revision_id == identity["source_revision_id"],
        ).order_by(CalculationMethod.created_at))
        entries = []
        for method in rows:
            if method.id in frozen:
                continue
            version = db.scalar(select(CalculationMethodVersion)
                                .where(CalculationMethodVersion.method_id == method.id)
                                .order_by(CalculationMethodVersion.version.desc()).limit(1))
            entries.append(self._source_entry(method, version, ports, known))
        return entries

    def _source_entry(self, method: CalculationMethod, version: CalculationMethodVersion | None,
                      ports: list[dict], known: set[str]) -> dict[str, Any]:
        rules = (version.rules if version is not None else None) or []
        dimensions = (version.reporting_dimensions if version is not None else None) or []
        declared = group_declarations([
            {"exchange_id": rule.get("exchange_id"), "rule_path": f"rules[{index}]"}
            for index, rule in enumerate(rules)
            if isinstance(rule, dict) and isinstance(rule.get("exchange_id"), str)
        ])
        purpose = str(method.purpose or "")
        status = str(version.status if version is not None else "draft")
        actions = ["view", "edit", "save_draft", "check"]
        if status == "ready":
            actions.append("run")
        return {
            "method_key": f"source:{method.id}@{version.version if version is not None else 0}",
            "purpose": purpose,
            "method_group": METHOD_GROUPS.get(purpose, "user"),
            "origin": "source_user_method",
            "display_name": {"zh": method.name, "en": method.name},
            "editable": True,
            "actions": actions,
            "base_method_ref": None,
            "rule_source": self._rule_source(declared, ports, known, "user_method_rules"),
            "coverage_gaps": [],
            "user_method": {
                "method_id": method.id,
                "version": version.version if version is not None else 0,
                "content_sha256": version.content_sha256 if version is not None else None,
                "status": status,
                "name": method.name,
                "description": method.description,
                "origin_method_id": method.origin_method_id,
                "origin_method_version": method.origin_method_version,
                "model_processing_rules_ref": version.model_processing_rules_ref if version is not None else None,
                "cbam_boundary_ref": version.cbam_boundary_ref if version is not None else None,
                "rule_count": len(rules),
                "reporting_dimension_count": len(dimensions),
                "semantics": version.semantics if version is not None else None,
                "reporting_dimensions": deepcopy(dimensions),
            },
            "check": {"status": "ready" if status == "ready" else "not_validated",
                      "status_basis": "method_version_status",
                      "problem_count": 0, "problems": []},
        }
