import json
from pathlib import Path

import pytest

from nebula_one.analysis.native_product_pcf import build_native_product_pcf
from nebula_one.errors import DomainError
from nebula_one.mapped_background_schemas import (
    ProviderNativeBackgroundClimateRequest,
    ProviderNativeBackgroundClimateResponse,
)


PACKAGE = json.loads((Path(__file__).resolve().parents[1] / "src" / "nebula_one" / "resources" / "official_methods" /
                      "pcf-native-model-boundary-1.0.0.json").read_text(encoding="utf-8"))
PIN = PACKAGE["manifest"]["formula_graph"]["source_method"]
HASH = "a" * 64


def _result(merge_status="merged", method_hash=None):
    request = ProviderNativeBackgroundClimateRequest(
        database_release="ecoinvent_3.11", method_package_id=PIN["id"],
        method_package_version=PIN["version"], method_package_sha256=method_hash or PIN["content_sha256"],
        runtime_manifest_sha256=HASH, flow_snapshot_hash=HASH,
        reference_dependency_snapshot_hash=HASH,
    )
    response = ProviderNativeBackgroundClimateResponse.model_validate({
        "schema_version": "provider.native-background-climate-total.response.v1",
        "method_package_id": request.method_package_id,
        "method_package_version": request.method_package_version,
        "method_package_sha256": request.method_package_sha256,
        "runtime_manifest_sha256": HASH,
        "indicator": {"method": "EF v3.1", "category": "climate change", "name": "GWP100", "unit": "kg CO2-Eq"},
        "merge_status": merge_status, "merge_blockers": [],
        "unified_climate_total": 12.5 if merge_status == "merged" else None,
        "domains": {key: {"source_namespace": namespace, "contribution_value": value,
                           "indicator_unit": "kg CO2-Eq", "coverage": {},
                           "negative_cf_exchange_count": 0, "terms": []}
                    for key, namespace, value in (("foreground", "tiangong_open_data", 10.0),
                                                  ("native_background", "ecoinvent", 2.5))},
        "provider_system_model_evidence": "not_asserted_by_local_vector_metadata",
        "carbon_storage_permanence": "not_assessed",
        "claim_limit": "partial_background_leaf_only_not_complete_product_carbon_footprint",
    })
    return build_native_product_pcf(
        snapshot_id="snapshot", snapshot_hash=HASH, revision_id="revision", graph_hash=HASH,
        source_parameters={"demand": [{"reference_flow_uuid": "steel", "amount": 1,
                                       "unit": "kg", "unit_group_uuid": "mass", "unit_group_version": "1"}]},
        provider_receipt={}, request=request, answer=response,
        method_ref="pcf.iron-steel.native-model-boundary@1.0.0", method_hash=HASH,
        manifest=PACKAGE["manifest"],
    )


def test_native_product_preserves_domains_and_partial_claim():
    result = _result()
    assert result["total_footprint"]["value"] == 12.5
    assert [item["value"] for item in result["component_results"]] == [10, 2.5]
    assert result["boundary_claim"]["complete_product_declaration"] is False


@pytest.mark.parametrize("kwargs,code", [
    ({"merge_status": "split_diagnostic"}, "PCF_NATIVE_TOTAL_UNAVAILABLE"),
    ({"method_hash": "b" * 64}, "PCF_NATIVE_METHOD_MISMATCH"),
])
def test_native_product_refuses_unmerged_or_different_method(kwargs, code):
    with pytest.raises(DomainError) as error:
        _result(**kwargs)
    assert error.value.code == code
