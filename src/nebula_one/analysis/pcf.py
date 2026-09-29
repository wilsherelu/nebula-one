from __future__ import annotations

import math
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .pcf_contributions import build_pcf_contribution_analysis


def _required_text(source: dict[str, Any], key: str, *, context: str) -> str:
    value = str(source.get(key) or "").strip()
    if not value:
        raise DomainError(
            code="PCF_METHOD_PACKAGE_INVALID",
            message=f"PCF method package requires {context}.{key}",
            status_code=422,
        )
    return value


def _functional_unit(parameters: dict[str, Any]) -> dict[str, Any]:
    demand = parameters.get("demand")
    if not isinstance(demand, list) or len(demand) != 1 or not isinstance(demand[0], dict):
        raise DomainError(
            code="PCF_FUNCTIONAL_UNIT_INVALID",
            message="PCF requires exactly one structured product demand",
            status_code=422,
        )
    functional_unit = dict(demand[0])
    required = (
        "reference_flow_uuid",
        "amount",
        "unit",
        "unit_group_uuid",
        "unit_group_version",
    )
    missing = [key for key in required if functional_unit.get(key) in (None, "")]
    amount = functional_unit.get("amount")
    if missing or isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise DomainError(
            code="PCF_FUNCTIONAL_UNIT_INVALID",
            message="PCF product demand lacks an exact flow, quantity, or unit identity",
            status_code=422,
            details={"missing": missing},
        )
    if not math.isfinite(float(amount)) or float(amount) <= 0:
        raise DomainError(
            code="PCF_FUNCTIONAL_UNIT_INVALID",
            message="PCF product demand amount must be finite and greater than zero",
            status_code=422,
        )
    functional_unit["amount"] = float(amount)
    return functional_unit


def build_product_pcf(
    *,
    solved_snapshot_id: str,
    solved_snapshot_sha256: str,
    lcia_results: dict[str, Any],
    provider_receipt: dict[str, Any],
    source_run_parameters: dict[str, Any],
    system_revision_id: str,
    model_graph_sha256: str,
    scaled_elementary_exchanges: list[dict[str, Any]],
    method_package_ref: str,
    method_package_sha256: str,
    method_package_kind: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if method_package_kind != "product_carbon_footprint":
        raise DomainError(
            code="PCF_METHOD_PACKAGE_KIND_MISMATCH",
            message="pcf.product.v1 requires a product_carbon_footprint method package",
            status_code=422,
            details={"package_kind": method_package_kind},
        )
    formula = manifest.get("formula_graph")
    boundary = manifest.get("boundary_schema")
    output_schema = manifest.get("output_schema")
    if not all(isinstance(item, dict) for item in (formula, boundary, output_schema)):
        raise DomainError(
            code="PCF_METHOD_PACKAGE_INVALID",
            message="PCF method package lacks formula, boundary, or output definitions",
            status_code=422,
        )
    lcia_method = _required_text(formula, "lcia_method", context="formula_graph")
    indicator_key = _required_text(
        formula, "total_indicator_key", context="formula_graph"
    )
    expected_unit = _required_text(formula, "result_unit", context="formula_graph")
    claim_scope = _required_text(boundary, "claim_scope", context="boundary_schema")
    result_schema = _required_text(
        output_schema, "schema_version", context="output_schema"
    )
    if result_schema != "nebula_one.pcf.product.v1":
        raise DomainError(
            code="PCF_METHOD_PACKAGE_INVALID",
            message="PCF method package output schema is not supported",
            status_code=422,
            details={"schema_version": result_schema},
        )
    if claim_scope != "foreground_boundary":
        raise DomainError(
            code="PCF_CLAIM_SCOPE_UNSUPPORTED",
            message="pcf.product.v1 currently supports foreground_boundary claims only",
            status_code=422,
            details={"claim_scope": claim_scope},
        )

    functional_unit = _functional_unit(source_run_parameters)
    requested_methods = source_run_parameters.get("lcia_methods")
    if not isinstance(requested_methods, list) or lcia_method not in requested_methods:
        raise DomainError(
            code="PCF_SOURCE_METHOD_NOT_REQUESTED",
            message="source solve did not request the PCF package LCIA method",
            status_code=422,
            details={"required_method": lcia_method},
        )
    if not isinstance(lcia_results, dict) or not lcia_results:
        # A native background climate solve answers with its own climate object only and returns no
        # LCIA object at all, so the honest cause is "nothing was characterised" rather than a
        # method mismatch on an empty dictionary.
        raise DomainError(
            code="PCF_LCIA_RESULT_REQUIRED",
            message="solved snapshot has no LCIA result object",
            status_code=422,
        )
    actual_method = str(lcia_results.get("method") or "").strip()
    lcia_database_release = str(lcia_results.get("database_release") or "").strip()
    receipt_database_release = str(
        provider_receipt.get("database_release") or ""
    ).strip()
    indicators = lcia_results.get("indicator_results")
    if actual_method != lcia_method or not isinstance(indicators, list):
        raise DomainError(
            code="PCF_LCIA_METHOD_MISMATCH",
            message="solved snapshot does not contain the method required by the PCF package",
            status_code=422,
            details={"expected_method": lcia_method, "actual_method": actual_method},
        )
    if not lcia_database_release or lcia_database_release != receipt_database_release:
        raise DomainError(
            code="PCF_DATABASE_RELEASE_MISMATCH",
            message="LCIA result and provider receipt bind different database releases",
            status_code=422,
            details={
                "lcia_database_release": lcia_database_release,
                "receipt_database_release": receipt_database_release,
            },
        )
    matches = [
        item
        for item in indicators
        if isinstance(item, dict)
        and str(item.get("canonical_indicator_key") or "").strip() == indicator_key
    ]
    if len(matches) != 1:
        raise DomainError(
            code="PCF_TOTAL_INDICATOR_NOT_UNIQUE",
            message="PCF requires exactly one total climate-change indicator",
            status_code=422,
            details={"indicator_key": indicator_key, "match_count": len(matches)},
        )
    total = matches[0]
    unit = str(total.get("unit") or total.get("indicator_unit") or "").strip()
    value = total.get("value")
    if unit != expected_unit:
        raise DomainError(
            code="PCF_RESULT_UNIT_MISMATCH",
            message="PCF indicator unit does not match the method package",
            status_code=422,
            details={"expected_unit": expected_unit, "actual_unit": unit},
        )
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise DomainError(
            code="PCF_RESULT_VALUE_INVALID",
            message="PCF total indicator value must be finite",
            status_code=422,
        )

    component_keys = formula.get("component_indicator_keys", [])
    if not isinstance(component_keys, list) or any(
        not isinstance(item, str) or not item.strip() for item in component_keys
    ):
        raise DomainError(
            code="PCF_METHOD_PACKAGE_INVALID",
            message="PCF component indicator keys must be a list of names",
            status_code=422,
        )
    components = []
    for key in component_keys:
        candidates = [
            item
            for item in indicators
            if isinstance(item, dict)
            and str(item.get("canonical_indicator_key") or "").strip() == key
        ]
        if len(candidates) != 1:
            raise DomainError(
                code="PCF_COMPONENT_INDICATOR_NOT_UNIQUE",
                message="PCF component indicator is missing or ambiguous",
                status_code=422,
                details={"indicator_key": key, "match_count": len(candidates)},
            )
        item = candidates[0]
        component_unit = str(
            item.get("unit") or item.get("indicator_unit") or ""
        ).strip()
        component_value = item.get("value")
        if component_unit != expected_unit or isinstance(component_value, bool) or not isinstance(
            component_value, (int, float)
        ) or not math.isfinite(float(component_value)):
            raise DomainError(
                code="PCF_COMPONENT_INDICATOR_INVALID",
                message="PCF component indicator has an invalid value or unit",
                status_code=422,
                details={"indicator_key": key},
            )
        components.append(
            {"indicator_key": key, "value": float(component_value), "unit": component_unit}
        )

    elementary_receipts = provider_receipt.get("elementary_flow_receipts")
    if not isinstance(elementary_receipts, list) or not elementary_receipts:
        raise DomainError(
            code="PCF_ELEMENTARY_FLOW_RECEIPTS_REQUIRED",
            message="PCF requires exact elementary Flow receipts from the provider solve",
            status_code=422,
        )
    required_receipt_fields = ("exchange_id", "flow_uuid", "version", "factor_hash")
    incomplete_receipts = [
        index
        for index, receipt in enumerate(elementary_receipts)
        if not isinstance(receipt, dict)
        or any(not str(receipt.get(key) or "").strip() for key in required_receipt_fields)
    ]
    if incomplete_receipts:
        raise DomainError(
            code="PCF_ELEMENTARY_FLOW_RECEIPTS_INVALID",
            message="PCF elementary Flow receipts lack exact identity or factor evidence",
            status_code=422,
            details={"indexes": incomplete_receipts},
        )
    background_receipts = provider_receipt.get("background_process_receipts")
    if not isinstance(background_receipts, list):
        background_receipts = []
    mapped_receipts = provider_receipt.get('mapped_background_process_receipts')
    if isinstance(mapped_receipts, list):
        background_receipts = [*background_receipts, *mapped_receipts]
    project_receipts = provider_receipt.get('project_background_process_receipts')
    if isinstance(project_receipts, list):
        background_receipts = [*background_receipts, *project_receipts]
    provenance = provider_receipt.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    # The solve names the mapping packages its identity decisions depended on. It is copied whole
    # when the frozen solve carries it and left out otherwise, so a pre-contract result stays as
    # it was instead of gaining an empty claim.
    has_mapping_dependencies = "elementary_mapping_dependencies" in provenance
    coverage = (
        "foreground_with_pinned_background"
        if background_receipts
        else "foreground_only"
    )
    validation_rules = manifest.get("validation_rules")
    limitations = validation_rules.get("limitations") if isinstance(validation_rules, dict) else None
    if isinstance(validation_rules, dict) and "limitations_by_coverage" in validation_rules:
        by_coverage = validation_rules["limitations_by_coverage"]
        if not isinstance(by_coverage, dict) or coverage not in by_coverage:
            raise DomainError(code="PCF_METHOD_PACKAGE_INVALID",
                              message="PCF method package lacks limitations for this coverage", status_code=422)
        limitations = [*limitations, *by_coverage[coverage]] if isinstance(limitations, list) and isinstance(by_coverage[coverage], list) else None
    if not isinstance(limitations, list) or any(
        not isinstance(item, str) or not item.strip() for item in limitations
    ):
        raise DomainError(
            code="PCF_METHOD_PACKAGE_INVALID",
            message="PCF method package limitations must be a list of statements",
            status_code=422,
        )
    total_footprint = {
        "value": float(value),
        "unit": unit,
        "indicator_key": indicator_key,
    }
    contribution_analysis, contribution_checks = build_pcf_contribution_analysis(
        lcia_results=lcia_results,
        total_footprint=total_footprint,
        scaled_elementary_exchanges=scaled_elementary_exchanges,
        elementary_flow_receipts=elementary_receipts,
    )
    result: dict[str, Any] = {
        "schema_version": result_schema,
        "capability_key": "pcf.product.v1",
        "method_package": {
            "reference": method_package_ref,
            "content_sha256": method_package_sha256,
            "lcia_method": lcia_method,
            "total_indicator_key": indicator_key,
        },
        "source_snapshot": {
            "id": solved_snapshot_id,
            "content_sha256": solved_snapshot_sha256,
            "system_revision_id": system_revision_id,
            "model_graph_sha256": model_graph_sha256,
        },
        "functional_unit": functional_unit,
        "total_footprint": total_footprint,
        "component_results": components,
        "contribution_analysis": contribution_analysis,
        "boundary_claim": {
            "claim_scope": "model_defined_partial_background" if background_receipts else claim_scope,
            "coverage": coverage,
            "complete_product_declaration": False,
        },
        "data_quality": {
            "database_release": provider_receipt.get("database_release"),
            "solver_version": provider_receipt.get("solver_version"),
            "elementary_flow_receipt_count": len(elementary_receipts),
            "background_process_receipt_count": len(background_receipts),
        },
        "audit": {
            "status": "passed",
            "checks": {
                "snapshot_content_pinned": True,
                "method_package_content_pinned": True,
                "structured_functional_unit": True,
                "total_indicator_unique": True,
                "result_unit_exact": True,
                "elementary_flow_receipts_present": True,
                **contribution_checks,
            },
            "limitations": limitations,
        },
        "provenance": {
            "provider": "nebula_lca",
            "provider_request_hash": provenance.get("request_hash"),
            **({"elementary_mapping_dependencies": provenance["elementary_mapping_dependencies"]}
               if has_mapping_dependencies else {}),
            "inventory_hash": lcia_results.get("inventory_hash"),
            "runtime_assets": lcia_results.get("runtime_assets") or [],
        },
    }
    result["content_sha256"] = canonical_json_sha256(result)
    return result
