"""Derive the calculation model one accounting purpose needs, before anything is solved.

Nebula LCA characterises the system it is asked to solve, so an accounting purpose that covers fewer
processes, or that must not carry an embedded supply chain, needs a different calculation model - not
a different reading of one shared answer. This module turns the stored model plus the saved background
associations and demand into that purpose-specific model by performing only the graph operations a
reviewed rule package declared, and records every difference. It never touches the stored model, and
it never computes or filters an emission value: that stays with the engine and the method packages.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .hashing import canonical_graph_sha256
from .emission_selectors import selector_matches
from .model_processing_contract import (
    ExchangeClassification,
    ModelProcessingRules,
    PackageRef,
)
from .errors import DomainError

DERIVATION_SCHEMA_VERSION = "nebula_one.model-derivation-record.v1"

# A pre-limited template is a claim about the exact identity of every emission flow, so a field the
# model does not carry cannot confirm the claim: absent, empty and different all refuse.
_REQUIRED_FLOW_IDENTITY = (
    "flowSourceNamespace",
    "flowUuid",
    "flowVersion",
    "flowPropertyUuid",
    "flowPropertyVersion",
    "unitGroupUuid",
    "unitGroupVersion",
    "unit",
    "direction",
)
# The method package names a compartment; the stored model records none, so requiring one would
# invent an identity the model never carried. Compared only when both sides do have it.
_OPTIONAL_FLOW_IDENTITY = ("compartment",)
_FLOW_IDENTITY_FIELDS = {
    "flowSourceNamespace": "source_namespace",
    "flowUuid": "flow_uuid",
    "flowVersion": "version",
    "flowPropertyUuid": "flow_property_uuid",
    "flowPropertyVersion": "flow_property_version",
    "unitGroupUuid": "unit_group_uuid",
    "unitGroupVersion": "unit_group_version",
    "unit": "unit",
    "direction": "direction",
    "compartment": "compartment",
}


def _carried(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or value.strip() != "")


# A mapped field in neither set would be skipped silently, which is the exact failure this identity
# gate exists to catch - so the split has to cover the mapping.
_UNCLASSIFIED_FLOW_IDENTITY = sorted(
    set(_FLOW_IDENTITY_FIELDS) - set(_REQUIRED_FLOW_IDENTITY) - set(_OPTIONAL_FLOW_IDENTITY)
)
if _UNCLASSIFIED_FLOW_IDENTITY:  # pragma: no cover - guards the module's own tables
    raise RuntimeError(
        "flow identity fields need a required/optional classification: "
        + ", ".join(_UNCLASSIFIED_FLOW_IDENTITY)
    )


@dataclass(frozen=True)
class DerivedCalculationModel:
    """One purpose's calculation model, plus the evidence of how it was derived."""

    purpose: str
    rules_reference: dict[str, Any]
    graph: dict[str, Any]
    demand: list[dict[str, Any]]
    background_process_pins: list[dict[str, Any]]
    mapped_background_process_pins: list[dict[str, Any]]
    project_background_pins: list[dict[str, Any]]
    source_graph_sha256: str
    derived_graph_sha256: str
    method_package_references: list[dict[str, Any]]
    process_map: list[dict[str, Any]]
    exchange_map: list[dict[str, Any]]
    flow_map: list[dict[str, Any]]
    actions: list[dict[str, Any]]

    @property
    def graph_hash(self) -> str:
        return self.derived_graph_sha256

    def record(self) -> dict[str, Any]:
        """The derivation receipt: enough to re-derive, replay, or audit one frozen answer."""
        return {
            "schema_version": DERIVATION_SCHEMA_VERSION,
            "purpose": self.purpose,
            "model_processing_rules": self.rules_reference,
            "source_graph_sha256": self.source_graph_sha256,
            "derived_graph_sha256": self.derived_graph_sha256,
            "method_packages": self.method_package_references,
            "process_map": self.process_map,
            "exchange_map": self.exchange_map,
            "flow_map": self.flow_map,
            "actions": self.actions,
            "effective_background_process_pins": self.background_process_pins,
            "effective_mapped_background_process_pins": self.mapped_background_process_pins,
            **({"effective_project_background_pins": self.project_background_pins} if self.project_background_pins else {}),
            "counts": {
                "source_processes": len(self.process_map),
                "derived_processes": sum(1 for item in self.process_map if item["state"] == "kept"),
                "source_exchanges": len(self.exchange_map),
                "removed_exchanges": sum(
                    1 for item in self.exchange_map if item["state"] != "kept"
                ),
                "classified_emission_exchanges": len(self.flow_map),
                "excluded_emission_exchanges": sum(
                    1 for item in self.flow_map if item["state"] == "excluded"
                ),
                "boundary_inputs": sum(
                    1 for action in self.actions if action["action"] == "keep_boundary_input"
                ),
                "unlinked_background_links": sum(
                    1 for action in self.actions if action["action"] == "unlink_background"
                ),
            },
        }


def _refuse(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def _dig(manifest: dict[str, Any], path: str, declaration: str) -> Any:
    cursor: Any = manifest
    for part in path.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            _refuse(
                "MODEL_PROCESSING_DECLARATION_UNREADABLE",
                f"the model processing rule '{declaration}' points at '{path}',"
                " which the bound method package does not declare",
                declaration=declaration,
                manifest_path=path,
            )
        cursor = cursor[part]
    return cursor


def _port_key(node_id: str, port: dict[str, Any]) -> str:
    return f"{node_id}::{port.get('id')}"


def _indexed_ports(graph: dict[str, Any]) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """Every port of the graph, addressed the way a background pin addresses it."""
    return {
        _port_key(node["id"], port): (node, port)
        for node in graph.get("nodes") or []
        for port in [*(node.get("inputs") or []), *(node.get("outputs") or [])]
    }


def _unconnected_inputs(graph: dict[str, Any]) -> set[str]:
    connected = {
        (exchange.get("toNode"), exchange.get("targetPortId"))
        for exchange in graph.get("exchanges") or []
    }
    return {
        _port_key(node["id"], port)
        for node in graph.get("nodes") or []
        for port in node.get("inputs") or []
        if (node["id"], port.get("id")) not in connected
    }


def _identity_drift(
    rule: dict[str, Any], port: dict[str, Any], node: dict[str, Any]
) -> dict[str, Any]:
    """Where a method's declared emission identity and the model's own disagree, field by field.

    Absent on either side is not agreement: a claim the model cannot confirm is as much a mismatch as
    a contradicting value. Both emission-selection modes compare through this one function so a
    reviewed exclusion cannot be held to a weaker identity than a reviewed inclusion.
    """
    mismatches: dict[str, Any] = {}
    for port_key, rule_key in _FLOW_IDENTITY_FIELDS.items():
        model_value = port.get(port_key)
        method_value = rule.get(rule_key)
        if port_key in _REQUIRED_FLOW_IDENTITY:
            if not _carried(model_value) or not _carried(method_value):
                mismatches[port_key] = {
                    "model": model_value if _carried(model_value) else None,
                    "method": method_value if _carried(method_value) else None,
                    "absent_on": [
                        side
                        for side, value in (("model", model_value), ("method", method_value))
                        if not _carried(value)
                    ],
                }
            elif model_value != method_value:
                mismatches[port_key] = {"model": model_value, "method": method_value}
        elif (
            port_key in _OPTIONAL_FLOW_IDENTITY
            and _carried(model_value)
            and _carried(method_value)
            and model_value != method_value
        ):
            mismatches[port_key] = {"model": model_value, "method": method_value}
    model_process = node.get("process_uuid")
    method_process = rule.get("process_uuid")
    if (
        not _carried(model_process)
        or not _carried(method_process)
        or str(model_process) != str(method_process)
    ):
        mismatches["process_uuid"] = {
            "model": model_process if _carried(model_process) else None,
            "method": method_process if _carried(method_process) else None,
        }
    return mismatches


class _Derivation:
    def __init__(
        self,
        *,
        graph: dict[str, Any],
        demand: list[dict[str, Any]],
        background_process_pins: list[dict[str, Any]],
        mapped_background_process_pins: list[dict[str, Any]],
        project_background_pins: list[dict[str, Any]],
        rules: ModelProcessingRules,
        purpose: str,
        method_packages: list[dict[str, Any]],
    ) -> None:
        self.source_graph = graph
        self.source_graph_sha256 = canonical_graph_sha256(graph)
        self.rules = rules
        self.purpose = purpose
        self.intent = rules.purpose(purpose)
        self.demand = deepcopy(demand)
        self.saved_pins = {
            "background": deepcopy(background_process_pins or []),
            "mapped": deepcopy(mapped_background_process_pins or []),
            "project": deepcopy(project_background_pins or []),
        }
        self.method_packages = {
            str(item.get("package_id")): item for item in (method_packages or [])
        }
        self.actions: list[dict[str, Any]] = []
        self.flow_map: list[dict[str, Any]] = []
        self.bound: dict[str, dict[str, Any]] = {}
        self.graph = deepcopy(graph)

    # ---- bound method packages ---------------------------------------------

    def package(self, ref: PackageRef, declaration: str) -> dict[str, Any]:
        package = self.method_packages.get(ref.package_id)
        if package is None:
            _refuse(
                "MODEL_PROCESSING_METHOD_PACKAGE_UNBOUND",
                f"the model processing rule '{declaration}' needs method package"
                f" {ref.package_id}@{ref.version}, which this calculation did not supply",
                declaration=declaration,
                package_id=ref.package_id,
                version=ref.version,
            )
        if package.get("version") != ref.version or package.get("content_sha256") != ref.content_sha256:
            _refuse(
                "MODEL_PROCESSING_METHOD_PACKAGE_MISMATCH",
                f"the supplied method package {ref.package_id} differs from the version and"
                f" content the rule '{declaration}' was reviewed against",
                declaration=declaration,
                expected={"version": ref.version, "content_sha256": ref.content_sha256},
                supplied={
                    "version": package.get("version"),
                    "content_sha256": package.get("content_sha256"),
                },
            )
        if not isinstance(package.get("manifest"), dict):
            _refuse(
                "MODEL_PROCESSING_METHOD_PACKAGE_UNBOUND",
                f"method package {ref.package_id} was supplied without the manifest the rule"
                f" '{declaration}' reads",
                declaration=declaration,
            )
        self.bound[ref.package_id] = {
            "package_id": ref.package_id,
            "version": ref.version,
            "content_sha256": ref.content_sha256,
        }
        return package

    # ---- steps --------------------------------------------------------------

    def select_processes(self) -> list[dict[str, Any]]:
        selection = self.intent.process_selection
        nodes = self.graph.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            _refuse(
                "MODEL_DERIVATION_GRAPH_INVALID",
                "a calculation model can only be derived from a graph that declares its processes",
            )
        by_uuid: dict[str, list[str]] = {}
        for node in nodes:
            if not isinstance(node, dict) or not node.get("id") or not node.get("process_uuid"):
                _refuse(
                    "MODEL_DERIVATION_GRAPH_INVALID",
                    "every process of a calculation model needs a graph instance id and a"
                    " standardised process uuid",
                )
            by_uuid.setdefault(str(node["process_uuid"]), []).append(str(node["id"]))
        shared = {uuid: ids for uuid, ids in by_uuid.items() if len(ids) > 1}
        if shared:
            # Renaming one uuid would fabricate a second instance the model author never froze.
            _refuse(
                "MODEL_DERIVATION_DUPLICATE_PROCESS_INSTANCE",
                "the same process uuid appears on more than one graph instance; the upstream solver"
                " addresses processes by uuid, so this cannot be derived by renaming it",
                process_uuids=sorted(shared),
                instances=shared,
            )

        if selection.mode == "all_model_processes":
            boundary: list[str] = []
            kept = [str(node["id"]) for node in nodes]
        else:
            package = self.package(selection.method_package, "process_selection")
            declared = _dig(
                package["manifest"],
                str(selection.process_uuids_path),
                "process_selection",
            )
            if not isinstance(declared, list) or not all(
                isinstance(item, str) and item for item in declared
            ):
                _refuse(
                    "MODEL_PROCESSING_DECLARATION_UNREADABLE",
                    "the method package boundary must be a list of standardised process uuids",
                    declaration="process_selection",
                )
            missing = [uuid for uuid in declared if uuid not in by_uuid]
            if missing:
                _refuse(
                    "MODEL_DERIVATION_PROCESS_NOT_IN_MODEL",
                    "the selected method boundary names processes this model does not contain;"
                    " the calculation template and the method package no longer match",
                    missing_process_uuids=missing,
                )
            boundary = sorted(str(uuid) for uuid in declared)
            selected = set(boundary)
            kept = [
                str(node["id"]) for node in nodes if str(node["process_uuid"]) in selected
            ]

        excluded = [str(node["id"]) for node in nodes if str(node["id"]) not in set(kept)]
        self.graph["nodes"] = [node for node in nodes if str(node["id"]) in set(kept)]
        self.kept_nodes = set(kept)
        self.kept_uuids = {
            str(node["process_uuid"]) for node in self.graph["nodes"]
        }
        self.method_boundary = boundary
        self.process_map = [
            {
                "source_node_id": str(node["id"]),
                "process_uuid": str(node["process_uuid"]),
                "state": "kept" if str(node["id"]) in self.kept_nodes else "excluded",
                "reason": None
                if str(node["id"]) in self.kept_nodes
                else "outside_selected_process_boundary",
                "derived_node_id": str(node["id"])
                if str(node["id"]) in self.kept_nodes
                else None,
            }
            for node in nodes
        ]
        self.actions.append(
            {
                "action": "select_processes",
                "mode": selection.mode,
                "method_package": (
                    selection.method_package.model_dump() if selection.method_package else None
                ),
                "kept_process_uuids": sorted(self.kept_uuids),
                "excluded_nodes": sorted(excluded),
            }
        )
        return kept

    def resolve_exchanges(self) -> None:
        source_edges = self.source_graph.get("exchanges") or []
        derived_edges: list[dict[str, Any]] = []
        cut: list[dict[str, Any]] = []
        for edge in source_edges:
            provider = str(edge.get("fromNode") or "")
            consumer = str(edge.get("toNode") or "")
            if provider in self.kept_nodes and consumer in self.kept_nodes:
                # A kept edge is copied, not borrowed: the stored model must survive any later edit
                # of the derived answer, and the derived answer must not change what is stored.
                derived_edges.append(deepcopy(edge))
                continue
            if consumer in self.kept_nodes:
                # The kept process loses its supplier: only a reviewed declaration may absorb it.
                cut.append(edge)
        self.graph["exchanges"] = derived_edges

        declared = {
            item.exchange_id: item
            for item in self.intent.cross_boundary_connections.boundary_exchanges
        }
        ports = _indexed_ports(self.graph)
        needed: list[str] = []
        for edge in cut:
            consumer = str(edge.get("toNode"))
            target_port_id = str(edge.get("targetPortId"))
            key = f"{consumer}::{target_port_id}"
            needed.append(key)
            rule = declared.get(key)
            if rule is None:
                continue
            node, port = ports.get(key, (None, None))
            if port is None:
                _refuse(
                    "MODEL_DERIVATION_PORT_MISSING",
                    "a declared boundary input no longer exists in the model, so the rule and the"
                    " template no longer match",
                    consumer_exchange_id=key,
                )
            edge_amount = edge.get("consumerAmount", edge.get("amount"))
            if port.get("amount") != edge_amount:
                # Turning a supplied link into a boundary input must not move a single quantity.
                _refuse(
                    "MODEL_CROSS_BOUNDARY_AMOUNT_CONFLICT",
                    "the declared boundary input's port amount differs from the supply exchange it"
                    " replaces, so cutting that link would change the activity data",
                    consumer_exchange_id=key,
                    port_amount=port.get("amount"),
                    exchange_amount=edge_amount,
                )
        undeclared = [edge for edge in cut if str(f"{edge.get('toNode')}::{edge.get('targetPortId')}") not in declared]
        if undeclared:
            _refuse(
                "MODEL_CROSS_BOUNDARY_UNDECLARED",
                "the selected processes cut a supply exchange that the rules do not declare how to"
                " keep; refusing rather than dropping the input or treating it as zero",
                consumer_exchange_ids=sorted(
                    f"{edge.get('toNode')}::{edge.get('targetPortId')}" for edge in undeclared
                ),
                exchange_ids=sorted(str(edge.get("id")) for edge in undeclared),
            )
        unused = sorted(set(declared) - set(needed))
        if unused:
            _refuse(
                "MODEL_CROSS_BOUNDARY_DECLARATION_UNUSED",
                "the rules declare a boundary input for a supply exchange this model does not cut;"
                " the template has changed underneath the reviewed rules",
                consumer_exchange_ids=unused,
            )
        for edge in cut:
            key = f"{edge.get('toNode')}::{edge.get('targetPortId')}"
            _, port = ports[key]
            self.actions.append(
                {
                    "action": "keep_boundary_input",
                    "consumer_exchange_id": key,
                    "removed_exchange_id": str(edge.get("id")),
                    "provider_node": str(edge.get("fromNode")),
                    "clause": declared[key].clause,
                    "amount": port.get("amount"),
                    "unit": port.get("unit"),
                    "flow_uuid": port.get("flowUuid"),
                    "flow_version": port.get("flowVersion"),
                    "flow_source_namespace": port.get("flowSourceNamespace"),
                }
            )
        self.exchange_map = []
        for edge in source_edges:
            consumer = str(edge.get("toNode"))
            provider = str(edge.get("fromNode"))
            if provider in self.kept_nodes and consumer in self.kept_nodes:
                state = "kept"
            elif consumer not in self.kept_nodes:
                state = "removed_with_excluded_process"
            else:
                state = "replaced_by_declared_boundary_input"
            self.exchange_map.append(
                {
                    "source_exchange_id": str(edge.get("id")),
                    "derived_exchange_id": str(edge.get("id")) if state == "kept" else None,
                    "state": state,
                    "consumer_exchange_id": f"{consumer}::{edge.get('targetPortId')}",
                }
            )
        dangling = [
            str(edge.get("id"))
            for edge in self.graph["exchanges"]
            if edge.get("fromNode") not in self.kept_nodes or edge.get("toNode") not in self.kept_nodes
        ]
        if dangling:
            _refuse(
                "MODEL_DERIVATION_DANGLING_EXCHANGE",
                "the derived model kept an exchange that points outside it",
                exchange_ids=dangling,
            )

    def preserve_reference_exchange(self) -> None:
        """The exchange a study reports on must survive the selection.

        Excluding a process is allowed; silently leaving the model without the output the stored
        metadata says it produces is not.
        """
        reference = (self.graph.get("metadata") or {}).get("reference_exchange_id")
        if not reference:
            return
        if str(reference) not in _indexed_ports(self.graph):
            _refuse(
                "MODEL_DERIVATION_REFERENCE_EXCHANGE_LOST",
                "the selected processes no longer contain the reference exchange this model reports"
                " on, so the calculation would have no functional output",
                reference_exchange_id=str(reference),
            )

    def resolve_demand(self) -> None:
        ports = _indexed_ports(self.graph)
        for item in self.demand:
            if not isinstance(item, dict):
                _refuse("MODEL_DERIVATION_DEMAND_INVALID", "a demand entry is not an object")
            uuid = item.get("process_uuid")
            if uuid is not None and str(uuid) not in self.kept_uuids:
                _refuse(
                    "MODEL_DERIVATION_DEMAND_ORPHANED",
                    "the saved demand targets a process this calculation model excludes, and"
                    " derivation never rewrites activity data",
                    process_uuid=str(uuid),
                )
            exchange_id = item.get("reference_exchange_id")
            if exchange_id is not None and str(exchange_id) not in ports:
                bare = {key.rsplit("::", 1)[-1] for key in ports}
                if str(exchange_id) not in bare:
                    _refuse(
                        "MODEL_DERIVATION_DEMAND_ORPHANED",
                        "the saved demand targets an exchange this calculation model no longer"
                        " contains, and derivation never rewrites activity data",
                        reference_exchange_id=str(exchange_id),
                    )
            flow_uuid = item.get("reference_flow_uuid")
            if flow_uuid is not None and not any(
                port.get("flowUuid") == flow_uuid for _, port in ports.values()
            ):
                _refuse(
                    "MODEL_DERIVATION_DEMAND_ORPHANED",
                    "the saved demand targets a flow this calculation model no longer contains",
                    reference_flow_uuid=str(flow_uuid),
                )

    def disposition_background(self) -> None:
        disposition = self.intent.background_disposition
        ports = _indexed_ports(self.graph)
        unconnected = _unconnected_inputs(self.graph)
        kept: dict[str, list[dict[str, Any]]] = {"background": [], "mapped": [], "project": []}

        if disposition.mode != "retain_saved_pins":
            package = self.package(
                disposition.evidence.method_package, "background_disposition"
            )
            value = _dig(
                package["manifest"],
                disposition.evidence.manifest_path,
                "background_disposition",
            )
            if value is not disposition.evidence.required_value:
                _refuse(
                    "MODEL_PROCESSING_EVIDENCE_NOT_DECLARED",
                    "the bound method package no longer declares the reading that justifies"
                    " dropping background links, so the links are kept",
                    manifest_path=disposition.evidence.manifest_path,
                    expected=disposition.evidence.required_value,
                    found=value,
                )
            clause = disposition.evidence.clause
        else:
            clause = None

        declared = {
            item.exchange_id
            for item in self.intent.cross_boundary_connections.boundary_exchanges
        }
        excluded_nodes = {
            item["source_node_id"]
            for item in self.process_map
            if item["state"] != "kept"
        }
        for kind, pins in self.saved_pins.items():
            for pin in pins:
                consumer_id = str(pin.get("consumer_exchange_id"))
                target = ports.get(consumer_id)
                if target is None or target[0]["id"] in excluded_nodes:
                    self.actions.append(
                        {
                            "action": "unlink_background",
                            "kind": kind,
                            "consumer_exchange_id": consumer_id,
                            "reason": "process_excluded",
                            "clause": None,
                        }
                    )
                    continue
                if consumer_id not in unconnected:
                    _refuse(
                        "MODEL_DERIVATION_PIN_CONFLICT",
                        "a saved background association sits on a port the model already supplies"
                        " internally, so the stored model and its pins disagree",
                        consumer_exchange_id=consumer_id,
                    )
                if disposition.mode == "retain_saved_pins":
                    kept[kind].append(pin)
                    continue
                retain = (
                    disposition.mode == "keep_declared_links_only"
                    and consumer_id in set(disposition.retained_consumer_exchange_ids)
                )
                if retain:
                    kept[kind].append(pin)
                    continue
                self.actions.append(
                    {
                        "action": "unlink_background",
                        "kind": kind,
                        "consumer_exchange_id": consumer_id,
                        "reason": disposition.mode,
                        "clause": clause,
                        "process_uuid": pin.get("process_uuid"),
                        "version": pin.get("version"),
                        "amount": target[1].get("amount"),
                        "unit": target[1].get("unit"),
                        "flow_uuid": target[1].get("flowUuid"),
                    }
                )
        self.background_process_pins = kept["background"]
        self.mapped_background_process_pins = kept["mapped"]
        self.project_background_pins = kept["project"]

    def verify_elementary_flows(self) -> None:
        flows = self.intent.elementary_flows
        if flows.mode == "not_applicable":
            return
        ports = _indexed_ports(self.graph)
        biosphere = {
            key: port
            for key, (node, port) in ports.items()
            if port.get("type") == "biosphere"
        }
        if flows.mode == "explicit_flow_rules":
            self.classify_emission_exchanges(flows, ports, biosphere)
            return

        evidence = flows.evidence
        package = self.package(evidence.method_package, "elementary_flows")
        manifest = package["manifest"]
        declared = _dig(manifest, evidence.manifest_path, "elementary_flows")
        if not isinstance(declared, list) or not all(isinstance(item, dict) for item in declared):
            _refuse(
                "MODEL_PROCESSING_DECLARATION_UNREADABLE",
                "the pre-limited emission set must be a list of exact flow rules",
                declaration="elementary_flows",
            )
        applicable_gases = (
            _dig(manifest, evidence.applicable_gases_path, "elementary_flows")
            if evidence.applicable_gases_path
            else None
        )
        if flows.mode == "identity_selector_rules":
            self.classify_identity_selected_emissions(
                declared, manifest, evidence, ports, biosphere, applicable_gases
            )
            return
        unnamed = sorted(
            index for index, rule in enumerate(declared) if not _carried(rule.get("exchange_id"))
        )
        if unnamed:
            _refuse(
                "MODEL_PROCESSING_DECLARATION_UNREADABLE",
                "a declared emission flow carries no exchange identity, so the pre-limited set"
                " cannot be matched against the model",
                declaration="elementary_flows",
                rule_indexes=unnamed,
            )
        claimed: set[str] = set()
        missing: list[dict[str, Any]] = []
        drift: list[dict[str, Any]] = []
        for rule in declared:
            exchange_id = str(rule.get("exchange_id"))
            claimed.add(exchange_id)
            port = biosphere.get(exchange_id)
            if port is None:
                missing.append({"exchange_id": exchange_id, "process_uuid": rule.get("process_uuid")})
                continue
            node_id = exchange_id.rsplit("::", 1)[0]
            node = ports[exchange_id][0]
            mismatches = _identity_drift(rule, port, node)
            if mismatches:
                drift.append({"exchange_id": exchange_id, "fields": mismatches, "node_id": node_id})
            if isinstance(applicable_gases, list) and rule.get("greenhouse_gas") not in applicable_gases:
                drift.append(
                    {
                        "exchange_id": exchange_id,
                        "fields": {"greenhouse_gas": {"method": rule.get("greenhouse_gas")}},
                        "reason": "not in the package's applicable gas set",
                    }
                )
        # A pre-limited template is a claim about the *whole* set, in both directions.
        undeclared = sorted(set(biosphere) - claimed)
        if missing or undeclared or drift:
            _refuse(
                "MODEL_ELEMENTARY_FLOW_TEMPLATE_MISMATCH",
                "the emission flows of the selected processes no longer match the reviewed method"
                " declaration exactly; the template or the method package changed, and no flow is"
                " dropped on a guess",
                missing_from_model=missing,
                undeclared_in_method=undeclared,
                identity_drift=drift,
            )
        self.actions.append(
            {
                "action": "verify_elementary_flows",
                "mode": "template_prelimited",
                "method_package": evidence.method_package.model_dump(),
                "manifest_path": evidence.manifest_path,
                "applicable_gases": applicable_gases,
                "verified_exchange_ids": sorted(claimed),
            }
        )

    def classify_identity_selected_emissions(
        self, declared, manifest, evidence, ports, biosphere, applicable_gases
    ) -> None:
        """Keep reviewed base exchanges and match additive streams by exact process/flow identity."""
        selectors = (manifest.get("classification_rules") or {}).get(
            "additional_direct_emission_selectors"
        )
        if not isinstance(selectors, list) or not selectors:
            _refuse("MODEL_PROCESSING_DECLARATION_UNREADABLE",
                    "the identity selector method declares no additional emission selectors")
        base = {}
        for rule in declared:
            exchange_id = str(rule.get("exchange_id") or "")
            if not exchange_id or exchange_id in base:
                _refuse("MODEL_PROCESSING_DECLARATION_UNREADABLE",
                        "the base emission declaration has a missing or duplicate exchange")
            base[exchange_id] = rule
        decisions = {}
        for exchange_id, rule in base.items():
            pair = ports.get(exchange_id)
            if pair is None or exchange_id not in biosphere:
                _refuse("MODEL_ELEMENTARY_FLOW_TEMPLATE_MISMATCH",
                        "a reviewed base emission is missing from the selected model",
                        missing_from_model=[exchange_id])
            node, port = pair
            drift = _identity_drift(rule, port, node)
            if drift:
                _refuse("MODEL_ELEMENTARY_FLOW_TEMPLATE_MISMATCH",
                        "a reviewed base emission identity changed", exchange_id=exchange_id,
                        identity_drift=drift)
            decisions[exchange_id] = (rule, "reviewed_base_exchange")
        unknown = []
        for exchange_id in sorted(set(biosphere) - set(base)):
            node, port = ports[exchange_id]
            matches = [item for item in selectors if isinstance(item, dict)
                       and isinstance(item.get("identity"), dict)
                       and selector_matches(item["identity"], node, port)]
            if len(matches) > 1:
                _refuse("MODEL_ELEMENTARY_FLOW_CLASSIFIED_TWICE",
                        "two reviewed selectors claim one emission", exchange_id=exchange_id)
            if not matches:
                unknown.append(exchange_id)
                continue
            rule = matches[0]["identity"]
            if not rule.get("greenhouse_gas") or not isinstance(matches[0].get("boundary_rule"), dict):
                _refuse("MODEL_PROCESSING_DECLARATION_UNREADABLE",
                        "the matching selector omits its gas or boundary disposition")
            decisions[exchange_id] = (rule, "reviewed_identity_selector")
        if unknown:
            _refuse("MODEL_ELEMENTARY_FLOW_CLASSIFICATION_REQUIRED",
                    "边界内排放流没有已审阅的过程、流身份及方向归属；该流及受影响合计暂不能计算，已确认的分项仍可查看。",
                    exchange_ids=unknown)
        if isinstance(applicable_gases, list):
            invalid = sorted(key for key, (rule, _) in decisions.items()
                             if rule.get("greenhouse_gas") not in applicable_gases)
            if invalid:
                _refuse("MODEL_ELEMENTARY_FLOW_GAS_NOT_APPLICABLE",
                        "a selected emission is outside the method's gas scope",
                        exchange_ids=invalid)
        self.flow_map = [
            {"exchange_id": key, "process_instance": key.rsplit("::", 1)[0],
             "process_uuid": ports[key][0]["process_uuid"], "state": "included",
             "clause": source, "amount": biosphere[key].get("amount"),
             "unit": biosphere[key].get("unit"), "flow_uuid": biosphere[key].get("flowUuid"),
             "flow_version": biosphere[key].get("flowVersion"),
             "greenhouse_gas": rule["greenhouse_gas"]}
            for key, (rule, source) in sorted(decisions.items())
        ]
        self.actions.append({
            "action": "classify_elementary_flows", "mode": "identity_selector_rules",
            "method_package": evidence.method_package.model_dump(),
            "manifest_path": evidence.manifest_path,
            "applicable_gases": applicable_gases,
            "included_exchange_ids": sorted(decisions), "excluded_exchange_ids": [],
        })

    def classify_emission_exchanges(
        self,
        flows: Any,
        ports: dict[str, tuple[dict[str, Any], dict[str, Any]]],
        biosphere: dict[str, dict[str, Any]],
    ) -> None:
        """Put every emission of a kept process in exactly one reviewed state, then cut what is out.

        A whole-plant model is allowed to hold processes and gases the method does not count: the
        processes already left with the selection, but an emission on a kept process is the method's
        own boundary. So it is either declared in or declared out, and neither may be inferred - an
        undeclared emission refuses, because answering from a subset nobody classified is the exact
        partial result this stage exists to prevent.
        """
        evidence = flows.evidence
        package = self.package(evidence.method_package, "elementary_flows")
        declared = _dig(package["manifest"], evidence.manifest_path, "elementary_flows")
        if not isinstance(declared, list) or not all(isinstance(item, dict) for item in declared):
            _refuse(
                "MODEL_PROCESSING_DECLARATION_UNREADABLE",
                "the explicit emission classification must be a list of exchange decisions",
                declaration="elementary_flows",
            )
        applicable_gases = (
            _dig(package["manifest"], evidence.applicable_gases_path, "elementary_flows")
            if evidence.applicable_gases_path
            else None
        )
        decisions: dict[str, tuple[ExchangeClassification, dict[str, Any]]] = {}
        for index, rule in enumerate(declared):
            try:
                decision = ExchangeClassification.model_validate(rule)
            except Exception as exc:  # a malformed decision is a review gap, not a zero
                _refuse(
                    "MODEL_PROCESSING_DECLARATION_UNREADABLE",
                    "an emission decision must name its exchange, the process instance carrying it,"
                    " an include/exclude disposition and the clause that justifies it: " + str(exc),
                    declaration="elementary_flows",
                    rule_index=index,
                )
            if decision.exchange_id in decisions:
                _refuse(
                    "MODEL_ELEMENTARY_FLOW_CLASSIFIED_TWICE",
                    "the method classifies one emission exchange twice, so the calculation could not"
                    " say which decision it is answering under",
                    exchange_id=decision.exchange_id,
                )
            decisions[decision.exchange_id] = (decision, rule)

        for exchange_id, (decision, rule) in sorted(decisions.items()):
            node, port = ports.get(exchange_id, (None, None))
            if node is None:
                _refuse(
                    "MODEL_ELEMENTARY_FLOW_DECISION_NOT_IN_MODEL",
                    "the method classifies an exchange this model does not have, so the reviewed"
                    " rules and the template no longer describe the same model",
                    exchange_id=exchange_id,
                    process_uuid=decision.process_uuid,
                )
            if port.get("type") != "biosphere":
                _refuse(
                    "MODEL_ELEMENTARY_FLOW_DECISION_NOT_ELEMENTARY",
                    "an emission decision names a technical exchange, not an emission, so the"
                    " declaration selects nothing the purpose could count",
                    exchange_id=exchange_id,
                    exchange_type=port.get("type"),
                )
            mismatches = _identity_drift(rule, port, node)
            if mismatches:
                _refuse(
                    "MODEL_ELEMENTARY_FLOW_IDENTITY_MISMATCH",
                    "an emission decision no longer matches the exact identity of the flow the model"
                    " carries, so neither its inclusion nor its exclusion can be trusted",
                    exchange_id=exchange_id,
                    fields=mismatches,
                )
            if (
                decision.disposition == "include"
                and isinstance(applicable_gases, list)
                and rule.get("greenhouse_gas") not in applicable_gases
            ):
                _refuse(
                    "MODEL_ELEMENTARY_FLOW_GAS_NOT_APPLICABLE",
                    "the method counts an emission of a gas its own boundary does not accept",
                    exchange_id=exchange_id,
                    greenhouse_gas=rule.get("greenhouse_gas"),
                    applicable_gases=applicable_gases,
                )

        awaiting = sorted(set(biosphere) - set(decisions))
        if awaiting:
            _refuse(
                "MODEL_ELEMENTARY_FLOW_CLASSIFICATION_REQUIRED",
                "an emission inside this purpose's process boundary carries no reviewed"
                " include/exclude decision, so the calculation is refused rather than answered from"
                " the exchanges that happen to be classified",
                exchange_ids=awaiting,
            )

        excluded = sorted(
            exchange_id for exchange_id, (decision, _) in decisions.items()
            if decision.disposition == "exclude"
        )
        self._drop_emission_ports(excluded)
        self.flow_map = [
            {
                "exchange_id": exchange_id,
                "process_instance": exchange_id.rsplit("::", 1)[0],
                "process_uuid": decisions[exchange_id][0].process_uuid,
                "state": "included"
                if decisions[exchange_id][0].disposition == "include"
                else "excluded",
                "clause": decisions[exchange_id][0].clause,
                "amount": biosphere[exchange_id].get("amount"),
                "unit": biosphere[exchange_id].get("unit"),
                "flow_uuid": biosphere[exchange_id].get("flowUuid"),
                "flow_version": biosphere[exchange_id].get("flowVersion"),
                "greenhouse_gas": decisions[exchange_id][1].get("greenhouse_gas"),
            }
            for exchange_id in sorted(decisions)
        ]
        self.actions.append(
            {
                "action": "classify_elementary_flows",
                "mode": "explicit_flow_rules",
                "method_package": evidence.method_package.model_dump(),
                "manifest_path": evidence.manifest_path,
                "applicable_gases": applicable_gases,
                "included_exchange_ids": sorted(set(decisions) - set(excluded)),
                "excluded_exchange_ids": excluded,
            }
        )

    def _drop_emission_ports(self, exchange_ids: list[str]) -> None:
        """Remove a refused emission from the calculation model, never from the stored one.

        The engine characterises the graph it is handed, so an exchange the method excludes has to be
        absent from what is sent: a note in the receipt alone would still have its number computed.
        """
        if not exchange_ids:
            return
        keys = set(exchange_ids)
        carried = {
            f"{edge.get('fromNode')}::{edge.get('sourcePortId')}"
            for edge in self.graph["exchanges"]
        } | {
            f"{edge.get('toNode')}::{edge.get('targetPortId')}"
            for edge in self.graph["exchanges"]
        }
        blocking = sorted(keys & carried)
        if blocking:
            _refuse(
                "MODEL_ELEMENTARY_FLOW_EXCHANGE_IN_USE",
                "an excluded emission is still carried by a supply exchange, so dropping it would"
                " leave the calculation model with a flow going nowhere",
                exchange_ids=blocking,
            )
        for node in self.graph["nodes"]:
            for side in ("inputs", "outputs"):
                node[side] = [
                    port
                    for port in (node.get(side) or [])
                    if f"{node['id']}::{port.get('id')}" not in keys
                ]

    def resolve_precursors(self) -> None:
        precursors = self.intent.precursors
        if precursors.mode == "not_applicable":
            return
        if precursors.mode == "in_model_expansion":
            _refuse(
                "MODEL_PRECURSOR_EXPANSION_UNSUPPORTED",
                "these rules ask for precursors to be expanded inside the calculation model, which"
                " the public provider contract cannot hand over as a complete supply chain yet",
                clause="expand_in_model",
            )
        self.actions.append(
            {
                "action": "reference_precursors",
                "mode": "reference_only",
                "expanded_processes_in_model": [],
            }
        )

    def run(self) -> DerivedCalculationModel:
        self.select_processes()
        self.preserve_reference_exchange()
        self.resolve_exchanges()
        self.resolve_demand()
        self.disposition_background()
        self.verify_elementary_flows()
        self.resolve_precursors()
        if canonical_graph_sha256(self.source_graph) != self.source_graph_sha256:
            # Derivation is only allowed to be a read of the stored model.
            _refuse(
                "MODEL_DERIVATION_SOURCE_MUTATED",
                "derivation changed the stored model, which must never happen",
            )
        derived_hash = canonical_graph_sha256(self.graph)
        return DerivedCalculationModel(
            purpose=self.purpose,
            rules_reference=self.rules.reference(),
            graph=self.graph,
            demand=self.demand,
            background_process_pins=self.background_process_pins,
            mapped_background_process_pins=self.mapped_background_process_pins,
            project_background_pins=self.project_background_pins,
            source_graph_sha256=self.source_graph_sha256,
            derived_graph_sha256=derived_hash,
            method_package_references=[self.bound[key] for key in sorted(self.bound)],
            process_map=self.process_map,
            exchange_map=self.exchange_map,
            flow_map=self.flow_map,
            actions=self.actions,
        )


def derive_calculation_model(
    *,
    graph: dict[str, Any],
    demand: list[dict[str, Any]],
    rules: ModelProcessingRules,
    purpose: str,
    method_packages: list[dict[str, Any]],
    background_process_pins: list[dict[str, Any]] | None = None,
    mapped_background_process_pins: list[dict[str, Any]] | None = None,
    project_background_pins: list[dict[str, Any]] | None = None,
) -> DerivedCalculationModel:
    """Apply one purpose's reviewed model-processing rules to the stored model."""
    return _Derivation(
        graph=graph,
        demand=demand,
        background_process_pins=background_process_pins,
        mapped_background_process_pins=mapped_background_process_pins,
        project_background_pins=project_background_pins,
        rules=rules,
        purpose=purpose,
        method_packages=method_packages,
    ).run()
