from __future__ import annotations

from collections import defaultdict, deque
from html import escape
from math import isfinite
from typing import Any

from ..errors import DomainError
from .mapped_background_mfa import mapped_supply_links
from .project_background_mfa import project_supply_links

# The formal mass-dimension unit-group identity (ECospacity / ILCD flow-property UUID). A series is
# a mass series exactly when its unit group carries this identity — never by "kg" text, a display
# name, or array position, so an energy or mass-named-but-not-mass series can never be mistaken
# for mass and vice versa.
MASS_UNIT_GROUP_UUID = "93a60a57-a4c8-11da-a746-0800200c9a66"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _handle_port(value: Any) -> str:
    token = _text(value)
    return token.split(":", 1)[1] if ":" in token else token


def _amount(item: dict[str, Any], *, context: str, allow_negative: bool = False) -> float:
    try:
        value = float(item.get("amount"))
    except (TypeError, ValueError) as exc:
        raise DomainError(
            code="SOLVED_MFA_AMOUNT_INVALID",
            message=f"solved MFA amount is invalid: {context}",
            status_code=422,
        ) from exc
    if not isfinite(value) or (value < 0 and not allow_negative):
        raise DomainError(
            code="SOLVED_MFA_AMOUNT_INVALID",
            message=f"solved MFA amount must be finite and non-negative: {context}",
            status_code=422,
        )
    return value


def _node_id(kind: str, value: str) -> str:
    return f"{kind}:{value}"


def _process_catalog(graph: dict[str, Any]) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    processes: dict[str, dict[str, str]] = {}
    node_to_process: dict[str, str] = {}
    for raw in graph.get("nodes") or []:
        if not isinstance(raw, dict):
            continue
        graph_node_id = _text(raw.get("id"))
        process_id = _text(raw.get("process_uuid") or raw.get("processUuid") or graph_node_id)
        if not graph_node_id or not process_id:
            continue
        node_to_process[graph_node_id] = process_id
        processes[process_id] = {
            "id": _node_id("process", process_id),
            "label": _text(raw.get("name")) or process_id,
            "kind": "process",
            "process_id": process_id,
            **({"background": True} if raw.get("mfa_background") else {}),
        }
    return processes, node_to_process


def _exchange_catalog(graph: dict[str, Any]) -> dict[str, dict[str, str]]:
    exchanges: dict[str, dict[str, str]] = {}
    for raw_node in graph.get("nodes") or []:
        if not isinstance(raw_node, dict):
            continue
        node_id = _text(raw_node.get("id"))
        if not node_id:
            continue
        for collection in ("inputs", "outputs", "emissions"):
            for raw_port in raw_node.get(collection) or []:
                if not isinstance(raw_port, dict):
                    continue
                port_id = _text(raw_port.get("id"))
                if not port_id:
                    continue
                exchanges[f"{node_id}::{port_id}"] = {
                    "name": _text(raw_port.get("name")) + (' — ' + raw_port['display_description'] if raw_port.get('display_description') else ''),
                    "flow_uuid": _text(
                        raw_port.get("flowUuid") or raw_port.get("flow_uuid")
                    ),
                }
    return exchanges


def _unit_group_labels(graph: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for raw_node in graph.get("nodes") or []:
        if not isinstance(raw_node, dict):
            continue
        for collection in ("inputs", "outputs", "emissions"):
            for raw_port in raw_node.get(collection) or []:
                if not isinstance(raw_port, dict):
                    continue
                identity = _text(
                    raw_port.get("unitGroupUuid")
                    or raw_port.get("unit_group_uuid")
                )
                label = _text(
                    raw_port.get("unitGroup") or raw_port.get("unit_group")
                )
                if identity and label:
                    labels.setdefault(identity, label)
    return labels


def _series_key(item: dict[str, Any]) -> tuple[str, str]:
    unit_group = _text(item.get("unit_group"))
    unit = _text(item.get("unit"))
    if not unit_group or not unit:
        raise DomainError(
            code="SOLVED_MFA_UNIT_IDENTITY_INCOMPLETE",
            message="solved MFA requires unit-group and unit identity on every exchange",
            status_code=422,
            details={"exchange_id": item.get("exchange_id")},
        )
    return unit_group, unit


def _background_process_receipts(
    solved_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    provider_receipt = solved_snapshot.get("provider_receipt")
    if not isinstance(provider_receipt, dict):
        return []
    receipts = provider_receipt.get("background_process_receipts")
    if not isinstance(receipts, list):
        return []
    return [item for item in receipts if isinstance(item, dict)]


def build_solved_mfa(
    *,
    solved_snapshot: dict[str, Any],
    revision_graph: dict[str, Any],
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    if tolerance < 0 or not isfinite(tolerance):
        raise DomainError(
            code="SOLVED_MFA_TOLERANCE_INVALID",
            message="solved MFA tolerance must be finite and non-negative",
            status_code=422,
        )
    processes, node_to_process = _process_catalog(revision_graph)
    exchange_catalog = _exchange_catalog(revision_graph)
    unit_group_labels = _unit_group_labels(revision_graph)
    internal_items = [
        item
        for item in solved_snapshot.get("internal_transfers") or []
        if isinstance(item, dict)
    ]
    boundary_items = [
        item
        for item in solved_snapshot.get("boundary_flows") or []
        if isinstance(item, dict)
    ]
    internal_by_exchange = {
        _text(item.get("exchange_id")): item
        for item in internal_items
        if _text(item.get("exchange_id"))
    }
    internal_exchange_ids: set[str] = set()
    links_by_series: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    nodes_by_series: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    edge_to_key: dict[str, tuple[str, str]] = {}
    issues: list[dict[str, Any]] = []
    background_exchange_catalog: dict[str, dict[str, str]] = {}

    mapped_links, mapped_issues = mapped_supply_links(solved_snapshot)
    issues.extend(mapped_issues)
    for mapped in mapped_links:
        source, target, receipt = mapped['source_item'], mapped['target_item'], mapped['receipt']
        key = _series_key(target)
        source_id, target_id = _node_id('process', source['process_id']), _node_id('process', target['process_id'])
        for item, node_id in ((source, source_id), (target, target_id)):
            nodes_by_series[key][node_id] = processes.get(item['process_id'], {
                'id': node_id, 'label': item['process_id'], 'kind': 'process', 'process_id': item['process_id']})
        exchange_ids = [source['exchange_id'], target['exchange_id']]
        internal_exchange_ids.update(exchange_ids)
        links_by_series[key].append({'id': f"mapped-background:{target['exchange_id']}", 'source': source_id,
            'target': target_id, 'value': mapped['target_amount'], 'kind': 'internal',
            'origin': 'mapped_background_process_receipt', 'flow_uuid': target['flow_uuid'],
            'flow_name': exchange_catalog.get(target['exchange_id'], {}).get('name') or target['flow_uuid'],
            'exchange_ids': exchange_ids, 'reconciliation': {'source_amount': mapped['source_amount'],
                'source_unit': source['unit'], 'target_amount': mapped['target_amount'], 'target_unit': target['unit'],
                'amount_factor': mapped['factor'], 'mapping_package_hash': receipt['mapping_package_hash'],
                'rule': 'mapped_background_consumer_unit'}})

    project_links, project_issues = project_supply_links(solved_snapshot)
    issues.extend(project_issues)
    for link in project_links:
        source, target, receipt = link['source_item'], link['target_item'], link['receipt']
        key = _series_key(target)
        source_id, target_id = _node_id('process', source['process_id']), _node_id('process', target['process_id'])
        for item, node_id in ((source, source_id), (target, target_id)):
            nodes_by_series[key][node_id] = processes.get(item['process_id'], {
                'id': node_id, 'label': item['process_id'], 'kind': 'process', 'process_id': item['process_id']})
        exchange_ids = [source['exchange_id'], target['exchange_id']]
        internal_exchange_ids.update(exchange_ids)
        links_by_series[key].append({
            'id': f"project-background:{target['exchange_id']}", 'source': source_id, 'target': target_id,
            'value': link['target_amount'], 'kind': 'internal', 'origin': 'project_background_process_receipt',
            'flow_uuid': target['flow_uuid'],
            'flow_name': exchange_catalog.get(target['exchange_id'], {}).get('name') or target['flow_uuid'],
            'exchange_ids': exchange_ids,
            'reconciliation': {'source_amount': link['source_amount'], 'source_unit': source['unit'],
                'target_amount': link['target_amount'], 'target_unit': target['unit'],
                'amount_factor': link['factor'], 'source_graph_hash': receipt['source_graph_hash'],
                'rule': 'project_background_consumer_unit'},
        })

    for receipt in _background_process_receipts(solved_snapshot):
        consumer_exchange_id = _text(receipt.get("consumer_exchange_id"))
        process_id = _text(receipt.get("process_uuid"))
        receipt_exchanges = receipt.get("exchanges")
        qref_rows = [
            item
            for item in receipt_exchanges or []
            if isinstance(item, dict) and item.get("role") == "quantitative_reference"
        ]
        if not consumer_exchange_id or not process_id or len(qref_rows) != 1:
            issues.append(
                {
                    "code": "BACKGROUND_INTERNAL_TRANSFER_RECEIPT_INVALID",
                    "severity": "error",
                    "consumer_exchange_id": consumer_exchange_id or None,
                    "process_id": process_id or None,
                }
            )
            continue
        qref = qref_rows[0]
        for item in receipt_exchanges or []:
            if not isinstance(item, dict):
                continue
            exchange_id = _text(item.get("expanded_exchange_id"))
            if exchange_id:
                background_exchange_catalog[exchange_id] = {
                    "name": _text(item.get("flow_name")),
                    "flow_uuid": _text(item.get("flow_uuid")),
                }
        provider_exchange_id = _text(qref.get("expanded_exchange_id"))
        source_item = internal_by_exchange.get(provider_exchange_id)
        target_item = internal_by_exchange.get(consumer_exchange_id)
        if source_item is None or target_item is None:
            issues.append(
                {
                    "code": "BACKGROUND_INTERNAL_TRANSFER_EVIDENCE_MISSING",
                    "severity": "error",
                    "consumer_exchange_id": consumer_exchange_id,
                    "provider_exchange_id": provider_exchange_id,
                }
            )
            continue
        internal_exchange_ids.update((provider_exchange_id, consumer_exchange_id))
        source_key = _series_key(source_item)
        target_key = _series_key(target_item)
        source_amount = _amount(source_item, context=provider_exchange_id)
        target_amount = _amount(target_item, context=consumer_exchange_id)
        try:
            receipt_amount = float(qref.get("scaled_amount"))
        except (TypeError, ValueError):
            receipt_amount = float("nan")
        flow_uuid = _text(qref.get("flow_uuid"))
        identity_matches = (
            source_key == target_key
            and _text(source_item.get("flow_uuid")) == flow_uuid
            and _text(target_item.get("flow_uuid")) == flow_uuid
            and _text(source_item.get("direction")) == "output"
            and _text(target_item.get("direction")) == "input"
        )
        amount_matches = (
            isfinite(receipt_amount)
            and abs(source_amount - target_amount) <= tolerance
            and abs(source_amount - receipt_amount) <= tolerance
        )
        if not identity_matches or not amount_matches:
            issues.append(
                {
                    "code": "BACKGROUND_INTERNAL_TRANSFER_MISMATCH",
                    "severity": "error",
                    "consumer_exchange_id": consumer_exchange_id,
                    "provider_exchange_id": provider_exchange_id,
                    "source_amount": source_amount,
                    "target_amount": target_amount,
                    "receipt_amount": receipt_amount,
                    "tolerance": tolerance,
                }
            )
            continue
        process_node_id = _node_id("process", process_id)
        consumer_process_id = _text(target_item.get("process_id"))
        consumer_node_id = _node_id("process", consumer_process_id)
        exchange_definition = exchange_catalog.get(consumer_exchange_id, {})
        flow_name = (
            _text(qref.get("flow_name"))
            or _text(exchange_definition.get("name"))
            or flow_uuid
        )
        processes.setdefault(
            process_id,
            {
                "id": process_node_id,
                "label": (
                    _text(receipt.get("process_name"))
                    or f"{flow_name} provider"
                ),
                "kind": "process",
                "process_id": process_id,
                "source_namespace": _text(receipt.get("source_namespace")),
                "version": _text(receipt.get("version")),
                "claim_role": _text(receipt.get("claim_role")),
            },
        )
        nodes_by_series[source_key][process_node_id] = processes[process_id]
        nodes_by_series[source_key][consumer_node_id] = processes.get(
            consumer_process_id,
            {
                "id": consumer_node_id,
                "label": consumer_process_id,
                "kind": "process",
                "process_id": consumer_process_id,
            },
        )
        links_by_series[source_key].append(
            {
                "id": f"background:{consumer_exchange_id}",
                "source": process_node_id,
                "target": consumer_node_id,
                "value": target_amount,
                "kind": "internal",
                "origin": "background_process_receipt",
                "flow_uuid": flow_uuid,
                "flow_name": flow_name,
                "exchange_ids": [provider_exchange_id, consumer_exchange_id],
                "reconciliation": {
                    "source_amount": source_amount,
                    "target_amount": target_amount,
                    "receipt_amount": receipt_amount,
                    "delta": source_amount - target_amount,
                    "rule": "exact_background_qref_scaled_amount",
                },
            }
        )

    for raw_edge in revision_graph.get("exchanges") or []:
        if not isinstance(raw_edge, dict):
            continue
        source_node = _text(raw_edge.get("fromNode") or raw_edge.get("from_node"))
        target_node = _text(raw_edge.get("toNode") or raw_edge.get("to_node"))
        source_port = _handle_port(
            raw_edge.get("sourcePortId")
            or raw_edge.get("source_port_id")
            or raw_edge.get("sourceHandle")
        )
        target_port = _handle_port(
            raw_edge.get("targetPortId")
            or raw_edge.get("target_port_id")
            or raw_edge.get("targetHandle")
        )
        source_exchange_id = f"{source_node}::{source_port}"
        target_exchange_id = f"{target_node}::{target_port}"
        source_item = internal_by_exchange.get(source_exchange_id)
        target_item = internal_by_exchange.get(target_exchange_id)
        if source_item is None or target_item is None:
            issues.append(
                {
                    "code": "INTERNAL_TRANSFER_EVIDENCE_MISSING",
                    "severity": "error",
                    "edge_id": raw_edge.get("id"),
                    "source_exchange_id": source_exchange_id,
                    "target_exchange_id": target_exchange_id,
                }
            )
            continue
        internal_exchange_ids.update((source_exchange_id, target_exchange_id))
        source_key = _series_key(source_item)
        target_key = _series_key(target_item)
        if source_key != target_key or _text(source_item.get("flow_uuid")) != _text(
            target_item.get("flow_uuid")
        ):
            issues.append(
                {
                    "code": "INTERNAL_TRANSFER_IDENTITY_MISMATCH",
                    "severity": "error",
                    "edge_id": raw_edge.get("id"),
                    "source_identity": {
                        "flow_uuid": source_item.get("flow_uuid"),
                        "unit_group": source_key[0],
                        "unit": source_key[1],
                    },
                    "target_identity": {
                        "flow_uuid": target_item.get("flow_uuid"),
                        "unit_group": target_key[0],
                        "unit": target_key[1],
                    },
                }
            )
            continue
        source_amount = _amount(source_item, context=source_exchange_id)
        target_amount = _amount(target_item, context=target_exchange_id)
        delta = source_amount - target_amount
        if abs(delta) > tolerance:
            issues.append(
                {
                    "code": "INTERNAL_TRANSFER_AMOUNT_MISMATCH",
                    "severity": "error",
                    "edge_id": raw_edge.get("id"),
                    "source_amount": source_amount,
                    "target_amount": target_amount,
                    "delta": delta,
                    "tolerance": tolerance,
                }
            )
        source_process = node_to_process.get(source_node, source_node)
        target_process = node_to_process.get(target_node, target_node)
        source_id = _node_id("process", source_process)
        target_id = _node_id("process", target_process)
        if _text(raw_edge.get("id")):
            edge_to_key[_text(raw_edge.get("id"))] = source_key
        nodes_by_series[source_key][source_id] = processes.get(
            source_process,
            {"id": source_id, "label": source_process, "kind": "process", "process_id": source_process},
        )
        nodes_by_series[source_key][target_id] = processes.get(
            target_process,
            {"id": target_id, "label": target_process, "kind": "process", "process_id": target_process},
        )
        links_by_series[source_key].append(
            {
                "id": f"internal:{_text(raw_edge.get('id')) or source_exchange_id}",
                "source": source_id,
                "target": target_id,
                "value": target_amount,
                "kind": "internal",
                "flow_uuid": target_item.get("flow_uuid"),
                "flow_name": raw_edge.get("flowName") or raw_edge.get("flow_name"),
                "exchange_ids": [source_exchange_id, target_exchange_id],
                "reconciliation": {
                    "source_amount": source_amount,
                    "target_amount": target_amount,
                    "delta": delta,
                    "rule": "consumer_scaled_amount",
                },
            }
        )

    for index, item in enumerate(boundary_items):
        key = _series_key(item)
        process_id = _text(item.get("process_id"))
        if not process_id:
            issues.append(
                {
                    "code": "BOUNDARY_PROCESS_ID_MISSING",
                    "severity": "error",
                    "exchange_id": item.get("exchange_id"),
                }
            )
            continue
        process_node_id = _node_id("process", process_id)
        nodes_by_series[key][process_node_id] = processes.get(
            process_id,
            {"id": process_node_id, "label": process_id, "kind": "process", "process_id": process_id},
        )
        direction = _text(item.get("direction"))
        flow_uuid = _text(item.get("flow_uuid"))
        exchange_type = _text(item.get("exchange_type"))
        exchange_id = _text(item.get("exchange_id"))
        exchange_definition = (
            exchange_catalog.get(exchange_id)
            or background_exchange_catalog.get(exchange_id)
            or {}
        )
        flow_name = _text(exchange_definition.get("name")) or flow_uuid
        boundary_kind = "environment" if exchange_type == "elementary" else "system_boundary"
        if direction not in ("input", "output"):
            issues.append(
                {
                    "code": "BOUNDARY_DIRECTION_INVALID",
                    "severity": "error",
                    "exchange_id": item.get("exchange_id"),
                    "direction": direction,
                }
            )
            continue
        signed_amount = _amount(
            item,
            context=f"boundary[{index}]",
            allow_negative=exchange_type == "elementary",
        )
        if signed_amount < 0:
            drawn_direction = "output" if direction == "input" else "input"
            drawn_amount = -signed_amount
            issues.append(
                {
                    "code": "ELEMENTARY_EXCHANGE_SIGN_NORMALIZED",
                    "severity": "warning",
                    "exchange_id": exchange_id,
                    "flow_uuid": flow_uuid or None,
                    "source_direction": direction,
                    "source_amount": signed_amount,
                    "drawn_direction": drawn_direction,
                    "drawn_amount": drawn_amount,
                    "rule": "negative_elementary_amount_drawn_as_opposite_direction",
                }
            )
        else:
            drawn_direction = direction
            drawn_amount = signed_amount
        boundary_id = _node_id(f"boundary-{drawn_direction}", flow_uuid)
        previous_label = nodes_by_series[key].get(boundary_id, {}).get("label")
        nodes_by_series[key][boundary_id] = {
            "id": boundary_id,
            "label": previous_label if flow_name == flow_uuid and previous_label else flow_name,
            "kind": boundary_kind,
            "flow_uuid": flow_uuid,
            "direction": drawn_direction,
        }
        if drawn_direction == "input":
            source_id, target_id = boundary_id, process_node_id
        else:
            source_id, target_id = process_node_id, boundary_id
        link = {
            "id": f"boundary:{_text(item.get('exchange_id')) or index}",
            "source": source_id,
            "target": target_id,
            "value": drawn_amount,
            "kind": "boundary",
            "flow_uuid": flow_uuid,
            "flow_name": flow_name,
            "exchange_ids": [item.get("exchange_id")],
            "exchange_type": exchange_type,
            "direction": drawn_direction,
        }
        if signed_amount < 0:
            link["sign_normalization"] = {
                "source_direction": direction,
                "source_amount": signed_amount,
                "rule": "negative_elementary_amount_drawn_as_opposite_direction",
            }
        links_by_series[key].append(link)

    orphan_internal = sorted(set(internal_by_exchange).difference(internal_exchange_ids))
    for exchange_id in orphan_internal:
        issues.append(
            {
                "code": "INTERNAL_TRANSFER_GRAPH_EDGE_MISSING",
                "severity": "error",
                "exchange_id": exchange_id,
            }
        )

    exchange_to_key: dict[str, tuple[str, str]] = {}
    for key, key_links in links_by_series.items():
        for link in key_links:
            for exchange_id in link.get("exchange_ids") or []:
                exchange_to_key.setdefault(_text(exchange_id), key)

    series_keys = set(nodes_by_series) | set(links_by_series)

    def _issue_series_key(issue: dict[str, Any]) -> tuple[str, str] | None:
        key = edge_to_key.get(_text(issue.get("edge_id")))
        if key is not None:
            return key
        for field in (
            "source_exchange_id",
            "target_exchange_id",
            "consumer_exchange_id",
            "provider_exchange_id",
            "exchange_id",
        ):
            key = exchange_to_key.get(_text(issue.get(field)))
            if key is not None:
                return key
        for side in ("source_identity", "target_identity"):
            identity = issue.get(side)
            if isinstance(identity, dict):
                candidate = (_text(identity.get("unit_group")), _text(identity.get("unit")))
                if candidate in series_keys:
                    return candidate
        return None

    series: list[dict[str, Any]] = []
    process_balance_checks: list[dict[str, Any]] = []
    for key in sorted(series_keys):
        links = sorted(links_by_series[key], key=lambda item: item["id"])
        incoming: dict[str, float] = defaultdict(float)
        outgoing: dict[str, float] = defaultdict(float)
        for link in links:
            outgoing[link["source"]] += link["value"]
            incoming[link["target"]] += link["value"]
        key_open_boundaries = 0
        for node in nodes_by_series[key].values():
            if node["kind"] != "process":
                continue
            residual = outgoing[node["id"]] - incoming[node["id"]]
            balance_status = "balanced" if abs(residual) <= tolerance else "open_boundary"
            if balance_status == "open_boundary":
                key_open_boundaries += 1
            process_balance_checks.append(
                {
                    "process_id": node["process_id"],
                    "unit_group": key[0],
                    "unit": key[1],
                    "incoming": incoming[node["id"]],
                    "outgoing": outgoing[node["id"]],
                    "residual": residual,
                    "status": balance_status,
                    "authority": "application_projection",
                }
            )
        series_error = sum(
            1 for item in issues if item.get("severity") == "error" and _issue_series_key(item) == key
        )
        series_warning = sum(
            1 for item in issues if item.get("severity") == "warning" and _issue_series_key(item) == key
        )
        series_conservation = (
            "failed"
            if series_error
            else ("pass_with_warnings" if series_warning or key_open_boundaries else "passed")
        )
        series.append(
            {
                "series_id": f"{key[0]}::{key[1]}",
                "unit_group": key[0],
                "unit_group_uuid": key[0],
                "unit_group_label": unit_group_labels.get(key[0], key[0]),
                "is_mass": key[0] == MASS_UNIT_GROUP_UUID,
                "conservation": {
                    "status": series_conservation,
                    "error_count": series_error,
                    "warning_count": series_warning,
                    "open_boundary_count": key_open_boundaries,
                },
                "unit": key[1],
                "nodes": sorted(nodes_by_series[key].values(), key=lambda item: item["id"]),
                "links": links,
                "totals": {
                    "internal": sum(item["value"] for item in links if item["kind"] == "internal"),
                    "boundary_input": sum(
                        item["value"]
                        for item in links
                        if item["kind"] == "boundary" and item.get("direction") == "input"
                    ),
                    "boundary_output": sum(
                        item["value"]
                        for item in links
                        if item["kind"] == "boundary" and item.get("direction") == "output"
                    ),
                },
            }
        )

    error_count = sum(item.get("severity") == "error" for item in issues)
    warning_count = sum(item.get("severity") == "warning" for item in issues)
    open_boundaries = sum(item["status"] == "open_boundary" for item in process_balance_checks)
    audit_status = "failed" if error_count else ("pass_with_warnings" if warning_count or open_boundaries else "passed")
    return {
        "schema_version": "nebula_one.mfa.solved.v1",
        "solved_snapshot_id": solved_snapshot.get("id"),
        "solve_hash": solved_snapshot.get("solve_hash"),
        "series": series,
        "audit": {
            "status": audit_status,
            "tolerance": tolerance,
            "checks": {
                "series_count": len(series),
                "link_count": sum(len(item["links"]) for item in series),
                "traceable_link_count": sum(
                    1
                    for item in series
                    for link in item["links"]
                    if link.get("exchange_ids")
                ),
                "error_count": error_count,
                "warning_count": warning_count,
                "open_boundary_process_count": open_boundaries,
            },
            "process_balances": process_balance_checks,
            "issues": issues,
            "provenance": {
                "solved_snapshot_content_sha256": solved_snapshot.get("content_sha256"),
                "provider_receipt": solved_snapshot.get("provider_receipt") or {},
                "source_fields": [
                    "internal_transfers",
                    "boundary_flows",
                    *(['provider_receipt.mapped_background_process_receipts'] if mapped_links else []),
                    *(
                        ["provider_receipt.background_process_receipts"]
                        if _background_process_receipts(solved_snapshot)
                        else []
                    ),
                ],
                "internal_transfer_value_rule": "consumer_scaled_amount",
                "boundary_elementary_sign_rule": (
                    "negative_elementary_amount_drawn_as_opposite_direction"
                    if any(
                        issue.get("code") == "ELEMENTARY_EXCHANGE_SIGN_NORMALIZED"
                        for issue in issues
                    )
                    else None
                ),
                "background_internal_transfer_value_rule": (
                    "exact_background_qref_scaled_amount"
                    if _background_process_receipts(solved_snapshot)
                    else None
                ),
            },
        },
    }


def _ranks(nodes: list[dict[str, Any]], links: list[dict[str, Any]]) -> dict[str, int]:
    node_ids = {item["id"] for item in nodes}
    indegree = {node_id: 0 for node_id in node_ids}
    adjacency: dict[str, list[str]] = defaultdict(list)
    for link in links:
        source = link["source"]
        target = link["target"]
        if source in node_ids and target in node_ids and target not in adjacency[source]:
            adjacency[source].append(target)
            indegree[target] += 1
    queue = deque(sorted(node_id for node_id, value in indegree.items() if value == 0))
    ranks = {node_id: 0 for node_id in node_ids}
    visited = 0
    while queue:
        source = queue.popleft()
        visited += 1
        for target in sorted(adjacency[source]):
            ranks[target] = max(ranks[target], ranks[source] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(node_ids):
        return {node_id: index for index, node_id in enumerate(sorted(node_ids))}
    return ranks


def _format_amount(value: Any) -> str:
    amount = float(value or 0)
    if amount == 0:
        return "0"
    if abs(amount) >= 1_000_000 or abs(amount) < 0.001:
        return f"{amount:.3g}"
    return f"{amount:,.3f}".rstrip("0").rstrip(".")


def _shorten(value: Any, limit: int = 24) -> str:
    text = _text(value)
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _link_anchors(
    *,
    links: list[dict[str, Any]],
    positions: dict[str, tuple[float, float]],
    card_height: float,
) -> dict[str, tuple[float, float]]:
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for link in links:
        outgoing[link["source"]].append(link)
        incoming[link["target"]].append(link)

    def offsets(items: list[dict[str, Any]], *, opposite: str) -> dict[str, float]:
        ordered = sorted(items, key=lambda item: positions[item[opposite]][1])
        if len(ordered) == 1:
            return {ordered[0]["id"]: 0.0}
        span = min(card_height - 22, 14.0 * (len(ordered) - 1))
        return {
            item["id"]: -span / 2 + span * index / (len(ordered) - 1)
            for index, item in enumerate(ordered)
        }

    source_offsets: dict[str, float] = {}
    target_offsets: dict[str, float] = {}
    for items in outgoing.values():
        source_offsets.update(offsets(items, opposite="target"))
    for items in incoming.values():
        target_offsets.update(offsets(items, opposite="source"))
    return {
        link["id"]: (source_offsets.get(link["id"], 0.0), target_offsets.get(link["id"], 0.0))
        for link in links
    }


def _resolve_label_centers(
    labels: list[dict[str, Any]],
    *,
    min_y: float,
    max_y: float,
    gap: float = 6.0,
) -> dict[str, float]:
    """Separate labels whose horizontal spans overlap without changing links."""
    if not labels:
        return {}
    groups: list[list[dict[str, Any]]] = []
    right_edges: list[float] = []
    for label in sorted(labels, key=lambda item: item["x"] - item["width"] / 2):
        left = label["x"] - label["width"] / 2
        right = label["x"] + label["width"] / 2
        if groups and left <= right_edges[-1] + gap:
            groups[-1].append(label)
            right_edges[-1] = max(right_edges[-1], right)
        else:
            groups.append([label])
            right_edges.append(right)

    resolved: dict[str, float] = {}
    for group in groups:
        ordered = sorted(group, key=lambda item: (item["y"], item["id"]))
        cursor = min_y
        centers: list[float] = []
        for label in ordered:
            half = label["height"] / 2
            center = max(float(label["y"]), cursor + half)
            centers.append(center)
            cursor = center + half + gap
        overflow = max(0.0, cursor - gap - max_y)
        if overflow:
            centers = [center - overflow for center in centers]
        for index in range(len(centers) - 2, -1, -1):
            current = ordered[index]
            following = ordered[index + 1]
            ceiling = centers[index + 1] - (
                current["height"] + following["height"]
            ) / 2 - gap
            centers[index] = min(centers[index], ceiling)
        underflow = max(0.0, min_y - (centers[0] - ordered[0]["height"] / 2))
        if underflow:
            centers = [center + underflow for center in centers]
        for label, center in zip(ordered, centers):
            resolved[label["id"]] = center
    return resolved


def render_sankey_svg(
    series: dict[str, Any],
    *,
    title: str = "Solved MFA Sankey",
    min_width: int = 1280,
    chinese_labels: bool = False,
) -> str:
    def L(zh: str, en: str) -> str:
        return zh if chinese_labels else en
    nodes = list(series.get("nodes") or [])
    links = list(series.get("links") or [])
    if not nodes:
        raise DomainError(
            code="SOLVED_MFA_SANKEY_EMPTY",
            message="cannot render a Sankey chart without nodes",
            status_code=422,
        )
    header_height = 112
    footer_height = 70
    card_width = 212.0
    card_height = 82.0
    margin_x = 56.0
    node_by_id = {node["id"]: node for node in nodes}
    process_nodes = [node for node in nodes if node.get("kind") == "process"]
    diagram_mode = series.get("diagram_mode")
    spatial_energy_mode = diagram_mode == "spatial_energy"
    spatial_energy_flow_mode = diagram_mode == "spatial_energy_flow"
    energy_flow_mode = diagram_mode == "energy_flow"
    park_mode = diagram_mode in {"park", "spatial_energy", "spatial_energy_flow"}
    standard_mode = not park_mode and not energy_flow_mode
    has_partial_background = any(
        node.get("claim_role") == "partial_background_leaf"
        for node in process_nodes
    )
    process_ids = {node["id"] for node in process_nodes}
    process_links = [
        link
        for link in links
        if link.get("kind") == "internal"
        and link.get("source") in process_ids
        and link.get("target") in process_ids
    ]
    process_ranks = _ranks(process_nodes, process_links)
    has_input_boundary = any(
        (node.get("kind") == "system_boundary" or (standard_mode and node.get("kind") == "environment")) and node.get("direction") == "input"
        for node in nodes
    )
    process_rank_offset = 1 if has_input_boundary else 0
    ranks: dict[str, int] = {
        node_id: rank + process_rank_offset
        for node_id, rank in process_ranks.items()
    }
    output_rank = max(ranks.values(), default=0) + 1
    for node in nodes:
        if node.get("kind") == "process":
            continue
        if (node.get("kind") == "system_boundary" or (standard_mode and node.get("kind") == "environment")) and node.get("direction") == "input":
            ranks[node["id"]] = 0
        else:
            ranks[node["id"]] = output_rank
    max_rank = max(ranks.values(), default=0)
    width = max(
        min_width,
        int(margin_x * 2 + card_width + max_rank * 450),
    )
    columns: dict[int, list[str]] = defaultdict(list)
    for node in nodes:
        columns[ranks[node["id"]]].append(node["id"])
    max_column_size = max((len(node_ids) for node_ids in columns.values()), default=1)
    chart_height = max(320.0, max_column_size * 104.0)
    height = int(header_height + chart_height + footer_height)
    node_area_top = header_height + 28.0
    node_area_height = chart_height - 28.0
    positions: dict[str, tuple[float, float]] = {}
    for rank, node_ids in columns.items():
        x = margin_x + card_width / 2 + (
            width - margin_x * 2 - card_width
        ) * (rank / max(max_rank, 1))
        ordered = sorted(
            node_ids,
            key=lambda node_id: (
                0 if node_by_id[node_id].get("kind") == "process" else 1,
                node_by_id[node_id].get("label") or node_id,
            ),
        )
        gap = node_area_height / max(len(ordered), 1)
        for index, node_id in enumerate(ordered):
            positions[node_id] = (x, node_area_top + gap * (index + 0.5))
    max_value = max((float(link.get("value") or 0) for link in links), default=1.0)
    anchors = _link_anchors(links=links, positions=positions, card_height=card_height)
    incoming_totals: dict[str, float] = defaultdict(float)
    outgoing_totals: dict[str, float] = defaultdict(float)
    for link in links:
        value = float(link.get("value") or 0)
        outgoing_totals[link["source"]] += value
        incoming_totals[link["target"]] += value
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        "<style>text{font-family:Segoe UI,Arial,sans-serif;fill:#17324d}.title{font-size:26px;font-weight:700}.subtitle{font-size:13px;fill:#58728b}.column-label{font-size:10px;font-weight:700;letter-spacing:.12em;fill:#7890a6}.node-title{font-size:14px;font-weight:700}.node-role{font-size:10px;font-weight:700;letter-spacing:.08em}.node-total{font-size:11px;font-variant-numeric:tabular-nums;fill:#58728b}.link-label{font-size:11px;font-weight:700}.link-value{font-size:10px;font-variant-numeric:tabular-nums;fill:#58728b}.legend{font-size:11px;fill:#58728b}.link{fill:none;stroke-linecap:round;opacity:.68;transition:opacity .15s}.link:hover{opacity:1}.card{stroke-width:1.5}.label-bg{fill:#fff;fill-opacity:.96;stroke:#dbe7f0;stroke-width:1}</style>",
        '<rect width="100%" height="100%" fill="#f5f9fc"/>',
        f'<rect x="24" y="18" width="{width - 48}" height="68" rx="14" fill="#ffffff" stroke="#e1eaf2"/>',
        f'<text id="title" x="48" y="49" class="title">{escape(title)}</text>',
        f'<text id="description" x="48" y="72" class="subtitle">{escape(_text(series.get("unit_group_label") or series.get("unit_group")))} · {escape(_text(series.get("unit")))} · {escape(L("冻结求解交换", "frozen solved exchanges"))}{escape((L(" · 部分背景叶", " · partial background leaf")) if has_partial_background else "")}</text>',
        f'<metadata>unit_group_identity={escape(_text(series.get("unit_group")))}</metadata>',
    ]
    for rank in sorted(columns):
        if standard_mode:
            continue
        node_ids = columns[rank]
        x = positions[node_ids[0]][0]
        if rank == 0 and has_input_boundary:
            column_label = (
                "ENERGY INPUTS"
                if energy_flow_mode
                else "PARK ENERGY INPUTS"
                if spatial_energy_mode or spatial_energy_flow_mode
                else "PARK INPUTS"
                if park_mode
                else L("系统输入", "SYSTEM INPUTS")
            )
        elif rank == output_rank:
            column_label = (
                "ENERGY OUTPUTS"
                if energy_flow_mode
                else "PARK OUTPUTS"
                if park_mode
                else L("系统输出", "SYSTEM OUTPUTS")
            )
        else:
            column_label = (
                f"FACILITY STAGE {rank - process_rank_offset + 1}"
                if park_mode
                else L(f"生产过程 {rank - process_rank_offset + 1}", f"PROCESS STAGE {rank - process_rank_offset + 1}")
            )
        chunks.append(
            f'<text class="column-label" x="{x:.1f}" y="{header_height + 17}" text-anchor="middle">{escape(column_label)}</text>'
        )
    label_specs: list[dict[str, Any]] = []
    for link in links:
        source = positions.get(link["source"])
        target = positions.get(link["target"])
        if source is None or target is None:
            continue
        x1, source_y = source
        x2, target_y = target
        source_offset, target_offset = anchors[link["id"]]
        x1 += card_width / 2
        x2 -= card_width / 2
        y1 = source_y + source_offset
        y2 = target_y + target_offset
        control = max(40, abs(x2 - x1) * 0.45)
        routed_explicit_loss = (
            spatial_energy_flow_mode
            and link.get("spatial_role") == "explicit_energy_loss"
        )
        if routed_explicit_loss:
            route_y = max(node_area_top + 24.0, min(y1, y2) - 112.0)
            midpoint_x = (x1 + x2) / 2
            path_data = (
                f"M{x1:.1f},{y1:.1f} "
                f"C{x1 + control * 0.45:.1f},{y1:.1f} "
                f"{x1 + control * 0.45:.1f},{route_y:.1f} "
                f"{midpoint_x:.1f},{route_y:.1f} "
                f"S{x2 - control * 0.45:.1f},{route_y:.1f} {x2:.1f},{y2:.1f}"
            )
            label_y = route_y
        else:
            path_data = (
                f"M{x1:.1f},{y1:.1f} "
                f"C{x1 + control:.1f},{y1:.1f} "
                f"{x2 - control:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"
            )
            label_y = (y1 + y2) / 2
        if link.get("kind") == "internal":
            stroke = "#3478d4"
        elif link.get("exchange_type") == "elementary":
            stroke = "#6f879e" if standard_mode and link.get("direction") == "input" else "#38a87c"
        elif link.get("direction") == "input":
            stroke = "#6f879e"
        else:
            stroke = "#4aa7b5"
        stroke_width = max(4.0, 24 * float(link["value"]) / max(max_value, 1e-12))
        tooltip = (
            f"{node_by_id[link['source']]['label']} → {node_by_id[link['target']]['label']}"
            f" | {link.get('flow_uuid')} | {link['value']} {series.get('unit')}"
            f" | exchanges: {', '.join(_text(item) for item in link.get('exchange_ids') or [])}"
        )
        chunks.append(
            f'<path class="link" data-link-id="{escape(_text(link["id"]))}" d="{path_data}" stroke="{stroke}" stroke-width="{stroke_width:.2f}"><title>{escape(tooltip)}</title></path>'
        )
        name = _text(link.get("flow_name"))
        flow_label = _shorten(name if name and name != link.get("flow_uuid") else L("未提供流名称", "Flow name unavailable"), 28)
        amount_label = f"{_format_amount(link['value'])} {series.get('unit')}"
        label_x = x1 + (x2 - x1) * 0.56
        label_width = min(226.0, max(132.0, 7.1 * len(flow_label) + 24.0))
        label_specs.append(
            {
                "id": link["id"],
                "x": label_x,
                "y": label_y,
                "width": label_width,
                "height": 40.0,
                "flow_label": flow_label,
                "amount_label": amount_label,
                "tooltip": tooltip,
            }
        )
    label_centers = _resolve_label_centers(
        label_specs,
        min_y=node_area_top,
        max_y=header_height + chart_height - 10.0,
    )
    for label in label_specs:
        label_y = label_centers[label["id"]]
        chunks.extend(
            [
                f'<g data-label-for="{escape(_text(label["id"]))}"><rect class="label-bg" x="{label["x"] - label["width"] / 2:.1f}" y="{label_y - label["height"] / 2:.1f}" width="{label["width"]:.1f}" height="{label["height"]:.1f}" rx="10"/>',
                f'<text class="link-label" x="{label["x"]:.1f}" y="{label_y - 3:.1f}" text-anchor="middle">{escape(label["flow_label"])}<title>{escape(label["tooltip"])}</title></text>',
                f'<text class="link-value" x="{label["x"]:.1f}" y="{label_y + 12:.1f}" text-anchor="middle">→ {escape(label["amount_label"])}</text></g>',
            ]
        )
    styles = {
        "process": ("#e9f2ff", "#3478d4", L("生产过程", "PROCESS")),
        "environment": ("#e7f7f0", "#38a87c", L("环境", "ENVIRONMENT")),
        "system_boundary": ("#edf3f7", "#6f879e", L("系统边界", "SYSTEM BOUNDARY")),
    }
    for node in nodes:
        x, y = positions[node["id"]]
        fill, stroke, role = styles.get(
            node.get("kind"), ("#edf3f7", "#6f879e", L("边界", "BOUNDARY"))
        )
        if node.get("claim_role") == "partial_background_leaf":
            fill, stroke, role = "#f3edff", "#7b61c9", L("部分背景", "PARTIAL BACKGROUND")
        if node.get("background"):
            fill, stroke, role = "#f3edff", "#7b61c9", L("背景过程", "BACKGROUND PROCESS")
        if node.get("kind") == "system_boundary" and node.get("direction") == "output":
            fill, stroke, role = "#e8f6f8", "#4aa7b5", L("系统输出", "SYSTEM OUTPUT")
        if standard_mode and node.get("kind") == "environment" and node.get("direction") == "input":
            fill, stroke, role = "#edf3f7", "#6f879e", L("自然资源投入", "NATURAL RESOURCE INPUT")
        if node.get("display_role"):
            role = _text(node["display_role"]).upper()
        full_label = _text(node.get("label"))
        if not full_label or full_label in {node.get("process_id"), node.get("flow_uuid")}:
            full_label = f"{L('未提供名称', 'Name unavailable')} {sorted(node_by_id).index(node['id']) + 1}"
        incoming = incoming_totals.get(node["id"], 0.0)
        outgoing = outgoing_totals.get(node["id"], 0.0)
        in_label = L("入 ", "IN ")
        out_label = L("出 ", "OUT ")
        if incoming and outgoing:
            total_label = (
                f"{in_label}{_format_amount(incoming)} · {out_label}{_format_amount(outgoing)} "
                f"{series.get('unit')}"
            )
        elif incoming:
            total_label = f"{in_label}{_format_amount(incoming)} {series.get('unit')}"
        else:
            total_label = f"{out_label}{_format_amount(outgoing)} {series.get('unit')}"
        chunks.append(
            f'<rect class="card" data-node-id="{escape(_text(node["id"]))}" x="{x - card_width / 2:.1f}" y="{y - card_height / 2:.1f}" width="{card_width:.1f}" height="{card_height:.1f}" rx="12" fill="{fill}" stroke="{stroke}"><title>{escape(full_label)} · {escape(role)} · {escape(total_label)}</title></rect>'
        )
        chunks.append(
            f'<circle cx="{x - card_width / 2 + 18:.1f}" cy="{y - 21:.1f}" r="5" fill="{stroke}"/>'
        )
        if not standard_mode or node.get("background"):
            chunks.append(
                f'<text class="node-role" x="{x - card_width / 2 + 31:.1f}" y="{y - 17:.1f}" fill="{stroke}">{escape(role)}</text>'
            )
        if node.get("background"):
            visible_label = _shorten(full_label, 78)
            for line_index, start in enumerate(range(0, len(visible_label), 26)):
                chunks.append(f'<text class="node-title" style="font-size:10px" x="{x - card_width / 2 + 16:.1f}" y="{y - 4 + line_index * 12:.1f}">{escape(visible_label[start:start + 26])}</text>')
        else:
            chunks.append(
                f'<text class="node-title" x="{x - card_width / 2 + 16:.1f}" y="{y + 4:.1f}">{escape(_shorten(full_label, 27))}</text>'
            )
        chunks.append(
            f'<text class="node-total" x="{x - card_width / 2 + 16:.1f}" y="{y + (38 if node.get("background") else 25):.1f}">{escape(total_label)}</text>'
        )
    legend_y = height - 28
    legend = (
        (
            ("#6f879e", "Energy input"),
            ("#3478d4", "Useful energy"),
            ("#4aa7b5", "Explicit loss"),
        )
        if energy_flow_mode
        else (
            ("#6f879e", "External energy input"),
            ("#3478d4", "Facility energy flow"),
            ("#4aa7b5", "Explicit loss"),
        )
        if spatial_energy_flow_mode
        else (("#6f879e", "External energy input"),)
        if spatial_energy_mode
        else (
            (("#6f879e", "Park input"), ("#3478d4", "Inter-facility flow"), ("#38a87c", "Elementary output"), ("#4aa7b5", "Park output"))
            if park_mode
            else (("#6f879e", L("外部投入", "External inputs")), ("#3478d4", L("工序间流", "Process transfers")), ("#38a87c", L("环境排放", "Environmental emissions")), ("#4aa7b5", L("产品与副产物", "Products and coproducts")))
        )
    )
    legend_x = 48
    for color, label in legend:
        chunks.append(f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 24}" y2="{legend_y}" stroke="{color}" stroke-width="6" stroke-linecap="round"/>')
        chunks.append(f'<text class="legend" x="{legend_x + 34}" y="{legend_y + 4}">{escape(label)}</text>')
        legend_x += 188
    footer_note = (
        "Explicit conversion and loss only · no inferred energy or efficiency"
        if energy_flow_mode
        else "Facility attribution only · no inferred energy, loss or allocation"
        if spatial_energy_flow_mode
        else "External inputs only · no inferred conversion, loss or allocation"
        if spatial_energy_mode
        else (
            L("部分背景不构成完整摇篮到大门 · 悬停查看流向来源", "Partial background is not complete cradle-to-gate · hover a flow for provenance")
            if has_partial_background
            else (
                "Intra-facility transfers are consolidated · hover for provenance"
                if park_mode
                else L("流宽按本单位序列内的相对值绘制 · 悬停查看来源", "Flow width is relative within this unit series · hover for provenance")
            )
        )
    )
    if not standard_mode or has_partial_background:
        note_y = legend_y + 24 if standard_mode else legend_y + 4
        chunks.append(f'<text class="legend" x="{width - 48}" y="{note_y}" text-anchor="end">{escape(footer_note)}</text>')
    chunks.append("</svg>")
    return "".join(chunks)
