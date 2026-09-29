"""Period inventory over one solved model and independently evidenced supplier activities."""
from __future__ import annotations

from math import isclose, isfinite
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


def _positive(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or float(value) <= 0:
        raise DomainError(code="ORGANIZATION_PERIOD_ACTIVITY_INVALID", message=f"{name} must be finite and positive", status_code=422)
    return float(value)


def build_organization_period(
    *, application_id: str, revision_id: str, snapshot_id: str, snapshot_hash: str,
    period: dict[str, Any], facility: str, controlled_process_ids: list[str],
    model_process_ids: list[str], baseline_output: float, period_output: float,
    output_unit: str, foreground_value: float, background_value: float,
    climate_unit: str, native_method: dict[str, str], method_ref: str,
    method_hash: str, manifest: dict[str, Any], mapped_exchange_ids: list[str],
    unmodelled_inputs: dict[str, dict[str, Any]],
    scope3_activities: list[dict[str, Any]], category_statuses: dict[str, str],
) -> dict[str, Any]:
    rules = manifest.get("classification_rules") or {}
    categories = rules.get("scope3_categories") or {}
    purchased = rules.get("scope2_purchase_exchange_ids") or []
    if (manifest.get("output_schema") or {}).get("schema_version") != "nebula_one.organization-period.v1":
        raise DomainError(code="ORGANIZATION_PERIOD_METHOD_INVALID", message="organization period method has another output contract", status_code=422)
    if not facility.strip() or sorted(set(controlled_process_ids)) != sorted(set(model_process_ids)) or len(controlled_process_ids) != len(set(controlled_process_ids)):
        raise DomainError(code="ORGANIZATION_CONTROL_BOUNDARY_UNSUPPORTED", message="the current native answer requires one facility controlling every solved foreground process", status_code=422)
    if sorted(mapped_exchange_ids) != sorted(purchased) or len(mapped_exchange_ids) != len(set(mapped_exchange_ids)):
        raise DomainError(code="ORGANIZATION_SCOPE2_SOURCE_MISMATCH", message="mapped background exchanges do not match this method's purchased energy boundary", status_code=422)
    if rules.get("scope2_allocation") != "generation_only_evidence_required":
        raise DomainError(code="ORGANIZATION_SCOPE2_METHOD_UNSUPPORTED", message="method must require separately evidenced generation-only Scope 2", status_code=422)
    if not isinstance(categories, dict) or not categories:
        raise DomainError(code="ORGANIZATION_SCOPE3_RULES_MISSING", message="method package must declare Scope 3 categories", status_code=422)
    scale = _positive(period_output, "period output") / _positive(baseline_output, "baseline output")
    if not all(isinstance(value, (float, int)) and isfinite(float(value)) for value in (foreground_value, background_value)):
        raise DomainError(code="ORGANIZATION_CLIMATE_VALUE_INVALID", message="native climate domains must be finite", status_code=422)
    if climate_unit != "kg CO2-Eq":
        raise DomainError(code="ORGANIZATION_CLIMATE_UNIT_UNSUPPORTED", message="organization method requires kg CO2-Eq", status_code=422)
    seen = set()
    counted_exchanges = set()
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in categories}
    for activity in scope3_activities:
        activity_id = activity["activity_id"]
        category = activity["category"]
        rule = categories.get(category)
        if (activity_id in seen or activity["consumer_exchange_id"] in counted_exchanges
                or not isinstance(rule, dict) or rule.get("source_type") != "supplier_statement_outside_model"):
            raise DomainError(code="ORGANIZATION_SCOPE3_CLASSIFICATION_INVALID", message="supplier activity is duplicated or not allowed by the method", status_code=422)
        seen.add(activity_id)
        counted_exchanges.add(activity["consumer_exchange_id"])
        if (activity["consumer_exchange_id"] not in rule.get("eligible_consumer_exchange_ids", [])
                or activity["consumer_exchange_id"] in mapped_exchange_ids
                or activity["factor_boundary"] != rule.get("factor_boundary")):
            raise DomainError(code="ORGANIZATION_SCOPE3_MODEL_OVERLAP", message="supplier activity is not an eligible unmodelled input", status_code=422)
        source_input = unmodelled_inputs.get(activity["consumer_exchange_id"])
        if (source_input is None or source_input.get("unit") != activity["activity_unit"]
                or not isclose(float(source_input["amount"]) * scale,
                               float(activity["quantity"]), rel_tol=1e-8, abs_tol=1e-9)):
            raise DomainError(code="ORGANIZATION_SCOPE3_ACTIVITY_MISMATCH", message="supplier quantity does not match the solved input scaled to the reporting period", status_code=422)
        if not activity["outside_model"] or not activity["evidence_sha256"] or not activity["factor_version"]:
            raise DomainError(code="ORGANIZATION_SCOPE3_EVIDENCE_REQUIRED", message="supplier factor must be versioned, evidenced and outside the solved model", status_code=422)
        quantity = _positive(activity["quantity"], "supplier activity quantity")
        factor = _positive(activity["factor_value"], "supplier factor")
        if activity["factor_unit"] != f"kg CO2-Eq/{activity['activity_unit']}":
            raise DomainError(code="ORGANIZATION_SCOPE3_FACTOR_UNIT_MISMATCH", message="supplier factor unit does not match its activity unit", status_code=422)
        grouped[category].append({**activity, "emissions": {"value": quantity * factor, "unit": climate_unit}})
    unknown_status = set(category_statuses) - set(categories)
    if unknown_status:
        raise DomainError(code="ORGANIZATION_SCOPE3_CATEGORY_UNKNOWN", message="scope 3 status names an unknown method category", status_code=422,
                          details={"categories": sorted(unknown_status)})
    scope3 = []
    for key, rule in categories.items():
        items = grouped[key]
        status = "calculated" if items else category_statuses.get(key, "missing_activity")
        if items and category_statuses.get(key) in ("not_applicable", "excluded_by_boundary"):
            raise DomainError(code="ORGANIZATION_SCOPE3_STATUS_CONFLICT", message="a calculated category cannot be excluded", status_code=422)
        if not items and status not in ("missing_activity", "not_applicable", "excluded_by_boundary"):
            raise DomainError(code="ORGANIZATION_SCOPE3_STATUS_INVALID", message="scope 3 category has an invalid status", status_code=422)
        scope3.append({"category": key, "name": rule.get("name", key), "status": status,
                       "value": sum(item["emissions"]["value"] for item in items) if items else None,
                       "unit": climate_unit, "activities": items})
    scope3_total = sum(item["value"] for item in scope3 if item["value"] is not None)
    incomplete = [item["category"] for item in scope3 if item["status"] == "missing_activity"]
    proxies = [item["activity_id"] for items in grouped.values() for item in items
               if item["evidence_role"] == "demonstration_proxy"]
    result: dict[str, Any] = {
        "schema_version": "nebula_one.organization-period.v1",
        "application_id": application_id, "system_revision_id": revision_id,
        "source_snapshot": {"id": snapshot_id, "content_sha256": snapshot_hash},
        "reporting_period": period,
        "organizational_boundary": {"facility": facility, "controlled_process_ids": sorted(controlled_process_ids),
                                    "control_approach": "operational_control_of_solved_foreground"},
        "activity_basis": {"baseline_output": baseline_output, "period_output": period_output,
                           "output_unit": output_unit, "scale_factor": scale},
        "method_package": {"reference": method_ref, "content_sha256": method_hash},
        "native_climate_method": native_method,
        "scopes": {"scope_1": {"value": float(foreground_value) * scale, "unit": climate_unit,
                               "status": "model_boundary_direct"},
                   "scope_2": {"value": None, "unit": climate_unit,
                               "status": "missing_generation_only_evidence"},
                   "scope_3": {"value": scope3_total if any(item["status"] == "calculated" for item in scope3) else None,
                               "unit": climate_unit, "status": "partial" if incomplete else "configured_categories",
                               "categories": scope3}},
        "unclassified_background_reference": {"value": float(background_value) * scale,
                                              "unit": climate_unit,
                                              "status": "lifecycle_electricity_background_not_allocated_to_scopes"},
        "combined_total": None,
        "coverage": {"status": "partial",
                     "missing_scope2_generation_evidence": True,
                     "missing_activity_categories": incomplete,
                     "demonstration_proxy_activity_ids": proxies,
                     "not_a_complete_corporate_inventory": True},
    }
    result["content_sha256"] = canonical_json_sha256(result)
    return result
