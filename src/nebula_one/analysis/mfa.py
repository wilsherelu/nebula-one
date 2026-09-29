from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..errors import AnalysisError


@dataclass(frozen=True, slots=True)
class PortRef:
    node_id: str
    node_name: str
    node_location: str
    port_id: str
    direction: str
    flow_uuid: str
    flow_name: str
    unit_group: str
    unit: str
    amount: float
    flow_type: str

    @property
    def key(self) -> tuple[str, str]:
        return self.node_id, self.port_id

    @property
    def series_key(self) -> tuple[str, str]:
        return self.unit_group.casefold(), self.unit.casefold()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _finite_non_negative(value: Any, *, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AnalysisError(
            code="MFA_AMOUNT_INVALID",
            message=f"{label} must be a number",
            status_code=422,
        ) from exc
    if not math.isfinite(number) or number < 0:
        raise AnalysisError(
            code="MFA_AMOUNT_INVALID",
            message=f"{label} must be finite and non-negative",
            status_code=422,
        )
    return number


def _edge_port_id(edge: dict[str, Any], *, side: str) -> str:
    if side == "source":
        value = edge.get("sourcePortId", edge.get("source_port_id"))
    else:
        value = edge.get("targetPortId", edge.get("target_port_id"))
    return _text(value)


def _is_elementary(port: PortRef) -> bool:
    return port.flow_type.casefold() in {"biosphere", "elementary", "elementary_flow"}


def _port_refs(graph: dict[str, Any]) -> tuple[dict[tuple[str, str], PortRef], list[dict[str, str]]]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        raise AnalysisError(
            code="MFA_GRAPH_INVALID",
            message="graph.nodes must be a list",
            status_code=422,
        )
    ports: dict[tuple[str, str], PortRef] = {}
    process_nodes: list[dict[str, str]] = []
    for raw_node in nodes:
        if not isinstance(raw_node, dict):
            raise AnalysisError(
                code="MFA_GRAPH_INVALID",
                message="every graph node must be an object",
                status_code=422,
            )
        node_id = _text(raw_node.get("id"))
        if not node_id:
            raise AnalysisError(
                code="MFA_GRAPH_INVALID",
                message="every graph node requires an id",
                status_code=422,
            )
        node_name = _text(raw_node.get("name")) or node_id
        node_location = _text(raw_node.get("location"))
        process_nodes.append(
            {
                "id": node_id,
                "name": node_name,
                "location": node_location,
                "kind": "process",
            }
        )
        groups = (
            ("input", raw_node.get("inputs")),
            ("output", raw_node.get("outputs")),
            ("output", raw_node.get("emissions")),
        )
        for default_direction, raw_ports in groups:
            if raw_ports is None:
                continue
            if not isinstance(raw_ports, list):
                raise AnalysisError(
                    code="MFA_GRAPH_INVALID",
                    message=f"node {node_id} ports must be lists",
                    status_code=422,
                )
            for raw_port in raw_ports:
                if not isinstance(raw_port, dict):
                    raise AnalysisError(
                        code="MFA_GRAPH_INVALID",
                        message=f"node {node_id} contains a non-object port",
                        status_code=422,
                    )
                port_id = _text(raw_port.get("id"))
                if not port_id:
                    raise AnalysisError(
                        code="MFA_GRAPH_INVALID",
                        message=f"node {node_id} contains a port without id",
                        status_code=422,
                    )
                unit_group = _text(raw_port.get("unitGroup", raw_port.get("unit_group")))
                unit = _text(raw_port.get("unit"))
                if not unit_group or not unit:
                    raise AnalysisError(
                        code="MFA_UNIT_EVIDENCE_MISSING",
                        message=f"port {node_id}/{port_id} requires unitGroup and unit",
                        status_code=422,
                    )
                direction = _text(raw_port.get("direction")) or default_direction
                if direction not in {"input", "output"}:
                    raise AnalysisError(
                        code="MFA_DIRECTION_INVALID",
                        message=f"port {node_id}/{port_id} has invalid direction {direction}",
                        status_code=422,
                    )
                ref = PortRef(
                    node_id=node_id,
                    node_name=node_name,
                    node_location=node_location,
                    port_id=port_id,
                    direction=direction,
                    flow_uuid=_text(raw_port.get("flowUuid", raw_port.get("flow_uuid"))),
                    flow_name=_text(raw_port.get("name")) or port_id,
                    unit_group=unit_group,
                    unit=unit,
                    amount=_finite_non_negative(
                        raw_port.get("amount"), label=f"port {node_id}/{port_id} amount"
                    ),
                    flow_type=_text(raw_port.get("type")),
                )
                if ref.key in ports:
                    raise AnalysisError(
                        code="MFA_PORT_DUPLICATE",
                        message=f"duplicate port identity {node_id}/{port_id}",
                        status_code=422,
                    )
                ports[ref.key] = ref
    return ports, process_nodes


def project_declared_mfa(
    graph: dict[str, Any], parameters: dict[str, Any] | None = None
) -> dict[str, Any]:
    options = parameters or {}
    include_elementary = bool(options.get("include_elementary", False))
    tolerance = _finite_non_negative(options.get("tolerance", 1e-9), label="tolerance")
    requested_groups = options.get("unit_groups")
    if requested_groups is not None and not isinstance(requested_groups, list):
        raise AnalysisError(
            code="MFA_PARAMETERS_INVALID",
            message="unit_groups must be a list of unit-group names",
            status_code=422,
        )
    group_filter = {
        _text(value).casefold() for value in (requested_groups or []) if _text(value)
    }

    ports, process_nodes = _port_refs(graph)
    selected: dict[tuple[str, str], PortRef] = {}
    for key, port in ports.items():
        if _is_elementary(port) and not include_elementary:
            continue
        if group_filter and port.unit_group.casefold() not in group_filter:
            continue
        selected[key] = port

    connected: dict[tuple[str, str], float] = {key: 0.0 for key in selected}
    series_data: dict[tuple[str, str], dict[str, Any]] = {}

    def ensure_series(port: PortRef) -> dict[str, Any]:
        series = series_data.get(port.series_key)
        if series is None:
            series = {
                "unit_group": port.unit_group,
                "unit": port.unit,
                "links": [],
                "node_ids": set(),
                "inflow": {},
                "outflow": {},
                "totals": {
                    "internal_flow": 0.0,
                    "boundary_in": 0.0,
                    "boundary_out": 0.0,
                },
            }
            series_data[port.series_key] = series
        return series

    raw_edges = graph.get("exchanges")
    if not isinstance(raw_edges, list):
        raise AnalysisError(
            code="MFA_GRAPH_INVALID",
            message="graph.exchanges must be a list",
            status_code=422,
        )
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            raise AnalysisError(
                code="MFA_GRAPH_INVALID",
                message="every graph exchange must be an object",
                status_code=422,
            )
        edge_id = _text(raw_edge.get("id"))
        source_node = _text(raw_edge.get("fromNode", raw_edge.get("from_node")))
        target_node = _text(raw_edge.get("toNode", raw_edge.get("to_node")))
        source_port_id = _edge_port_id(raw_edge, side="source")
        target_port_id = _edge_port_id(raw_edge, side="target")
        if not edge_id or not source_node or not target_node:
            raise AnalysisError(
                code="MFA_EDGE_IDENTITY_MISSING",
                message="every exchange requires id, fromNode and toNode",
                status_code=422,
            )
        if not source_port_id or not target_port_id:
            raise AnalysisError(
                code="MFA_EDGE_PORT_EVIDENCE_MISSING",
                message=f"exchange {edge_id} requires explicit sourcePortId and targetPortId",
                status_code=422,
            )
        source = ports.get((source_node, source_port_id))
        target = ports.get((target_node, target_port_id))
        if source is None or target is None:
            raise AnalysisError(
                code="MFA_EDGE_PORT_NOT_FOUND",
                message=f"exchange {edge_id} references a missing port",
                status_code=422,
                details={
                    "source": [source_node, source_port_id],
                    "target": [target_node, target_port_id],
                },
            )
        source_selected = source.key in selected
        target_selected = target.key in selected
        if not source_selected and not target_selected:
            continue
        if source_selected != target_selected:
            raise AnalysisError(
                code="MFA_EDGE_SELECTION_INCOMPLETE",
                message=f"exchange {edge_id} has only one endpoint in the selected MFA scope",
                status_code=422,
            )
        if source.direction != "output" or target.direction != "input":
            raise AnalysisError(
                code="MFA_EDGE_DIRECTION_INVALID",
                message=f"exchange {edge_id} must connect output to input",
                status_code=422,
            )
        if source.unit_group.casefold() != target.unit_group.casefold():
            raise AnalysisError(
                code="MFA_UNIT_GROUP_MISMATCH",
                message=f"exchange {edge_id} connects incompatible unit groups",
                status_code=422,
                details={
                    "source_unit_group": source.unit_group,
                    "target_unit_group": target.unit_group,
                },
            )
        edge_unit = _text(raw_edge.get("unit")) or source.unit
        if source.unit.casefold() != target.unit.casefold() or edge_unit.casefold() != source.unit.casefold():
            raise AnalysisError(
                code="MFA_REFERENCE_UNIT_NORMALIZATION_REQUIRED",
                message=f"exchange {edge_id} requires reference-unit normalization in Nebula LCA",
                status_code=422,
                details={
                    "edge_unit": edge_unit,
                    "source_unit": source.unit,
                    "target_unit": target.unit,
                },
            )
        quantity_mode = _text(raw_edge.get("quantityMode", raw_edge.get("quantity_mode"))) or "single"
        edge_amount = _finite_non_negative(
            raw_edge.get("amount"), label=f"exchange {edge_id} amount"
        )
        if quantity_mode == "dual":
            provider_amount = _finite_non_negative(
                raw_edge.get("providerAmount", raw_edge.get("provider_amount")),
                label=f"exchange {edge_id} provider amount",
            )
            consumer_amount = _finite_non_negative(
                raw_edge.get("consumerAmount", raw_edge.get("consumer_amount")),
                label=f"exchange {edge_id} consumer amount",
            )
            if abs(provider_amount - consumer_amount) > tolerance:
                raise AnalysisError(
                    code="MFA_DUAL_QUANTITY_NORMALIZATION_REQUIRED",
                    message=f"exchange {edge_id} requires a UnitGroupSwitch-aware quantity conversion",
                    status_code=422,
                    details={
                        "provider_amount": provider_amount,
                        "consumer_amount": consumer_amount,
                    },
                )
            edge_amount = consumer_amount
        elif quantity_mode != "single":
            raise AnalysisError(
                code="MFA_QUANTITY_MODE_INVALID",
                message=f"exchange {edge_id} has unsupported quantity mode {quantity_mode}",
                status_code=422,
            )
        connected[source.key] += edge_amount
        connected[target.key] += edge_amount
        series = ensure_series(source)
        series["node_ids"].update((source.node_id, target.node_id))
        series["links"].append(
            {
                "id": edge_id,
                "source": source.node_id,
                "target": target.node_id,
                "flow_uuid": _text(raw_edge.get("flowUuid", raw_edge.get("flow_uuid"))) or source.flow_uuid,
                "flow_name": _text(raw_edge.get("flowName", raw_edge.get("flow_name"))) or source.flow_name,
                "value": edge_amount,
                "unit_group": source.unit_group,
                "unit": source.unit,
                "kind": "internal",
            }
        )
        series["totals"]["internal_flow"] += edge_amount
        series["outflow"][source.node_id] = series["outflow"].get(source.node_id, 0.0) + edge_amount
        series["inflow"][target.node_id] = series["inflow"].get(target.node_id, 0.0) + edge_amount

    for key, port in selected.items():
        internal_amount = connected.get(key, 0.0)
        if internal_amount > port.amount + tolerance:
            raise AnalysisError(
                code="MFA_INTERNAL_FLOW_EXCEEDS_PORT",
                message=f"internal exchanges exceed declared amount on port {port.node_id}/{port.port_id}",
                status_code=422,
                details={"declared": port.amount, "internal": internal_amount},
            )
        residual = max(0.0, port.amount - internal_amount)
        series = ensure_series(port)
        if internal_amount > tolerance:
            series["node_ids"].add(port.node_id)
        if residual <= tolerance:
            continue
        series["node_ids"].add(port.node_id)
        if port.direction == "input":
            source = "boundary:input"
            target = port.node_id
            kind = "boundary_input"
            series["totals"]["boundary_in"] += residual
            series["inflow"][port.node_id] = series["inflow"].get(port.node_id, 0.0) + residual
        else:
            source = port.node_id
            target = "boundary:output"
            kind = "boundary_output"
            series["totals"]["boundary_out"] += residual
            series["outflow"][port.node_id] = series["outflow"].get(port.node_id, 0.0) + residual
        series["links"].append(
            {
                "id": f"boundary:{port.node_id}:{port.port_id}",
                "source": source,
                "target": target,
                "flow_uuid": port.flow_uuid,
                "flow_name": port.flow_name,
                "value": residual,
                "unit_group": port.unit_group,
                "unit": port.unit,
                "kind": kind,
            }
        )

    node_by_id = {node["id"]: node for node in process_nodes}
    output_series: list[dict[str, Any]] = []
    for key in sorted(series_data):
        series = series_data[key]
        links = sorted(series["links"], key=lambda item: (item["source"], item["target"], item["id"]))
        boundary_kinds = {link["kind"] for link in links}
        nodes = [node_by_id[node_id] for node_id in sorted(series["node_ids"])]
        if "boundary_input" in boundary_kinds:
            nodes.append({"id": "boundary:input", "name": "System boundary input", "location": "", "kind": "boundary"})
        if "boundary_output" in boundary_kinds:
            nodes.append({"id": "boundary:output", "name": "System boundary output", "location": "", "kind": "boundary"})
        balances: list[dict[str, Any]] = []
        for node_id in sorted(series["node_ids"]):
            inflow = series["inflow"].get(node_id, 0.0)
            outflow = series["outflow"].get(node_id, 0.0)
            net = inflow - outflow
            status = "balanced" if abs(net) <= tolerance else ("accumulation" if net > 0 else "deficit")
            balances.append(
                {
                    "node_id": node_id,
                    "inflow": inflow,
                    "outflow": outflow,
                    "net": net,
                    "status": status,
                }
            )
        output_series.append(
            {
                "unit_group": series["unit_group"],
                "unit": series["unit"],
                "nodes": nodes,
                "links": links,
                "totals": series["totals"],
                "balances": balances,
            }
        )

    warnings: list[str] = []
    if not output_series:
        warnings.append("No ports matched the requested MFA scope.")
    return {
        "schema_version": "nebula_one.mfa.v1",
        "basis": "nebula_lca_graph_declared_amounts",
        "functional_unit": _text(graph.get("functionalUnit", graph.get("functional_unit"))),
        "include_elementary": include_elementary,
        "series": output_series,
        "warnings": warnings,
    }
