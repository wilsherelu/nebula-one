from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import re
from typing import Any

from ..analysis.energy_carrier import EnergyCarrierSolved
from ..analysis.energy_scenarios import energy_series_metric_key
from ..errors import DomainError
from ..hashing import canonical_json_sha256


SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _fail(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def _relative(value: Decimal, reference: Decimal) -> str | None:
    if reference == 0:
        return None
    return str((value - reference) / reference)


def _carrier_signature(series: Any) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted(
            (
                entry.carrier_flow.source_namespace,
                str(entry.carrier_flow.flow_uuid),
                entry.carrier_flow.version,
            )
            for entry in series.entries
        )
    )


def build_period_energy_trend(
    *,
    application_id: str,
    system_model_id: str,
    functional_unit: Any,
    functional_unit_sha256: str,
    observations: tuple[dict[str, Any], ...],
    baseline_period_id: str,
    metric_labels: dict[str, str],
) -> dict[str, Any]:
    if not 2 <= len(observations) <= 24:
        _fail(
            "PERIOD_ENERGY_TREND_COUNT_UNSUPPORTED",
            "energy trend requires two to twenty-four period observations",
            observation_count=len(observations),
        )
    if not application_id.strip() or not system_model_id.strip():
        _fail(
            "PERIOD_ENERGY_TREND_SOURCE_REQUIRED",
            "energy trend requires exact application and system model identities",
        )
    if SHA256_RE.fullmatch(functional_unit_sha256) is None or (
        canonical_json_sha256(functional_unit) != functional_unit_sha256
    ):
        _fail(
            "PERIOD_ENERGY_FUNCTIONAL_UNIT_MISMATCH",
            "functional unit identity is missing or does not match its content",
        )

    period_ids: list[str] = []
    snapshot_ids: list[str] = []
    resolutions: set[str] = set()
    parsed: dict[str, EnergyCarrierSolved] = {}
    normalized: list[dict[str, Any]] = []
    for item in observations:
        period = dict(item.get("period") or {})
        period_id = str(period.get("id") or "").strip()
        period_basis = {
            key: period.get(key)
            for key in ("id", "key", "name", "start_date", "end_date", "resolution")
        }
        if (
            not period_id
            or SHA256_RE.fullmatch(str(period.get("content_sha256") or "")) is None
            or canonical_json_sha256(period_basis) != period.get("content_sha256")
        ):
            _fail(
                "PERIOD_ENERGY_PERIOD_IDENTITY_INVALID",
                "period observation requires an exact immutable period identity",
                period_id=period_id or None,
            )
        if str(period.get("start_date")) > str(period.get("end_date")):
            _fail(
                "PERIOD_ENERGY_PERIOD_RANGE_INVALID",
                "period end date cannot be earlier than its start date",
                period_id=period_id,
            )
        source = dict(item.get("source") or {})
        source_hash_fields = (
            "energy_result_id",
            "energy_result_record_sha256",
            "solved_snapshot_id",
            "solved_snapshot_content_sha256",
            "solve_hash",
            "system_revision_id",
            "system_revision_sha256",
            "system_model_id",
        )
        if any(not str(source.get(key) or "").strip() for key in source_hash_fields):
            _fail(
                "PERIOD_ENERGY_SOURCE_IDENTITY_INVALID",
                "period observation source identity is incomplete",
                period_id=period_id,
            )
        if any(
            SHA256_RE.fullmatch(str(source.get(key) or "")) is None
            for key in (
                "energy_result_record_sha256",
                "solved_snapshot_content_sha256",
                "solve_hash",
                "system_revision_sha256",
            )
        ):
            _fail(
                "PERIOD_ENERGY_SOURCE_IDENTITY_INVALID",
                "period observation source hashes are invalid",
                period_id=period_id,
            )
        if source["system_model_id"] != system_model_id:
            _fail(
                "PERIOD_ENERGY_SYSTEM_MODEL_MISMATCH",
                "all period observations must use the same system model",
                period_id=period_id,
            )
        try:
            energy = EnergyCarrierSolved.model_validate(item.get("energy_result"))
        except Exception as exc:
            raise DomainError(
                code="PERIOD_ENERGY_RESULT_INVALID",
                message="period energy result failed strict validation",
                status_code=422,
                details={"period_id": period_id},
            ) from exc
        snapshot_ref = energy.solved_snapshot_ref
        if (
            str(snapshot_ref.id) != source["solved_snapshot_id"]
            or snapshot_ref.content_sha256 != source["solved_snapshot_content_sha256"]
            or snapshot_ref.solve_hash != source["solve_hash"]
        ):
            _fail(
                "PERIOD_ENERGY_SNAPSHOT_MISMATCH",
                "energy result and solved snapshot identities do not match",
                period_id=period_id,
            )
        period_ids.append(period_id)
        snapshot_ids.append(source["solved_snapshot_id"])
        resolutions.add(str(period["resolution"]))
        parsed[period_id] = energy
        normalized.append(
            {
                "period": {**period_basis, "content_sha256": period["content_sha256"]},
                "source": source,
                "energy_result_content_sha256": energy.content_sha256,
            }
        )

    if len(period_ids) != len(set(period_ids)):
        _fail("PERIOD_ENERGY_PERIOD_DUPLICATE", "period ids must be unique")
    if len(snapshot_ids) != len(set(snapshot_ids)):
        _fail(
            "PERIOD_ENERGY_SNAPSHOT_DUPLICATE",
            "each reporting period must use a distinct solved snapshot",
        )
    if baseline_period_id not in period_ids:
        _fail(
            "PERIOD_ENERGY_BASELINE_MISSING",
            "baseline period is not included in the trend",
        )
    if len(resolutions) != 1:
        _fail(
            "PERIOD_ENERGY_RESOLUTION_MISMATCH",
            "period observations must use one resolution",
            resolutions=sorted(resolutions),
        )
    normalized.sort(
        key=lambda item: (
            item["period"]["start_date"],
            item["period"]["end_date"],
            item["period"]["id"],
        )
    )
    for previous, current in zip(normalized, normalized[1:]):
        if current["period"]["start_date"] <= previous["period"]["end_date"]:
            _fail(
                "PERIOD_ENERGY_PERIOD_OVERLAP",
                "period observations must not overlap",
                previous_period_id=previous["period"]["id"],
                period_id=current["period"]["id"],
            )

    ordered_period_ids = [item["period"]["id"] for item in normalized]
    series_maps = {
        period_id: {
            energy_series_metric_key(series.unit_identity_sha256, series.basis): series
            for series in parsed[period_id].series
        }
        for period_id in ordered_period_ids
    }
    baseline_keys = set(series_maps[baseline_period_id])
    for period_id, series_map in series_maps.items():
        if set(series_map) != baseline_keys:
            _fail(
                "PERIOD_ENERGY_SERIES_NOT_COMPARABLE",
                "period observations do not contain the same exact energy series",
                period_id=period_id,
            )
        for metric_key in baseline_keys:
            if _carrier_signature(series_map[metric_key]) != _carrier_signature(
                series_maps[baseline_period_id][metric_key]
            ):
                _fail(
                    "PERIOD_ENERGY_CARRIER_SET_MISMATCH",
                    "period energy carrier Flow identities differ",
                    period_id=period_id,
                    metric_key=metric_key,
                )
    if set(metric_labels) != baseline_keys or any(
        not str(label).strip() for label in metric_labels.values()
    ):
        _fail(
            "PERIOD_ENERGY_LABELS_INCOMPLETE",
            "metric labels must exactly cover comparable energy series",
        )

    metrics: list[dict[str, Any]] = []
    for metric_key in sorted(baseline_keys):
        baseline_series = series_maps[baseline_period_id][metric_key]
        values = {
            period_id: series_maps[period_id][metric_key].total_amount
            for period_id in ordered_period_ids
        }
        baseline_value = values[baseline_period_id]
        previous_id: str | None = None
        previous_deltas: dict[str, dict[str, str | None] | None] = {}
        for period_id in ordered_period_ids:
            if previous_id is None:
                previous_deltas[period_id] = None
            else:
                previous_value = values[previous_id]
                previous_deltas[period_id] = {
                    "absolute": str(values[period_id] - previous_value),
                    "relative": _relative(values[period_id], previous_value),
                }
            previous_id = period_id
        metric_basis = {
            "metric_key": metric_key,
            "label": metric_labels[metric_key].strip(),
            "unit_symbol": "MJ",
            "unit_identity_sha256": baseline_series.unit_identity_sha256,
            "basis": baseline_series.basis.model_dump(mode="json"),
            "values": {key: str(value) for key, value in values.items()},
            "deltas_from_baseline": {
                period_id: {
                    "absolute": str(value - baseline_value),
                    "relative": _relative(value, baseline_value),
                }
                for period_id, value in values.items()
            },
            "deltas_from_previous": previous_deltas,
            "summary": {
                "minimum": str(min(values.values())),
                "maximum": str(max(values.values())),
                "arithmetic_mean": str(
                    sum(values.values(), Decimal("0")) / Decimal(len(values))
                ),
            },
        }
        metrics.append(
            {**metric_basis, "content_sha256": canonical_json_sha256(metric_basis)}
        )

    warnings: dict[str, set[str]] = defaultdict(set)
    for period_id, energy in parsed.items():
        for issue in energy.issues:
            warnings[issue.code].add(period_id)
    issues = [
        {
            "code": code,
            "severity": "warning",
            "message": "one or more period energy results retain this source warning",
            "period_ids": sorted(ids),
        }
        for code, ids in sorted(warnings.items())
    ]
    content = {
        "schema_version": "nebula_one.period-energy-trend.v1",
        "capability_key": "energy.period-trend.v1",
        "application_id": application_id,
        "system_model_id": system_model_id,
        "value_semantics": {
            "kind": "functional_unit_intensity",
            "functional_unit": functional_unit,
            "functional_unit_sha256": functional_unit_sha256,
            "aggregation": "none",
        },
        "baseline_period_id": baseline_period_id,
        "observations": normalized,
        "metrics": metrics,
        "issues": issues,
        "status": "passed_with_warnings" if issues else "passed",
        "audit": {
            "status": "passed_with_warnings" if issues else "passed",
            "checks": {
                "same_application": True,
                "same_system_model": True,
                "same_functional_unit": True,
                "periods_immutable_and_hashed": True,
                "periods_unique_non_overlapping": True,
                "resolution_consistent": True,
                "energy_results_match_solved_snapshots": True,
                "unit_basis_and_carrier_sets_comparable": True,
                "zero_reference_relative_delta_nullable": True,
            },
            "counts": {
                "period_count": len(normalized),
                "metric_count": len(metrics),
            },
            "limitations": [
                "v1 compares functional-unit energy intensity across periods",
                "v1 does not sum period totals or infer production volume",
                "unlike unit, basis or carrier Flow identities are never combined",
                "results do not claim a complete energy balance",
            ],
        },
    }
    return {**content, "content_sha256": canonical_json_sha256(content)}
