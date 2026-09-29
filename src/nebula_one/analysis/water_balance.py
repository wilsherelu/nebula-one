from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


SCHEMA_VERSION = "nebula_one.water-balance.solved.v1"
CAPABILITY_KEY = "water.balance.solved.v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _fail(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def _decimal(value: Any, *, exchange_id: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DomainError(
            code="WATER_BALANCE_AMOUNT_INVALID",
            message="water balance exchange amount is invalid",
            status_code=422,
            details={"exchange_id": exchange_id},
        ) from exc
    if not parsed.is_finite() or parsed < 0:
        _fail(
            "WATER_BALANCE_AMOUNT_INVALID",
            "water balance exchange amount must be finite and non-negative",
            exchange_id=exchange_id,
        )
    return parsed


def _graph_catalog(graph: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    processes: dict[str, dict[str, Any]] = {}
    exchanges: dict[str, dict[str, Any]] = {}
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = _text(node.get("id"))
        process_uuid = _text(node.get("process_uuid") or node.get("processUuid"))
        if not node_id or not process_uuid or process_uuid in processes:
            _fail(
                "WATER_BALANCE_GRAPH_PROCESS_INVALID",
                "water balance requires unique graph process identities",
                node_id=node_id,
                process_uuid=process_uuid,
            )
        processes[process_uuid] = {
            "node_id": node_id,
            "process_uuid": process_uuid,
            "name": _text(node.get("name")) or node_id,
        }
        for collection in ("inputs", "outputs", "emissions"):
            for exchange in node.get(collection) or []:
                local_id = _text(exchange.get("id"))
                exchange_id = f"{node_id}::{local_id}"
                if not local_id or exchange_id in exchanges:
                    _fail(
                        "WATER_BALANCE_GRAPH_EXCHANGE_INVALID",
                        "water balance requires unique graph exchange identities",
                        exchange_id=exchange_id,
                    )
                exchanges[exchange_id] = {
                    **exchange,
                    "exchange_id": exchange_id,
                    "node_id": node_id,
                    "process_uuid": process_uuid,
                    "process_name": _text(node.get("name")) or node_id,
                }
    return processes, exchanges


def _solved_index(
    solved_snapshot: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], set[str], set[str], set[str]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for collection in ("scaled_technosphere_exchanges", "scaled_elementary_exchanges"):
        for item in solved_snapshot.get(collection) or []:
            if isinstance(item, dict):
                index[_text(item.get("exchange_id"))].append(item)
    internal_ids = {
        _text(item.get("exchange_id"))
        for item in solved_snapshot.get("internal_transfers") or []
        if isinstance(item, dict)
    }
    boundary_ids = {
        _text(item.get("exchange_id"))
        for item in solved_snapshot.get("boundary_flows") or []
        if isinstance(item, dict)
    }
    elementary_ids = {
        _text(item.get("exchange_id"))
        for item in solved_snapshot.get("scaled_elementary_exchanges") or []
        if isinstance(item, dict)
    }
    return index, internal_ids, boundary_ids, elementary_ids


def _graph_link_pairs(graph: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for edge in graph.get("exchanges") or []:
        if not isinstance(edge, dict):
            continue
        source_node = _text(edge.get("fromNode") or edge.get("from_node"))
        target_node = _text(edge.get("toNode") or edge.get("to_node"))
        source_port = _text(
            edge.get("sourcePortId")
            or edge.get("source_port_id")
            or edge.get("sourceHandle")
        ).split(":")[-1]
        target_port = _text(
            edge.get("targetPortId")
            or edge.get("target_port_id")
            or edge.get("targetHandle")
        ).split(":")[-1]
        if source_node and target_node and source_port and target_port:
            pairs.add((f"{source_node}::{source_port}", f"{target_node}::{target_port}"))
    return pairs


def _single(
    index: dict[str, list[dict[str, Any]]], exchange_id: str
) -> dict[str, Any]:
    matches = index.get(exchange_id, [])
    if len(matches) != 1:
        _fail(
            "WATER_BALANCE_EXCHANGE_UNRESOLVED",
            "water balance exchange must resolve exactly once",
            exchange_id=exchange_id,
            count=len(matches),
        )
    return matches[0]


def _identity(graph_exchange: dict[str, Any]) -> dict[str, str]:
    return {
        "source_namespace": _text(
            graph_exchange.get("flowSourceNamespace")
            or graph_exchange.get("flow_source_namespace")
        ),
        "flow_uuid": _text(graph_exchange.get("flowUuid") or graph_exchange.get("flow_uuid")),
        "flow_version": _text(
            graph_exchange.get("flowVersion") or graph_exchange.get("flow_version")
        ),
        "flow_property_uuid": _text(
            graph_exchange.get("flowPropertyUuid")
            or graph_exchange.get("flow_property_uuid")
        ),
        "flow_property_version": _text(
            graph_exchange.get("flowPropertyVersion")
            or graph_exchange.get("flow_property_version")
        ),
        "unit_group_uuid": _text(
            graph_exchange.get("unitGroupUuid") or graph_exchange.get("unit_group_uuid")
        ),
        "unit_group_version": _text(
            graph_exchange.get("unitGroupVersion")
            or graph_exchange.get("unit_group_version")
        ),
        "unit": _text(graph_exchange.get("unit")),
    }


def _provider_receipt_indexes(
    solved_snapshot: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    provider_receipt = solved_snapshot.get("provider_receipt")
    if not isinstance(provider_receipt, dict):
        _fail(
            "WATER_BALANCE_PROVIDER_RECEIPT_MISSING",
            "water balance requires provider Flow identity receipts",
        )
    indexes: list[dict[str, list[dict[str, Any]]]] = []
    for key in ("technosphere_flow_receipts", "elementary_flow_receipts"):
        index: dict[str, list[dict[str, Any]]] = defaultdict(list)
        rows = provider_receipt.get(key)
        if not isinstance(rows, list):
            _fail(
                "WATER_BALANCE_PROVIDER_RECEIPT_INVALID",
                "water balance provider receipt collection is invalid",
                collection=key,
            )
        for item in rows:
            if isinstance(item, dict):
                index[_text(item.get("exchange_id"))].append(item)
        indexes.append(index)
    return indexes[0], indexes[1]


def _verify_provider_receipt(
    *,
    exchange_id: str,
    identity: dict[str, str],
    receipt_index: dict[str, list[dict[str, Any]]],
    receipt_kind: str,
) -> dict[str, Any]:
    matches = receipt_index.get(exchange_id, [])
    if len(matches) != 1:
        _fail(
            "WATER_BALANCE_PROVIDER_RECEIPT_UNRESOLVED",
            "water balance Flow identity receipt must resolve exactly once",
            exchange_id=exchange_id,
            receipt_kind=receipt_kind,
            count=len(matches),
        )
    receipt = matches[0]
    expected = {
        "source_namespace": identity["source_namespace"],
        "flow_uuid": identity["flow_uuid"],
        "version": identity["flow_version"],
        "flow_property_uuid": identity["flow_property_uuid"],
        "flow_property_version": identity["flow_property_version"],
        "unit_group_uuid": identity["unit_group_uuid"],
        "unit_group_version": identity["unit_group_version"],
        "unit": identity["unit"],
    }
    if any(_text(receipt.get(key)) != value for key, value in expected.items()):
        _fail(
            "WATER_BALANCE_PROVIDER_RECEIPT_MISMATCH",
            "water balance provider receipt does not match the frozen graph identity",
            exchange_id=exchange_id,
            receipt_kind=receipt_kind,
        )
    if not _text(receipt.get("content_hash")) or not _text(receipt.get("snapshot_hash")):
        _fail(
            "WATER_BALANCE_PROVIDER_RECEIPT_HASH_MISSING",
            "water balance provider receipt requires content and snapshot hashes",
            exchange_id=exchange_id,
            receipt_kind=receipt_kind,
        )
    if receipt_kind == "elementary" and not _text(receipt.get("compartment")):
        _fail(
            "WATER_BALANCE_ELEMENTARY_COMPARTMENT_MISSING",
            "consumptive elementary output requires an exact compartment receipt",
            exchange_id=exchange_id,
        )
    return receipt


def _resolve_exchange(
    *,
    exchange_id: str,
    expected_direction: str,
    graph_exchanges: dict[str, dict[str, Any]],
    solved_index: dict[str, list[dict[str, Any]]],
    required_membership: set[str],
    membership_label: str,
    receipt_index: dict[str, list[dict[str, Any]]],
    receipt_kind: str,
) -> dict[str, Any]:
    graph_exchange = graph_exchanges.get(exchange_id)
    solved = _single(solved_index, exchange_id)
    identity = _identity(graph_exchange or {})
    required_identity = (
        "source_namespace",
        "flow_uuid",
        "flow_version",
        "flow_property_uuid",
        "flow_property_version",
        "unit_group_uuid",
        "unit_group_version",
        "unit",
    )
    if graph_exchange is None or any(not identity[key] for key in required_identity):
        _fail(
            "WATER_BALANCE_FLOW_IDENTITY_INCOMPLETE",
            "water balance requires an exact versioned Flow identity",
            exchange_id=exchange_id,
        )
    if (
        exchange_id not in required_membership
        or _text(solved.get("direction")) != expected_direction
        or _text(graph_exchange.get("direction")) != expected_direction
        or _text(solved.get("process_id")) != _text(graph_exchange.get("process_uuid"))
        or _text(solved.get("flow_uuid")) != identity["flow_uuid"]
        or _text(solved.get("unit_group")) != identity["unit_group_uuid"]
        or _text(solved.get("unit")) != identity["unit"]
    ):
        _fail(
            "WATER_BALANCE_EXCHANGE_MISMATCH",
            "water balance exchange does not match the frozen graph and solved classification",
            exchange_id=exchange_id,
            required_membership=membership_label,
            expected_direction=expected_direction,
        )
    receipt = _verify_provider_receipt(
        exchange_id=exchange_id,
        identity=identity,
        receipt_index=receipt_index,
        receipt_kind=receipt_kind,
    )
    return {
        "exchange_id": exchange_id,
        "process_uuid": _text(solved.get("process_id")),
        "process_name": _text(graph_exchange.get("process_name")),
        "flow_name": _text(graph_exchange.get("name")) or identity["flow_uuid"],
        "identity": identity,
        "amount": _decimal(solved.get("amount"), exchange_id=exchange_id),
        "provider_receipt": receipt,
    }


def _assert_series_identity(
    receipt: dict[str, Any], *, unit_group_uuid: str, unit: str
) -> None:
    identity = receipt["identity"]
    if identity["unit_group_uuid"] != unit_group_uuid or identity["unit"] != unit:
        _fail(
            "WATER_BALANCE_SERIES_IDENTITY_MISMATCH",
            "water balance series cannot mix unit identities",
            exchange_id=receipt["exchange_id"],
            expected_unit_group_uuid=unit_group_uuid,
            expected_unit=unit,
        )


def _process_node(receipt: dict[str, Any], *, role: str) -> dict[str, Any]:
    return {
        "id": f"process:{receipt['process_uuid']}",
        "label": receipt["process_name"],
        "kind": "process",
        "process_id": receipt["process_uuid"],
        "display_role": role,
    }


def _upsert_process_node(
    nodes: dict[str, dict[str, Any]], receipt: dict[str, Any], *, role: str
) -> None:
    process_id = f"process:{receipt['process_uuid']}"
    role_priority = {
        "WATER USER": 1,
        "WATER TREATMENT": 2,
        "WATER RECOVERY": 3,
    }
    current = nodes.get(process_id)
    if current is None or role_priority[role] > role_priority.get(
        current.get("display_role"), 0
    ):
        nodes[process_id] = _process_node(receipt, role=role)


def _boundary_node(exchange_id: str, label: str, *, role: str, direction: str) -> dict[str, Any]:
    return {
        "id": f"water-boundary:{role}:{exchange_id}",
        "label": label,
        "kind": "system_boundary",
        "direction": direction,
        "display_role": role.upper().replace("_", " "),
    }


def build_water_balance(
    *,
    solved_snapshot: dict[str, Any],
    revision_graph: dict[str, Any],
    series_specs: list[dict[str, Any]],
    tolerance: Decimal,
) -> dict[str, Any]:
    if not tolerance.is_finite() or tolerance < 0:
        _fail("WATER_BALANCE_TOLERANCE_INVALID", "water balance tolerance is invalid")
    if not series_specs:
        _fail("WATER_BALANCE_SERIES_EMPTY", "at least one water balance series is required")
    processes, graph_exchanges = _graph_catalog(revision_graph)
    solved_index, internal_ids, boundary_ids, elementary_ids = _solved_index(
        solved_snapshot
    )
    graph_link_pairs = _graph_link_pairs(revision_graph)
    technosphere_receipts, elementary_receipts = _provider_receipt_indexes(
        solved_snapshot
    )
    if not processes:
        _fail("WATER_BALANCE_GRAPH_EMPTY", "water balance requires a non-empty frozen graph")

    used_exchange_ids: set[str] = set()
    output_series: list[dict[str, Any]] = []
    for spec in series_specs:
        series_id = _text(spec.get("series_id"))
        unit_group_uuid = _text(spec.get("unit_group_uuid"))
        unit = _text(spec.get("unit"))
        if not series_id or not unit_group_uuid or not unit:
            _fail("WATER_BALANCE_SERIES_INVALID", "water balance series identity is incomplete")

        role_ids = {
            "withdrawal": [_text(item) for item in spec.get("withdrawal_exchange_ids") or []],
            "discharge": [_text(item) for item in spec.get("discharge_exchange_ids") or []],
            "consumption": [
                _text(item)
                for item in spec.get("consumptive_output_exchange_ids") or []
            ],
        }
        if any(not values for values in role_ids.values()):
            _fail(
                "WATER_BALANCE_REQUIRED_ROLE_EMPTY",
                "withdrawal, discharge and consumption exchanges are required",
                series_id=series_id,
            )
        wastewater_links = list(spec.get("wastewater_links") or [])
        reuse_links = list(spec.get("reuse_links") or [])
        if not wastewater_links or not reuse_links:
            _fail(
                "WATER_BALANCE_REQUIRED_LINK_EMPTY",
                "wastewater and reclaimed-water links are required",
                series_id=series_id,
            )

        nodes: dict[str, dict[str, Any]] = {}
        links: list[dict[str, Any]] = []
        receipts: dict[str, list[dict[str, Any]]] = {
            "withdrawals": [],
            "wastewater_links": [],
            "reuse_links": [],
            "discharges": [],
            "consumption_sinks": [],
        }
        totals = {
            "withdrawal": Decimal("0"),
            "wastewater": Decimal("0"),
            "reclaimed": Decimal("0"),
            "discharge": Decimal("0"),
            "consumption": Decimal("0"),
        }

        for role, ids in role_ids.items():
            duplicate = used_exchange_ids.intersection(ids)
            if duplicate and role != "consumption":
                _fail(
                    "WATER_BALANCE_EXCHANGE_DOUBLE_COUNTED",
                    "a water exchange cannot be assigned to multiple accounting roles",
                    exchange_ids=sorted(duplicate),
                )
            for exchange_id in ids:
                expected_direction = "input" if role == "withdrawal" else "output"
                membership = (
                    boundary_ids.union(elementary_ids)
                    if role == "consumption"
                    else boundary_ids
                )
                receipt = _resolve_exchange(
                    exchange_id=exchange_id,
                    expected_direction=expected_direction,
                    graph_exchanges=graph_exchanges,
                    solved_index=solved_index,
                    required_membership=membership,
                    membership_label=(
                        "scaled_elementary_exchanges_or_boundary_flows"
                        if role == "consumption"
                        else "boundary_flows"
                    ),
                    receipt_index=(
                        elementary_receipts
                        if role == "consumption"
                        else technosphere_receipts
                    ),
                    receipt_kind="elementary" if role == "consumption" else "technosphere",
                )
                _assert_series_identity(receipt, unit_group_uuid=unit_group_uuid, unit=unit)
                totals[role] += receipt["amount"]
                process_id = f"process:{receipt['process_uuid']}"
                _upsert_process_node(nodes, receipt, role="WATER USER")
                boundary = _boundary_node(
                    exchange_id,
                    receipt["flow_name"],
                    role=role,
                    direction="input" if role == "withdrawal" else "output",
                )
                nodes[boundary["id"]] = boundary
                source, target = (
                    (boundary["id"], process_id)
                    if role == "withdrawal"
                    else (process_id, boundary["id"])
                )
                links.append(
                    {
                        "id": f"water-{role}:{exchange_id}",
                        "source": source,
                        "target": target,
                        "value": float(receipt["amount"]),
                        "kind": "boundary",
                        "direction": expected_direction,
                        "flow_uuid": receipt["identity"]["flow_uuid"],
                        "flow_name": receipt["flow_name"],
                        "exchange_ids": [exchange_id],
                        "water_role": role,
                    }
                )
                receipts[{"withdrawal": "withdrawals", "discharge": "discharges", "consumption": "consumption_sinks"}[role]].append(
                    {**receipt, "amount": str(receipt["amount"])}
                )
            used_exchange_ids.update(ids)

        for role, raw_links, total_key in (
            ("wastewater", wastewater_links, "wastewater"),
            ("reuse", reuse_links, "reclaimed"),
        ):
            for raw_link in raw_links:
                source_id = _text(raw_link.get("source_exchange_id"))
                target_id = _text(raw_link.get("target_exchange_id"))
                if not source_id or not target_id or source_id == target_id:
                    _fail("WATER_BALANCE_INTERNAL_LINK_INVALID", "water internal link is invalid")
                if (source_id, target_id) not in graph_link_pairs:
                    _fail(
                        "WATER_BALANCE_INTERNAL_LINK_UNDECLARED",
                        "water internal link must exist in the frozen graph",
                        source_exchange_id=source_id,
                        target_exchange_id=target_id,
                    )
                if used_exchange_ids.intersection({source_id, target_id}):
                    _fail(
                        "WATER_BALANCE_EXCHANGE_DOUBLE_COUNTED",
                        "a water exchange cannot be assigned to multiple accounting roles",
                        exchange_ids=sorted(used_exchange_ids.intersection({source_id, target_id})),
                    )
                source = _resolve_exchange(
                    exchange_id=source_id,
                    expected_direction="output",
                    graph_exchanges=graph_exchanges,
                    solved_index=solved_index,
                    required_membership=internal_ids,
                    membership_label="internal_transfers",
                    receipt_index=technosphere_receipts,
                    receipt_kind="technosphere",
                )
                target = _resolve_exchange(
                    exchange_id=target_id,
                    expected_direction="input",
                    graph_exchanges=graph_exchanges,
                    solved_index=solved_index,
                    required_membership=internal_ids,
                    membership_label="internal_transfers",
                    receipt_index=technosphere_receipts,
                    receipt_kind="technosphere",
                )
                _assert_series_identity(source, unit_group_uuid=unit_group_uuid, unit=unit)
                _assert_series_identity(target, unit_group_uuid=unit_group_uuid, unit=unit)
                if (
                    source["identity"] != target["identity"]
                    or abs(source["amount"] - target["amount"]) > tolerance
                ):
                    _fail(
                        "WATER_BALANCE_INTERNAL_LINK_MISMATCH",
                        "water internal link is not an exact balanced Flow pair",
                        source_exchange_id=source_id,
                        target_exchange_id=target_id,
                    )
                source_process = f"process:{source['process_uuid']}"
                target_process = f"process:{target['process_uuid']}"
                source_role = "WATER USER" if role == "wastewater" else "WATER RECOVERY"
                target_role = "WATER TREATMENT" if role == "wastewater" else "WATER USER"
                _upsert_process_node(nodes, source, role=source_role)
                _upsert_process_node(nodes, target, role=target_role)
                links.append(
                    {
                        "id": f"water-{role}:{canonical_json_sha256([source_id, target_id])[:20]}",
                        "source": source_process,
                        "target": target_process,
                        "value": float(source["amount"]),
                        "kind": "internal",
                        "direction": "output",
                        "flow_uuid": source["identity"]["flow_uuid"],
                        "flow_name": source["flow_name"],
                        "exchange_ids": [source_id, target_id],
                        "water_role": role,
                    }
                )
                receipts[f"{role}_links"].append(
                    {
                        "source_exchange_id": source_id,
                        "target_exchange_id": target_id,
                        "identity": source["identity"],
                        "flow_name": source["flow_name"],
                        "amount": str(source["amount"]),
                    }
                )
                totals[total_key] += source["amount"]
                used_exchange_ids.update({source_id, target_id})

        residual = totals["withdrawal"] - totals["discharge"] - totals["consumption"]
        if abs(residual) > tolerance:
            _fail(
                "WATER_BALANCE_CONSERVATION_FAILED",
                "withdrawal must equal explicit discharge plus explicit consumption",
                series_id=series_id,
                withdrawal=str(totals["withdrawal"]),
                discharge=str(totals["discharge"]),
                consumption=str(totals["consumption"]),
                residual=str(residual),
                tolerance=str(tolerance),
            )
        if totals["wastewater"] <= 0 or totals["withdrawal"] <= 0:
            _fail("WATER_BALANCE_DENOMINATOR_ZERO", "water balance denominator must be positive")
        total_process_use = totals["withdrawal"] + totals["reclaimed"]
        treatment_recovery = totals["reclaimed"] / totals["wastewater"]
        reuse_share = totals["reclaimed"] / total_process_use
        if treatment_recovery > 1 + tolerance:
            _fail(
                "WATER_BALANCE_RECOVERY_EXCEEDS_INPUT",
                "reclaimed water cannot exceed treated wastewater",
                series_id=series_id,
            )

        output_series.append(
            {
                "series_id": series_id,
                "unit_group_uuid": unit_group_uuid,
                "unit": unit,
                "withdrawal_amount": str(totals["withdrawal"]),
                "wastewater_treated_amount": str(totals["wastewater"]),
                "reclaimed_water_amount": str(totals["reclaimed"]),
                "discharge_amount": str(totals["discharge"]),
                "consumption_amount": str(totals["consumption"]),
                "total_process_water_use": str(total_process_use),
                "treatment_recovery_rate": str(treatment_recovery),
                "reuse_share_of_total_use": str(reuse_share),
                "balance_residual": str(residual),
                "receipts": receipts,
                "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
                "links": sorted(links, key=lambda item: item["id"]),
            }
        )

    content = {
        "schema_version": SCHEMA_VERSION,
        "capability_key": CAPABILITY_KEY,
        "source_snapshot": {
            "id": solved_snapshot.get("id"),
            "system_revision_id": solved_snapshot.get("system_revision_id"),
            "content_sha256": solved_snapshot.get("content_sha256"),
            "solve_hash": solved_snapshot.get("solve_hash"),
        },
        "series": sorted(output_series, key=lambda item: item["series_id"]),
        "audit": {
            "status": "passed",
            "checks": {
                "exact_versioned_flow_identity": True,
                "solved_exchange_trace_complete": True,
                "unit_series_kept_separate": True,
                "internal_links_exact_and_balanced": True,
                "withdrawal_discharge_consumption_reconciled": True,
                "no_name_based_role_inference": True,
                "no_inferred_water_loss": True,
            },
            "counts": {
                "series_count": len(output_series),
                "traced_exchange_count": len(used_exchange_ids),
            },
            "issues": [],
            "limitations": [
                "v1 analyzes only explicitly bound solved water exchanges",
                "v1 does not infer water roles from Flow names or classifications",
                "mass and volume series are never combined without an explicit conversion receipt",
                "water quality, pollutant load and scarcity impacts are outside this balance contract",
            ],
            "provenance": {
                "system_revision_id": solved_snapshot.get("system_revision_id"),
                "exchange_ids": sorted(used_exchange_ids),
            },
        },
    }
    return {**content, "content_sha256": canonical_json_sha256(content)}
