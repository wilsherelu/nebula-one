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


def _decimal(
    value: Any, *, field: str, allow_negative: bool = False
) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DomainError(
            code="SPATIAL_ENERGY_FLOW_AMOUNT_INVALID",
            message=f"spatial energy flow {field} is invalid",
            status_code=422,
        ) from exc
    if not parsed.is_finite() or (parsed < 0 and not allow_negative):
        _fail(
            "SPATIAL_ENERGY_FLOW_AMOUNT_INVALID",
            f"spatial energy flow {field} must be finite and non-negative",
        )
    return parsed


def _verify_content_hash(payload: dict[str, Any], *, code: str) -> None:
    claimed = _text(payload.get("content_sha256"))
    content = dict(payload)
    content.pop("content_sha256", None)
    if not claimed or canonical_json_sha256(content) != claimed:
        _fail(code, "source analysis content hash does not match its payload")


def _snapshot_identity(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _text(payload.get("id")),
        _text(payload.get("system_revision_id")),
        _text(payload.get("content_sha256")),
        _text(payload.get("solve_hash")),
    )


def build_spatial_energy_flow(
    *,
    solved_snapshot: dict[str, Any],
    energy_flow: dict[str, Any],
    spatial_aggregate: dict[str, Any],
    tolerance: Decimal = Decimal("0.000000001"),
) -> dict[str, Any]:
    if not tolerance.is_finite() or tolerance < 0:
        _fail(
            "SPATIAL_ENERGY_FLOW_TOLERANCE_INVALID",
            "spatial energy flow tolerance must be finite and non-negative",
        )
    expected_snapshot = _snapshot_identity(solved_snapshot)
    energy_snapshot = _snapshot_identity(energy_flow.get("source_snapshot") or {})
    spatial_snapshot = _snapshot_identity(spatial_aggregate.get("source_snapshot") or {})
    if not all(expected_snapshot) or energy_snapshot != expected_snapshot or spatial_snapshot != expected_snapshot:
        _fail(
            "SPATIAL_ENERGY_FLOW_SNAPSHOT_MISMATCH",
            "energy flow and spatial aggregate must share the exact solved snapshot",
        )
    if (
        energy_flow.get("schema_version") != "nebula_one.energy-flow.solved.v1"
        or energy_flow.get("capability_key") != "energy.flow.solved.v1"
    ):
        _fail(
            "SPATIAL_ENERGY_FLOW_SOURCE_INVALID",
            "source energy flow does not implement energy.flow.solved.v1",
        )
    if spatial_aggregate.get("schema_version") != "nebula_one.spatial.aggregate.v1":
        _fail(
            "SPATIAL_ENERGY_FLOW_SOURCE_INVALID",
            "source spatial result does not implement spatial.aggregate.v1",
        )
    if (energy_flow.get("audit") or {}).get("status") not in {
        "passed",
        "passed_with_warnings",
    } or (spatial_aggregate.get("audit") or {}).get("status") not in {
        "passed",
        "passed_with_warnings",
    }:
        _fail(
            "SPATIAL_ENERGY_FLOW_SOURCE_FAILED",
            "source energy flow and spatial aggregate must pass their audits",
        )
    _verify_content_hash(
        energy_flow, code="SPATIAL_ENERGY_FLOW_SOURCE_HASH_MISMATCH"
    )
    _verify_content_hash(
        spatial_aggregate, code="SPATIAL_ENERGY_FLOW_SOURCE_HASH_MISMATCH"
    )

    facilities = list(spatial_aggregate.get("facilities") or [])
    if not facilities:
        _fail(
            "SPATIAL_ENERGY_FLOW_FACILITY_EMPTY",
            "spatial energy flow requires at least one included facility",
        )
    facility_by_process: dict[str, dict[str, Any]] = {}
    facility_by_id: dict[str, dict[str, Any]] = {}
    for facility in facilities:
        facility_id = _text(facility.get("entity_id"))
        if not facility_id or facility_id in facility_by_id:
            _fail(
                "SPATIAL_ENERGY_FLOW_FACILITY_INVALID",
                "facility identities must be non-empty and unique",
                entity_id=facility_id,
            )
        facility_by_id[facility_id] = facility
        for process_uuid in facility.get("process_uuids") or []:
            process_id = _text(process_uuid)
            if not process_id or process_id in facility_by_process:
                _fail(
                    "SPATIAL_ENERGY_FLOW_BINDING_AMBIGUOUS",
                    "each energy-flow process must resolve to exactly one facility",
                    process_uuid=process_id,
                )
            facility_by_process[process_id] = facility

    result_series: list[dict[str, Any]] = []
    traced_processes: set[str] = set()
    traced_exchanges: set[str] = set()
    for source_series in energy_flow.get("series") or []:
        source_nodes = {
            _text(item.get("id")): item for item in source_series.get("nodes") or []
        }
        if not source_nodes or any(not item for item in source_nodes):
            _fail(
                "SPATIAL_ENERGY_FLOW_NODE_INVALID",
                "source energy flow nodes require unique non-empty identities",
            )
        mapped_nodes: dict[str, dict[str, Any]] = {}
        mapped_process_nodes: dict[str, tuple[str, str]] = {}
        for source_node_id, node in source_nodes.items():
            if node.get("kind") != "process":
                mapped_nodes[source_node_id] = dict(node)
                continue
            process_id = _text(node.get("process_id"))
            facility = facility_by_process.get(process_id)
            if facility is None:
                _fail(
                    "SPATIAL_ENERGY_FLOW_FACILITY_UNRESOLVED",
                    "an energy-flow process is not bound to an included facility",
                    process_uuid=process_id,
                )
            facility_id = _text(facility.get("entity_id"))
            mapped_id = f"facility-process:{facility_id}:{process_id}"
            mapped_process_nodes[source_node_id] = (mapped_id, facility_id)
            mapped_nodes[mapped_id] = {
                "id": mapped_id,
                "label": facility.get("name") or facility_id,
                "kind": "process",
                "process_id": process_id,
                "entity_id": facility_id,
                "external_id": facility.get("external_id"),
                "display_role": (
                    "FACILITY · ENERGY CONVERSION"
                    if node.get("display_role") == "ENERGY CONVERSION"
                    else "FACILITY · ENERGY USER"
                ),
                "source_process_label": node.get("label"),
                "spatial_unit_ref": (
                    f"{facility['spatial_unit']['spatial_unit_id']}@"
                    f"{facility['spatial_unit']['version']}"
                ),
                "spatial_unit_sha256": facility["spatial_unit"]["content_sha256"],
            }
            traced_processes.add(process_id)

        facility_metrics: dict[str, dict[str, Decimal]] = {
            facility_id: {
                "external_input": Decimal("0"),
                "useful_input": Decimal("0"),
                "useful_output": Decimal("0"),
                "inter_facility_input": Decimal("0"),
                "inter_facility_output": Decimal("0"),
                "intra_facility": Decimal("0"),
                "explicit_loss": Decimal("0"),
            }
            for facility_id in facility_by_id
        }
        mapped_links: list[dict[str, Any]] = []
        totals = defaultdict(lambda: Decimal("0"))
        for link in source_series.get("links") or []:
            source_id = _text(link.get("source"))
            target_id = _text(link.get("target"))
            if source_id not in source_nodes or target_id not in source_nodes:
                _fail(
                    "SPATIAL_ENERGY_FLOW_LINK_INVALID",
                    "source energy-flow link endpoint is missing",
                    link_id=link.get("id"),
                )
            source_process = mapped_process_nodes.get(source_id)
            target_process = mapped_process_nodes.get(target_id)
            amount = _decimal(link.get("value"), field="link amount")
            if source_process and target_process:
                source_mapped, source_facility = source_process
                target_mapped, target_facility = target_process
                role = (
                    "intra_facility"
                    if source_facility == target_facility
                    else "inter_facility"
                )
                facility_metrics[source_facility]["useful_output"] += amount
                facility_metrics[target_facility]["useful_input"] += amount
                facility_metrics[source_facility][
                    "intra_facility" if role == "intra_facility" else "inter_facility_output"
                ] += amount
                if role == "inter_facility":
                    facility_metrics[target_facility]["inter_facility_input"] += amount
                totals[f"useful_{role}"] += amount
                direction = "internal"
                kind = "internal"
            elif target_process and not source_process:
                source_mapped = source_id
                target_mapped, target_facility = target_process
                role = "external_energy_input"
                facility_metrics[target_facility]["external_input"] += amount
                totals[role] += amount
                direction = "input"
                kind = "boundary"
            elif source_process and not target_process:
                source_mapped, source_facility = source_process
                target_mapped = target_id
                role = "explicit_energy_loss"
                facility_metrics[source_facility]["explicit_loss"] += amount
                totals[role] += amount
                direction = "output"
                kind = "boundary"
            else:
                _fail(
                    "SPATIAL_ENERGY_FLOW_LINK_UNATTRIBUTED",
                    "every energy-flow link requires a facility process endpoint",
                    link_id=link.get("id"),
                )
            exchange_ids = sorted(_text(item) for item in link.get("exchange_ids") or [])
            traced_exchanges.update(exchange_ids)
            mapped_links.append(
                {
                    **link,
                    "id": "spatial-energy-flow:"
                    + canonical_json_sha256(
                        {
                            "source_link_id": link.get("id"),
                            "source": source_mapped,
                            "target": target_mapped,
                            "spatial_role": role,
                        }
                    )[:20],
                    "source": source_mapped,
                    "target": target_mapped,
                    "kind": kind,
                    "direction": direction,
                    "spatial_role": role,
                    "source_energy_flow_link_id": link.get("id"),
                    "exchange_ids": exchange_ids,
                }
            )

        external_input = totals["external_energy_input"]
        useful_total = totals["useful_inter_facility"] + totals["useful_intra_facility"]
        explicit_loss = totals["explicit_energy_loss"]
        residual = external_input - useful_total - explicit_loss
        source_residual = _decimal(
            source_series.get("balance_residual"),
            field="source balance residual",
            allow_negative=True,
        )
        if abs(residual - source_residual) > tolerance:
            _fail(
                "SPATIAL_ENERGY_FLOW_BALANCE_MISMATCH",
                "facility-attributed energy does not reconcile to the source energy flow",
                series_id=source_series.get("series_id"),
                expected=str(source_residual),
                actual=str(residual),
            )
        result_series.append(
            {
                "series_id": source_series.get("series_id"),
                "unit_group": source_series.get("input_unit_identity_sha256"),
                "unit_group_label": "Facility-attributed explicit energy flow",
                "unit": source_series.get("unit"),
                "diagram_mode": "spatial_energy_flow",
                "input_basis": source_series.get("input_basis"),
                "source_process_node_id": source_series.get("process_node_id"),
                "nodes": sorted(mapped_nodes.values(), key=lambda item: item["id"]),
                "links": sorted(mapped_links, key=lambda item: item["id"]),
                "totals": {
                    "external_input": str(external_input),
                    "useful_inter_facility": str(totals["useful_inter_facility"]),
                    "useful_intra_facility": str(totals["useful_intra_facility"]),
                    "explicit_loss": str(explicit_loss),
                    "balance_residual": str(residual),
                },
                "facility_metrics": [
                    {
                        "entity_id": facility_id,
                        **{key: str(value) for key, value in metrics.items()},
                    }
                    for facility_id, metrics in sorted(facility_metrics.items())
                ],
            }
        )

    if not result_series:
        _fail(
            "SPATIAL_ENERGY_FLOW_SERIES_EMPTY",
            "source energy flow contains no series",
        )
    energy_audit = energy_flow.get("audit") or {}
    spatial_audit = spatial_aggregate.get("audit") or {}
    issues = list(energy_audit.get("issues") or []) + list(
        spatial_audit.get("issues") or []
    )
    source_snapshot = {
        "id": solved_snapshot.get("id"),
        "system_revision_id": solved_snapshot.get("system_revision_id"),
        "content_sha256": solved_snapshot.get("content_sha256"),
        "solve_hash": solved_snapshot.get("solve_hash"),
    }
    content = {
        "schema_version": "nebula_one.spatial.energy-flow.v1",
        "capability_key": "spatial.energy-flow.v1",
        "source_snapshot": source_snapshot,
        "source_energy_flow": {
            "content_sha256": energy_flow.get("content_sha256"),
            "source_energy_result": energy_flow.get("source_energy_result"),
        },
        "source_spatial_result": {
            "content_sha256": spatial_aggregate.get("content_sha256"),
            "boundary_id": spatial_audit.get("provenance", {}).get("boundary_id"),
        },
        "park": spatial_aggregate.get("park"),
        "facilities": facilities,
        "series": sorted(result_series, key=lambda item: _text(item.get("series_id"))),
        "audit": {
            "status": "passed_with_warnings" if issues else "passed",
            "checks": {
                "snapshot_identity_match": True,
                "source_hashes_verified": True,
                "source_audits_passed": True,
                "process_facility_bindings_unique": True,
                "all_energy_processes_attributed": True,
                "facility_links_reconciled": True,
                "explicit_losses_preserved": True,
                "no_energy_inferred": True,
            },
            "counts": {
                "series_count": len(result_series),
                "facility_count": len(facilities),
                "attributed_process_count": len(traced_processes),
                "traced_exchange_count": len(traced_exchanges),
            },
            "issues": issues,
            "limitations": [
                "v1 composes explicit solved energy-flow links with frozen facility bindings",
                "v1 does not infer conversion, loss, downstream allocation or facility geometry effects",
                "different energy basis and unit identities remain separate series",
            ],
            "provenance": {
                "process_uuids": sorted(traced_processes),
                "exchange_ids": sorted(traced_exchanges),
                "energy_flow_audit": energy_audit,
                "spatial_aggregate_audit": spatial_audit,
            },
        },
    }
    return {**content, "content_sha256": canonical_json_sha256(content)}
