from __future__ import annotations

import copy
import math
from typing import Any, Callable

from ..errors import DomainError


OperationResult = tuple[dict[str, Any], dict[str, Any], str, str | None]


def _fail(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _amount(value: Any, *, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DomainError(
            code="MODEL_AMOUNT_INVALID",
            message=f"{label} must be a number",
            status_code=422,
        ) from exc
    if not math.isfinite(number) or number < 0:
        _fail("MODEL_AMOUNT_INVALID", f"{label} must be finite and non-negative")
    return number


def _nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        _fail("MODEL_GRAPH_INVALID", "graph.nodes must be a list")
    return nodes


def _exchanges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    exchanges = graph.get("exchanges")
    if not isinstance(exchanges, list):
        _fail("MODEL_GRAPH_INVALID", "graph.exchanges must be a list")
    return exchanges


def _node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    for candidate in _nodes(graph):
        if isinstance(candidate, dict) and _text(candidate.get("id")) == node_id:
            return candidate
    _fail("PROCESS_NOT_FOUND", f"process not found: {node_id}", process_id=node_id)


def _port_groups(node: dict[str, Any]):
    for group, direction in (("inputs", "input"), ("outputs", "output"), ("emissions", "output")):
        values = node.get(group, [])
        if not isinstance(values, list):
            _fail(
                "MODEL_GRAPH_INVALID",
                f"process {_text(node.get('id'))} {group} must be a list",
            )
        yield group, direction, values


def _port(
    graph: dict[str, Any], process_id: str, port_id: str
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    node = _node(graph, process_id)
    for group, _, values in _port_groups(node):
        for candidate in values:
            if isinstance(candidate, dict) and _text(candidate.get("id")) == port_id:
                return candidate, group, values
    _fail(
        "FLOW_PORT_NOT_FOUND",
        f"flow port not found: {process_id}/{port_id}",
        process_id=process_id,
        port_id=port_id,
    )


def _edge_node_id(edge: dict[str, Any], *, side: str) -> str:
    if side == "source":
        return _text(edge.get("fromNode", edge.get("from_node")))
    return _text(edge.get("toNode", edge.get("to_node")))


def _edge_port_id(edge: dict[str, Any], *, side: str) -> str:
    if side == "source":
        return _text(edge.get("sourcePortId", edge.get("source_port_id")))
    return _text(edge.get("targetPortId", edge.get("target_port_id")))


def _exchange(graph: dict[str, Any], exchange_id: str) -> dict[str, Any]:
    for candidate in _exchanges(graph):
        if isinstance(candidate, dict) and _text(candidate.get("id")) == exchange_id:
            return candidate
    _fail(
        "FLOW_EXCHANGE_NOT_FOUND",
        f"flow exchange not found: {exchange_id}",
        exchange_id=exchange_id,
    )


def validate_graph(graph: dict[str, Any]) -> None:
    if not isinstance(graph, dict):
        _fail("MODEL_GRAPH_INVALID", "graph must be an object")
    node_ids: set[str] = set()
    ports: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
    for raw_node in _nodes(graph):
        if not isinstance(raw_node, dict):
            _fail("MODEL_GRAPH_INVALID", "every graph node must be an object")
        node_id = _text(raw_node.get("id"))
        if not node_id:
            _fail("PROCESS_ID_MISSING", "every process requires an id")
        if node_id in node_ids:
            _fail("PROCESS_ID_DUPLICATE", f"duplicate process id: {node_id}")
        node_ids.add(node_id)
        local_port_ids: set[str] = set()
        for group, direction, values in _port_groups(raw_node):
            for raw_port in values:
                if not isinstance(raw_port, dict):
                    _fail(
                        "MODEL_GRAPH_INVALID",
                        f"process {node_id} contains a non-object flow port",
                    )
                port_id = _text(raw_port.get("id"))
                if not port_id:
                    _fail(
                        "FLOW_PORT_ID_MISSING",
                        f"process {node_id} contains a flow port without id",
                    )
                if port_id in local_port_ids:
                    _fail(
                        "FLOW_PORT_ID_DUPLICATE",
                        f"duplicate flow port id in process {node_id}: {port_id}",
                    )
                local_port_ids.add(port_id)
                declared_direction = _text(raw_port.get("direction")) or direction
                if declared_direction != direction:
                    _fail(
                        "FLOW_PORT_DIRECTION_INVALID",
                        f"flow port {node_id}/{port_id} direction does not match {group}",
                    )
                if "amount" in raw_port:
                    _amount(raw_port["amount"], label=f"flow port {node_id}/{port_id} amount")
                ports[(node_id, port_id)] = (raw_port, direction)

    edge_ids: set[str] = set()
    for raw_edge in _exchanges(graph):
        if not isinstance(raw_edge, dict):
            _fail("MODEL_GRAPH_INVALID", "every graph exchange must be an object")
        edge_id = _text(raw_edge.get("id"))
        if not edge_id:
            _fail("FLOW_EXCHANGE_ID_MISSING", "every exchange requires an id")
        if edge_id in edge_ids:
            _fail("FLOW_EXCHANGE_ID_DUPLICATE", f"duplicate exchange id: {edge_id}")
        edge_ids.add(edge_id)
        source_key = (
            _edge_node_id(raw_edge, side="source"),
            _edge_port_id(raw_edge, side="source"),
        )
        target_key = (
            _edge_node_id(raw_edge, side="target"),
            _edge_port_id(raw_edge, side="target"),
        )
        if not all(source_key) or not all(target_key):
            _fail(
                "FLOW_EXCHANGE_ENDPOINT_MISSING",
                f"exchange {edge_id} requires explicit process and port endpoints",
            )
        source = ports.get(source_key)
        target = ports.get(target_key)
        if source is None or target is None:
            _fail(
                "FLOW_EXCHANGE_ENDPOINT_NOT_FOUND",
                f"exchange {edge_id} references a missing flow port",
                source=list(source_key),
                target=list(target_key),
            )
        if source[1] != "output" or target[1] != "input":
            _fail(
                "FLOW_EXCHANGE_DIRECTION_INVALID",
                f"exchange {edge_id} must connect an output to an input",
            )
        source_flow = _text(source[0].get("flowUuid", source[0].get("flow_uuid")))
        target_flow = _text(target[0].get("flowUuid", target[0].get("flow_uuid")))
        edge_flow = _text(raw_edge.get("flowUuid", raw_edge.get("flow_uuid")))
        identified = {item for item in (source_flow, target_flow, edge_flow) if item}
        if len(identified) > 1:
            _fail(
                "FLOW_EXCHANGE_IDENTITY_MISMATCH",
                f"exchange {edge_id} endpoints refer to different flows",
                flow_uuids=sorted(identified),
            )
        if "amount" not in raw_edge:
            _fail("FLOW_EXCHANGE_AMOUNT_MISSING", f"exchange {edge_id} requires amount")
        _amount(raw_edge["amount"], label=f"exchange {edge_id} amount")
        quantity_mode = _text(
            raw_edge.get("quantityMode", raw_edge.get("quantity_mode"))
        ) or "single"
        if quantity_mode not in {"single", "dual"}:
            _fail(
                "FLOW_QUANTITY_MODE_INVALID",
                f"exchange {edge_id} has unsupported quantity mode: {quantity_mode}",
            )
        if quantity_mode == "dual":
            for camel, snake in (
                ("providerAmount", "provider_amount"),
                ("consumerAmount", "consumer_amount"),
            ):
                value = raw_edge.get(camel, raw_edge.get(snake))
                if value is None:
                    _fail(
                        "FLOW_DUAL_QUANTITY_INCOMPLETE",
                        f"exchange {edge_id} requires provider and consumer amounts",
                    )
                _amount(value, label=f"exchange {edge_id} {camel}")


def _set_functional_unit(
    graph: dict[str, Any], context: dict[str, Any], payload: dict[str, Any]
) -> OperationResult:
    functional_unit = payload.get("functional_unit")
    if functional_unit is None or functional_unit == "":
        _fail("FUNCTIONAL_UNIT_REQUIRED", "functional_unit is required")
    graph["functionalUnit"] = copy.deepcopy(functional_unit)
    return graph, context, "system", None


def _merge_context(
    graph: dict[str, Any], context: dict[str, Any], payload: dict[str, Any]
) -> OperationResult:
    update = payload.get("context")
    if not isinstance(update, dict):
        _fail("APPLICATION_CONTEXT_INVALID", "context must be an object")
    context.update(copy.deepcopy(update))
    return graph, context, "system", None


def _scale_flows(
    graph: dict[str, Any], context: dict[str, Any], payload: dict[str, Any]
) -> OperationResult:
    factor = _amount(payload.get("factor"), label="scale factor")
    if factor == 0:
        _fail("FLOW_SCALE_FACTOR_INVALID", "scale factor must be greater than zero")
    unit_groups = payload.get("unit_groups")
    flow_uuids = payload.get("flow_uuids")
    if unit_groups is not None and (
        not isinstance(unit_groups, list) or not all(_text(item) for item in unit_groups)
    ):
        _fail("FLOW_SCALE_SCOPE_INVALID", "unit_groups must be a list of names")
    if flow_uuids is not None and (
        not isinstance(flow_uuids, list) or not all(_text(item) for item in flow_uuids)
    ):
        _fail("FLOW_SCALE_SCOPE_INVALID", "flow_uuids must be a list of identifiers")
    group_filter = {_text(item).casefold() for item in unit_groups or []}
    flow_filter = {_text(item) for item in flow_uuids or []}

    def matches(port: dict[str, Any]) -> bool:
        group = _text(port.get("unitGroup", port.get("unit_group"))).casefold()
        flow = _text(port.get("flowUuid", port.get("flow_uuid")))
        return (not group_filter or group in group_filter) and (
            not flow_filter or flow in flow_filter
        )

    port_index: dict[tuple[str, str], dict[str, Any]] = {}
    scaled_ports = 0
    for node in _nodes(graph):
        node_id = _text(node.get("id"))
        for _, _, values in _port_groups(node):
            for port in values:
                port_index[(node_id, _text(port.get("id")))] = port
                if matches(port) and "amount" in port:
                    port["amount"] = _amount(port["amount"], label="flow port amount") * factor
                    scaled_ports += 1
    scaled_exchanges = 0
    for edge in _exchanges(graph):
        source = port_index.get(
            (_edge_node_id(edge, side="source"), _edge_port_id(edge, side="source"))
        )
        target = port_index.get(
            (_edge_node_id(edge, side="target"), _edge_port_id(edge, side="target"))
        )
        source_selected = source is not None and matches(source)
        target_selected = target is not None and matches(target)
        if source_selected != target_selected:
            _fail(
                "FLOW_SCALE_EDGE_SCOPE_INCOMPLETE",
                f"exchange {_text(edge.get('id'))} has only one endpoint in the scale scope",
            )
        if not source_selected:
            continue
        for key in ("amount", "providerAmount", "consumerAmount", "provider_amount", "consumer_amount"):
            if key in edge and edge[key] is not None:
                edge[key] = _amount(edge[key], label=f"exchange {_text(edge.get('id'))} {key}") * factor
        scaled_exchanges += 1
    if not scaled_ports and not scaled_exchanges:
        _fail("FLOW_SCALE_SCOPE_EMPTY", "no flows matched the requested scale scope")
    context["last_scale"] = {
        "factor": factor,
        "unit_groups": sorted(group_filter),
        "flow_uuids": sorted(flow_filter),
        "scaled_ports": scaled_ports,
        "scaled_exchanges": scaled_exchanges,
    }
    return graph, context, "system", None


def _add_process(
    graph: dict[str, Any], context: dict[str, Any], payload: dict[str, Any]
) -> OperationResult:
    process = payload.get("process")
    if not isinstance(process, dict):
        _fail("PROCESS_PAYLOAD_INVALID", "process must be an object")
    process = copy.deepcopy(process)
    process_id = _text(process.get("id"))
    if not process_id:
        _fail("PROCESS_ID_MISSING", "process.id is required")
    if any(_text(item.get("id")) == process_id for item in _nodes(graph) if isinstance(item, dict)):
        _fail("PROCESS_ID_DUPLICATE", f"process already exists: {process_id}")
    for group in ("inputs", "outputs", "emissions"):
        process.setdefault(group, [])
    _nodes(graph).append(process)
    return graph, context, "process", process_id


def _update_process(
    graph: dict[str, Any], context: dict[str, Any], payload: dict[str, Any]
) -> OperationResult:
    process_id = _text(payload.get("process_id"))
    changes = payload.get("changes")
    if not process_id or not isinstance(changes, dict) or not changes:
        _fail("PROCESS_UPDATE_INVALID", "process_id and non-empty changes are required")
    protected = {"id", "inputs", "outputs", "emissions"}
    blocked = sorted(protected.intersection(changes))
    if blocked:
        _fail(
            "PROCESS_UPDATE_STRUCTURAL_FIELDS_FORBIDDEN",
            "use Flow operations to change process ports",
            fields=blocked,
        )
    _node(graph, process_id).update(copy.deepcopy(changes))
    return graph, context, "process", process_id


def _remove_process(
    graph: dict[str, Any], context: dict[str, Any], payload: dict[str, Any]
) -> OperationResult:
    process_id = _text(payload.get("process_id"))
    if not process_id:
        _fail("PROCESS_ID_MISSING", "process_id is required")
    _node(graph, process_id)
    connected = [
        edge
        for edge in _exchanges(graph)
        if process_id
        in {
            _edge_node_id(edge, side="source"),
            _edge_node_id(edge, side="target"),
        }
    ]
    if connected and payload.get("remove_connected_exchanges") is not True:
        _fail(
            "PROCESS_HAS_CONNECTED_EXCHANGES",
            "explicitly confirm removal of connected exchanges",
            exchange_ids=[_text(edge.get("id")) for edge in connected],
        )
    graph["nodes"] = [node for node in _nodes(graph) if _text(node.get("id")) != process_id]
    graph["exchanges"] = [edge for edge in _exchanges(graph) if edge not in connected]
    return graph, context, "process", process_id


def _add_port(
    graph: dict[str, Any], context: dict[str, Any], payload: dict[str, Any]
) -> OperationResult:
    process_id = _text(payload.get("process_id"))
    group = _text(payload.get("port_group"))
    port = payload.get("port")
    if group not in {"inputs", "outputs", "emissions"} or not isinstance(port, dict):
        _fail(
            "FLOW_PORT_PAYLOAD_INVALID",
            "process_id, port_group and port are required",
        )
    node = _node(graph, process_id)
    port = copy.deepcopy(port)
    port_id = _text(port.get("id"))
    if not port_id:
        _fail("FLOW_PORT_ID_MISSING", "port.id is required")
    for _, _, values in _port_groups(node):
        if any(_text(item.get("id")) == port_id for item in values):
            _fail("FLOW_PORT_ID_DUPLICATE", f"flow port already exists: {process_id}/{port_id}")
    port["direction"] = "input" if group == "inputs" else "output"
    node.setdefault(group, []).append(port)
    return graph, context, "flow", f"{process_id}/{port_id}"


def _update_port(
    graph: dict[str, Any], context: dict[str, Any], payload: dict[str, Any]
) -> OperationResult:
    process_id = _text(payload.get("process_id"))
    port_id = _text(payload.get("port_id"))
    changes = payload.get("changes")
    if not process_id or not port_id or not isinstance(changes, dict) or not changes:
        _fail("FLOW_PORT_UPDATE_INVALID", "process_id, port_id and non-empty changes are required")
    blocked = sorted({"id", "direction"}.intersection(changes))
    if blocked:
        _fail(
            "FLOW_PORT_IDENTITY_CHANGE_FORBIDDEN",
            "flow port identity and direction cannot be changed in place",
            fields=blocked,
        )
    port, _, _ = _port(graph, process_id, port_id)
    port.update(copy.deepcopy(changes))
    return graph, context, "flow", f"{process_id}/{port_id}"


def _remove_port(
    graph: dict[str, Any], context: dict[str, Any], payload: dict[str, Any]
) -> OperationResult:
    process_id = _text(payload.get("process_id"))
    port_id = _text(payload.get("port_id"))
    if not process_id or not port_id:
        _fail("FLOW_PORT_IDENTITY_MISSING", "process_id and port_id are required")
    _, _, values = _port(graph, process_id, port_id)
    connected = [
        edge
        for edge in _exchanges(graph)
        if (process_id, port_id)
        in {
            (_edge_node_id(edge, side="source"), _edge_port_id(edge, side="source")),
            (_edge_node_id(edge, side="target"), _edge_port_id(edge, side="target")),
        }
    ]
    if connected and payload.get("remove_connected_exchanges") is not True:
        _fail(
            "FLOW_PORT_HAS_CONNECTED_EXCHANGES",
            "explicitly confirm removal of connected exchanges",
            exchange_ids=[_text(edge.get("id")) for edge in connected],
        )
    values[:] = [port for port in values if _text(port.get("id")) != port_id]
    graph["exchanges"] = [edge for edge in _exchanges(graph) if edge not in connected]
    return graph, context, "flow", f"{process_id}/{port_id}"


def _connect(
    graph: dict[str, Any], context: dict[str, Any], payload: dict[str, Any]
) -> OperationResult:
    exchange = payload.get("exchange")
    if not isinstance(exchange, dict):
        _fail("FLOW_EXCHANGE_PAYLOAD_INVALID", "exchange must be an object")
    exchange = copy.deepcopy(exchange)
    exchange_id = _text(exchange.get("id"))
    if not exchange_id:
        _fail("FLOW_EXCHANGE_ID_MISSING", "exchange.id is required")
    if any(_text(item.get("id")) == exchange_id for item in _exchanges(graph)):
        _fail("FLOW_EXCHANGE_ID_DUPLICATE", f"exchange already exists: {exchange_id}")
    _exchanges(graph).append(exchange)
    return graph, context, "flow", exchange_id


def _update_exchange(
    graph: dict[str, Any], context: dict[str, Any], payload: dict[str, Any]
) -> OperationResult:
    exchange_id = _text(payload.get("exchange_id"))
    changes = payload.get("changes")
    if not exchange_id or not isinstance(changes, dict) or not changes:
        _fail(
            "FLOW_EXCHANGE_UPDATE_INVALID",
            "exchange_id and non-empty changes are required",
        )
    if "id" in changes:
        _fail("FLOW_EXCHANGE_IDENTITY_CHANGE_FORBIDDEN", "exchange id cannot be changed in place")
    _exchange(graph, exchange_id).update(copy.deepcopy(changes))
    return graph, context, "flow", exchange_id


def _disconnect(
    graph: dict[str, Any], context: dict[str, Any], payload: dict[str, Any]
) -> OperationResult:
    exchange_id = _text(payload.get("exchange_id"))
    if not exchange_id:
        _fail("FLOW_EXCHANGE_ID_MISSING", "exchange_id is required")
    _exchange(graph, exchange_id)
    graph["exchanges"] = [
        edge for edge in _exchanges(graph) if _text(edge.get("id")) != exchange_id
    ]
    return graph, context, "flow", exchange_id


OPERATIONS: dict[
    str, Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], OperationResult]
] = {
    "system.set_functional_unit": _set_functional_unit,
    "system.merge_context": _merge_context,
    "system.scale_flows": _scale_flows,
    "process.add": _add_process,
    "process.update": _update_process,
    "process.remove": _remove_process,
    "flow.add_port": _add_port,
    "flow.update_port": _update_port,
    "flow.remove_port": _remove_port,
    "flow.connect": _connect,
    "flow.update_exchange": _update_exchange,
    "flow.disconnect": _disconnect,
}


OPERATION_PAYLOAD_CONTRACTS: dict[str, dict[str, Any]] = {
    "system.set_functional_unit": {
        "required": ["functional_unit"],
        "properties": {"functional_unit": {"description": "JSON functional-unit value"}},
    },
    "system.merge_context": {
        "required": ["context"],
        "properties": {"context": {"type": "object"}},
    },
    "system.scale_flows": {
        "required": ["factor"],
        "properties": {
            "factor": {"type": "number", "exclusiveMinimum": 0},
            "unit_groups": {"type": "array", "items": {"type": "string"}},
            "flow_uuids": {"type": "array", "items": {"type": "string"}},
        },
    },
    "process.add": {
        "required": ["process"],
        "properties": {"process": {"type": "object"}},
    },
    "process.update": {
        "required": ["process_id", "changes"],
        "forbidden_change_fields": ["id", "inputs", "outputs", "emissions"],
    },
    "process.remove": {
        "required": ["process_id"],
        "properties": {"remove_connected_exchanges": {"type": "boolean"}},
    },
    "flow.add_port": {
        "required": ["process_id", "port_group", "port"],
        "port_group_enum": ["inputs", "outputs", "emissions"],
    },
    "flow.update_port": {
        "required": ["process_id", "port_id", "changes"],
        "forbidden_change_fields": ["id", "direction"],
    },
    "flow.remove_port": {
        "required": ["process_id", "port_id"],
        "properties": {"remove_connected_exchanges": {"type": "boolean"}},
    },
    "flow.connect": {
        "required": ["exchange"],
        "properties": {"exchange": {"type": "object"}},
    },
    "flow.update_exchange": {
        "required": ["exchange_id", "changes"],
        "forbidden_change_fields": ["id"],
    },
    "flow.disconnect": {
        "required": ["exchange_id"],
    },
}


def apply_operation(
    graph: dict[str, Any],
    application_context: dict[str, Any],
    operation_type: str,
    payload: dict[str, Any],
) -> OperationResult:
    operation = OPERATIONS.get(operation_type)
    if operation is None:
        _fail(
            "MODEL_OPERATION_NOT_SUPPORTED",
            f"model operation is not supported: {operation_type}",
            supported_operations=sorted(OPERATIONS),
        )
    next_graph = copy.deepcopy(graph)
    next_context = copy.deepcopy(application_context)
    result = operation(next_graph, next_context, payload)
    validate_graph(result[0])
    return result
