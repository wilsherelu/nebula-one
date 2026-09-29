from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


SCHEMA_VERSION = "nebula_one.organization-ghg-inventory-trial.v1"
CAPABILITY_KEY = "ghg.inventory.trial.v1"
PACKAGE_KIND = "organization_ghg_inventory_trial"
SCOPE_1_CALCULATION_CONTRACT = "scope1-period-scale-factor-sum.v1"


def _fail(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def _verified(payload: dict[str, Any], *, subject: str) -> str:
    content_hash = str(payload.get("content_sha256") or "").strip()
    basis = dict(payload)
    basis.pop("content_sha256", None)
    if (
        re.fullmatch(r"[0-9a-f]{64}", content_hash) is None
        or canonical_json_sha256(basis) != content_hash
    ):
        _fail(
            "GHG_INVENTORY_SOURCE_HASH_MISMATCH",
            f"{subject} does not match its content hash",
        )
    return content_hash


def _number(value: Any, *, subject: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        _fail("GHG_INVENTORY_VALUE_INVALID", f"{subject} is not a finite number")
    return float(value)


def _source_rule(manifest: dict[str, Any], key: str) -> dict[str, Any]:
    rules = manifest.get("classification_rules")
    rule = rules.get(key) if isinstance(rules, dict) else None
    if not isinstance(rule, dict):
        _fail(
            "GHG_INVENTORY_METHOD_PACKAGE_INVALID",
            f"classification_rules.{key} is required",
        )
    return rule


def validate_organization_ghg_inventory_method_package(
    *,
    method_package_ref: str,
    method_package_kind: str,
    manifest: dict[str, Any],
) -> None:
    if method_package_kind != PACKAGE_KIND:
        _fail(
            "GHG_INVENTORY_METHOD_PACKAGE_KIND_MISMATCH",
            f"{CAPABILITY_KEY} requires an {PACKAGE_KIND} method package",
        )
    output = manifest.get("output_schema")
    if not isinstance(output, dict) or output.get("schema_version") != SCHEMA_VERSION:
        _fail(
            "GHG_INVENTORY_METHOD_PACKAGE_INVALID",
            "the method package output schema is unsupported",
        )
    contracts = manifest.get("calculation_contracts")
    declared_contract = (
        contracts.get(CAPABILITY_KEY) if isinstance(contracts, dict) else None
    )
    if declared_contract != SCOPE_1_CALCULATION_CONTRACT:
        _fail(
            "GHG_INVENTORY_CALCULATION_CONTRACT_UNSUPPORTED",
            "已固定版本的方法包未声明本实现使用的 Scope 1 计算合同，其期间分摊不能按新公式重跑；"
            "请改用已声明该合同的方法包版本（见 details.required_contract）。"
            "The pinned method package does not declare the Scope 1 calculation "
            "contract this build implements, so its period scaling cannot be "
            "re-run under these formulas.",
            method_package_ref=method_package_ref,
            declared_contract=declared_contract,
            required_contract=SCOPE_1_CALCULATION_CONTRACT,
        )


def build_organization_ghg_inventory(
    *,
    application_id: str,
    period_energy_total: dict[str, Any],
    scope_1_observations: list[dict[str, Any]],
    province_electricity: dict[str, Any],
    scope_2_scenario_id: str,
    method_package_ref: str,
    method_package_sha256: str,
    method_package_kind: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    validate_organization_ghg_inventory_method_package(
        method_package_ref=method_package_ref,
        method_package_kind=method_package_kind,
        manifest=manifest,
    )
    period_total_hash = _verified(
        period_energy_total, subject="period energy total result"
    )
    electricity_hash = _verified(
        province_electricity, subject="province electricity result"
    )
    if (
        period_energy_total.get("application_id") != application_id
        or province_electricity.get("application_id") != application_id
        or province_electricity.get("source_period_energy_total", {}).get(
            "content_sha256"
        )
        != period_total_hash
    ):
        _fail(
            "GHG_INVENTORY_ELECTRICITY_APPLICATION_MISMATCH",
            "period totals and electricity result must bind the same application and source",
        )

    scope_1_rule = _source_rule(manifest, "scope_1")
    scope_2_rule = _source_rule(manifest, "scope_2")
    scope_3_rule = _source_rule(manifest, "scope_3")
    if (
        scope_1_rule.get("source_capability") != "carbon.management.v1"
        or scope_1_rule.get("category") != "direct"
        or scope_1_rule.get("accepted_coverage")
        != ["exact_contributions", "partial_exact_contributions"]
        or scope_1_rule.get("result_unit") != "kg CO2-Eq"
    ):
        _fail(
            "GHG_INVENTORY_SCOPE_1_RULE_INVALID",
            "Scope 1 requires the exact direct EF 3.1 contribution contract",
        )
    period_ids = {
        str(item.get("period", {}).get("id") or "")
        for item in period_energy_total.get("observations") or []
    }
    observation_ids = {
        str(item.get("period_id") or "") for item in scope_1_observations
    }
    if not period_ids or period_ids != observation_ids:
        _fail(
            "GHG_INVENTORY_SCOPE_1_PERIOD_SET_MISMATCH",
            "Scope 1 observations must exactly cover the period-total observations",
        )
    scope_1_total = Decimal("0")
    scope_1_sources: list[dict[str, Any]] = []
    source_issues: list[dict[str, Any]] = []
    reporting_periods: set[tuple[str, str, str]] = set()
    for observation in sorted(
        scope_1_observations, key=lambda item: str(item.get("period_id") or "")
    ):
        carbon = observation.get("carbon_management")
        activity = observation.get("activity")
        if not isinstance(carbon, dict) or not isinstance(activity, dict):
            _fail(
                "GHG_INVENTORY_SCOPE_1_EVIDENCE_INVALID",
                "each Scope 1 observation requires carbon and production evidence",
            )
        carbon_hash = _verified(carbon, subject="carbon management result")
        attribution = carbon.get("carbon_attribution")
        if (
            not isinstance(attribution, dict)
            or attribution.get("coverage") not in scope_1_rule["accepted_coverage"]
        ):
            _fail(
                "GHG_INVENTORY_SCOPE_1_EVIDENCE_INCOMPLETE",
                "Scope 1 requires exact provider contributions with an explicit direct category",
            )
        direct = [
            item
            for item in attribution.get("categories") or []
            if isinstance(item, dict) and item.get("category") == "direct"
        ]
        if len(direct) != 1 or direct[0].get("unit") != scope_1_rule["result_unit"]:
            _fail(
                "GHG_INVENTORY_SCOPE_1_EVIDENCE_INVALID",
                "the exact direct contribution must resolve once in kg CO2-Eq",
            )
        try:
            intensity = Decimal(str(direct[0].get("value")))
            scale_factor = Decimal(str(activity.get("scale_factor")))
        except (InvalidOperation, ValueError):
            _fail(
                "GHG_INVENTORY_VALUE_INVALID",
                "Scope 1 intensity or production scale factor is invalid",
            )
        if not intensity.is_finite() or not scale_factor.is_finite() or scale_factor <= 0:
            _fail(
                "GHG_INVENTORY_VALUE_INVALID",
                "Scope 1 intensity and production scale factor must be finite and positive",
            )
        period_value = intensity * scale_factor
        scope_1_total += period_value
        carbon_source = carbon.get("source_snapshot")
        energy_source = activity.get("source")
        if (
            not isinstance(carbon_source, dict)
            or not isinstance(energy_source, dict)
            or carbon_source.get("id") != energy_source.get("solved_snapshot_id")
            or carbon_source.get("content_sha256")
            != energy_source.get("solved_snapshot_content_sha256")
        ):
            _fail(
                "GHG_INVENTORY_CARBON_SNAPSHOT_MISMATCH",
                "a period carbon result does not bind its production-scaled snapshot",
            )
        period = carbon.get("reporting_period")
        if not isinstance(period, dict) or any(
            not str(period.get(key) or "").strip()
            for key in ("id", "version", "content_sha256")
        ):
            _fail(
                "GHG_INVENTORY_REPORTING_PERIOD_REQUIRED",
                "a carbon result lacks an exact reporting period",
            )
        reporting_periods.add(
            (str(period["id"]), str(period["version"]), str(period["content_sha256"]))
        )
        source_issues.extend(carbon.get("audit", {}).get("issues") or [])
        scope_1_sources.append(
            {
                "period_id": observation["period_id"],
                "source_snapshot": carbon_source,
                "carbon_result_sha256": carbon_hash,
                "production_scale_factor": str(scale_factor),
                "direct_intensity": str(intensity),
                "period_value": str(period_value),
                "unit": scope_1_rule["result_unit"],
                "provider_receipt": attribution.get("indicator_receipt"),
                "production_evidence": activity.get("production_evidence"),
            }
        )
    if len(reporting_periods) != 1:
        _fail(
            "GHG_INVENTORY_REPORTING_PERIOD_MISMATCH",
            "Scope 1 observations must share one frozen reporting-period contract",
        )

    semantics = province_electricity.get("value_semantics")
    if (
        scope_2_rule.get("source_capability")
        != "electricity.province-scenario.v1"
        or scope_2_rule.get("accounting_method") != "location_based_reference"
        or scope_2_rule.get("result_unit") != "kg CO2"
        or not isinstance(semantics, dict)
        or semantics.get("kind")
        != "location_based_purchased_electricity_co2_reference"
        or semantics.get("not_lcia") is not True
        or semantics.get("not_complete_scope_2_statement") is not True
    ):
        _fail(
            "GHG_INVENTORY_SCOPE_2_RULE_INVALID",
            "Scope 2 reference requires the explicit province location-based contract",
        )
    matches = [
        item
        for item in province_electricity.get("scenarios") or []
        if isinstance(item, dict) and item.get("scenario_id") == scope_2_scenario_id
    ]
    if len(matches) != 1 or matches[0].get("result_unit") != scope_2_rule["result_unit"]:
        _fail(
            "GHG_INVENTORY_SCOPE_2_SCENARIO_NOT_FOUND",
            "the selected Scope 2 reference scenario must resolve once with the required unit",
        )
    electricity = matches[0]
    scope_2_value = str(electricity.get("covered_period_total") or "").strip()
    try:
        scope_2_numeric = float(scope_2_value)
    except ValueError:
        scope_2_numeric = math.nan
    if not math.isfinite(scope_2_numeric):
        _fail("GHG_INVENTORY_VALUE_INVALID", "Scope 2 reference is not finite")
    if scope_3_rule != {
        "status": "not_calculated",
        "reason": "no frozen value-chain classification evidence",
    }:
        _fail(
            "GHG_INVENTORY_SCOPE_3_RULE_INVALID",
            "the trial package must leave Scope 3 uncalculated",
        )

    source_issues.extend(province_electricity.get("issues") or [])
    issues = [
        *source_issues,
        {
            "code": "GHG_INVENTORY_PARTIAL_SCOPE_1",
            "severity": "warning",
            "message": "Scope 1 covers only exact direct contributions present in the frozen model boundary.",
        },
        {
            "code": "GHG_INVENTORY_SCOPE_2_REFERENCE_ONLY",
            "severity": "warning",
            "message": "Scope 2 is a province location-based electricity CO2 reference, not a complete Scope 2 inventory.",
        },
        {
            "code": "GHG_INVENTORY_SCOPE_3_NOT_CALCULATED",
            "severity": "warning",
            "message": "Scope 3 remains uncalculated because no frozen value-chain classification evidence was supplied.",
        },
    ]
    content = {
        "schema_version": SCHEMA_VERSION,
        "capability_key": CAPABILITY_KEY,
        "application_id": application_id,
        "method_package": {
            "ref": method_package_ref,
            "content_sha256": method_package_sha256,
        },
        "source_period_energy_total": {
            "content_sha256": period_total_hash,
            "period_ids": sorted(period_ids),
        },
        "reporting_period": {
            "id": next(iter(reporting_periods))[0],
            "version": next(iter(reporting_periods))[1],
            "content_sha256": next(iter(reporting_periods))[2],
            "covered_start_date": min(
                item["period"]["start_date"]
                for item in period_energy_total["observations"]
            ),
            "covered_end_date": max(
                item["period"]["end_date"]
                for item in period_energy_total["observations"]
            ),
        },
        "inventory_boundary": {
            "status": "partial_trial",
            "organizational_boundary_complete": False,
            "combined_total_available": False,
            "reason": "Scope 1 and Scope 2 inputs use different result semantics and Scope 3 is not calculated.",
        },
        "scopes": [
            {
                "scope": "scope_1",
                "status": "quantified_partial",
                "value": str(scope_1_total),
                "unit": scope_1_rule["result_unit"],
                "label": "Exact direct EF 3.1 contribution",
                "source": {
                    "capability_key": "carbon.management.v1",
                    "period_observations": scope_1_sources,
                },
            },
            {
                "scope": "scope_2",
                "status": "reference_only",
                "value": scope_2_value,
                "unit": scope_2_rule["result_unit"],
                "label": "Purchased electricity location-based CO2 reference",
                "accounting_method": "location_based_reference",
                "source": {
                    "capability_key": "electricity.province-scenario.v1",
                    "content_sha256": electricity_hash,
                    "scenario_id": scope_2_scenario_id,
                    "province_code": electricity.get("province_code"),
                    "factor": electricity.get("factor"),
                    "factor_unit": electricity.get("factor_unit"),
                },
            },
            {
                "scope": "scope_3",
                "status": "not_calculated",
                "value": None,
                "unit": None,
                "label": "Value-chain emissions",
                "reason": scope_3_rule["reason"],
            },
        ],
        "combined_total": None,
        "issues": issues,
        "status": "passed_with_warnings",
        "audit": {
            "status": "passed_with_warnings",
            "checks": {
                "method_package_content_pinned": True,
                "carbon_result_hash_valid": True,
                "period_energy_total_hash_valid": True,
                "electricity_result_hash_valid": True,
                "carbon_snapshots_exact": True,
                "scope_1_period_scaling_explicit": True,
                "electricity_application_exact": True,
                "scope_1_exact_contributions": True,
                "scope_2_reference_semantics_explicit": True,
                "scope_3_not_inferred": True,
                "unlike_result_semantics_not_summed": True,
            },
            "limitations": list(
                (manifest.get("validation_rules") or {}).get("limitations") or []
            ),
        },
    }
    return {**content, "content_sha256": canonical_json_sha256(content)}
