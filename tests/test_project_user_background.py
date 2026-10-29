from types import SimpleNamespace

import pytest

from nebula_one.errors import DomainError
from nebula_one.services.project_user_background import ProjectUserBackgroundService, UserBackgroundSelection


FLOW = "3d76981f-964a-4865-b588-0e067a2a1163"


def _port(port_id, unit, amount, direction, product=False):
    return {"id": port_id, "flowUuid": FLOW, "flowSourceNamespace": "tiangong_open_data",
            "flowVersion": "01.01.003", "flowPropertyUuid": "fp-energy",
            "flowPropertyVersion": "01.00.000", "unitGroupUuid": "ug-energy",
            "unitGroupVersion": "01.00.000", "unitGroup": "Energy", "unit": unit,
            "amount": amount, "direction": direction, "type": "technosphere", "isProduct": product}


def test_user_project_link_pins_exact_version_hash_and_catalog_conversion():
    consumer = {"nodes": [{"id": "sinter", "inputs": [_port("power", "MJ", 610, "input")]}], "exchanges": []}
    source = {"graph_hash": "a" * 64, "graph": {"nodes": [{"id": "supply", "name": "我的电力供应",
        "inputs": [], "outputs": [_port("electricity", "kWh", 1, "output", True)]}], "exchanges": []}}
    class Client:
        def get_provider_model_snapshot(self, project_id, version):
            assert (project_id, version) == ("my-supply", 2)
            return SimpleNamespace(payload=source)

        def convert_unit(self, **kwargs):
            assert kwargs == {"from_unit": "MJ", "to_unit": "kWh", "unit_group": "Energy"}
            return SimpleNamespace(payload={"from_unit": "MJ", "to_unit": "kWh",
                                            "unit_group": "Energy", "converted_value": 1 / 3.6})

    service = ProjectUserBackgroundService(Client())
    answer = service.resolve(consumer, UserBackgroundSelection(
        consumer_exchange_id="sinter::power", project_id="my-supply", version=2))
    assert answer["pin"]["expected_graph_hash"] == "a" * 64
    assert answer["pin"]["provider_amount_per_consumer_unit"] == pytest.approx(1 / 3.6)
    generic = service.resolve(consumer, UserBackgroundSelection(
        consumer_exchange_id="sinter::power", project_id="my-supply", version=2),
        revision=SimpleNamespace(id="generic-revision", application_context={}), application=None)
    assert "model_processing_rules_ref" not in generic
    service.validate(consumer, [SimpleNamespace(**answer["pin"], model_dump=lambda **_: answer["pin"])])
    changed = {**answer["pin"], "expected_graph_hash": "b" * 64}
    with pytest.raises(DomainError) as error:
        service.validate(consumer, [SimpleNamespace(**changed, model_dump=lambda **_: changed)])
    assert error.value.code == "PROJECT_BACKGROUND_PIN_CHANGED"


def test_closed_network_selects_exact_external_product_and_rejects_open_input():
    consumer = {"nodes": [{"id": "sinter", "inputs": [_port("power", "MJ", 610, "input")]}], "exchanges": []}
    nodes = [{"id": "delivery", "inputs": [_port("upstream", "kWh", 1, "input")],
              "outputs": [_port("electricity", "kWh", 1, "output", True)]},
             {"id": "supply", "inputs": [], "outputs": [_port("electricity", "kWh", 1, "output", True)]}]
    snapshot = {"graph_hash": "a" * 64, "graph": {"nodes": nodes, "exchanges": [
        {"fromNode": "supply", "toNode": "delivery", "sourcePortId": "electricity", "targetPortId": "upstream"}]}}
    client = SimpleNamespace(get_provider_model_snapshot=lambda *_: SimpleNamespace(payload=snapshot),
        convert_unit=lambda **_: SimpleNamespace(payload={"from_unit": "MJ", "to_unit": "kWh", "converted_value": 1 / 3.6}))
    service = ProjectUserBackgroundService(client)
    request = UserBackgroundSelection(consumer_exchange_id="sinter::power", project_id="supply", version=2)
    answer = service.resolve(consumer, request)
    assert answer["pin"]["source_node_id"] == "delivery"
    assert answer["pin"]["claim_role"] == "user_declared_partial_background_network"
    nodes[0]["inputs"].append(_port("unresolved", "kWh", 1, "input"))
    with pytest.raises(DomainError) as error:
        service.resolve(consumer, request)
    assert error.value.code == "PROJECT_BACKGROUND_NOT_CLOSED_LEAF"


def test_network_receipts_require_every_node_once_and_match_solved_activities():
    from copy import deepcopy
    from nebula_one.hashing import canonical_json_sha256
    from nebula_one.runtime_schemas import ProviderProjectBackgroundPin
    from nebula_one.services.provider_solve import _validated_project_background_receipts

    pin = ProviderProjectBackgroundPin(consumer_exchange_id="sinter::power", project_id="supply",
        version=2, expected_graph_hash="a" * 64, source_node_id="delivery",
        reference_port_id="electricity", provider_amount_per_consumer_unit=1 / 3.6,
        claim_role="user_declared_partial_background_network")
    frozen = pin.model_dump(mode="json")
    rows = [{"pin": frozen, "source_graph_hash": "a" * 64,
        "claim_limit": "user_declared_partial_background_closed_network",
        "source_node_id": node, "expanded_node_id": "expanded-" + node,
        "expanded_network_node_ids": ["expanded-delivery", "expanded-supply"],
        "source_process_uuid": node, "activity_amount": 10.0} for node in ("delivery", "supply")]
    result = {"project_background_process_receipts": rows,
        "provenance": {"project_background_pins_hash": canonical_json_sha256([frozen])},
        "activity_vector": [{"process_uuid": node, "activity_amount": 10.0} for node in ("delivery", "supply")]}
    assert len(_validated_project_background_receipts(result, [pin])) == 2
    for mutation in ("missing", "duplicate", "activity"):
        changed = deepcopy(result)
        if mutation == "missing":
            changed["project_background_process_receipts"].pop()
        elif mutation == "duplicate":
            changed["project_background_process_receipts"].append(deepcopy(rows[0]))
        else:
            changed["activity_vector"][0]["activity_amount"] = 20.0
        with pytest.raises(DomainError) as error:
            _validated_project_background_receipts(changed, [pin])
        assert error.value.code == "PROJECT_BACKGROUND_RECEIPT_MISMATCH"
