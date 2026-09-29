from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


def _text(value: Any) -> str:
    return str(value or "").strip()


def _decimal(value: Any, *, code: str, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DomainError(
            code=code,
            message=f"energy flow {field} is invalid",
            status_code=422,
        ) from exc
    if not parsed.is_finite() or parsed < 0:
        raise DomainError(
            code=code,
            message=f"energy flow {field} must be finite and non-negative",
            status_code=422,
        )
    return parsed


def _fail(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def _single(
    index: dict[str, list[dict[str, Any]]],
    exchange_id: str,
    *,
    code: str,
) -> dict[str, Any]:
    matches = index.get(exchange_id, [])
    if len(matches) != 1:
        _fail(
            code,
            "energy flow exchange must resolve exactly once",
            exchange_id=exchange_id,
            count=len(matches),
        )
    return matches[0]


def _exchange_index(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        index[_text(item.get("exchange_id"))].append(item)
    return index


def _graph_index(graph: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    processes: dict[str, dict[str, Any]] = {}
    exchanges: dict[str, dict[str, Any]] = {}
    for node in graph.get("nodes") or []:
        node_id = _text(node.get("id"))
        process_uuid = _text(node.get("process_uuid"))
        if not node_id or not process_uuid or node_id in processes:
            _fail(
                "ENERGY_FLOW_GRAPH_PROCESS_INVALID",
                "energy flow requires unique graph node and process identities",
                node_id=node_id,
                process_uuid=process_uuid,
            )
        processes[node_id] = node
        for collection in ("inputs", "outputs", "emissions"):
            for exchange in node.get(collection) or []:
                local_id = _text(exchange.get("id"))
                exchange_id = f"{node_id}::{local_id}"
                if not local_id or exchange_id in exchanges:
                    _fail(
                        "ENERGY_FLOW_GRAPH_EXCHANGE_INVALID",
                        "energy flow requires unique graph exchange identities",
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


def _energy_entries(energy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for series in energy.get("series") or []:
        for entry in series.get("entries") or []:
            entry_id = _text(entry.get("entry_id"))
            if not entry_id or entry_id in entries:
                _fail(
                    "ENERGY_FLOW_ENTRY_ID_INVALID",
                    "energy flow requires unique energy entry identities",
                    entry_id=entry_id,
                )
            entries[entry_id] = {**entry, "series_id": series.get("series_id")}
    return entries


def _source_exchange_id(entry: dict[str, Any]) -> str:
    source = entry.get("source") or {}
    if source.get("kind") == "direct_solved_exchange":
        return _text(source.get("exchange_id"))
    if source.get("kind") == "quantity_conversion":
        return _text(source.get("source_exchange_id"))
    _fail(
        "ENERGY_FLOW_ENTRY_SOURCE_UNSUPPORTED",
        "energy flow entry has an unsupported source contract",
        entry_id=entry.get("entry_id"),
    )
    raise AssertionError("unreachable")


def _verify_snapshot_identity(
    solved_snapshot: dict[str, Any], energy_record: dict[str, Any]
) -> dict[str, Any]:
    energy = energy_record.get("result")
    if not isinstance(energy, dict):
        _fail("ENERGY_FLOW_RESULT_INVALID", "energy carrier result payload is missing")
    expected = (
        _text(solved_snapshot.get("id")),
        _text(solved_snapshot.get("content_sha256")),
        _text(solved_snapshot.get("solve_hash")),
    )
    ref = energy.get("solved_snapshot_ref") or {}
    actual = (
        _text(ref.get("id")),
        _text(ref.get("content_sha256")),
        _text(ref.get("solve_hash")),
    )
    if (
        not all(expected)
        or actual != expected
        or _text(energy_record.get("solved_snapshot_id")) != expected[0]
    ):
        _fail(
            "ENERGY_FLOW_SNAPSHOT_MISMATCH",
            "energy flow inputs must share the exact frozen solved snapshot",
        )
    if energy.get("status") not in {"passed", "passed_with_warnings"}:
        _fail("ENERGY_FLOW_SOURCE_FAILED", "energy carrier result did not pass its audit")
    if not _text(energy_record.get("content_sha256")) or not _text(
        energy.get("content_sha256")
    ):
        _fail("ENERGY_FLOW_IDENTITY_MISSING", "energy flow source hashes are incomplete")
    return energy


def build_energy_flow(
    *,
    solved_snapshot: dict[str, Any],
    graph: dict[str, Any],
    energy_record: dict[str, Any],
    conversions: list[dict[str, Any]],
    tolerance: Decimal,
) -> dict[str, Any]:
    if tolerance < 0 or not tolerance.is_finite():
        _fail("ENERGY_FLOW_TOLERANCE_INVALID", "energy flow tolerance is invalid")
    energy = _verify_snapshot_identity(solved_snapshot, energy_record)
    processes, graph_exchanges = _graph_index(graph)
    entries = _energy_entries(energy)
    solved_exchanges = _exchange_index(
        list(solved_snapshot.get("scaled_technosphere_exchanges") or [])
    )
    internal = _exchange_index(list(solved_snapshot.get("internal_transfers") or []))
    boundary = _exchange_index(list(solved_snapshot.get("boundary_flows") or []))

    if not conversions:
        _fail("ENERGY_FLOW_CONVERSION_EMPTY", "at least one explicit conversion process is required")

    used_entry_ids: set[str] = set()
    used_exchange_ids: set[str] = set()
    series: list[dict[str, Any]] = []
    for specification in conversions:
        node_id = _text(specification.get("process_node_id"))
        node = processes.get(node_id)
        if node is None:
            _fail(
                "ENERGY_FLOW_PROCESS_UNRESOLVED",
                "conversion process does not exist in the frozen graph",
                process_node_id=node_id,
            )
        process_uuid = _text(node.get("process_uuid"))
        input_ids = [_text(item) for item in specification.get("input_energy_entry_ids") or []]
        if not input_ids or len(input_ids) != len(set(input_ids)):
            _fail(
                "ENERGY_FLOW_INPUT_ENTRY_INVALID",
                "conversion input energy entries must be non-empty and unique",
                process_node_id=node_id,
            )
        duplicate_entries = sorted(set(input_ids).intersection(used_entry_ids))
        if duplicate_entries:
            _fail(
                "ENERGY_FLOW_ENTRY_DOUBLE_COUNTED",
                "an energy entry cannot feed more than one conversion balance",
                entry_ids=duplicate_entries,
            )

        input_amount = Decimal("0")
        input_exchange_ids: list[str] = []
        input_basis: dict[str, Any] | None = None
        input_unit_identity: str | None = None
        input_flow_names: list[str] = []
        for entry_id in input_ids:
            entry = entries.get(entry_id)
            if entry is None:
                _fail(
                    "ENERGY_FLOW_ENTRY_UNRESOLVED",
                    "conversion input energy entry does not exist",
                    entry_id=entry_id,
                )
            if entry.get("unit_symbol") != "MJ":
                _fail("ENERGY_FLOW_UNIT_UNSUPPORTED", "energy flow v1 requires MJ")
            basis = entry.get("basis") or {}
            unit_identity = _text((entry.get("unit_identity") or {}).get("identity_sha256"))
            if input_basis is None:
                input_basis = basis
                input_unit_identity = unit_identity
            elif basis != input_basis or unit_identity != input_unit_identity:
                _fail(
                    "ENERGY_FLOW_INPUT_SERIES_MISMATCH",
                    "one conversion balance cannot mix energy basis or unit identities",
                    process_node_id=node_id,
                )
            exchange_id = _source_exchange_id(entry)
            solved_exchange = _single(
                solved_exchanges,
                exchange_id,
                code="ENERGY_FLOW_INPUT_EXCHANGE_UNRESOLVED",
            )
            graph_exchange = graph_exchanges.get(exchange_id)
            if (
                graph_exchange is None
                or _text(solved_exchange.get("process_id")) != process_uuid
                or _text(graph_exchange.get("process_uuid")) != process_uuid
                or solved_exchange.get("direction") != "input"
                or graph_exchange.get("direction") != "input"
                or _text(graph_exchange.get("flowUuid"))
                != _text(solved_exchange.get("flow_uuid"))
                or _text(graph_exchange.get("unit")) != _text(solved_exchange.get("unit"))
                or _text(graph_exchange.get("unitGroupUuid"))
                != _text(solved_exchange.get("unit_group"))
            ):
                _fail(
                    "ENERGY_FLOW_INPUT_PROCESS_MISMATCH",
                    "energy input exchange is not an input of the declared conversion process",
                    exchange_id=exchange_id,
                    process_node_id=node_id,
                )
            input_amount += _decimal(
                entry.get("amount"), code="ENERGY_FLOW_AMOUNT_INVALID", field="input amount"
            )
            input_exchange_ids.append(exchange_id)
            input_flow_names.append(_text(graph_exchange.get("name")) or exchange_id)
        if input_amount <= 0:
            _fail("ENERGY_FLOW_INPUT_ZERO", "conversion energy input must be positive")

        useful_links = list(specification.get("useful_internal_links") or [])
        loss_ids = [_text(item) for item in specification.get("loss_output_exchange_ids") or []]
        if not useful_links:
            _fail("ENERGY_FLOW_USEFUL_OUTPUT_EMPTY", "explicit useful internal energy is required")
        if not loss_ids:
            _fail("ENERGY_FLOW_LOSS_OUTPUT_EMPTY", "explicit conversion loss is required")

        nodes: dict[str, dict[str, Any]] = {}
        links: list[dict[str, Any]] = []
        conversion_node_id = f"process:{process_uuid}"
        nodes[conversion_node_id] = {
            "id": conversion_node_id,
            "label": _text(node.get("name")) or node_id,
            "kind": "process",
            "process_id": process_uuid,
            "display_role": "ENERGY CONVERSION",
        }
        input_node_id = f"energy-input:{canonical_json_sha256(input_ids)[:16]}"
        nodes[input_node_id] = {
            "id": input_node_id,
            "label": " + ".join(sorted(set(input_flow_names))),
            "kind": "system_boundary",
            "direction": "input",
            "display_role": "ENERGY INPUT",
        }
        links.append(
            {
                "id": f"energy-flow-input:{canonical_json_sha256(input_ids)[:20]}",
                "source": input_node_id,
                "target": conversion_node_id,
                "value": float(input_amount),
                "kind": "boundary",
                "direction": "input",
                "flow_name": " + ".join(sorted(set(input_flow_names))),
                "exchange_ids": sorted(input_exchange_ids),
                "energy_entry_ids": sorted(input_ids),
            }
        )

        useful_amount = Decimal("0")
        useful_receipts: list[dict[str, Any]] = []
        output_unit_group: str | None = None
        for link_spec in useful_links:
            source_id = _text(link_spec.get("source_exchange_id"))
            target_id = _text(link_spec.get("target_exchange_id"))
            if not source_id or not target_id or source_id == target_id:
                _fail("ENERGY_FLOW_INTERNAL_LINK_INVALID", "internal energy link is invalid")
            if source_id in used_exchange_ids or target_id in used_exchange_ids:
                _fail(
                    "ENERGY_FLOW_EXCHANGE_DOUBLE_COUNTED",
                    "an energy exchange cannot be used twice",
                    exchange_ids=[source_id, target_id],
                )
            source = _single(internal, source_id, code="ENERGY_FLOW_INTERNAL_SOURCE_UNRESOLVED")
            target = _single(internal, target_id, code="ENERGY_FLOW_INTERNAL_TARGET_UNRESOLVED")
            source_graph = graph_exchanges.get(source_id)
            target_graph = graph_exchanges.get(target_id)
            same_identity = (
                source.get("flow_uuid") == target.get("flow_uuid")
                and source.get("unit") == target.get("unit") == "MJ"
                and source.get("unit_group") == target.get("unit_group")
            )
            graph_identity_match = (
                _text(source_graph.get("flowUuid") if source_graph else None)
                == _text(source.get("flow_uuid"))
                and _text(target_graph.get("flowUuid") if target_graph else None)
                == _text(target.get("flow_uuid"))
                and _text(source_graph.get("unit") if source_graph else None)
                == _text(source.get("unit"))
                and _text(target_graph.get("unit") if target_graph else None)
                == _text(target.get("unit"))
                and _text(source_graph.get("unitGroupUuid") if source_graph else None)
                == _text(source.get("unit_group"))
                and _text(target_graph.get("unitGroupUuid") if target_graph else None)
                == _text(target.get("unit_group"))
            )
            source_amount = _decimal(
                source.get("amount"), code="ENERGY_FLOW_AMOUNT_INVALID", field="useful output"
            )
            target_amount = _decimal(
                target.get("amount"), code="ENERGY_FLOW_AMOUNT_INVALID", field="useful input"
            )
            if (
                source_graph is None
                or target_graph is None
                or source.get("direction") != "output"
                or target.get("direction") != "input"
                or _text(source.get("process_id")) != process_uuid
                or _text(source_graph.get("process_uuid")) != process_uuid
                or _text(target.get("process_id")) != _text(target_graph.get("process_uuid"))
                or not same_identity
                or not graph_identity_match
                or abs(source_amount - target_amount) > tolerance
            ):
                _fail(
                    "ENERGY_FLOW_INTERNAL_LINK_MISMATCH",
                    "useful internal energy link is not an exact balanced Flow pair",
                    source_exchange_id=source_id,
                    target_exchange_id=target_id,
                )
            current_unit_group = _text(source.get("unit_group"))
            if output_unit_group is None:
                output_unit_group = current_unit_group
            elif current_unit_group != output_unit_group:
                _fail(
                    "ENERGY_FLOW_OUTPUT_SERIES_MISMATCH",
                    "one conversion balance cannot mix output energy unit groups",
                    process_node_id=node_id,
                )
            target_process_uuid = _text(target.get("process_id"))
            target_process_node_id = f"process:{target_process_uuid}"
            nodes[target_process_node_id] = {
                "id": target_process_node_id,
                "label": _text(target_graph.get("process_name")) or target_process_uuid,
                "kind": "process",
                "process_id": target_process_uuid,
                "display_role": "ENERGY USER",
            }
            flow_name = _text(source_graph.get("name")) or _text(source.get("flow_uuid"))
            links.append(
                {
                    "id": f"energy-flow-useful:{canonical_json_sha256([source_id, target_id])[:20]}",
                    "source": conversion_node_id,
                    "target": target_process_node_id,
                    "value": float(source_amount),
                    "kind": "internal",
                    "direction": "output",
                    "flow_uuid": source.get("flow_uuid"),
                    "flow_name": flow_name,
                    "exchange_ids": [source_id, target_id],
                }
            )
            useful_receipts.append(
                {
                    "source_exchange_id": source_id,
                    "target_exchange_id": target_id,
                    "flow_uuid": source.get("flow_uuid"),
                    "amount": str(source_amount),
                    "unit": "MJ",
                    "unit_group": source.get("unit_group"),
                }
            )
            useful_amount += source_amount
            used_exchange_ids.update({source_id, target_id})

        loss_amount = Decimal("0")
        loss_receipts: list[dict[str, Any]] = []
        for exchange_id in loss_ids:
            if exchange_id in used_exchange_ids:
                _fail(
                    "ENERGY_FLOW_EXCHANGE_DOUBLE_COUNTED",
                    "an energy exchange cannot be used twice",
                    exchange_ids=[exchange_id],
                )
            loss = _single(boundary, exchange_id, code="ENERGY_FLOW_LOSS_UNRESOLVED")
            graph_loss = graph_exchanges.get(exchange_id)
            if (
                graph_loss is None
                or loss.get("direction") != "output"
                or graph_loss.get("direction") != "output"
                or _text(loss.get("process_id")) != process_uuid
                or _text(graph_loss.get("process_uuid")) != process_uuid
                or loss.get("unit") != "MJ"
                or _text(graph_loss.get("flowUuid")) != _text(loss.get("flow_uuid"))
                or _text(graph_loss.get("unit")) != _text(loss.get("unit"))
                or _text(graph_loss.get("unitGroupUuid"))
                != _text(loss.get("unit_group"))
            ):
                _fail(
                    "ENERGY_FLOW_LOSS_PROCESS_MISMATCH",
                    "loss must be an explicit MJ boundary output of the conversion process",
                    exchange_id=exchange_id,
                )
            current_unit_group = _text(loss.get("unit_group"))
            if output_unit_group is None or current_unit_group != output_unit_group:
                _fail(
                    "ENERGY_FLOW_OUTPUT_SERIES_MISMATCH",
                    "useful energy and explicit loss must share one output energy unit group",
                    process_node_id=node_id,
                )
            amount = _decimal(
                loss.get("amount"), code="ENERGY_FLOW_AMOUNT_INVALID", field="loss output"
            )
            if amount <= 0:
                _fail("ENERGY_FLOW_LOSS_ZERO", "explicit conversion loss must be positive")
            loss_node_id = f"energy-loss:{exchange_id}"
            flow_name = _text(graph_loss.get("name")) or exchange_id
            nodes[loss_node_id] = {
                "id": loss_node_id,
                "label": flow_name,
                "kind": "system_boundary",
                "direction": "output",
                "display_role": "EXPLICIT ENERGY LOSS",
            }
            links.append(
                {
                    "id": f"energy-flow-loss:{canonical_json_sha256(exchange_id)[:20]}",
                    "source": conversion_node_id,
                    "target": loss_node_id,
                    "value": float(amount),
                    "kind": "boundary",
                    "direction": "output",
                    "flow_uuid": loss.get("flow_uuid"),
                    "flow_name": flow_name,
                    "exchange_ids": [exchange_id],
                }
            )
            loss_receipts.append(
                {
                    "exchange_id": exchange_id,
                    "flow_uuid": loss.get("flow_uuid"),
                    "amount": str(amount),
                    "unit": "MJ",
                    "unit_group": loss.get("unit_group"),
                }
            )
            loss_amount += amount
            used_exchange_ids.add(exchange_id)

        residual = input_amount - useful_amount - loss_amount
        if abs(residual) > tolerance:
            _fail(
                "ENERGY_FLOW_BALANCE_FAILED",
                "explicit useful energy and loss do not reconcile to conversion input",
                process_node_id=node_id,
                input_amount=str(input_amount),
                useful_amount=str(useful_amount),
                loss_amount=str(loss_amount),
                residual=str(residual),
                tolerance=str(tolerance),
            )
        series_basis = {
            "series_id": f"energy-flow-{canonical_json_sha256({'process': node_id, 'entries': sorted(input_ids)})[:24]}",
            "process_node_id": node_id,
            "process_uuid": process_uuid,
            "process_name": _text(node.get("name")) or node_id,
            "unit": "MJ",
            "input_basis": input_basis,
            "input_unit_identity_sha256": input_unit_identity,
            "input_amount": str(input_amount),
            "useful_output_amount": str(useful_amount),
            "explicit_loss_amount": str(loss_amount),
            "balance_residual": str(residual),
            "conversion_efficiency": str(useful_amount / input_amount),
            "input_energy_entry_ids": sorted(input_ids),
            "input_exchange_ids": sorted(input_exchange_ids),
            "useful_internal_links": useful_receipts,
            "explicit_loss_outputs": loss_receipts,
            "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
            "links": sorted(links, key=lambda item: item["id"]),
        }
        series.append(series_basis)
        used_entry_ids.update(input_ids)

    inherited_issues = list(energy.get("issues") or [])
    source_snapshot = {
        "id": solved_snapshot.get("id"),
        "system_revision_id": solved_snapshot.get("system_revision_id"),
        "content_sha256": solved_snapshot.get("content_sha256"),
        "solve_hash": solved_snapshot.get("solve_hash"),
    }
    content = {
        "schema_version": "nebula_one.energy-flow.solved.v1",
        "capability_key": "energy.flow.solved.v1",
        "source_snapshot": source_snapshot,
        "source_energy_result": {
            "id": energy_record.get("id"),
            "record_content_sha256": energy_record.get("content_sha256"),
            "result_content_sha256": energy.get("content_sha256"),
        },
        "series": sorted(series, key=lambda item: item["series_id"]),
        "audit": {
            "status": "passed_with_warnings" if inherited_issues else "passed",
            "checks": {
                "snapshot_identity_match": True,
                "source_energy_result_passed": True,
                "conversion_process_resolved": True,
                "input_entries_used_once": True,
                "input_basis_kept_separate": True,
                "internal_links_exact_and_balanced": True,
                "losses_explicit": True,
                "conversion_balances_reconciled": True,
                "no_inferred_loss": True,
            },
            "counts": {
                "conversion_process_count": len(series),
                "input_entry_count": len(used_entry_ids),
                "traced_exchange_count": len(used_exchange_ids) + len(
                    {item for series_item in series for item in series_item["input_exchange_ids"]}
                ),
            },
            "issues": inherited_issues,
            "limitations": [
                "v1 audits only explicitly declared conversion processes and exchange pairs",
                "v1 does not infer heat losses, conversion efficiency or missing energy exchanges",
                "heating-value inputs retain their physical-property basis while declared-energy outputs retain their Flow identity",
            ],
            "provenance": {
                "system_revision_id": solved_snapshot.get("system_revision_id"),
                "energy_entry_ids": sorted(used_entry_ids),
                "exchange_ids": sorted(
                    used_exchange_ids.union(
                        {item for series_item in series for item in series_item["input_exchange_ids"]}
                    )
                ),
            },
        },
    }
    return {**content, "content_sha256": canonical_json_sha256(content)}
