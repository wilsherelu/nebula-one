from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


SCHEMA_VERSION = "nebula_one.province-electricity-scenario.v1"
CAPABILITY_KEY = "electricity.province-scenario.v1"
PACKAGE_KIND = "province_electricity_factor"


def _fail(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def _decimal(value: Any, *, field: str, allow_zero: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DomainError(
            code="PROVINCE_ELECTRICITY_NUMBER_INVALID",
            message="province electricity input must be numeric",
            status_code=422,
            details={"field": field},
        ) from exc
    if not parsed.is_finite() or (parsed < 0 if allow_zero else parsed <= 0):
        _fail(
            "PROVINCE_ELECTRICITY_NUMBER_INVALID",
            "province electricity input is outside its allowed range",
            field=field,
        )
    return parsed


def _verified_hash(payload: dict[str, Any], *, code: str, subject: str) -> str:
    basis = dict(payload)
    expected = str(basis.pop("content_sha256", "")).strip()
    if not expected or canonical_json_sha256(basis) != expected:
        _fail(code, f"{subject} content hash does not match")
    return expected


def _relative(value: Decimal, baseline: Decimal) -> str | None:
    if baseline == 0:
        return None
    return str((value - baseline) / baseline)


def build_province_electricity_scenario(
    *,
    period_energy_total: dict[str, Any],
    source_binding: dict[str, Any],
    method_package_ref: str,
    method_package_sha256: str,
    method_package_kind: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if method_package_kind != PACKAGE_KIND:
        _fail(
            "PROVINCE_ELECTRICITY_METHOD_KIND_INVALID",
            "method package is not a province electricity factor package",
        )
    if (manifest.get("output_schema") or {}).get("schema_version") != SCHEMA_VERSION:
        _fail(
            "PROVINCE_ELECTRICITY_OUTPUT_SCHEMA_MISMATCH",
            "method package does not target province-electricity-scenario.v1",
        )
    if period_energy_total.get("schema_version") != "nebula_one.period-energy-total.v1":
        _fail(
            "PROVINCE_ELECTRICITY_PERIOD_TOTAL_REQUIRED",
            "province electricity scenarios require a period energy total",
        )
    period_total_hash = _verified_hash(
        period_energy_total,
        code="PROVINCE_ELECTRICITY_PERIOD_TOTAL_HASH_MISMATCH",
        subject="period energy total",
    )
    binding_hash = _verified_hash(
        source_binding,
        code="PROVINCE_ELECTRICITY_SOURCE_BINDING_HASH_MISMATCH",
        subject="electricity source binding",
    )

    formula = manifest.get("formula_graph")
    if not isinstance(formula, dict):
        _fail(
            "PROVINCE_ELECTRICITY_METHOD_INVALID",
            "province electricity method lacks a formula graph",
        )
    if formula.get("source_collection") != "energy.period-total.v1.metrics":
        _fail(
            "PROVINCE_ELECTRICITY_SOURCE_UNSUPPORTED",
            "province electricity must consume frozen period energy totals",
        )
    if formula.get("calculation") != "electricity_kwh_times_province_factor":
        _fail(
            "PROVINCE_ELECTRICITY_FORMULA_UNSUPPORTED",
            "province electricity calculation formula is unsupported",
        )

    selector = formula.get("electricity_flow_selector")
    if not isinstance(selector, dict):
        _fail(
            "PROVINCE_ELECTRICITY_SELECTOR_INVALID",
            "province electricity requires an exact TIDAS Flow selector",
        )
    selector_fields = (
        "source_namespace",
        "flow_uuid",
        "version",
        "flow_content_sha256",
        "flow_snapshot_sha256",
    )
    if any(not str(selector.get(field) or "").strip() for field in selector_fields):
        _fail(
            "PROVINCE_ELECTRICITY_SELECTOR_INVALID",
            "province electricity Flow selector is incomplete",
        )
    if any(source_binding.get(field) != selector.get(field) for field in selector_fields):
        _fail(
            "PROVINCE_ELECTRICITY_SELECTOR_MISMATCH",
            "period electricity source differs from the exact method selector",
        )

    conversion = formula.get("unit_conversion")
    if not isinstance(conversion, dict):
        _fail(
            "PROVINCE_ELECTRICITY_CONVERSION_INVALID",
            "province electricity method requires an exact unit conversion",
        )
    required_conversion = {
        "source_unit": "MJ",
        "target_unit": "kWh",
        "operator": "source_amount_divided_by_target_factor_to_reference",
        "target_factor_to_reference": "3.6",
    }
    if any(conversion.get(key) != value for key, value in required_conversion.items()):
        _fail(
            "PROVINCE_ELECTRICITY_CONVERSION_INVALID",
            "province electricity method unit conversion is unsupported",
        )
    if any(
        not str(conversion.get(key) or "").strip()
        for key in (
            "unit_group_uuid",
            "unit_group_version",
            "unit_group_content_sha256",
        )
    ):
        _fail(
            "PROVINCE_ELECTRICITY_CONVERSION_INVALID",
            "province electricity conversion requires an exact UnitGroup identity",
        )
    if any(
        source_binding.get(key) != conversion.get(key)
        for key in ("unit_group_uuid", "unit_group_version", "unit_group_content_sha256")
    ):
        _fail(
            "PROVINCE_ELECTRICITY_UNIT_IDENTITY_MISMATCH",
            "electricity activity and conversion UnitGroup identities differ",
        )
    divisor = _decimal(
        conversion.get("target_factor_to_reference"),
        field="unit_conversion.target_factor_to_reference",
    )

    metric_key = str(source_binding.get("metric_key") or "").strip()
    metric_matches = [
        item
        for item in period_energy_total.get("metrics") or []
        if isinstance(item, dict) and item.get("metric_key") == metric_key
    ]
    if len(metric_matches) != 1:
        _fail(
            "PROVINCE_ELECTRICITY_METRIC_NOT_UNIQUE",
            "exact electricity metric must resolve once in period energy totals",
            match_count=len(metric_matches),
        )
    metric = metric_matches[0]
    _verified_hash(
        metric,
        code="PROVINCE_ELECTRICITY_METRIC_HASH_MISMATCH",
        subject="electricity metric",
    )
    if metric.get("unit_symbol") != "MJ" or metric.get("basis") != {
        "energy_convention": "declared_energy",
        "material_condition": "not_applicable",
    }:
        _fail(
            "PROVINCE_ELECTRICITY_METRIC_BASIS_INVALID",
            "province electricity requires declared electricity energy in MJ",
        )

    period_ids = [
        str(item.get("period", {}).get("id") or "")
        for item in period_energy_total.get("observations") or []
    ]
    if not period_ids or set(period_ids) != set(source_binding.get("period_ids") or []):
        _fail(
            "PROVINCE_ELECTRICITY_PERIOD_SET_MISMATCH",
            "electricity source binding must exactly cover the energy-total periods",
        )
    raw_values = metric.get("period_total_values") or {}
    if set(raw_values) != set(period_ids):
        _fail(
            "PROVINCE_ELECTRICITY_PERIOD_SET_MISMATCH",
            "electricity metric values must exactly cover the selected periods",
        )
    activity_mj = {
        period_id: _decimal(raw_values[period_id], field=f"activity.{period_id}")
        for period_id in period_ids
    }
    activity_kwh = {key: value / divisor for key, value in activity_mj.items()}

    factors = manifest.get("classification_rules")
    if not isinstance(factors, dict):
        _fail(
            "PROVINCE_ELECTRICITY_FACTORS_INVALID",
            "province electricity method lacks factor scenarios",
        )
    factor_source = factors.get("factor_source")
    if not isinstance(factor_source, dict):
        _fail(
            "PROVINCE_ELECTRICITY_FACTOR_SOURCE_REQUIRED",
            "province electricity factors require an exact source record",
        )
    _verified_hash(
        factor_source,
        code="PROVINCE_ELECTRICITY_FACTOR_SOURCE_HASH_MISMATCH",
        subject="electricity factor source",
    )
    if (
        factor_source.get("factor_scope") != "province_average_location_based"
        or factor_source.get("activity_unit") != "kWh"
        or factor_source.get("factor_unit") != "kg CO2/kWh"
    ):
        _fail(
            "PROVINCE_ELECTRICITY_FACTOR_SCOPE_INVALID",
            "province electricity factor scope or units are unsupported",
        )

    scenarios = factors.get("scenarios")
    if not isinstance(scenarios, list) or not 2 <= len(scenarios) <= 31:
        _fail(
            "PROVINCE_ELECTRICITY_SCENARIOS_REQUIRED",
            "province electricity comparison requires two to thirty-one scenarios",
        )
    scenario_by_id: dict[str, dict[str, Any]] = {}
    province_codes: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            _fail(
                "PROVINCE_ELECTRICITY_SCENARIO_INVALID",
                "province electricity scenarios must be objects",
            )
        scenario_id = str(scenario.get("scenario_id") or "").strip()
        province_code = str(scenario.get("province_code") or "").strip()
        if (
            not scenario_id
            or not province_code
            or not str(scenario.get("province_name") or "").strip()
            or scenario_id in scenario_by_id
            or province_code in province_codes
        ):
            _fail(
                "PROVINCE_ELECTRICITY_SCENARIO_INVALID",
                "province electricity scenario identities must be complete and unique",
            )
        _verified_hash(
            scenario,
            code="PROVINCE_ELECTRICITY_SCENARIO_HASH_MISMATCH",
            subject=f"scenario {scenario_id}",
        )
        scenario_by_id[scenario_id] = scenario
        province_codes.add(province_code)
    baseline_id = str(factors.get("baseline_scenario_id") or "").strip()
    if baseline_id not in scenario_by_id:
        _fail(
            "PROVINCE_ELECTRICITY_BASELINE_NOT_FOUND",
            "province electricity baseline scenario is missing",
        )

    computed: dict[str, dict[str, Any]] = {}
    for scenario_id, scenario in scenario_by_id.items():
        factor = _decimal(
            scenario.get("factor"),
            field=f"scenarios.{scenario_id}.factor",
            allow_zero=True,
        )
        period_values = {
            period_id: activity_kwh[period_id] * factor for period_id in period_ids
        }
        computed[scenario_id] = {
            "scenario": scenario,
            "factor": factor,
            "period_values": period_values,
            "covered_period_total": sum(period_values.values(), Decimal("0")),
        }
    baseline_total = computed[baseline_id]["covered_period_total"]
    result_scenarios: list[dict[str, Any]] = []
    for scenario_id in sorted(computed):
        item = computed[scenario_id]
        total = item["covered_period_total"]
        result_scenarios.append(
            {
                "scenario_id": scenario_id,
                "name": item["scenario"]["name"],
                "province_code": item["scenario"]["province_code"],
                "province_name": item["scenario"]["province_name"],
                "factor": str(item["factor"]),
                "factor_unit": factor_source["factor_unit"],
                "period_emissions": {
                    key: str(value) for key, value in item["period_values"].items()
                },
                "covered_period_total": str(total),
                "result_unit": "kg CO2",
                "delta_from_baseline": {
                    "absolute": str(total - baseline_total),
                    "relative": _relative(total, baseline_total),
                },
                "content_sha256": item["scenario"]["content_sha256"],
            }
        )

    factor_year = str(factor_source.get("data_year") or "")
    period_years = sorted(
        {
            str(item.get("period", {}).get("start_date") or "")[:4]
            for item in period_energy_total.get("observations") or []
        }
    )
    issues = list(period_energy_total.get("issues") or [])
    if period_years != [factor_year]:
        issues.append(
            {
                "code": "ELECTRICITY_FACTOR_VINTAGE_DIFFERS_FROM_ACTIVITY_PERIOD",
                "severity": "warning",
                "message": "the official factor year differs from one or more activity periods",
                "factor_year": factor_year,
                "activity_years": period_years,
            }
        )
    status = "passed_with_warnings" if issues else "passed"
    content = {
        "schema_version": SCHEMA_VERSION,
        "capability_key": CAPABILITY_KEY,
        "application_id": period_energy_total["application_id"],
        "system_model_id": period_energy_total["system_model_id"],
        "source_period_energy_total": {
            "content_sha256": period_total_hash,
            "baseline_period_id": period_energy_total["baseline_period_id"],
        },
        "source_binding": {**source_binding, "content_sha256": binding_hash},
        "method_package": {
            "ref": method_package_ref,
            "content_sha256": method_package_sha256,
        },
        "value_semantics": {
            "kind": "location_based_purchased_electricity_co2_reference",
            "formula": "period_electricity_MJ / 3.6_MJ_per_kWh * province_factor_kg_CO2_per_kWh",
            "not_lcia": True,
            "not_complete_scope_2_statement": True,
        },
        "electricity_activity": {
            "period_values_mj": {key: str(value) for key, value in activity_mj.items()},
            "period_values_kwh": {key: str(value) for key, value in activity_kwh.items()},
            "covered_period_total_mj": str(sum(activity_mj.values(), Decimal("0"))),
            "covered_period_total_kwh": str(sum(activity_kwh.values(), Decimal("0"))),
            "unit_conversion": conversion,
        },
        "factor_source": factor_source,
        "baseline_scenario_id": baseline_id,
        "scenarios": result_scenarios,
        "issues": issues,
        "status": status,
        "audit": {
            "status": status,
            "checks": {
                "period_energy_total_hash_valid": True,
                "source_binding_hash_valid": True,
                "exact_tidas_electricity_flow_bound": True,
                "exact_tidas_energy_unit_group_bound": True,
                "factor_source_hash_valid": True,
                "scenario_hashes_valid": True,
                "units_and_scope_explicit": True,
                "zero_baseline_relative_delta_nullable": True,
            },
            "counts": {
                "period_count": len(period_ids),
                "scenario_count": len(result_scenarios),
            },
            "limitations": [
                "province factors are location-based electricity CO2 references, not EF 3.1 LCIA factors",
                "the scenario changes factor attribution only and does not re-solve the LCA model",
                "the result is not a complete Scope 2 inventory or assurance statement",
                "factor vintage must be assessed against the reporting period before business use",
                "the repository contains a transformed factual subset, not the source PDF or official table layout",
            ],
        },
    }
    return {**content, "content_sha256": canonical_json_sha256(content)}
