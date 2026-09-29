from __future__ import annotations

import pytest

from nebula_one.errors import DomainError
from nebula_one.services.provider_solve import _validated_technosphere_receipts


def _graph() -> dict:
    return {
        "nodes": [
            {
                "id": "distillation",
                "process_uuid": "process-distillation",
                "inputs": [
                    {
                        "id": "crude-in",
                        "type": "technosphere",
                        "flowUuid": "95151b26-d16b-4669-b433-fc0bd633f564",
                        "flowSourceNamespace": "tiangong_open_data",
                        "flowVersion": "01.01.002",
                        "flowPropertyUuid": "mass-property",
                        "flowPropertyVersion": "03.00.003",
                        "unitGroupUuid": "mass-group",
                        "unitGroupVersion": "03.00.003",
                        "unit": "kg",
                    }
                ],
                "outputs": [
                    {
                        "id": "product-out",
                        "type": "technosphere",
                        "flowUuid": "custom-product",
                        "flowSourceNamespace": "nebula-one.casepack",
                        "flowVersion": "0.1.0",
                        "flowPropertyUuid": "mass-property",
                        "flowPropertyVersion": "03.00.003",
                        "unitGroupUuid": "mass-group",
                        "unitGroupVersion": "03.00.003",
                        "unit": "kg",
                    }
                ],
            }
        ]
    }


def _receipts() -> list[dict]:
    common = {
        "process_uuid": "process-distillation",
        "flow_property_uuid": "mass-property",
        "flow_property_version": "03.00.003",
        "unit_group_uuid": "mass-group",
        "unit_group_version": "03.00.003",
        "unit": "kg",
    }
    return [
        {
            **common,
            "exchange_id": "distillation::crude-in",
            "resolution": "tidas_exact_snapshot",
            "source_namespace": "tiangong_open_data",
            "flow_uuid": "95151b26-d16b-4669-b433-fc0bd633f564",
            "version": "01.01.002",
            "content_hash": "flow-hash",
            "snapshot_hash": "snapshot-hash",
            "flow_property_content_hash": "property-hash",
            "unit_group_content_hash": "group-hash",
            "unit_content_hash": "unit-hash",
        },
        {
            **common,
            "exchange_id": "distillation::product-out",
            "resolution": "inline_custom",
            "source_namespace": "nebula-one.casepack",
            "flow_uuid": "custom-product",
            "version": "0.1.0",
        },
    ]


def test_exact_tidas_and_custom_receipts_are_preserved_deterministically() -> None:
    result = {"technosphere_flow_receipts": list(reversed(_receipts()))}

    receipts = _validated_technosphere_receipts(
        result, _graph(), analysis_run_id="run-1"
    )

    assert [item["exchange_id"] for item in receipts] == [
        "distillation::crude-in",
        "distillation::product-out",
    ]
    assert receipts[0]["resolution"] == "tidas_exact_snapshot"
    assert receipts[1]["resolution"] == "inline_custom"


def test_exact_tidas_graph_fails_closed_without_receipts() -> None:
    with pytest.raises(DomainError) as captured:
        _validated_technosphere_receipts({}, _graph(), analysis_run_id="run-1")

    assert captured.value.code == "PROVIDER_TIDAS_RECEIPT_MISSING"


def test_exact_tidas_graph_rejects_identity_mismatch() -> None:
    receipts = _receipts()
    receipts[0]["version"] = "01.01.001"

    with pytest.raises(DomainError) as captured:
        _validated_technosphere_receipts(
            {"technosphere_flow_receipts": receipts},
            _graph(),
            analysis_run_id="run-1",
        )

    assert captured.value.code == "PROVIDER_TECHNOSPHERE_RECEIPT_IDENTITY_MISMATCH"
    assert captured.value.details["mismatches"]["version"] == {
        "graph": "01.01.002",
        "receipt": "01.01.001",
    }


def test_exact_tidas_graph_rejects_incomplete_dependency_hashes() -> None:
    receipts = _receipts()
    receipts[0]["unit_group_content_hash"] = None

    with pytest.raises(DomainError) as captured:
        _validated_technosphere_receipts(
            {"technosphere_flow_receipts": receipts},
            _graph(),
            analysis_run_id="run-1",
        )

    assert captured.value.code == "PROVIDER_TIDAS_RECEIPT_INVALID"
    assert captured.value.details["missing_hash_fields"] == [
        "unit_group_content_hash"
    ]
