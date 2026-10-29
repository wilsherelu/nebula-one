import json
from copy import deepcopy
from pathlib import Path

import pytest

from nebula_one.seeds.open_process_supply import ensure_open_process_supply_flows, validate_open_process_supply


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


class _Response:
    def __init__(self, payload):
        self.payload = payload


class _CatalogClient:
    """Engine stub that answers catalog resolution for the first public supply Flow only."""

    def __init__(self, resolution):
        self.resolution = resolution

    def get_flow_version(self, namespace, flow_uuid, version):
        return _Response({"flow_uuid": flow_uuid})

    def resolve_provider_catalog(self, request):
        return _Response({"items": [self.resolution]})


def _first_port():
    document = json.loads(RESOURCE.read_text(encoding="utf-8"))
    return document, document["graph"]["nodes"][0]["outputs"][0]


def test_unresolved_public_flow_reports_the_engine_code_instead_of_source_drift():
    document, port = _first_port()
    client = _CatalogClient({"status": "unsupported", "code": "ELEMENTARY_FLOW_CF_NOT_FOUND",
                             "message": "The exact elementary Flow has no non-zero EF3.1 characterization factor coverage."})
    with pytest.raises(ValueError) as refusal:
        ensure_open_process_supply_flows(client, document, RESOURCE)
    message = str(refusal.value)
    assert "ELEMENTARY_FLOW_CF_NOT_FOUND" in message
    assert port["flowUuid"] in message
    assert "differs from its exact source" not in message


def test_public_flow_content_hash_drift_is_still_reported_as_source_drift():
    document, port = _first_port()
    client = _CatalogClient({"status": "resolved", "value": {"content_hash": "0" * 64}})
    with pytest.raises(ValueError, match="public Process Flow differs from its exact source"):
        ensure_open_process_supply_flows(client, document, RESOURCE)
