"""A versioned organization lifecycle carbon grouping over one frozen model."""
from __future__ import annotations

from math import isclose, isfinite
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


def build_organization_lifecycle(*, application_id: str, revision_id: str,
                                 snapshot_id: str, snapshot_hash: str, period: dict[str, Any],
                                 facility: str, controlled_process_ids: list[str],
                                 model_process_ids: list[str], input_basis: str,
                                 baseline_output: float, period_output: float,
                                 foreground_value: float, background_value: float,
                                 climate_unit: str, native_method: dict[str, str],
                                 method_ref: str, method_hash: str, manifest: dict[str, Any],
                                 mapped_exchange_ids: list[str],
                                 external_exchanges: dict[str, dict[str, Any]],
                                 activities: list[dict[str, Any]],
                                 climate_source: dict[str, Any] | None = None) -> dict[str, Any]:
    output_schema = (manifest.get("output_schema") or {}).get("schema_version")
    if (output_schema not in {"nebula_one.organization-lifecycle-carbon.v1", "nebula_one.organization-lifecycle-carbon.v2"}
            or (output_schema.endswith(".v2")) != (climate_source is not None)):
        raise DomainError(code="ORGANIZATION_LIFECYCLE_METHOD_INVALID", message="method has another output contract", status_code=422)
    rules = manifest.get("classification_rules") or {}
    expected_energy = rules.get("energy_purchase_exchange_ids") or []
    energy_types = rules.get("energy_purchase_types") or {}
    allowed_energy_types = set(rules.get("allowed_lc_scope_2_types") or [])
    categories = rules.get("other_value_chain_categories") or {}
    explicit_boundary = rules.get("category_boundary_contract") == "explicit_selection_v1"
    if (not facility.strip() or sorted(controlled_process_ids) != sorted(model_process_ids)
            or len(set(controlled_process_ids)) != len(controlled_process_ids)):
        raise DomainError(code="ORGANIZATION_LIFECYCLE_CONTROL_INVALID", message="controlled processes must match the solved foreground", status_code=422)
    selection = rules.get("energy_path_selection")
    energy_paths_match = ((bool(mapped_exchange_ids) and set(mapped_exchange_ids) <= set(expected_energy))
                          if selection == "nonempty_declared_subset_v1" else
                          (set(mapped_exchange_ids) <= set(expected_energy))
                          if selection == "declared_subset_v1" else
                          sorted(mapped_exchange_ids) == sorted(expected_energy))
    if (not energy_paths_match
            or len(set(mapped_exchange_ids)) != len(mapped_exchange_ids)
            or not allowed_energy_types
            or any(energy_types.get(exchange_id) not in allowed_energy_types for exchange_id in mapped_exchange_ids)):
        raise DomainError(code="ORGANIZATION_LIFECYCLE_ENERGY_PATH_MISMATCH", message="native background contains a path outside the method's purchased energy group", status_code=422)
    if not isinstance(categories, dict) or not categories:
        raise DomainError(code="ORGANIZATION_LIFECYCLE_CATEGORIES_MISSING", message="method declares no other value-chain categories", status_code=422)
    if (not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                and isfinite(value) and value > 0 for value in (baseline_output, period_output))
            or climate_unit != "kg CO2-Eq"):
        raise DomainError(code="ORGANIZATION_LIFECYCLE_BASIS_INVALID", message="product basis or climate unit is invalid", status_code=422)
    if input_basis in {"annual_total", "current_model_total"}:
        if not isclose(period_output, baseline_output, rel_tol=1e-9, abs_tol=1e-9):
            raise DomainError(code="ORGANIZATION_LIFECYCLE_ANNUAL_RESCALE" if input_basis == "annual_total" else "ORGANIZATION_LIFECYCLE_MODEL_RESCALE", message="total basis must match the frozen product output", status_code=422)
        scale = 1.0
    elif input_basis == "per_unit_product":
        scale = period_output / baseline_output
    else:
        raise DomainError(code="ORGANIZATION_LIFECYCLE_INPUT_BASIS_INVALID", message="input basis must be annual total or per unit product", status_code=422)
    if not all(isfinite(value) for value in (foreground_value, background_value)):
        raise DomainError(code="ORGANIZATION_LIFECYCLE_CLIMATE_INVALID", message="climate domains must be finite", status_code=422)
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in categories}
    proxy_rows: dict[str, list[dict[str, Any]]] = {key: [] for key in categories}
    receipt_grouping = rules.get("non_energy_path_source") == "project_background_category_receipts_v1"
    receipt_rows = (climate_source or {}).get("category_suppliers", []) if receipt_grouping else []
    solved_ports = {row["consumer_exchange_id"] for row in (climate_source or {}).get("suppliers", [])}
    seen: set[str] = set(solved_ports) if receipt_grouping else set()
    for item in activities:
        category = item["category"]
        rule = categories.get(category)
        exchange_id = item["consumer_exchange_id"]
        source = external_exchanges.get(exchange_id)
        if (not isinstance(rule, dict) or exchange_id not in rule.get("eligible_consumer_exchange_ids", [])
                or exchange_id in mapped_exchange_ids or exchange_id in seen or source is None
                or source.get("direction") != rule.get("direction")
                or item["factor_boundary"] != rule.get("factor_boundary")):
            raise DomainError(code="ORGANIZATION_LIFECYCLE_OVERLAP", message="other value-chain activity overlaps a solved path or is not declared", status_code=422)
        seen.add(exchange_id)
        quantity = float(item["quantity"])
        factor = float(item["factor_value"])
        if (source.get("unit") != item["activity_unit"]
                or not isclose(float(source["amount"]) * scale, quantity, rel_tol=1e-8, abs_tol=1e-9)
                or not isfinite(factor) or factor <= 0
                or item["factor_unit"] != f"kg CO2-Eq/{item['activity_unit']}"
                or not item["outside_model"] or not item["evidence_sha256"] or not item["factor_version"]):
            raise DomainError(code="ORGANIZATION_LIFECYCLE_FACTOR_INVALID", message="activity or factor lacks an exact source, unit or boundary", status_code=422)
        row = {**item, "emissions": {"value": quantity * factor, "unit": climate_unit}}
        if item["evidence_role"] == "demonstration_proxy":
            proxy_rows[category].append(row)
        else:
            if (item.get("factor_method_id") != native_method.get("id")
                    or item.get("factor_method_version") != native_method.get("version")
                    or item.get("factor_method_sha256") != native_method.get("content_sha256")
                    or item.get("factor_reference_product") != source.get("flow_uuid")):
                raise DomainError(code="ORGANIZATION_LIFECYCLE_METHOD_MISMATCH", message="supplier factor method or reference product differs from the native climate method and input flow", status_code=422)
            grouped[category].append(row)
    category_rows = []
    for key, rule in categories.items():
        boundary_status = rule.get("boundary_status") if explicit_boundary else "selected"
        if explicit_boundary and (boundary_status not in {"selected", "not_in_boundary", "required_missing"}
                                  or (boundary_status == "not_in_boundary" and rule.get("eligible_consumer_exchange_ids"))
                                  or (boundary_status == "selected" and not rule.get("eligible_consumer_exchange_ids"))):
            raise DomainError(code="ORGANIZATION_LIFECYCLE_BOUNDARY_INVALID", message="category needs an explicit, consistent boundary status", status_code=422)
        expected = [exchange_id for exchange_id in rule.get("eligible_consumer_exchange_ids", [])
                    if exchange_id in external_exchanges]
        supplied = [row for row in receipt_rows if row["category"] == key]
        if (len({row["consumer_exchange_id"] for row in supplied}) != len(supplied)
                or any(row["consumer_exchange_id"] not in expected
                       or external_exchanges[row["consumer_exchange_id"]].get("direction") != rule.get("direction")
                       for row in supplied)):
            raise DomainError(code="ORGANIZATION_LIFECYCLE_OVERLAP", message="category receipt is duplicated or outside the selected model boundary", status_code=422)
        covered_ports = {row["consumer_exchange_id"] for row in grouped[key]}
        covered_ports.update(row["consumer_exchange_id"] for row in supplied if row["status"] == "calculated")
        values = [row["emissions"]["value"] for row in grouped[key]] + [row["contribution_value"] * scale
            for row in supplied if row["contribution_value"] is not None]
        status = ("not_in_boundary" if boundary_status == "not_in_boundary" else
                  "required_missing" if boundary_status == "required_missing" else
                  "proxy_reference_only" if proxy_rows[key] and not values else
                  "missing_activity" if not values else
                  "partial_activity" if (set(expected) - covered_ports if receipt_grouping else len(grouped[key]) < len(expected)) else "calculated")
        category_rows.append({"category": key, "name": rule.get("name", key),
                              "status": status,
                              **({"boundary_status": boundary_status} if explicit_boundary else {}),
                              "value": sum(values) if values else None,
                              "activities": grouped[key],
                              "proxy_reference_value": sum(row["emissions"]["value"] for row in proxy_rows[key]) if proxy_rows[key] else None,
                              "proxy_activities": proxy_rows[key]})
        if receipt_grouping:
            category_rows[-1].update({"supply_receipts": [{**row, "contribution_value": row["contribution_value"] * scale
                if row["contribution_value"] is not None else None} for row in supplied],
                "missing_exchange_ids": sorted(set(expected) - covered_ports)})
    missing = [row["category"] for row in category_rows if row["status"] not in {"calculated", "not_in_boundary"}]
    excluded = [row["category"] for row in category_rows if row["status"] == "not_in_boundary"]
    proxies = [row["activity_id"] for items in proxy_rows.values() for row in items]
    missing_energy_paths = sorted(set(expected_energy) - set(mapped_exchange_ids))
    incomplete_energy = selection == "declared_subset_v1" and bool(missing_energy_paths)
    result = {
        "schema_version": output_schema,
        "application_id": application_id, "system_revision_id": revision_id,
        "source_snapshot": {"id": snapshot_id, "content_sha256": snapshot_hash},
        "reporting_period": period, "facility": facility,
        "method_package": {"reference": method_ref, "content_sha256": method_hash},
        "activity_basis": {"mode": input_basis, "baseline_output": baseline_output,
                           "period_output": period_output, "unit": "kg", "scale_factor": scale},
        "organizational_boundary": {"controlled_process_ids": sorted(controlled_process_ids),
                                    "mode": "controlled_foreground_plus_declared_external_paths"},
        "groups": {
            "on_site_direct": {"value": foreground_value * scale, "unit": climate_unit,
                               "label": "范围 1：厂内直接排放",
                               "status": "calculated_from_controlled_foreground"},
            "purchased_energy_lifecycle": {"value": background_value * scale if mapped_exchange_ids else None, "unit": climate_unit,
                                           "label": "LC-Scope 2：外购二次能源生命周期排放",
                                           "status": "calculated_from_exclusive_energy_background_paths" if mapped_exchange_ids else "missing_energy_path",
                                           "exchange_ids": sorted(mapped_exchange_ids)},
            "other_value_chain": {"value": sum(row["value"] for row in category_rows if row["value"] is not None)
                                  if any(row["value"] is not None for row in category_rows) else None,
                                  "unit": climate_unit, "label": "LC-Scope 3：其他价值链排放", "categories": category_rows,
                                  "status": "partial" if missing else "configured_categories"},
        },
        "combined_total": None if missing or proxies or incomplete_energy or not mapped_exchange_ids else foreground_value * scale + background_value * scale
                          + sum(row["value"] for row in category_rows if row["value"] is not None),
        "coverage": {"status": "partial" if missing or proxies or incomplete_energy or not mapped_exchange_ids else "configured_boundary_calculated",
                     "missing_categories": missing, "not_in_boundary_categories": excluded,
                     "demonstration_proxy_activity_ids": proxies,
                     "not_a_complete_lifecycle_inventory": True,
                     "not_ghg_protocol_scopes": True},
    }
    if climate_source is None:
        result["native_climate_method"] = native_method
    else:
        result["climate_source"] = climate_source
    if input_basis == "current_model_total":
        result["reporting_period"]["role"] = "project_context_not_annual_inventory"
    if (climate_source or {}).get("unassigned_suppliers"):
        result["combined_total"] = None
        result["coverage"]["status"] = "partial"
        result["coverage"]["unassigned_supplier_exchange_ids"] = [row["consumer_exchange_id"]
            for row in climate_source["unassigned_suppliers"]]
    if receipt_grouping and any(row["status"] != "calculated" for row in (climate_source or {}).get("energy_suppliers", [])):
        result["combined_total"] = None
        result["coverage"]["status"] = "partial"
        result["groups"]["purchased_energy_lifecycle"]["status"] = "partial_activity"
    if selection == "declared_subset_v1":
        result["coverage"]["missing_energy_paths"] = missing_energy_paths
    if not explicit_boundary:
        result["coverage"].pop("not_in_boundary_categories")
    result["content_sha256"] = canonical_json_sha256(result)
    return result
