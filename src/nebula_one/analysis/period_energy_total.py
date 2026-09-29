from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _fail(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def _decimal(value: Any, *, field: str, period_id: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DomainError(
            code="PERIOD_ENERGY_ACTIVITY_INVALID",
            message="period activity contains a non-numeric quantity",
            status_code=422,
            details={"field": field, "period_id": period_id},
        ) from exc
    if not parsed.is_finite() or parsed <= 0:
        _fail(
            "PERIOD_ENERGY_ACTIVITY_INVALID",
            "period activity quantities must be finite and greater than zero",
            field=field,
            period_id=period_id,
        )
    return parsed


def _relative(value: Decimal, reference: Decimal) -> str | None:
    if reference == 0:
        return None
    return str((value - reference) / reference)


def build_period_energy_total(
    *,
    intensity_trend: dict[str, Any],
    activities: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    if intensity_trend.get("schema_version") != "nebula_one.period-energy-trend.v1":
        _fail(
            "PERIOD_ENERGY_TREND_REQUIRED",
            "period energy totals require a validated intensity trend",
        )
    trend_hash = str(intensity_trend.get("content_sha256") or "")
    trend_basis = dict(intensity_trend)
    trend_basis.pop("content_sha256", None)
    if SHA256_RE.fullmatch(trend_hash) is None or canonical_json_sha256(
        trend_basis
    ) != trend_hash:
        _fail(
            "PERIOD_ENERGY_TREND_HASH_MISMATCH",
            "period energy trend content hash does not match",
        )

    observations = intensity_trend.get("observations") or []
    period_ids = [item["period"]["id"] for item in observations]
    observation_by_period = {
        item["period"]["id"]: item for item in observations
    }
    activity_by_period = {
        str(item.get("period_id") or "").strip(): item for item in activities
    }
    if len(activity_by_period) != len(activities) or set(activity_by_period) != set(
        period_ids
    ):
        _fail(
            "PERIOD_ENERGY_ACTIVITY_SET_MISMATCH",
            "period activities must exactly cover the intensity trend periods",
        )

    normalized_activities: list[dict[str, Any]] = []
    output_signatures: set[str] = set()
    units: set[str] = set()
    production_values: dict[str, Decimal] = {}
    reference_values: dict[str, Decimal] = {}
    for period_id in period_ids:
        activity = activity_by_period[period_id]
        inventory = dict(activity.get("inventory_snapshot") or {})
        data_point = dict(activity.get("data_point") or {})
        evidence = dict(activity.get("evidence") or {})
        functional_output = dict(activity.get("functional_output") or {})
        for field in ("id", "content_sha256", "system_revision_id", "boundary_id"):
            if not str(inventory.get(field) or "").strip():
                _fail(
                    "PERIOD_ENERGY_INVENTORY_IDENTITY_INVALID",
                    "period activity requires a frozen inventory identity",
                    period_id=period_id,
                )
        source = observation_by_period[period_id].get("source") or {}
        if inventory.get("period_id") != period_id or (
            inventory.get("system_revision_id") != source.get("system_revision_id")
        ):
            _fail(
                "PERIOD_ENERGY_ACTIVITY_SOURCE_MISMATCH",
                "period inventory must match the trend period and solved revision",
                period_id=period_id,
            )
        if SHA256_RE.fullmatch(str(inventory["content_sha256"])) is None:
            _fail(
                "PERIOD_ENERGY_INVENTORY_IDENTITY_INVALID",
                "period inventory content hash is invalid",
                period_id=period_id,
            )
        if data_point.get("metric_key") != "period_product_output":
            _fail(
                "PERIOD_ENERGY_ACTIVITY_METRIC_INVALID",
                "period energy totals require period_product_output activity",
                period_id=period_id,
            )
        if data_point.get("inventory_snapshot_id") != inventory["id"] or (
            data_point.get("evidence_id") != evidence.get("id")
        ):
            _fail(
                "PERIOD_ENERGY_ACTIVITY_SOURCE_MISMATCH",
                "period product output must belong to the selected inventory and evidence",
                period_id=period_id,
            )
        mapping_target = data_point.get("mapping_target") or {}
        expected_exchange_id = (
            f"{data_point.get('process_id')}::{mapping_target.get('port_id')}"
        )
        if mapping_target.get("role") != "period_product_output" or (
            functional_output.get("exchange_id") != expected_exchange_id
        ):
            _fail(
                "PERIOD_ENERGY_ACTIVITY_MAPPING_INVALID",
                "period product output mapping must resolve the solved output exchange",
                period_id=period_id,
            )
        if data_point.get("quality_status") in {"invalid", "rejected"} or (
            data_point.get("review_status") != "approved"
        ):
            _fail(
                "PERIOD_ENERGY_ACTIVITY_REVIEW_INCOMPLETE",
                "period product output must be approved and quality-valid",
                period_id=period_id,
            )
        data_point_hash = str(data_point.get("content_sha256") or "")
        data_point_basis = dict(data_point)
        data_point_basis.pop("content_sha256", None)
        if SHA256_RE.fullmatch(data_point_hash) is None or canonical_json_sha256(
            data_point_basis
        ) != data_point_hash:
            _fail(
                "PERIOD_ENERGY_ACTIVITY_HASH_MISMATCH",
                "period product output content hash does not match",
                period_id=period_id,
            )
        if not str(evidence.get("id") or "").strip() or SHA256_RE.fullmatch(
            str(evidence.get("content_sha256") or "")
        ) is None:
            _fail(
                "PERIOD_ENERGY_EVIDENCE_IDENTITY_INVALID",
                "period activity requires exact evidence identity",
                period_id=period_id,
            )
        output_identity = dict(functional_output.get("flow_identity") or {})
        required_identity = (
            "source_namespace",
            "flow_uuid",
            "version",
            "flow_property_uuid",
            "flow_property_version",
            "unit_group_uuid",
            "unit_group_version",
            "unit",
        )
        if any(not str(output_identity.get(key) or "").strip() for key in required_identity):
            _fail(
                "PERIOD_ENERGY_FUNCTIONAL_OUTPUT_INVALID",
                "functional output identity is incomplete",
                period_id=period_id,
            )
        if data_point.get("flow_uuid") != output_identity["flow_uuid"] or (
            data_point.get("unit") != output_identity["unit"]
        ):
            _fail(
                "PERIOD_ENERGY_ACTIVITY_OUTPUT_MISMATCH",
                "period product output differs from the solved functional output",
                period_id=period_id,
            )
        production = _decimal(
            data_point.get("quantity"), field="production_quantity", period_id=period_id
        )
        reference = _decimal(
            functional_output.get("solved_reference_amount"),
            field="solved_reference_amount",
            period_id=period_id,
        )
        output_signature = canonical_json_sha256(output_identity)
        output_signatures.add(output_signature)
        units.add(output_identity["unit"])
        production_values[period_id] = production
        reference_values[period_id] = reference
        normalized_activities.append(
            {
                "period_id": period_id,
                "inventory_snapshot": inventory,
                "data_point": data_point,
                "evidence": evidence,
                "functional_output": {
                    **functional_output,
                    "flow_identity_sha256": output_signature,
                },
                "scale_factor": str(production / reference),
            }
        )

    if len(output_signatures) != 1 or len(units) != 1:
        _fail(
            "PERIOD_ENERGY_FUNCTIONAL_OUTPUT_NOT_COMPARABLE",
            "all periods must use one exact functional output and unit",
        )

    baseline_period_id = intensity_trend["baseline_period_id"]
    metrics: list[dict[str, Any]] = []
    for metric in intensity_trend.get("metrics") or []:
        intensity_values = {
            period_id: Decimal(str(metric["values"][period_id]))
            for period_id in period_ids
        }
        total_values = {
            period_id: intensity_values[period_id]
            * production_values[period_id]
            / reference_values[period_id]
            for period_id in period_ids
        }
        baseline_value = total_values[baseline_period_id]
        previous_id: str | None = None
        previous_deltas: dict[str, dict[str, str | None] | None] = {}
        for period_id in period_ids:
            if previous_id is None:
                previous_deltas[period_id] = None
            else:
                previous_value = total_values[previous_id]
                previous_deltas[period_id] = {
                    "absolute": str(total_values[period_id] - previous_value),
                    "relative": _relative(total_values[period_id], previous_value),
                }
            previous_id = period_id
        metric_basis = {
            "metric_key": metric["metric_key"],
            "label": metric["label"],
            "unit_symbol": metric["unit_symbol"],
            "unit_identity_sha256": metric["unit_identity_sha256"],
            "basis": metric["basis"],
            "intensity_values": {
                key: str(value) for key, value in intensity_values.items()
            },
            "period_total_values": {
                key: str(value) for key, value in total_values.items()
            },
            "deltas_from_baseline": {
                period_id: {
                    "absolute": str(value - baseline_value),
                    "relative": _relative(value, baseline_value),
                }
                for period_id, value in total_values.items()
            },
            "deltas_from_previous": previous_deltas,
            "covered_period_total": str(sum(total_values.values(), Decimal("0"))),
        }
        metrics.append(
            {**metric_basis, "content_sha256": canonical_json_sha256(metric_basis)}
        )

    inherited_issues: dict[str, set[str]] = defaultdict(set)
    for issue in intensity_trend.get("issues") or []:
        for period_id in issue.get("period_ids") or []:
            inherited_issues[str(issue.get("code") or "SOURCE_WARNING")].add(period_id)
    issues = [
        {
            "code": code,
            "severity": "warning",
            "message": "one or more source energy results retain this warning",
            "period_ids": sorted(ids),
        }
        for code, ids in sorted(inherited_issues.items())
    ]
    status = "passed_with_warnings" if issues else "passed"
    content = {
        "schema_version": "nebula_one.period-energy-total.v1",
        "capability_key": "energy.period-total.v1",
        "application_id": intensity_trend["application_id"],
        "system_model_id": intensity_trend["system_model_id"],
        "source_intensity_trend": {
            "content_sha256": trend_hash,
            "baseline_period_id": baseline_period_id,
        },
        "value_semantics": {
            "kind": "evidence_scaled_period_total",
            "formula": "solved_energy / solved_functional_output * period_product_output",
            "aggregation": "sum_of_non_overlapping_periods",
            "functional_output_unit": next(iter(units)),
        },
        "baseline_period_id": baseline_period_id,
        "observations": observations,
        "activities": normalized_activities,
        "metrics": metrics,
        "issues": issues,
        "status": status,
        "audit": {
            "status": status,
            "checks": {
                "source_intensity_trend_hash_valid": True,
                "activity_period_set_exact": True,
                "inventories_frozen_and_hashed": True,
                "inventory_revision_matches_solved_snapshot": True,
                "production_data_points_approved": True,
                "production_evidence_pinned": True,
                "functional_output_flow_and_unit_exact": True,
                "periods_non_overlapping": True,
                "zero_or_negative_activity_rejected": True,
            },
            "counts": {
                "period_count": len(period_ids),
                "metric_count": len(metrics),
                "evidence_count": len(normalized_activities),
            },
            "limitations": [
                "period totals depend on authored and reviewed production activity",
                "v1 performs exact-unit scaling only and does not convert production units",
                "covered_period_total sums only the supplied non-overlapping periods",
                "results do not claim a complete site energy balance",
            ],
        },
    }
    return {**content, "content_sha256": canonical_json_sha256(content)}
