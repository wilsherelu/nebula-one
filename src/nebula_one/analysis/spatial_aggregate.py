from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .solved_mfa import build_solved_mfa


def _text(value: Any) -> str:
    return str(value or "").strip()


def _spatial_unit(entity: dict[str, Any]) -> dict[str, Any]:
    attributes = entity.get("attributes")
    value = attributes.get("spatial_unit") if isinstance(attributes, dict) else None
    if not isinstance(value, dict):
        raise DomainError(
            code="SPATIAL_UNIT_REQUIRED",
            message="every park and facility entity requires an exact spatial_unit",
            status_code=422,
            details={"entity_id": entity.get("id")},
        )
    required = {
        "schema_version",
        "spatial_unit_id",
        "version",
        "spatial_level",
        "geometry",
        "claim_level",
        "content_sha256",
    }
    missing = sorted(required.difference(value))
    if missing:
        raise DomainError(
            code="SPATIAL_UNIT_INVALID",
            message="spatial_unit is missing required identity fields",
            status_code=422,
            details={"entity_id": entity.get("id"), "missing": missing},
        )
    if value["schema_version"] != "nebula.spatial-unit.v1":
        raise DomainError(
            code="SPATIAL_UNIT_SCHEMA_UNSUPPORTED",
            message="spatial_unit schema version is unsupported",
            status_code=422,
            details={"entity_id": entity.get("id")},
        )
    if value["spatial_level"] != entity.get("entity_type"):
        raise DomainError(
            code="SPATIAL_UNIT_LEVEL_MISMATCH",
            message="spatial_unit level must match the entity type",
            status_code=422,
            details={"entity_id": entity.get("id")},
        )
    geometry = value.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") not in {
        "Point",
        "Polygon",
        "MultiPolygon",
    } or not isinstance(geometry.get("coordinates"), list):
        raise DomainError(
            code="SPATIAL_GEOMETRY_INVALID",
            message="spatial_unit geometry must be a GeoJSON Point, Polygon or MultiPolygon",
            status_code=422,
            details={"entity_id": entity.get("id")},
        )
    basis = dict(value)
    expected = _text(basis.pop("content_sha256", None))
    if expected != canonical_json_sha256(basis):
        raise DomainError(
            code="SPATIAL_UNIT_HASH_MISMATCH",
            message="spatial_unit content hash does not match its immutable content",
            status_code=409,
            details={"entity_id": entity.get("id")},
        )
    return value


def _process_catalog(graph: dict[str, Any]) -> tuple[dict[str, str], set[str]]:
    node_to_uuid: dict[str, str] = {}
    process_uuids: set[str] = set()
    for item in graph.get("nodes") or []:
        if not isinstance(item, dict):
            continue
        node_id = _text(item.get("id"))
        process_uuid = _text(item.get("process_uuid") or item.get("processUuid") or node_id)
        if not node_id or not process_uuid:
            continue
        if process_uuid in process_uuids:
            raise DomainError(
                code="SPATIAL_PROCESS_ID_AMBIGUOUS",
                message="the revision contains a duplicate process UUID",
                status_code=422,
                details={"process_uuid": process_uuid},
            )
        node_to_uuid[node_id] = process_uuid
        process_uuids.add(process_uuid)
    return node_to_uuid, process_uuids


def _binding_process_uuid(
    token: str, *, node_to_uuid: dict[str, str], process_uuids: set[str]
) -> str:
    normalized = _text(token)
    if normalized in node_to_uuid:
        return node_to_uuid[normalized]
    if normalized in process_uuids:
        return normalized
    raise DomainError(
        code="SPATIAL_BOUND_PROCESS_NOT_FOUND",
        message="a facility binding refers to a process absent from the frozen revision",
        status_code=422,
        details={"process_id": normalized},
    )


def _facility_node(entity: dict[str, Any], spatial: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"facility:{entity['id']}",
        "label": entity["name"],
        "kind": "process",
        "process_id": entity["id"],
        "entity_id": entity["id"],
        "external_id": entity.get("external_id"),
        "display_role": "FACILITY",
        "spatial_unit_ref": f"{spatial['spatial_unit_id']}@{spatial['version']}",
        "spatial_unit_sha256": spatial["content_sha256"],
    }


def build_spatial_aggregate(
    *,
    solved_snapshot: dict[str, Any],
    revision_graph: dict[str, Any],
    entities: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    boundary: dict[str, Any],
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    if not isfinite(tolerance) or tolerance < 0:
        raise DomainError(
            code="SPATIAL_TOLERANCE_INVALID",
            message="spatial aggregation tolerance must be finite and non-negative",
            status_code=422,
        )
    if boundary.get("status") != "frozen" or not boundary.get("content_sha256"):
        raise DomainError(
            code="SPATIAL_BOUNDARY_NOT_FROZEN",
            message="park aggregation requires a frozen boundary",
            status_code=422,
        )
    if boundary.get("boundary_type") != "park":
        raise DomainError(
            code="SPATIAL_BOUNDARY_TYPE_INVALID",
            message="spatial.aggregate.v1 requires a park boundary",
            status_code=422,
        )
    expected_policy = {
        "intra_facility": "eliminate",
        "inter_facility": "retain_as_internal",
        "external_boundary": "solved_snapshot_boundary_flows",
    }
    policy = boundary.get("consolidation_policy")
    if policy != expected_policy:
        raise DomainError(
            code="SPATIAL_CONSOLIDATION_POLICY_UNSUPPORTED",
            message="park boundary consolidation policy is unsupported",
            status_code=422,
            details={"required": expected_policy},
        )

    entity_by_id = {item["id"]: item for item in entities}
    included_ids = list(boundary.get("included_entity_ids") or [])
    included = [entity_by_id[item] for item in included_ids if item in entity_by_id]
    if len(included) != len(included_ids):
        raise DomainError(
            code="SPATIAL_BOUNDARY_ENTITY_MISSING",
            message="park boundary includes an entity outside the selected application",
            status_code=422,
        )
    parks = [item for item in included if item.get("entity_type") == "park"]
    facilities = [item for item in included if item.get("entity_type") == "facility"]
    if len(parks) != 1 or not facilities:
        raise DomainError(
            code="SPATIAL_BOUNDARY_STRUCTURE_INVALID",
            message="park boundary requires exactly one park and at least one facility",
            status_code=422,
        )
    park = parks[0]
    park_spatial = _spatial_unit(park)
    geographic_scope = boundary.get("geographic_scope")
    if not isinstance(geographic_scope, dict) or geographic_scope.get(
        "spatial_unit_ref"
    ) != f"{park_spatial['spatial_unit_id']}@{park_spatial['version']}" or geographic_scope.get(
        "spatial_unit_sha256"
    ) != park_spatial["content_sha256"]:
        raise DomainError(
            code="SPATIAL_BOUNDARY_GEOGRAPHY_MISMATCH",
            message="park boundary geographic scope does not pin the park spatial unit",
            status_code=409,
        )

    facility_spatial: dict[str, dict[str, Any]] = {}
    for facility in facilities:
        if facility.get("parent_id") != park["id"]:
            raise DomainError(
                code="SPATIAL_FACILITY_PARENT_MISMATCH",
                message="every included facility must be a direct child of the park",
                status_code=422,
                details={"entity_id": facility["id"]},
            )
        facility_spatial[facility["id"]] = _spatial_unit(facility)

    node_to_uuid, process_uuids = _process_catalog(revision_graph)
    revision_id = _text(solved_snapshot.get("system_revision_id"))
    facility_ids = {item["id"] for item in facilities}
    relevant_bindings = [item for item in bindings if item.get("entity_id") in facility_ids]
    assignment: dict[str, str] = {}
    binding_receipts: list[dict[str, Any]] = []
    bound_facilities: set[str] = set()
    for binding in relevant_bindings:
        facility_id = binding["entity_id"]
        if binding.get("system_revision_id") != revision_id:
            raise DomainError(
                code="SPATIAL_BINDING_REVISION_MISMATCH",
                message="facility binding does not target the solved revision",
                status_code=409,
                details={"binding_id": binding.get("id")},
            )
        if boundary.get("period_id") and binding.get("period_id") != boundary.get("period_id"):
            raise DomainError(
                code="SPATIAL_BINDING_PERIOD_MISMATCH",
                message="facility binding period does not match the park boundary",
                status_code=409,
                details={"binding_id": binding.get("id")},
            )
        if facility_id in bound_facilities:
            raise DomainError(
                code="SPATIAL_FACILITY_BINDING_AMBIGUOUS",
                message="a facility has more than one binding for the solved revision",
                status_code=409,
                details={"entity_id": facility_id},
            )
        bound_facilities.add(facility_id)
        resolved_processes = sorted(
            _binding_process_uuid(
                token, node_to_uuid=node_to_uuid, process_uuids=process_uuids
            )
            for token in binding.get("process_ids") or []
        )
        if not resolved_processes:
            raise DomainError(
                code="SPATIAL_FACILITY_PROCESS_BINDING_REQUIRED",
                message="every facility requires at least one exact process binding",
                status_code=422,
                details={"entity_id": facility_id},
            )
        for process_uuid in resolved_processes:
            previous = assignment.get(process_uuid)
            if previous is not None:
                raise DomainError(
                    code="SPATIAL_PROCESS_BINDING_OVERLAP",
                    message="one process cannot belong to multiple facilities",
                    status_code=409,
                    details={
                        "process_uuid": process_uuid,
                        "facility_ids": sorted([previous, facility_id]),
                    },
                )
            assignment[process_uuid] = facility_id
        binding_receipts.append(
            {
                "binding_id": binding["id"],
                "content_sha256": binding["content_sha256"],
                "entity_id": facility_id,
                "process_uuids": resolved_processes,
            }
        )
    missing_facilities = sorted(facility_ids.difference(bound_facilities))
    missing_processes = sorted(process_uuids.difference(assignment))
    if missing_facilities or missing_processes:
        raise DomainError(
            code="SPATIAL_BINDING_COVERAGE_INCOMPLETE",
            message="facility bindings must cover every included facility and foreground process",
            status_code=422,
            details={
                "missing_facility_ids": missing_facilities,
                "missing_process_uuids": missing_processes,
            },
        )

    source_mfa = build_solved_mfa(
        solved_snapshot=solved_snapshot,
        revision_graph=revision_graph,
        tolerance=tolerance,
    )
    if source_mfa["audit"]["status"] == "failed":
        raise DomainError(
            code="SPATIAL_SOURCE_MFA_FAILED",
            message="park aggregation cannot consume a failed solved MFA result",
            status_code=422,
            details={"source_audit": source_mfa["audit"]},
        )

    facility_nodes = {
        item["id"]: _facility_node(item, facility_spatial[item["id"]])
        for item in facilities
    }
    aggregate_series: list[dict[str, Any]] = []
    eliminated_exchange_ids: list[str] = []
    for source_series in source_mfa["series"]:
        source_nodes = {item["id"]: item for item in source_series["nodes"]}
        nodes: dict[str, dict[str, Any]] = {}
        links: dict[tuple[str, ...], dict[str, Any]] = {}
        eliminated = 0.0
        facility_metrics: dict[str, dict[str, float]] = {
            item["id"]: {
                "external_input": 0.0,
                "external_output": 0.0,
                "inter_facility_input": 0.0,
                "inter_facility_output": 0.0,
            }
            for item in facilities
        }
        external_metrics: dict[tuple[str, str, str], dict[str, Any]] = {}

        def endpoint(node_id: str, *, direction: str) -> tuple[str, str | None]:
            node = source_nodes.get(node_id) or {}
            if node.get("kind") == "process":
                process_uuid = _text(node.get("process_id"))
                facility_id = assignment.get(process_uuid)
                if facility_id:
                    target_id = f"facility:{facility_id}"
                    nodes[target_id] = facility_nodes[facility_id]
                    return target_id, facility_id
                if node.get("claim_role") == "partial_background_leaf":
                    external_id = f"external-provider:{process_uuid}"
                    nodes[external_id] = {
                        "id": external_id,
                        "label": node.get("label") or process_uuid,
                        "kind": "system_boundary",
                        "direction": direction,
                        "display_role": "EXTERNAL PROVIDER",
                        "process_id": process_uuid,
                        "claim_role": node.get("claim_role"),
                    }
                    return external_id, None
                raise DomainError(
                    code="SPATIAL_PROCESS_BINDING_MISSING",
                    message="a solved foreground process is not bound to a facility",
                    status_code=422,
                    details={"process_uuid": process_uuid},
                )
            nodes[node_id] = dict(node)
            return node_id, None

        for source_link in source_series["links"]:
            source_id, source_facility = endpoint(source_link["source"], direction="input")
            target_id, target_facility = endpoint(source_link["target"], direction="output")
            value = float(source_link["value"])
            if source_facility and target_facility and source_facility == target_facility:
                eliminated += value
                eliminated_exchange_ids.extend(
                    _text(item) for item in source_link.get("exchange_ids") or []
                )
                continue
            if source_facility and target_facility:
                kind = "inter_facility"
                direction = "internal"
                facility_metrics[source_facility]["inter_facility_output"] += value
                facility_metrics[target_facility]["inter_facility_input"] += value
            elif source_facility or target_facility:
                kind = "boundary"
                direction = "output" if source_facility else "input"
                facility_id = source_facility or target_facility
                assert facility_id is not None
                facility_metrics[facility_id][f"external_{direction}"] += value
                metric_key = (
                    _text(source_link.get("flow_uuid")),
                    direction,
                    _text(source_link.get("exchange_type")),
                )
                metric = external_metrics.setdefault(
                    metric_key,
                    {
                        "flow_uuid": metric_key[0],
                        "flow_name": source_link.get("flow_name") or metric_key[0],
                        "direction": direction,
                        "exchange_type": metric_key[2] or None,
                        "amount": 0.0,
                        "unit": source_series["unit"],
                        "unit_group": source_series["unit_group"],
                        "exchange_ids": [],
                    },
                )
                metric["amount"] += value
                metric["exchange_ids"].extend(
                    _text(item) for item in source_link.get("exchange_ids") or []
                )
            else:
                raise DomainError(
                    code="SPATIAL_LINK_OUTSIDE_PARK",
                    message="a solved MFA link has no included facility endpoint",
                    status_code=422,
                    details={"link_id": source_link.get("id")},
                )
            key = (
                source_id,
                target_id,
                _text(source_link.get("flow_uuid")),
                kind,
                direction,
                _text(source_link.get("exchange_type")),
            )
            aggregate = links.setdefault(
                key,
                {
                    "id": "spatial:" + canonical_json_sha256(key)[:20],
                    "source": source_id,
                    "target": target_id,
                    "value": 0.0,
                    "kind": "internal" if kind == "inter_facility" else "boundary",
                    "spatial_role": kind,
                    "direction": direction,
                    "flow_uuid": source_link.get("flow_uuid"),
                    "flow_name": source_link.get("flow_name"),
                    "exchange_type": source_link.get("exchange_type"),
                    "exchange_ids": [],
                },
            )
            aggregate["value"] += value
            aggregate["exchange_ids"].extend(
                _text(item) for item in source_link.get("exchange_ids") or []
            )

        ordered_links = []
        for item in sorted(links.values(), key=lambda value: value["id"]):
            item["exchange_ids"] = sorted(set(item["exchange_ids"]))
            ordered_links.append(item)
        for item in external_metrics.values():
            item["exchange_ids"] = sorted(set(item["exchange_ids"]))
        aggregate_series.append(
            {
                "series_id": source_series["series_id"],
                "unit_group": source_series["unit_group"],
                "unit_group_label": source_series["unit_group_label"],
                "unit": source_series["unit"],
                "diagram_mode": "park",
                "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
                "links": ordered_links,
                "totals": {
                    "external_input": sum(
                        item["value"]
                        for item in ordered_links
                        if item.get("direction") == "input"
                    ),
                    "external_output": sum(
                        item["value"]
                        for item in ordered_links
                        if item.get("direction") == "output"
                    ),
                    "inter_facility": sum(
                        item["value"]
                        for item in ordered_links
                        if item.get("spatial_role") == "inter_facility"
                    ),
                    "eliminated_intra_facility": eliminated,
                },
                "facility_metrics": [
                    {"entity_id": facility_id, **metrics}
                    for facility_id, metrics in sorted(facility_metrics.items())
                ],
                "external_flow_metrics": sorted(
                    external_metrics.values(),
                    key=lambda item: (
                        item["direction"],
                        item["flow_uuid"],
                        item.get("exchange_type") or "",
                    ),
                ),
            }
        )

    source_status = source_mfa["audit"]["status"]
    content = {
        "schema_version": "nebula_one.spatial.aggregate.v1",
        "capability_key": "spatial.aggregate.v1",
        "source_snapshot": {
            "id": solved_snapshot.get("id"),
            "content_sha256": solved_snapshot.get("content_sha256"),
            "solve_hash": solved_snapshot.get("solve_hash"),
            "system_revision_id": revision_id,
        },
        "park": {
            "entity_id": park["id"],
            "external_id": park.get("external_id"),
            "name": park["name"],
            "spatial_unit": park_spatial,
        },
        "facilities": [
            {
                "entity_id": item["id"],
                "external_id": item.get("external_id"),
                "name": item["name"],
                "spatial_unit": facility_spatial[item["id"]],
                "process_uuids": sorted(
                    process_uuid
                    for process_uuid, facility_id in assignment.items()
                    if facility_id == item["id"]
                ),
            }
            for item in sorted(facilities, key=lambda value: value["id"])
        ],
        "series": aggregate_series,
        "audit": {
            "status": "passed_with_warnings" if source_status != "passed" else "passed",
            "checks": {
                "boundary_frozen": True,
                "park_spatial_identity_verified": True,
                "facility_spatial_identity_verified": True,
                "binding_revision_match": True,
                "binding_coverage_complete": True,
                "process_bindings_disjoint": True,
                "source_mfa_not_failed": True,
                "unit_series_kept_separate": True,
            },
            "counts": {
                "facility_count": len(facilities),
                "foreground_process_count": len(process_uuids),
                "binding_count": len(binding_receipts),
                "series_count": len(aggregate_series),
                "eliminated_exchange_count": len(set(eliminated_exchange_ids)),
            },
            "issues": (
                []
                if source_status == "passed"
                else [
                    {
                        "code": "SPATIAL_SOURCE_MFA_WARNINGS_PRESERVED",
                        "severity": "warning",
                        "message": "source solved MFA completed with warnings; its audit remains authoritative",
                    }
                ]
            ),
            "provenance": {
                "boundary_id": boundary["id"],
                "boundary_content_sha256": boundary["content_sha256"],
                "binding_receipts": sorted(binding_receipts, key=lambda item: item["binding_id"]),
                "source_mfa_sha256": canonical_json_sha256(source_mfa),
                "source_mfa_audit": source_mfa["audit"],
                "eliminated_intra_facility_exchange_ids": sorted(
                    set(eliminated_exchange_ids)
                ),
            },
        },
    }
    return {**content, "content_sha256": canonical_json_sha256(content)}
