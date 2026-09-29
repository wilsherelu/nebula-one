from __future__ import annotations

from math import isclose, isfinite
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


SCHEMA_VERSION = "nebula_one.spatial.distribution.v1"
CAPABILITY_KEY = "spatial.distribution.v1"
PACKAGE_KIND = "spatial_distribution"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _require_dict(value: Any, *, code: str, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DomainError(code=code, message=message, status_code=422)
    return value


def _verified_hash(payload: dict[str, Any], *, code: str, subject: str) -> str:
    basis = dict(payload)
    expected = _text(basis.pop("content_sha256", None))
    if not expected or expected != canonical_json_sha256(basis):
        raise DomainError(
            code=code,
            message=f"{subject} content hash does not match its immutable content",
            status_code=409,
        )
    return expected


def _point(payload: Any, *, subject: str) -> tuple[float, float]:
    geometry = _require_dict(
        payload,
        code="SPATIAL_DISTRIBUTION_POINT_INVALID",
        message=f"{subject} requires a GeoJSON Point",
    )
    coordinates = geometry.get("coordinates")
    if (
        geometry.get("type") != "Point"
        or geometry.get("crs") != "EPSG:4326"
        or not isinstance(coordinates, list)
        or len(coordinates) != 2
    ):
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_POINT_INVALID",
            message=f"{subject} requires an EPSG:4326 GeoJSON Point",
            status_code=422,
        )
    try:
        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
    except (TypeError, ValueError) as exc:
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_POINT_INVALID",
            message=f"{subject} coordinates must be numeric",
            status_code=422,
        ) from exc
    if (
        not isfinite(longitude)
        or not isfinite(latitude)
        or not -180 <= longitude <= 180
        or not -90 <= latitude <= 90
    ):
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_POINT_INVALID",
            message=f"{subject} coordinates are outside longitude/latitude bounds",
            status_code=422,
        )
    return longitude, latitude


def _source_selector(manifest: dict[str, Any]) -> tuple[dict[str, str], str]:
    formula = _require_dict(
        manifest.get("formula_graph"),
        code="SPATIAL_DISTRIBUTION_METHOD_INVALID",
        message="spatial distribution method lacks a formula graph",
    )
    if formula.get("source_collection") != "solved_system_snapshot.boundary_flows":
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_SOURCE_UNSUPPORTED",
            message="spatial distribution must consume frozen solved boundary flows",
            status_code=422,
        )
    if formula.get("allocation") != "source_amount_times_declared_share":
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_FORMULA_UNSUPPORTED",
            message="spatial distribution allocation formula is unsupported",
            status_code=422,
        )
    raw = _require_dict(
        formula.get("source_flow_selector"),
        code="SPATIAL_DISTRIBUTION_SELECTOR_INVALID",
        message="spatial distribution requires an exact source Flow selector",
    )
    fields = (
        "exchange_id",
        "source_namespace",
        "flow_uuid",
        "version",
        "direction",
        "exchange_type",
        "unit_group_uuid",
        "unit_group_version",
        "unit",
    )
    selector = {field: _text(raw.get(field)) for field in fields}
    source_flow_name = _text(formula.get("source_flow_name"))
    missing = [field for field, value in selector.items() if not value]
    if missing or not source_flow_name:
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_SELECTOR_INVALID",
            message="spatial distribution source Flow selector is incomplete",
            status_code=422,
            details={
                "missing_fields": missing,
                "source_flow_name_missing": not source_flow_name,
            },
        )
    return selector, source_flow_name


def _source_flow(
    solved_snapshot: dict[str, Any], selector: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    matches = [
        item
        for item in solved_snapshot.get("boundary_flows") or []
        if isinstance(item, dict)
        and _text(item.get("exchange_id")) == selector["exchange_id"]
        and _text(item.get("flow_uuid")) == selector["flow_uuid"]
        and _text(item.get("direction")) == selector["direction"]
        and _text(item.get("exchange_type")) == selector["exchange_type"]
        and _text(item.get("unit_group") or item.get("unit_group_uuid"))
        == selector["unit_group_uuid"]
        and _text(item.get("unit")) == selector["unit"]
    ]
    if len(matches) != 1:
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_SOURCE_FLOW_NOT_UNIQUE",
            message="the exact source selector must match one solved boundary Flow",
            status_code=422,
            details={"match_count": len(matches), "exchange_id": selector["exchange_id"]},
        )
    source = matches[0]
    try:
        amount = float(source.get("amount"))
    except (TypeError, ValueError) as exc:
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_SOURCE_AMOUNT_INVALID",
            message="the solved source Flow amount must be numeric",
            status_code=422,
        ) from exc
    if not isfinite(amount) or amount < 0:
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_SOURCE_AMOUNT_INVALID",
            message="the solved source Flow amount must be finite and non-negative",
            status_code=422,
        )

    receipts = [
        item
        for item in (solved_snapshot.get("provider_receipt") or {}).get(
            "technosphere_flow_receipts", []
        )
        if isinstance(item, dict)
        and _text(item.get("exchange_id")) == selector["exchange_id"]
    ]
    receipt = receipts[0] if len(receipts) == 1 else None
    if selector["source_namespace"] == "tiangong_open_data":
        if receipt is None:
            raise DomainError(
                code="SPATIAL_DISTRIBUTION_TIDAS_RECEIPT_REQUIRED",
                message="TIDAS source allocation requires one exact provider Flow receipt",
                status_code=422,
            )
        identity = {
            "source_namespace": selector["source_namespace"],
            "flow_uuid": selector["flow_uuid"],
            "version": selector["version"],
            "unit_group_uuid": selector["unit_group_uuid"],
            "unit_group_version": selector["unit_group_version"],
            "unit": selector["unit"],
        }
        mismatches = {
            field: {"selector": expected, "receipt": receipt.get(field)}
            for field, expected in identity.items()
            if _text(receipt.get(field)) != expected
        }
        if mismatches:
            raise DomainError(
                code="SPATIAL_DISTRIBUTION_TIDAS_RECEIPT_MISMATCH",
                message="source selector differs from the exact provider Flow receipt",
                status_code=409,
                details={"mismatches": mismatches},
            )
    return {**source, "amount": amount}, receipt


def build_spatial_distribution(
    *,
    solved_snapshot: dict[str, Any],
    method_package_ref: str,
    method_package_sha256: str,
    method_package_kind: str,
    manifest: dict[str, Any],
    destination_spatial_unit: dict[str, Any],
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    if not isfinite(tolerance) or tolerance < 0:
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_TOLERANCE_INVALID",
            message="spatial distribution tolerance must be finite and non-negative",
            status_code=422,
        )
    if method_package_kind != PACKAGE_KIND:
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_METHOD_KIND_INVALID",
            message="method package is not a spatial distribution package",
            status_code=422,
        )
    if (manifest.get("output_schema") or {}).get("schema_version") != SCHEMA_VERSION:
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_OUTPUT_SCHEMA_MISMATCH",
            message="method package does not target spatial.distribution.v1",
            status_code=409,
        )
    selector, source_flow_name = _source_selector(manifest)
    source, source_receipt = _source_flow(solved_snapshot, selector)
    _verified_hash(
        destination_spatial_unit,
        code="SPATIAL_DISTRIBUTION_DESTINATION_HASH_MISMATCH",
        subject="destination spatial unit",
    )
    destination_point = _point(
        destination_spatial_unit.get("geometry"), subject="destination spatial unit"
    )

    rules = _require_dict(
        manifest.get("classification_rules"),
        code="SPATIAL_DISTRIBUTION_METHOD_INVALID",
        message="spatial distribution method lacks classification rules",
    )
    destination_ref = _require_dict(
        rules.get("destination"),
        code="SPATIAL_DISTRIBUTION_DESTINATION_REQUIRED",
        message="spatial distribution method requires a destination",
    )
    expected_destination_ref = (
        f"{destination_spatial_unit.get('spatial_unit_id')}"
        f"@{destination_spatial_unit.get('version')}"
    )
    if (
        destination_ref.get("spatial_unit_ref") != expected_destination_ref
        or destination_ref.get("spatial_unit_sha256")
        != destination_spatial_unit.get("content_sha256")
    ):
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_DESTINATION_MISMATCH",
            message="method destination does not match the application spatial unit",
            status_code=409,
        )

    raw_regions = rules.get("regions")
    if not isinstance(raw_regions, list) or not raw_regions:
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_REGIONS_REQUIRED",
            message="spatial distribution requires at least one region",
            status_code=422,
        )
    regions: dict[str, dict[str, Any]] = {}
    for raw in raw_regions:
        region = _require_dict(
            raw,
            code="SPATIAL_DISTRIBUTION_REGION_INVALID",
            message="spatial distribution regions must be objects",
        )
        region_id = _text(region.get("region_id"))
        if (
            not region_id
            or not _text(region.get("name"))
            or region.get("administrative_level") != "province"
            or region.get("claim_level") != "demonstration"
        ):
            raise DomainError(
                code="SPATIAL_DISTRIBUTION_REGION_INVALID",
                message="each region requires a demonstration province identity",
                status_code=422,
            )
        if region_id in regions:
            raise DomainError(
                code="SPATIAL_DISTRIBUTION_REGION_DUPLICATE",
                message="spatial distribution region IDs must be unique",
                status_code=422,
                details={"region_id": region_id},
            )
        _verified_hash(
            region,
            code="SPATIAL_DISTRIBUTION_REGION_HASH_MISMATCH",
            subject=f"region {region_id}",
        )
        _point(region.get("representative_point"), subject=f"region {region_id}")
        regions[region_id] = region

    raw_scenarios = rules.get("scenarios")
    if not isinstance(raw_scenarios, list) or len(raw_scenarios) < 2:
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_SCENARIOS_REQUIRED",
            message="spatial distribution comparison requires at least two scenarios",
            status_code=422,
        )
    scenario_by_id: dict[str, dict[str, Any]] = {}
    for raw in raw_scenarios:
        scenario = _require_dict(
            raw,
            code="SPATIAL_DISTRIBUTION_SCENARIO_INVALID",
            message="spatial distribution scenarios must be objects",
        )
        scenario_id = _text(scenario.get("scenario_id"))
        if not scenario_id or not _text(scenario.get("name")):
            raise DomainError(
                code="SPATIAL_DISTRIBUTION_SCENARIO_INVALID",
                message="each spatial distribution scenario requires an ID and name",
                status_code=422,
            )
        if scenario_id in scenario_by_id:
            raise DomainError(
                code="SPATIAL_DISTRIBUTION_SCENARIO_DUPLICATE",
                message="spatial distribution scenario IDs must be unique",
                status_code=422,
            )
        _verified_hash(
            scenario,
            code="SPATIAL_DISTRIBUTION_SCENARIO_HASH_MISMATCH",
            subject=f"scenario {scenario_id}",
        )
        scenario_by_id[scenario_id] = scenario
    baseline_id = _text(rules.get("baseline_scenario_id"))
    if baseline_id not in scenario_by_id:
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_BASELINE_NOT_FOUND",
            message="spatial distribution baseline scenario is missing",
            status_code=422,
        )

    source_amount = source["amount"]
    computed: dict[str, list[dict[str, Any]]] = {}
    for scenario_id, scenario in scenario_by_id.items():
        allocations = scenario.get("allocations")
        if not isinstance(allocations, list):
            allocations = []
        shares: dict[str, float] = {}
        for allocation in allocations:
            if not isinstance(allocation, dict):
                raise DomainError(
                    code="SPATIAL_DISTRIBUTION_ALLOCATION_INVALID",
                    message="scenario allocations must be objects",
                    status_code=422,
                )
            region_id = _text(allocation.get("region_id"))
            try:
                share = float(allocation.get("share"))
            except (TypeError, ValueError) as exc:
                raise DomainError(
                    code="SPATIAL_DISTRIBUTION_SHARE_INVALID",
                    message="allocation shares must be numeric",
                    status_code=422,
                ) from exc
            if region_id not in regions or region_id in shares or not isfinite(share) or not 0 <= share <= 1:
                raise DomainError(
                    code="SPATIAL_DISTRIBUTION_SHARE_INVALID",
                    message="allocation shares require unique known regions and values from zero to one",
                    status_code=422,
                    details={"scenario_id": scenario_id, "region_id": region_id},
                )
            shares[region_id] = share
        if set(shares) != set(regions) or not isclose(
            sum(shares.values()), 1.0, rel_tol=0.0, abs_tol=tolerance
        ):
            raise DomainError(
                code="SPATIAL_DISTRIBUTION_SHARE_SUM_MISMATCH",
                message="each scenario must allocate every region and sum to one",
                status_code=422,
                details={"scenario_id": scenario_id, "share_sum": sum(shares.values())},
            )
        computed[scenario_id] = [
            {
                "region": regions[region_id],
                "share": shares[region_id],
                "amount": source_amount * shares[region_id],
            }
            for region_id in sorted(regions)
        ]

    baseline_amounts = {
        item["region"]["region_id"]: item["amount"]
        for item in computed[baseline_id]
    }
    result_scenarios: list[dict[str, Any]] = []
    for scenario_id in sorted(scenario_by_id):
        source_scenario = scenario_by_id[scenario_id]
        rows = []
        for item in computed[scenario_id]:
            baseline_amount = baseline_amounts[item["region"]["region_id"]]
            delta = item["amount"] - baseline_amount
            rows.append(
                {
                    **item,
                    "baseline_amount": baseline_amount,
                    "amount_delta_from_baseline": delta,
                    "relative_delta_from_baseline": (
                        None if baseline_amount == 0 else delta / baseline_amount
                    ),
                }
            )
        allocated = sum(item["amount"] for item in rows)
        result_scenarios.append(
            {
                "scenario_id": scenario_id,
                "name": source_scenario["name"],
                "description": source_scenario.get("description"),
                "content_sha256": source_scenario["content_sha256"],
                "regions": rows,
                "total_allocated": allocated,
                "allocation_residual": source_amount - allocated,
            }
        )

    content = {
        "schema_version": SCHEMA_VERSION,
        "capability_key": CAPABILITY_KEY,
        "source_snapshot": {
            "id": solved_snapshot.get("id"),
            "system_revision_id": solved_snapshot.get("system_revision_id"),
            "solve_hash": solved_snapshot.get("solve_hash"),
            "content_sha256": solved_snapshot.get("content_sha256"),
        },
        "method_package": {
            "ref": method_package_ref,
            "content_sha256": method_package_sha256,
        },
        "source_flow": {
            "name": source_flow_name,
            "selector": selector,
            "amount": source_amount,
            "unit": selector["unit"],
            "provider_flow_receipt": source_receipt,
        },
        "destination": {
            "spatial_unit": destination_spatial_unit,
            "longitude": destination_point[0],
            "latitude": destination_point[1],
        },
        "baseline_scenario_id": baseline_id,
        "scenarios": result_scenarios,
        "audit": {
            "status": "passed",
            "checks": {
                "frozen_snapshot_bound": True,
                "method_package_hash_bound": True,
                "destination_hash_verified": True,
                "region_hashes_verified": True,
                "source_flow_unique": True,
                "exact_tidas_receipt_verified": selector["source_namespace"]
                == "tiangong_open_data",
                "scenario_hashes_verified": True,
                "shares_complete_and_sum_to_one": True,
                "unit_identity_preserved": True,
            },
            "counts": {
                "region_count": len(regions),
                "scenario_count": len(result_scenarios),
            },
            "limitations": [
                "regions use demonstration representative points, not official administrative boundary geometry",
                "declared shares are scenario attribution inputs, not measured supply data",
                "changing source origin does not change the solved model or LCIA in this version",
            ],
        },
    }
    return {**content, "content_sha256": canonical_json_sha256(content)}
