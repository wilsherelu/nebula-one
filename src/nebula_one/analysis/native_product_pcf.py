"""Product projection of one frozen, pinned native climate calculation."""
from __future__ import annotations

from math import isclose
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..mapped_background_schemas import (
    ProviderNativeBackgroundClimateRequest,
    ProviderNativeBackgroundClimateResponse,
)
from .pcf import _functional_unit


def build_native_product_pcf(
    *, snapshot_id: str, snapshot_hash: str, revision_id: str, graph_hash: str,
    source_parameters: dict[str, Any], provider_receipt: dict[str, Any],
    request: ProviderNativeBackgroundClimateRequest,
    answer: ProviderNativeBackgroundClimateResponse,
    method_ref: str, method_hash: str, manifest: dict[str, Any],
) -> dict[str, Any]:
    formula = manifest.get("formula_graph") or {}
    boundary = manifest.get("boundary_schema") or {}
    output = manifest.get("output_schema") or {}
    if (formula.get("source_contract") != "provider.native-background-climate-total.response.v1"
            or output.get("schema_version") != "nebula_one.pcf.product.v1"
            or boundary.get("claim_scope") != "model_defined_partial_background"):
        raise DomainError(code="PCF_NATIVE_METHOD_INVALID", message="native product method declares an unsupported source or boundary", status_code=422)
    expected = formula.get("source_method") or {}
    actual = {"id": request.method_package_id, "version": request.method_package_version,
              "content_sha256": request.method_package_sha256}
    if expected != actual or answer.method_package_sha256 != request.method_package_sha256:
        raise DomainError(code="PCF_NATIVE_METHOD_MISMATCH", message="product method and frozen climate method identities differ", status_code=422)
    if answer.merge_status != "merged" or answer.unified_climate_total is None:
        raise DomainError(code="PCF_NATIVE_TOTAL_UNAVAILABLE", message="native climate domains have no validated merged total", status_code=422,
                          details={"merge_blockers": answer.merge_blockers})
    if not isclose(answer.unified_climate_total,
                   sum(item.contribution_value for item in answer.domains.values()),
                   rel_tol=1e-9, abs_tol=1e-12):
        raise DomainError(code="PCF_NATIVE_TOTAL_INCONSISTENT", message="native merged total differs from its domains", status_code=422)
    if answer.claim_limit != "partial_background_leaf_only_not_complete_product_carbon_footprint":
        raise DomainError(code="PCF_NATIVE_CLAIM_MISMATCH", message="native climate source has a different coverage claim", status_code=422)
    functional_unit = _functional_unit(source_parameters)
    unit = answer.indicator.unit
    components = [
        {"indicator_key": key, "value": answer.domains[key].contribution_value, "unit": unit}
        for key in ("foreground", "native_background")
    ]
    result: dict[str, Any] = {
        "schema_version": "nebula_one.pcf.product.v1", "capability_key": "pcf.product.v1",
        "method_package": {"reference": method_ref, "content_sha256": method_hash,
                           "lcia_method": answer.indicator.method,
                           "total_indicator_key": "climate-change-total"},
        "source_snapshot": {"id": snapshot_id, "content_sha256": snapshot_hash,
                            "system_revision_id": revision_id, "model_graph_sha256": graph_hash},
        "functional_unit": functional_unit,
        "total_footprint": {"value": answer.unified_climate_total, "unit": unit,
                            "indicator_key": "climate-change-total"},
        "component_results": components,
        "contribution_analysis": {"status": "unavailable", "coverage": "total_only",
                                  "reason": "The pinned native answer exposes domain totals; product process hotspots are not asserted.",
                                  "indicator_receipt": None, "hotspots": []},
        "boundary_claim": {"claim_scope": "model_defined_partial_background",
                           "coverage": "foreground_with_pinned_background",
                           "complete_product_declaration": False,
                           "source_claim_limit": answer.claim_limit},
        "data_quality": {"database_release": request.database_release,
                         "solver_version": provider_receipt.get("solver_version"),
                         "elementary_flow_receipt_count": len(provider_receipt.get("elementary_flow_receipts") or []),
                         "background_process_receipt_count": len(provider_receipt.get("mapped_background_process_receipts") or [])},
        "audit": {"status": "passed", "checks": {"snapshot_content_pinned": True,
                    "method_package_content_pinned": True, "structured_functional_unit": True,
                    "native_method_identity_exact": True, "merged_total_from_provider": True},
                  "limitations": manifest.get("validation_rules", {}).get("limitations", [])},
        "provenance": {"provider": "nebula_lca", "native_method_package": actual,
                       "runtime_manifest_sha256": request.runtime_manifest_sha256,
                       "flow_snapshot_hash": request.flow_snapshot_hash,
                       "reference_dependency_snapshot_hash": request.reference_dependency_snapshot_hash,
                       "provider_request_hash": (provider_receipt.get("provenance") or {}).get("request_hash")},
    }
    result["content_sha256"] = canonical_json_sha256(result)
    return result
