from copy import deepcopy

import pytest

from nebula_one.analysis.solved_mfa import build_solved_mfa


def snapshot():
    return {
        "id": "synthetic", "internal_transfers": [
            {"exchange_id": "provider::out", "process_id": "provider", "flow_uuid": "target-flow",
             "direction": "output", "unit_group": "energy", "unit": "kWh", "amount": 10},
            {"exchange_id": "steel::power", "process_id": "steel", "flow_uuid": "source-flow",
             "direction": "input", "unit_group": "energy", "unit": "MJ", "amount": 36},
        ],
        "provider_receipt": {"mapped_background_process_receipts": [{
            "consumer_exchange_id": "steel::power", "process_uuid": "provider",
            "source_flow_uuid": "source-flow", "target_flow_uuid": "target-flow",
            "source_unit": "MJ", "target_unit": "kWh", "amount_factor": 1 / 3.6,
            "activity_amount": 10, "mapping_package_hash": "a" * 64,
        }]},
    }


def test_mapped_power_is_projected_in_consumer_units_with_conversion_evidence():
    result = build_solved_mfa(solved_snapshot=snapshot(), revision_graph={"nodes": [], "exchanges": []})
    series = next(s for s in result["series"] if s["unit"] == "MJ")
    link = series["links"][0]
    assert link["value"] == 36
    assert link["reconciliation"]["source_amount"] == 10
    assert link["reconciliation"]["source_unit"] == "kWh"
    assert link["reconciliation"]["target_unit"] == "MJ"
    assert result["audit"]["checks"]["error_count"] == 0


@pytest.mark.parametrize("field,value", [("amount_factor", 1), ("activity_amount", 11), ("source_unit", "kg")])
def test_mapped_power_rejects_inconsistent_transfer(field, value):
    data = deepcopy(snapshot())
    data["provider_receipt"]["mapped_background_process_receipts"][0][field] = value
    result = build_solved_mfa(solved_snapshot=data, revision_graph={"nodes": [], "exchanges": []})
    assert result["audit"]["status"] == "failed"
    assert any(i["code"] == "MAPPED_BACKGROUND_TRANSFER_MISMATCH" for i in result["audit"]["issues"])


def test_shared_power_projects_each_consumer_share_without_duplicating_total():
    data = snapshot()
    data['internal_transfers'][1]['amount'] = 12
    other = dict(data['internal_transfers'][1], exchange_id='casting::power', process_id='casting', amount=24)
    data['internal_transfers'].append(other)
    first = data['provider_receipt']['mapped_background_process_receipts'][0]
    first.update(shared_activity_schema_version='provider.mapped-background-shared-activity.v1',
                 shared_process_total_activity_amount=10, consumer_attributed_activity_amount=10 / 3)
    data['provider_receipt']['mapped_background_process_receipts'].append(dict(first,
        consumer_exchange_id='casting::power', consumer_attributed_activity_amount=20 / 3))
    result = build_solved_mfa(solved_snapshot=data, revision_graph={'nodes': [], 'exchanges': []})
    series = next(s for s in result['series'] if s['unit'] == 'MJ')
    assert sorted(link['value'] for link in series['links']) == [12, 24]
    assert sum(link['reconciliation']['source_amount'] for link in series['links']) == 10
    assert result['audit']['checks']['error_count'] == 0
