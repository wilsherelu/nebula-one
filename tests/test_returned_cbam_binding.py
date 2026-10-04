from copy import deepcopy
import json
from pathlib import Path

import pytest

from nebula_one.errors import DomainError
from nebula_one.services.returned_cbam_binding import (
    _first_difference, _identity_graph, _reviewed_selector_additions,
)
from test_steel_model_processing_assets import _graph as steel_graph


def _graph():
    return {"nodes": [{"id": "process-a", "process_uuid": "process-identity", "name": "A",
                       "inputs": [], "outputs": [{"id": "co2-out", "flowUuid": "co2-identity",
                                                  "flowSourceNamespace": "reviewed", "unit": "kg",
                                                  "direction": "output", "amount": 10}]}],
            "exchanges": []}


def test_reviewed_cbam_identity_survives_names_and_quantities():
    original = _graph()
    edited = deepcopy(original)
    edited["nodes"][0]["name"] = "炼钢"
    edited["nodes"][0]["outputs"][0]["amount"] = 11
    edited["nodes"][0]["outputs"][0]["externalSaleAmount"] = 0
    assert _first_difference(_identity_graph(original), _identity_graph(edited)) is None


def test_reviewed_cbam_identity_rejects_an_unknown_emission_and_changed_flow():
    original = _graph()
    unknown = deepcopy(original)
    unknown["nodes"][0]["outputs"].append({"id": "new-out", "flowUuid": "unknown",
                                             "unit": "kg", "direction": "output", "amount": 1})
    assert _first_difference(_identity_graph(original), _identity_graph(unknown))
    changed = deepcopy(original)
    changed["nodes"][0]["outputs"][0]["flowUuid"] = "another-flow"
    assert "flowUuid" in _first_difference(_identity_graph(original), _identity_graph(changed))


@pytest.mark.parametrize("normalized_side", ["fromNode", "toNode"])
def test_reviewed_identity_uses_endpoint_mode_for_legacy_normalized_links(normalized_side):
    original = _graph()
    original["nodes"].append({"id": "process-b", "mode": "balanced", "inputs": [], "outputs": []})
    original["nodes"][0]["mode"] = "balanced"
    edge = {"id": "link", "fromNode": "process-a", "toNode": "process-b", "quantityMode": "single"}
    original["exchanges"] = [edge]
    next(node for node in original["nodes"] if node["id"] == edge[normalized_side])["mode"] = "normalized"
    returned = deepcopy(original)
    returned["exchanges"][0]["quantityMode"] = "dual"
    assert _identity_graph(original) == _identity_graph(returned)
    returned["exchanges"][0]["toNode"] = "unknown-process"
    assert _first_difference(_identity_graph(original), _identity_graph(returned))


def test_balanced_link_quantity_mode_is_still_part_of_reviewed_identity():
    original = _graph()
    original["exchanges"] = [{"id": "link", "fromNode": "process-a", "toNode": "process-b", "quantityMode": "single"}]
    returned = deepcopy(original)
    returned["exchanges"][0]["quantityMode"] = "dual"
    assert _first_difference(_identity_graph(original), _identity_graph(returned)).endswith("quantityMode")


def _selector():
    path = Path("src/nebula_one/resources/official_methods/cbam-steel-direct-selector-1.1.3.json")
    method = json.loads(path.read_text(encoding="utf-8"))
    return method["manifest"]["classification_rules"]["additional_direct_emission_selectors"]


def _added_co2(graph, port_id):
    source = next(port for node in graph["nodes"] for port in node["outputs"]
                  if port["id"] == "co2-sinter-breeze-out")
    secondary = next(node for node in graph["nodes"] if node["id"] == "secondary-metallurgy-and-degassing")
    port = {**deepcopy(source), "id": port_id, "amount": 1.0}
    secondary["outputs"].append(port)
    return port


@pytest.mark.parametrize("port_id", ["output_random_a", "output_random_b"])
def test_returned_selector_counts_exact_tiangong_co2_with_any_local_port_id(port_id):
    source = steel_graph()
    returned = deepcopy(source)
    _added_co2(returned, port_id)
    matched = _reviewed_selector_additions(
        source, returned, _selector(),
        {node["process_uuid"] for node in source["nodes"]},
    )
    assert [row[0] for row in matched] == [f"secondary-metallurgy-and-degassing::{port_id}"]


def test_returned_selector_refuses_unknown_in_boundary_flow_but_allows_outside_process():
    source = steel_graph()
    returned = deepcopy(source)
    port = _added_co2(returned, "output_unknown")
    port["flowUuid"] = "unreviewed-flow"
    with pytest.raises(DomainError) as error:
        _reviewed_selector_additions(source, returned, _selector(),
                                     {node["process_uuid"] for node in source["nodes"]})
    assert error.value.code == "CBAM_EMISSION_ROLE_REVIEW_REQUIRED"
    assert error.value.details["exchange_id"] == "secondary-metallurgy-and-degassing::output_unknown"

    outside = deepcopy(source)
    node = deepcopy(source["nodes"][0])
    node.update(id="outside-process", process_uuid="outside-boundary-process")
    outside["nodes"].append(node)
    assert _reviewed_selector_additions(source, outside, _selector(),
                                        {item["process_uuid"] for item in source["nodes"]}) == []
