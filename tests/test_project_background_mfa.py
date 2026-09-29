from copy import deepcopy

import pytest

from nebula_one.analysis.solved_mfa import build_solved_mfa


def _snapshot():
    pin = {
        "schema_version": "provider.project-background-pin.v1",
        "consumer_exchange_id": "steel::power", "expected_graph_hash": "a" * 64,
        "reference_port_id": "electricity-out", "provider_amount_per_consumer_unit": 1 / 3.6,
    }
    return {
        "id": "solved-project-supply",
        "internal_transfers": [
            {"exchange_id": "project-background-1::electricity-out", "process_id": "supply-process",
             "flow_uuid": "electricity-flow", "direction": "output", "unit_group": "energy",
             "unit": "kWh", "amount": 610 / 3.6},
            {"exchange_id": "steel::power", "process_id": "steel-process",
             "flow_uuid": "electricity-flow", "direction": "input", "unit_group": "energy",
             "unit": "MJ", "amount": 610},
        ],
        "provider_receipt": {
            "calculation_basis": {"project_background_pins": [pin]},
            "project_background_process_receipts": [{
                "pin": pin, "expanded_node_id": "project-background-1",
                "source_process_uuid": "supply-process", "source_graph_hash": "a" * 64,
                "reference_flow_uuid": "electricity-flow", "reference_unit": "kWh",
                "consumer_unit": "MJ", "unit_conversion_factor": 1 / 3.6,
                "activity_amount": 610 / 3.6,
            }],
        },
    }


def test_project_supply_mfa_uses_frozen_conversion_and_consumes_both_internal_rows():
    result = build_solved_mfa(solved_snapshot=_snapshot(), revision_graph={"nodes": [], "exchanges": []})
    assert result["audit"]["checks"]["error_count"] == 0
    link = next(link for series in result["series"] for link in series["links"]
                if link.get("origin") == "project_background_process_receipt")
    assert link["value"] == 610
    assert link["exchange_ids"] == ["project-background-1::electricity-out", "steel::power"]
    assert link["reconciliation"]["source_amount"] == pytest.approx(169.44444444444446)
    assert link["reconciliation"]["source_unit"] == "kWh"
    assert link["reconciliation"]["target_unit"] == "MJ"


@pytest.mark.parametrize("field,value", [
    ("unit_conversion_factor", 1), ("activity_amount", 610), ("source_graph_hash", "b" * 64),
])
def test_project_supply_mfa_refuses_unreconciled_receipt(field, value):
    snapshot = deepcopy(_snapshot())
    snapshot["provider_receipt"]["project_background_process_receipts"][0][field] = value
    result = build_solved_mfa(solved_snapshot=snapshot, revision_graph={"nodes": [], "exchanges": []})
    assert result["audit"]["status"] == "failed"
    assert any(issue["code"] == "PROJECT_BACKGROUND_TRANSFER_MISMATCH"
               for issue in result["audit"]["issues"])
