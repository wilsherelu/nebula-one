from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


def _text(value: Any) -> str:
    return str(value or "").strip()


def _fail(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def _source_exchange_id(entry: dict[str, Any]) -> str:
    source = entry.get("source") or {}
    if source.get("kind") == "direct_solved_exchange":
        return _text(source.get("exchange_id"))
    if source.get("kind") == "quantity_conversion":
        return _text(source.get("source_exchange_id"))
    _fail(
        "SPATIAL_ENERGY_SOURCE_UNSUPPORTED",
        "energy entry has an unsupported source contract",
        entry_id=entry.get("entry_id"),
    )
    raise AssertionError("unreachable")


def build_spatial_energy(
    *,
    solved_snapshot: dict[str, Any],
    energy_record: dict[str, Any],
    spatial_aggregate: dict[str, Any],
) -> dict[str, Any]:
    energy = energy_record.get("result")
    if not isinstance(energy, dict):
        _fail("SPATIAL_ENERGY_RESULT_INVALID", "energy result payload is missing")

    snapshot_id = _text(solved_snapshot.get("id"))
    snapshot_hash = _text(solved_snapshot.get("content_sha256"))
    solve_hash = _text(solved_snapshot.get("solve_hash"))
    energy_ref = energy.get("solved_snapshot_ref") or {}
    spatial_ref = spatial_aggregate.get("source_snapshot") or {}
    expected_ref = (snapshot_id, snapshot_hash, solve_hash)
    if (
        _text(energy_record.get("solved_snapshot_id")) != snapshot_id
        or (
            _text(energy_ref.get("id")),
            _text(energy_ref.get("content_sha256")),
            _text(energy_ref.get("solve_hash")),
        )
        != expected_ref
        or (
            _text(spatial_ref.get("id")),
            _text(spatial_ref.get("content_sha256")),
            _text(spatial_ref.get("solve_hash")),
        )
        != expected_ref
    ):
        _fail(
            "SPATIAL_ENERGY_SNAPSHOT_MISMATCH",
            "energy, spatial and solved results must share the exact frozen snapshot",
        )
    if not _text(energy_record.get("content_sha256")) or not _text(
        energy.get("content_sha256")
    ):
        _fail(
            "SPATIAL_ENERGY_IDENTITY_MISSING",
            "energy result requires immutable record and result hashes",
        )
    if energy.get("status") not in {"passed", "passed_with_warnings"}:
        _fail("SPATIAL_ENERGY_SOURCE_FAILED", "energy result did not pass its audit")
    spatial_audit = spatial_aggregate.get("audit") or {}
    if spatial_audit.get("status") not in {"passed", "passed_with_warnings"}:
        _fail("SPATIAL_ENERGY_SPATIAL_FAILED", "spatial result did not pass its audit")

    facility_by_process: dict[str, dict[str, Any]] = {}
    facilities = list(spatial_aggregate.get("facilities") or [])
    for facility in facilities:
        for process_uuid in facility.get("process_uuids") or []:
            process_key = _text(process_uuid)
            if process_key in facility_by_process:
                _fail(
                    "SPATIAL_ENERGY_PROCESS_BINDING_OVERLAP",
                    "a process is assigned to more than one facility",
                    process_uuid=process_key,
                )
            facility_by_process[process_key] = facility

    exchanges_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for exchange in solved_snapshot.get("scaled_technosphere_exchanges") or []:
        exchanges_by_id[_text(exchange.get("exchange_id"))].append(exchange)

    spatial_metrics_by_exchange: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for series in spatial_aggregate.get("series") or []:
        for metric in series.get("external_flow_metrics") or []:
            for exchange_id in metric.get("exchange_ids") or []:
                spatial_metrics_by_exchange[_text(exchange_id)].append(metric)

    result_series: list[dict[str, Any]] = []
    traced_exchange_ids: list[str] = []
    traced_entry_ids: list[str] = []
    for energy_series in energy.get("series") or []:
        nodes: dict[str, dict[str, Any]] = {}
        links: list[dict[str, Any]] = []
        facility_amounts: dict[str, Decimal] = {
            _text(item.get("entity_id")): Decimal("0") for item in facilities
        }
        carrier_amounts: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        entries = list(energy_series.get("entries") or [])
        for entry in entries:
            entry_id = _text(entry.get("entry_id"))
            exchange_id = _source_exchange_id(entry)
            exchange_matches = exchanges_by_id.get(exchange_id, [])
            if len(exchange_matches) != 1:
                _fail(
                    "SPATIAL_ENERGY_EXCHANGE_UNRESOLVED",
                    "energy source exchange must resolve exactly once in the solved inventory",
                    entry_id=entry_id,
                    exchange_id=exchange_id,
                    count=len(exchange_matches),
                )
            exchange = exchange_matches[0]
            if exchange.get("direction") != "input":
                _fail(
                    "SPATIAL_ENERGY_NOT_EXTERNAL_INPUT",
                    "spatial.energy.v1 only attributes solved external energy inputs",
                    exchange_id=exchange_id,
                    direction=exchange.get("direction"),
                )
            process_uuid = _text(exchange.get("process_id"))
            facility = facility_by_process.get(process_uuid)
            if facility is None:
                _fail(
                    "SPATIAL_ENERGY_FACILITY_UNRESOLVED",
                    "energy source process is not bound to an included facility",
                    exchange_id=exchange_id,
                    process_uuid=process_uuid,
                )
            spatial_matches = spatial_metrics_by_exchange.get(exchange_id, [])
            if len(spatial_matches) != 1 or spatial_matches[0].get("direction") != "input":
                _fail(
                    "SPATIAL_ENERGY_BOUNDARY_EVIDENCE_UNRESOLVED",
                    "energy source must resolve to exactly one spatial external-input metric",
                    exchange_id=exchange_id,
                    count=len(spatial_matches),
                )
            spatial_metric = spatial_matches[0]
            carrier_flow = entry.get("carrier_flow") or {}
            flow_uuid = _text(carrier_flow.get("flow_uuid"))
            if flow_uuid != _text(exchange.get("flow_uuid")) or flow_uuid != _text(
                spatial_metric.get("flow_uuid")
            ):
                _fail(
                    "SPATIAL_ENERGY_FLOW_IDENTITY_MISMATCH",
                    "energy entry Flow does not match solved and spatial evidence",
                    entry_id=entry_id,
                    exchange_id=exchange_id,
                )
            try:
                amount = Decimal(str(entry.get("amount")))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise DomainError(
                    code="SPATIAL_ENERGY_AMOUNT_INVALID",
                    message="energy entry amount is invalid",
                    status_code=422,
                ) from exc
            if not amount.is_finite() or amount <= 0:
                _fail(
                    "SPATIAL_ENERGY_AMOUNT_INVALID",
                    "energy entry amount must be finite and positive",
                    entry_id=entry_id,
                )

            facility_id = _text(facility.get("entity_id"))
            source_id = f"energy-flow:{flow_uuid}"
            target_id = f"facility:{facility_id}"
            flow_name = _text(spatial_metric.get("flow_name")) or flow_uuid
            nodes[source_id] = {
                "id": source_id,
                "label": flow_name,
                "kind": "system_boundary",
                "direction": "input",
                "display_role": "ENERGY CARRIER",
                "flow_uuid": flow_uuid,
            }
            nodes[target_id] = {
                "id": target_id,
                "label": facility.get("name") or facility_id,
                "kind": "process",
                "process_id": facility_id,
                "entity_id": facility_id,
                "display_role": "FACILITY",
                "spatial_unit_ref": (
                    f"{facility['spatial_unit']['spatial_unit_id']}@"
                    f"{facility['spatial_unit']['version']}"
                ),
                "spatial_unit_sha256": facility["spatial_unit"]["content_sha256"],
            }
            links.append(
                {
                    "id": "spatial-energy:" + canonical_json_sha256(
                        {"entry_id": entry_id, "facility_id": facility_id}
                    )[:20],
                    "source": source_id,
                    "target": target_id,
                    "value": float(amount),
                    "kind": "boundary",
                    "spatial_role": "external_energy_input",
                    "direction": "input",
                    "flow_uuid": flow_uuid,
                    "flow_name": flow_name,
                    "exchange_ids": [exchange_id],
                    "energy_entry_ids": [entry_id],
                }
            )
            facility_amounts[facility_id] += amount
            carrier_amounts[(flow_uuid, flow_name)] += amount
            traced_exchange_ids.append(exchange_id)
            traced_entry_ids.append(entry_id)

        expected_total = Decimal(str(energy_series.get("total_amount")))
        attributed_total = sum(facility_amounts.values(), Decimal("0"))
        if attributed_total != expected_total:
            _fail(
                "SPATIAL_ENERGY_TOTAL_MISMATCH",
                "facility-attributed energy does not equal the source energy series total",
                series_id=energy_series.get("series_id"),
                expected=str(expected_total),
                actual=str(attributed_total),
            )
        basis = energy_series.get("basis") or {}
        result_series.append(
            {
                "series_id": energy_series.get("series_id"),
                "unit_group": energy_series.get("unit_identity_sha256"),
                "unit_group_label": (
                    "Energy · "
                    + _text(basis.get("energy_convention")).replace("_", " ")
                    + " · "
                    + _text(basis.get("material_condition")).replace("_", " ")
                ),
                "unit": energy_series.get("unit_symbol"),
                "diagram_mode": "spatial_energy",
                "basis": basis,
                "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
                "links": sorted(links, key=lambda item: item["id"]),
                "total_amount": str(attributed_total),
                "facility_metrics": [
                    {
                        "entity_id": facility_id,
                        "amount": str(amount),
                        "share": (
                            "0"
                            if amount == 0
                            else str(amount / attributed_total)
                            if attributed_total
                            else None
                        ),
                    }
                    for facility_id, amount in sorted(facility_amounts.items())
                ],
                "carrier_metrics": [
                    {
                        "flow_uuid": flow_uuid,
                        "flow_name": flow_name,
                        "amount": str(amount),
                    }
                    for (flow_uuid, flow_name), amount in sorted(carrier_amounts.items())
                ],
            }
        )

    if not result_series:
        _fail("SPATIAL_ENERGY_SERIES_EMPTY", "energy result contains no series")
    issues = list(energy.get("issues") or [])
    content = {
        "schema_version": "nebula_one.spatial.energy.v1",
        "capability_key": "spatial.energy.v1",
        "source_snapshot": spatial_ref,
        "source_energy_result": {
            "id": energy_record.get("id"),
            "record_content_sha256": energy_record.get("content_sha256"),
            "result_content_sha256": energy.get("content_sha256"),
        },
        "source_spatial_result": {
            "content_sha256": spatial_aggregate.get("content_sha256"),
            "boundary_id": spatial_audit.get("provenance", {}).get("boundary_id"),
        },
        "park": spatial_aggregate.get("park"),
        "facilities": facilities,
        "series": result_series,
        "audit": {
            "status": "passed_with_warnings" if issues else "passed",
            "checks": {
                "snapshot_identity_match": True,
                "energy_result_not_failed": True,
                "spatial_result_not_failed": True,
                "source_exchange_resolved": True,
                "external_input_verified": True,
                "flow_identity_match": True,
                "facility_binding_resolved": True,
                "series_totals_reconciled": True,
                "unit_series_kept_separate": True,
            },
            "counts": {
                "series_count": len(result_series),
                "entry_count": len(traced_entry_ids),
                "facility_count": len(facilities),
                "facilities_with_energy_count": len(
                    {
                        item["entity_id"]
                        for series_item in result_series
                        for item in series_item["facility_metrics"]
                        if Decimal(item["amount"]) > 0
                    }
                ),
            },
            "issues": issues,
            "limitations": [
                "v1 attributes solved external energy inputs to the facility owning the source process",
                "v1 does not infer internal energy conversion, losses or downstream allocation",
            ],
            "provenance": {
                "energy_entry_ids": sorted(traced_entry_ids),
                "source_exchange_ids": sorted(traced_exchange_ids),
                "spatial_aggregate_audit": spatial_audit,
            },
        },
    }
    return {**content, "content_sha256": canonical_json_sha256(content)}
