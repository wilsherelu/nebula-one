"""Review an exact direct CBAM term alongside pending precursor electricity."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


def build_cbam_partial_review(*, snapshot: dict[str, Any], direct: dict[str, Any],
                              method_ref: str, method_hash: str, manifest: dict[str, Any],
                              factor_package: dict[str, Any] | None = None,
                              condition_declarations: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    formula = manifest.get("formula_graph") or {}
    calculation = formula.get("calculation")
    legacy = calculation == "direct_component_plus_non_annex_ii_precursor_indirect_pending"
    schema = (manifest.get("output_schema") or {}).get("schema_version")
    if (legacy and schema != "nebula_one.cbam.partial-review.v1"
            or not legacy and (calculation != "direct_component_plus_eligible_precursor_indirect_v1"
                               or schema != "nebula_one.cbam.partial-review.v2")):
        raise DomainError(code="CBAM_PARTIAL_METHOD_INVALID", message="partial CBAM method has another calculation contract", status_code=422)
    if legacy and (factor_package or condition_declarations):
        raise DomainError(code="CBAM_PARTIAL_METHOD_INVALID", message="historical review method does not accept factor evidence", status_code=422)
    source = formula.get("source_direct_method") or {}
    if (direct.get("method_package") or {}).get("ref") != source.get("reference") or (
        direct.get("method_package") or {}).get("content_sha256") != source.get("content_sha256"):
        raise DomainError(code="CBAM_PARTIAL_DIRECT_METHOD_MISMATCH", message="direct term does not use the pinned historical method", status_code=422)
    if (direct.get("source_snapshot") or {}).get("id") != snapshot["id"] or (
        direct.get("source_snapshot") or {}).get("content_sha256") != snapshot["content_sha256"]:
        raise DomainError(code="CBAM_PARTIAL_SNAPSHOT_MISMATCH", message="direct term and electricity activity have different frozen snapshots", status_code=422)
    if direct.get("status") not in {"trial_passed", "partial_calculated"} or direct.get("schema_version") != "nebula_one.cbam.trial.v2":
        raise DomainError(code="CBAM_PARTIAL_DIRECT_UNVERIFIED", message="source direct term did not pass its historical trial", status_code=422)
    rule = formula.get("indirect_activity") or {}
    exchange_id = rule.get("consumer_exchange_id")
    rows = [item for item in snapshot["scaled_technosphere_exchanges"] if item.get("exchange_id") == exchange_id]
    if len(rows) != 1 or rows[0].get("process_id") != rule.get("process_uuid") or rows[0].get("flow_uuid") != rule.get("flow_uuid") or rows[0].get("unit") != rule.get("source_unit") or rows[0].get("direction") != "input":
        raise DomainError(code="CBAM_PARTIAL_ELECTRICITY_IDENTITY_MISMATCH", message="sintering electricity activity is absent or has a different identity", status_code=422)
    excluded = set(formula.get("excluded_final_good_electricity_exchange_ids") or [])
    if exchange_id in excluded:
        raise DomainError(code="CBAM_PARTIAL_ELECTRICITY_OVERLAP", message="the same electricity input is both applicable and excluded", status_code=422)
    amount = Decimal(str(rows[0]["amount"]))
    product_kg = Decimal(str((direct.get("activity_level") or {}).get("source_value")))
    mj_per_mwh = Decimal(str(rule.get("mj_per_mwh")))
    if amount <= 0 or product_kg <= 0 or mj_per_mwh != Decimal("3600"):
        raise DomainError(code="CBAM_PARTIAL_ACTIVITY_INVALID", message="electricity and product activity require positive values and the exact MJ/MWh conversion", status_code=422)
    activity_per_t = amount / product_kg * Decimal("1000") / mj_per_mwh
    specific = direct.get("specific_embedded_emissions") or {}
    # The partial source exposes its calculated component separately from the
    # unavailable complete value. Historical sources retain their original field.
    direct_value = Decimal(str(specific.get("partial_value") if direct.get("status") == "partial_calculated" else specific.get("value")))
    if direct_value < 0 or (direct.get("specific_embedded_emissions") or {}).get("unit") != "t CO2e/t product":
        raise DomainError(code="CBAM_PARTIAL_DIRECT_UNIT_INVALID", message="historical direct term has another unit", status_code=422)
    factor_value = None
    eligible_factor = None
    if factor_package:
        factor = (factor_package.get("manifest") or {}).get("factor") or {}
        source_evidence = factor.get("source_evidence") or {}
        period = direct.get("reporting_period") or {}
        try:
            factor_value = Decimal(str(factor.get("value")))
            period_start = date.fromisoformat(period["start_date"])
            period_end = date.fromisoformat(period["end_date"])
            valid_from = date.fromisoformat(factor_package["valid_from"])
            valid_to = date.fromisoformat(factor_package["valid_to"])
        except (InvalidOperation, ValueError, KeyError, TypeError) as exc:
            raise DomainError(code="CBAM_ELECTRICITY_FACTOR_INVALID", message="factor or reporting dates are invalid", status_code=422) from exc
        if (not factor_value.is_finite() or factor_value < 0
                or factor.get("unit") != "t CO2e/MWh"
                or factor.get("good_cn_code") != (manifest.get("boundary_schema") or {}).get("good_cn_code")
                or factor.get("process_uuid") != rule.get("process_uuid")
                or factor.get("flow_uuid") != rule.get("flow_uuid")
                or factor.get("applies_to") != rule.get("applies_to")
                or factor.get("boundary") != (manifest.get("classification_rules") or {}).get("factor_boundary")
                or factor.get("eligible_partial_method_ref") != method_ref
                or not source_evidence.get("document_id")
                or not re.fullmatch(r"[0-9a-f]{64}", str(source_evidence.get("sha256", "")))
                or valid_from > period_start or valid_to < period_end):
            raise DomainError(code="CBAM_ELECTRICITY_FACTOR_INAPPLICABLE", message="factor does not match the method, activity, evidence or reporting period", status_code=422)
        eligible_factor = {"value": str(factor_value), "unit": "t CO2e/MWh",
                           "package_reference": factor_package["reference"],
                           "package_content_sha256": factor_package["content_sha256"],
                           "source_evidence": source_evidence}
    declared = condition_declarations or {}
    required = formula.get("required_condition_keys") or []
    condition_rules = formula.get("condition_rules") or {}
    if not legacy and (not isinstance(required, list) or not required or set(declared) - set(required)):
        raise DomainError(code="CBAM_PARTIAL_CONDITIONS_INVALID", message="method condition declarations are invalid", status_code=422)
    if not legacy and declared and (not isinstance(condition_rules, dict)
                                or set(condition_rules) != set(required)):
        raise DomainError(code="CBAM_PARTIAL_CONDITIONS_INVALID", message="method does not specify required scenario statuses", status_code=422)
    for key, evidence in declared.items():
        rule_for_key = condition_rules.get(key)
        statuses = rule_for_key.get("allowed_statuses") if isinstance(rule_for_key, dict) else None
        if (not isinstance(statuses, list) or not statuses
                or any(not isinstance(item, dict) or not isinstance(item.get("code"), str)
                       for item in statuses)):
            raise DomainError(code="CBAM_PARTIAL_CONDITIONS_INVALID", message=f"condition {key} has no versioned allowed statuses", status_code=422)
        allowed = {item["code"] for item in statuses}
        if (not isinstance(evidence, dict) or evidence.get("status") not in allowed
                or not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("evidence_sha256", "")))):
            raise DomainError(code="CBAM_PARTIAL_CONDITIONS_INVALID", message=f"condition {key} needs a status and exact evidence hash", status_code=422)
    indirect_value = activity_per_t * factor_value if factor_value is not None else None
    conditions_complete = bool(required) and set(condition_rules) == set(required) and all(key in declared for key in required)
    total_value = direct_value + indirect_value if indirect_value is not None and conditions_complete else None
    missing = (["eligible_sinter_electricity_factor"] if factor_value is None else [])
    missing.extend(key for key in required if key not in declared)
    source_stream_coverage = manifest.get('source_stream_coverage') or []
    uncovered = [row['item'] for row in source_stream_coverage
                 if row.get('state') not in ('modelled', 'not_applicable_with_basis')]
    missing.extend(uncovered)
    if uncovered:
        total_value = None
    if legacy:
        missing = ["eligible_sinter_electricity_factor", "article_4_9_same_installation_no_sale_no_other_use_evidence",
                   "waste_gas_attribution", "flue_gas_cleaning_declaration"]
    result = {
        "schema_version": schema,
        "method_package": {"reference": method_ref, "content_sha256": method_hash},
        "source_snapshot": {"id": snapshot["id"], "content_sha256": snapshot["content_sha256"],
                            "system_revision_id": snapshot["system_revision_id"]},
        "source_direct_method": source,
        "source_direct_result_sha256": direct["content_sha256"],
        "reporting_period": direct["reporting_period"],
        "components": {
            "direct": {"value": str(direct_value), "unit": "t CO2e/t product",
                       "status": ("reviewed_graph_component_not_complete_total"
                                  if manifest.get("reviewed_graph_identity_sha256")
                                  else "historical_calculated_component_not_complete_total"),
                       "exchanges": [{"exchange_id": item["exchange_id"],
                                      "amount": item.get("amount"), "unit": item.get("unit"),
                                      "clause": item.get("clause")}
                                     for item in (direct.get("coverage") or {}).get("exchanges", [])
                                     if item.get("disposition") == "counted"]},
            "sinter_precursor_indirect": {
                "electricity_activity": {"value": str(activity_per_t), "unit": "MWh/t product",
                                         "source_value": str(amount), "source_unit": "MJ",
                                         "consumer_exchange_id": exchange_id},
                "eligible_factor": eligible_factor, "value": str(indirect_value) if indirect_value is not None else None,
                "unit": "t CO2e/t product",
                "status": "calculated_from_pinned_factor" if indirect_value is not None else "eligible_electricity_factor_required",
                "formula": formula.get("indirect_term"),
            },
        },
        "specific_embedded_emissions": {"value": str(total_value) if total_value is not None else None,
                                        "unit": "t CO2e/t product",
                                        "status": "conditional_calculated" if total_value is not None else "not_calculated",
                                        "partial_direct_value": str(direct_value)},
        "coverage": {"status": "declared_boundary_calculated" if total_value is not None else "partial",
                     "missing": missing, "condition_declarations": declared,
                     "source_streams": source_stream_coverage,
                     "external_precursor_status": "declared" if "external_precursor" in declared else "not_demonstrated_by_this_model",
                     "default_values": "published_but_not_connected"},
        "claim_boundary": {"trial_only": True, "complete_cbam_total": False,
                           "not_a_cbam_declaration": True, "no_conservative_upper_bound_claim": True},
    }
    if not legacy:
        result["claim_boundary"]["conditional_selected_boundary_total"] = total_value is not None
    if legacy:
        result["coverage"].pop("condition_declarations")
    project_receipts = (snapshot.get("provider_receipt") or {}).get("project_background_process_receipts") or []
    selected = [item for item in project_receipts
                if (item.get("pin") or {}).get("consumer_exchange_id") == exchange_id]
    if len(selected) > 1:
        raise DomainError(code="CBAM_USER_SUPPLY_AMBIGUOUS", message="multiple user supply receipts claim the sinter input", status_code=422)
    if selected:
        supplier = selected[0]
        node_id = supplier.get("expanded_node_id")
        source_process = supplier.get("source_process_uuid")
        co2_flows = {item.get("flow_identity", {}).get("flow_uuid") for item in
                     (direct.get("attributed_emissions") or {}).get("direct", {}).get("exchanges", [])}
        emissions = [item for item in snapshot.get("scaled_elementary_exchanges") or []
                     if item.get("process_id") == source_process and
                     str(item.get("exchange_id") or "").startswith(f"{node_id}::") and
                     item.get("flow_uuid") in co2_flows and item.get("direction") == "output" and
                     item.get("unit") == "kg"]
        receipts = (snapshot.get("provider_receipt") or {}).get("elementary_flow_receipts") or []
        if (not source_process or not node_id or not supplier.get("source_graph_hash") or
                len(emissions) != 1 or
                not any(item.get("exchange_id") == emissions[0]["exchange_id"] and
                        item.get("content_hash") and item.get("snapshot_hash") for item in receipts)):
            raise DomainError(code="CBAM_USER_SUPPLY_EVIDENCE_INCOMPLETE",
                              message="the user supply CO2 result lacks exact source and elementary Flow evidence", status_code=422)
        supplier_kg = Decimal(str(emissions[0]["amount"]))
        if not supplier_kg.is_finite() or supplier_kg < 0:
            raise DomainError(code="CBAM_USER_SUPPLY_AMOUNT_INVALID", message="user supply CO2 amount is invalid", status_code=422)
        result["components"]["user_supply_electricity_trial"] = {
            "value": str(supplier_kg / product_kg), "unit": "t CO2/t product",
            "source_amount": str(supplier_kg), "source_unit": "kg CO2",
            "source_project_id": supplier["pin"]["project_id"],
            "source_version": supplier["pin"]["version"],
            "source_graph_hash": supplier["source_graph_hash"],
            "exchange_id": emissions[0]["exchange_id"],
            "status": "user_declared_trial_not_eligible_cbam_factor",
        }
    result["content_sha256"] = canonical_json_sha256(result)
    return result
