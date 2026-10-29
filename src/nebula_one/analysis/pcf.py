from __future__ import annotations

import math
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .method_grouping import build_dimension_grouping, path_rows_to_weighted_terms
from .method_path_grouping import group_path_weighted_scopes, select_path_weighted_receipt
from .method_scope_grouping import group_organization_scopes
from .pcf_contributions import build_pcf_contribution_analysis
from .tag_grouping import (
    TAG_SEMANTICS,
    consumer_path_exchanges,
    group_tag_scheme,
    tag_dimension,
)


def _receipt_gap_breakdown(
    path_receipt: dict[str, Any],
    scaled_elementary_exchanges: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Separate the two gap reasons a Scope bucket cannot express on its own.

    ``uncharacterized`` is an inventory elementary flow this LCIA method gave no factor for: it
    never appears in the receipt, so it is absent rather than zero. ``zero_cf`` is a flow the
    method did characterize with a zero coefficient, which is a real zero and must not be reported
    as a missing factor. Both are informational — neither changes the reconciliation invariant.
    """
    rows = [item for item in (path_receipt.get("terms") or []) if isinstance(item, dict)]
    receipt_ids = {str(row.get("exchange_id") or "") for row in rows}
    inventory_ids: set[str] = set()
    for item in scaled_elementary_exchanges:
        if not isinstance(item, dict):
            continue
        exchange_id = str(item.get("exchange_id") or "")
        if not exchange_id:
            continue
        try:
            amount = float(item.get("amount"))
        except (TypeError, ValueError):
            amount = 0.0
        # A zero-quantity flow contributes nothing whether the method characterizes it or not, so
        # it is not a missing factor and must not be reported as one.
        if math.isfinite(amount) and amount:
            inventory_ids.add(exchange_id)
    return {
        "uncharacterized_exchange_ids": sorted(inventory_ids.difference(receipt_ids) | {
            str(row["exchange_id"]) for row in rows
            if row.get("cf_presence") == "implicit_zero" and row.get("exchange_id")
        }),
        "zero_cf_exchange_ids": sorted({
            str(row.get("exchange_id") or "")
            for row in rows
            if row.get("cf_presence") == "explicit_zero" and str(row.get("exchange_id") or "")
        }),
    }


def _attach_pcf_user_method_grouping(
    *,
    contribution_analysis: dict[str, Any],
    provider_receipt: dict[str, Any],
    scaled_elementary_exchanges: list[dict[str, Any]],
    lcia_results: dict[str, Any],
    indicator_key: str,
    indicator_unit: str,
) -> dict[str, Any]:
    """Apply a referenced user method to PCF's own frozen contributions, without re-solving.

    This is R5's "same solve basis, choose/classify" operation: the method's include/exclude and
    category decisions re-bucket the contributions Nebula LCA already produced for this product
    footprint. A path-weighted receipt decomposes a shared background emission per consumption
    path and keeps every path; a path the engine could not attribute is reported as an engine gap.
    The engine ``total_footprint`` and its coverage evidence are NOT changed here — a method view
    is a reporting subset, never a claim that a partial selection is a complete PCF. Exclusion moves
    a contribution into ``excluded``; it never deletes a technosphere node or rescales a partial
    contribution into a full footprint. A run with no user method is returned untouched.
    """
    user_method = provider_receipt.get("user_calculation_method") if isinstance(provider_receipt, dict) else None
    tag_scheme = isinstance(user_method, dict) and user_method.get("semantics") == TAG_SEMANTICS
    if not isinstance(user_method, dict) or (not user_method.get("rules") and not tag_scheme):
        return contribution_analysis

    identity = {
        key: user_method.get(key)
        for key in (
            "method_id",
            "version",
            "content_sha256",
            "model_revision_id",
            "execution_plan_sha256",
            "compiler_version",
        )
    }
    path_receipt = select_path_weighted_receipt(lcia_results, canonical_indicator_key=str(indicator_key or ""))

    if path_receipt is not None and tag_scheme:
        # A tag view reports matched, unmatched, pending and missing paths apart; it never reads
        # "not tagged" as "excluded", so the LC-Scope buckets below would misstate its range.
        tag_grouping = group_tag_scheme(
            rules=user_method.get("rules") or [],
            scaled_exchanges=scaled_elementary_exchanges,
            weighted_terms=path_rows_to_weighted_terms(path_receipt),
            dimension=tag_dimension(user_method),
            indicator_unit=indicator_unit or "",
            consumer_paths=consumer_path_exchanges(path_receipt),
        )
        partial = (
            not tag_grouping["coverage"]["complete"]
            or bool(tag_grouping["missing"]["term_count"])
            or not tag_grouping["reconciled"]
        )
        contribution_analysis["user_method_grouping"] = {
            "method": identity,
            "grouping_mode": "flow_tag",
            "execution_status": "executed_partial" if partial else "executed_full",
            "counts_as_complete_pcf": False,
            "coverage": {
                "matched_share": tag_grouping["coverage"]["matched_share"],
                "unmatched_exchange_ids": tag_grouping["unmatched"]["exchange_ids"],
                "pending_exchange_ids": tag_grouping["pending"]["exchange_ids"],
                "missing_exchange_ids": tag_grouping["missing"]["exchange_ids"],
            },
            "grouping": None,
            "dimension_grouping": None,
            "tag_grouping": tag_grouping,
        }
        return contribution_analysis

    if path_receipt is not None:
        grouping = group_path_weighted_scopes(
            rules=user_method["rules"],
            scaled_exchanges=scaled_elementary_exchanges,
            path_receipt=path_receipt,
            indicator_unit=indicator_unit,
        )
        coverage_gaps = grouping["coverage_gaps"]
        unattributed_ids = grouping["unattributed"]["exchange_ids"]
        engine_gap_ids = grouping["engine_gap"]["exchange_ids"]
        gap_breakdown = _receipt_gap_breakdown(path_receipt, scaled_elementary_exchanges)
        partial = bool(coverage_gaps) or bool(unattributed_ids) or bool(engine_gap_ids) or not grouping["reconciled"]
        contribution_analysis["user_method_grouping"] = {
            "method": identity,
            "grouping_mode": "path_weighted",
            "execution_status": "executed_partial" if partial else "executed_full",
            "counts_as_complete_pcf": False,
            "coverage": {
                "attribution_coverage": grouping.get("attribution_coverage"),
                "coverage_gaps": coverage_gaps,
                "unattributed_exchange_ids": unattributed_ids,
                "engine_gap_exchange_ids": engine_gap_ids,
                **gap_breakdown,
            },
            "grouping": grouping,
            "dimension_grouping": build_dimension_grouping(
                user_method=user_method,
                scaled_exchanges=scaled_elementary_exchanges,
                weighted_terms=path_rows_to_weighted_terms(path_receipt),
                indicator_unit=indicator_unit or "",
                path_receipt=path_receipt,
            ),
        }
        return contribution_analysis

    hotspots = contribution_analysis.get("hotspots") or []
    if contribution_analysis.get("status") != "available" or not hotspots:
        contribution_analysis["user_method_grouping"] = {
            "method": identity,
            "grouping_mode": "exchange_weighted",
            "execution_status": "no_weighted_contributions",
            "counts_as_complete_pcf": False,
            "grouping": None,
            "dimension_grouping": None,
        }
        return contribution_analysis

    terms = [
        {"exchange_id": hotspot["exchange_id"], "contribution_value": hotspot["contribution_value"]}
        for hotspot in hotspots
    ]
    grouping = group_organization_scopes(
        rules=user_method["rules"],
        scaled_exchanges=scaled_elementary_exchanges,
        terms=terms,
        indicator_unit=indicator_unit,
    )
    coverage_gaps = grouping["coverage_gaps"]
    unattributed_ids = grouping["unattributed"]["exchange_ids"]
    partial = bool(coverage_gaps) or bool(unattributed_ids) or not grouping["reconciled"]
    contribution_analysis["user_method_grouping"] = {
        "method": identity,
        "grouping_mode": "exchange_weighted",
        "execution_status": "executed_partial" if partial else "executed_full",
        "counts_as_complete_pcf": False,
        "coverage": {
            "coverage_gaps": coverage_gaps,
            "unattributed_exchange_ids": unattributed_ids,
        },
        "grouping": grouping,
        "dimension_grouping": build_dimension_grouping(
            user_method=user_method,
            scaled_exchanges=scaled_elementary_exchanges,
            weighted_terms=terms,
            indicator_unit=indicator_unit or "",
        ),
    }
    return contribution_analysis


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
    contribution_analysis = _attach_pcf_user_method_grouping(
        contribution_analysis=contribution_analysis,
        provider_receipt=provider_receipt,
        scaled_elementary_exchanges=scaled_elementary_exchanges,
        lcia_results=lcia_results,
        indicator_key=indicator_key,
        indicator_unit=unit,
    )
    characterization = contribution_analysis.get("characterization_coverage")
    if characterization is not None:
        total_footprint["value_kind"] = characterization["value_kind"]
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
            **({"characterization_coverage": characterization} if characterization is not None else {}),
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
