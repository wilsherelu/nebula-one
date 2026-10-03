from copy import deepcopy
from types import SimpleNamespace

from nebula_one.analysis.solved_mfa import build_solved_mfa
from nebula_one.services.mfa_display_graph import MFADisplayGraph


def test_exact_background_labels_restore_names_without_changing_quantities_or_graph():
    original = {"nodes": [{"id": "foreground", "process_uuid": "p", "name": "Steel process",
                           "outputs": [{"id": "co2", "flowUuid": "co2", "name": "Carbon dioxide, fossil"}]}]}
    before = deepcopy(original)
    supplier = {"nodes": [{"id": "supply", "process_uuid": "b", "name": "Grid electricity, original dataset",
                           "outputs": [{"id": "co2", "flowUuid": "co2", "name": "Carbon dioxide, fossil"}]}]}
    calls = []
    def get_snapshot(project, version):
        calls.append((project, version))
        return SimpleNamespace(payload={"graph_hash": "pinned-hash", "graph": supplier})
    resolver = MFADisplayGraph(SimpleNamespace(get_provider_model_snapshot=get_snapshot))
    receipts = [{"pin": {"project_id": "supplier", "version": 3, "expected_graph_hash": "pinned-hash", "source_node_id": "supply"},
                 "expanded_node_id": "expanded", "source_process_uuid": "b", "source_model_process_uuid": "b"}]
    display, sources, issues = resolver.enrich(original, receipts)
    assert not issues and sources[0]["version"] == 3 and calls == [("supplier", 3)]
    resolver.enrich(original, receipts)
    assert calls == [("supplier", 3)]
    assert original == before
    solved = {"provider_receipt": {}, "boundary_flows": [
        {"exchange_id": node + "::co2", "process_id": process, "flow_uuid": "co2", "unit_group": "mass",
         "unit": "kg", "direction": "output", "exchange_type": "elementary", "amount": amount}
        for node, process, amount in [("foreground", "p", 10), ("expanded", "b", 2)]]}
    old = build_solved_mfa(solved_snapshot=solved, revision_graph=original)["series"][0]
    new = build_solved_mfa(solved_snapshot=solved, revision_graph=display)["series"][0]
    assert old["totals"] == new["totals"]
    assert [(l["id"], l["source"], l["target"], l["value"]) for l in old["links"]] == [(l["id"], l["source"], l["target"], l["value"]) for l in new["links"]]
    assert {n["id"] for n in old["nodes"]} == {n["id"] for n in new["nodes"]}
    assert next(n for n in new["nodes"] if n["id"] == "process:b")["label"] == supplier["nodes"][0]["name"]
    assert next(n for n in old["nodes"] if n.get("flow_uuid") == "co2")["label"] == "Carbon dioxide, fossil"


def test_display_rejects_changed_exact_hash_and_never_uses_latest():
    calls = []
    def snapshot(project, version):
        calls.append((project, version))
        return SimpleNamespace(payload={"graph_hash": "different-hash", "graph": {"nodes": []}})
    resolver = MFADisplayGraph(SimpleNamespace(get_provider_model_snapshot=snapshot))
    graph = {"nodes": []}
    enriched, sources, issues = resolver.enrich(graph, [{"pin": {
        "project_id": "supplier", "version": 3, "expected_graph_hash": "pinned-hash", "source_node_id": "supply"}}])
    assert enriched == graph and not sources
    assert calls == [("supplier", 3)] and issues[0]["code"] == "MFA_DISPLAY_SOURCE_HASH_MISMATCH"
