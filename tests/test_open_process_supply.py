import json
from copy import deepcopy
from pathlib import Path

import pytest

from nebula_one.seeds.open_process_supply import validate_open_process_supply


RESOURCE = Path(__file__).resolve().parents[1] / "src/nebula_one/resources/public_supply/tiangong-china-grid-2022.v1.json"


def test_public_supply_preserves_all_source_exchanges_and_exact_dependencies():
    document = json.loads(RESOURCE.read_text(encoding="utf-8"))
    record, flows = validate_open_process_supply(document, RESOURCE)
    assert record["source_version"] == "01.01.014"
    assert len(document["graph"]["nodes"][0]["outputs"]) == 4
    assert len(flows["records"]) == 4
    assert "factor" not in document
    assert document["source_process"]["claim_limit"] == "source_declared_partly_terminated_system"


@pytest.mark.parametrize("change", ["omit", "amount", "identity", "reference"])
def test_public_supply_rejects_inventory_projection_drift(change):
    document = deepcopy(json.loads(RESOURCE.read_text(encoding="utf-8")))
    outputs = document["graph"]["nodes"][0]["outputs"]
    if change == "omit":
        outputs.pop()
    elif change == "amount":
        outputs[0]["amount"] = 0
    elif change == "identity":
        outputs[0]["flowVersion"] = "latest"
    else:
        outputs[0]["isProduct"] = not outputs[0]["isProduct"]
    with pytest.raises(ValueError):
        validate_open_process_supply(document, RESOURCE)
