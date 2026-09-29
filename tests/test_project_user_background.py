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
