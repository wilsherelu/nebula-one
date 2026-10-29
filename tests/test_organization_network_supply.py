"""E1: a closed multi-node background network must aggregate per consumer path, once."""
from copy import deepcopy
from json import loads
from pathlib import Path
from types import SimpleNamespace

import pytest

from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.services.organization_project_supply import project_supply_climate

_ROOT = Path(__file__).resolve().parents[1] / "src" / "nebula_one" / "resources" / "official_methods"
LEAF_MANIFEST = loads((_ROOT / "organization-lifecycle-carbon-steel-1.0.5.json").read_text(encoding="utf-8"))["manifest"]


def _network_manifest():
    """A method that explicitly accepts both leaf and closed-network background claims."""
    manifest = deepcopy(LEAF_MANIFEST)
    manifest["classification_rules"]["accepted_project_claim_roles"] = [
        "user_declared_partial_background_leaf", "user_declared_partial_background_network"]
    return manifest


def test_explicit_frozen_user_path_accepts_network_without_modifying_official_manifest():
    snapshot,revision,_ = _network_source()
    before=deepcopy(LEAF_MANIFEST)
    with pytest.raises(DomainError): project_supply_climate(snapshot,revision,LEAF_MANIFEST)
    answer=project_supply_climate(snapshot,revision,LEAF_MANIFEST,
        user_network_paths={'ore-sintering::grid-electricity-in'})
    assert answer[1]==pytest.approx(101.66666666666667)
    assert answer[4]['user_rule_network_paths']==['ore-sintering::grid-electricity-in']
    assert LEAF_MANIFEST==before
    with pytest.raises(DomainError):
        project_supply_climate(snapshot,revision,LEAF_MANIFEST,user_network_paths={'other::port'})


def _network_source(process_terms=("supply-process-entry", "supply-process-mid")):
    """One network pin (entry + one internal node) feeding a single purchased-energy port.

    `process_terms` selects which supply node rows the engine actually characterized with a
    contribution term. The real Tiangong grid network emits a term only for the generating node,
    while a lossless internal transport node carries none — so a caller can reproduce either shape.
    """
    node_values = {"supply-process-entry": 61.66666666666667, "supply-process-mid": 40.0}
    pin = {"schema_version": "provider.project-background-pin.v1",
           "consumer_exchange_id": "ore-sintering::grid-electricity-in", "project_id": "supply-network",
           "version": 2, "expected_graph_hash": "a" * 64, "source_node_id": "bg-entry",
           "reference_port_id": "electricity-out", "provider_amount_per_consumer_unit": 1 / 3.6,
           "claim_role": "user_declared_partial_background_network"}
    claim = "user_declared_partial_background_closed_network"
    entry = {"pin": pin, "expanded_node_id": "bg-entry", "source_node_id": "bg-entry",
             "expanded_network_node_ids": ["bg-entry", "bg-mid"], "source_process_uuid": "supply-process-entry",
             "source_graph_hash": "a" * 64, "claim_limit": claim, "reference_flow_uuid": "electricity-flow",
             "reference_unit": "kWh", "consumer_unit": "MJ", "unit_conversion_factor": 1 / 3.6,
             "activity_amount": 610 / 3.6}
    mid = {"pin": pin, "expanded_node_id": "bg-mid", "source_node_id": "bg-mid",
           "expanded_network_node_ids": ["bg-entry", "bg-mid"], "source_process_uuid": "supply-process-mid",
           "source_graph_hash": "a" * 64, "claim_limit": claim, "reference_flow_uuid": "electricity-flow",
           "reference_unit": "kWh", "consumer_unit": "MJ", "unit_conversion_factor": 1 / 3.6,
           "activity_amount": 300 / 3.6}
    key = LEAF_MANIFEST["formula_graph"]["total_indicator_key"]
    terms = [{"process_uuid": "steel-process", "contribution_value": 1941.739734,
              "contribution_unit": "kg CO2-Eq", "cf_method": "EF v3.1", "cf_presence": "explicit_nonzero",
              "cf_runtime_assets_hash": "b" * 64}]
    background = 0.0
    for process_id in process_terms:
        value = node_values[process_id]
        background += value
        terms.append({"process_uuid": process_id, "contribution_value": value,
                      "contribution_unit": "kg CO2-Eq", "cf_method": "EF v3.1", "cf_presence": "explicit_nonzero",
                      "cf_runtime_assets_hash": "b" * 64})
    total = 1941.739734 + background
    climate = {"schema_version": "provider.lcia.indicator-contribution-receipt.v1",
               "canonical_indicator_key": key, "method": "EF v3.1", "indicator_unit": "kg CO2-Eq",
               "indicator_value": total, "contribution_total": total, "terms": terms}
    climate["content_hash"] = canonical_json_sha256(climate)
    snapshot = SimpleNamespace(
        native_background_climate=None,
        internal_transfers=[{"exchange_id": "bg-entry::electricity-out", "process_id": "supply-process-entry",
                             "flow_uuid": "electricity-flow", "direction": "output", "unit_group": "energy",
                             "unit": "kWh", "amount": 610 / 3.6},
                            {"exchange_id": "ore-sintering::grid-electricity-in", "process_id": "steel-process",
                             "flow_uuid": "electricity-flow", "direction": "input", "unit_group": "energy",
                             "unit": "MJ", "amount": 610}],
        provider_receipt={"calculation_basis": {"project_background_pins": [pin]},
                          "project_background_process_receipts": [entry, mid],
                          "provenance": {"project_background_pins_hash": canonical_json_sha256([pin])}},
        lcia_results={"method": "EF v3.1", "database_release": "EF3.1", "runtime_assets_hash": "b" * 64,
                      "indicator_contribution_receipts": [climate],
                      "contribution_receipts_hash": canonical_json_sha256([climate]),
                      "indicator_results": [{"canonical_indicator_key": key, "unit": "kg CO2-Eq",
                                             "value": total}]})
    revision = SimpleNamespace(graph_snapshot={"nodes": [{"process_uuid": "steel-process"}]})
    return snapshot, revision, background


def test_closed_network_multi_node_aggregates_by_consumer_path_once():
    snapshot, revision, background = _network_source()
    foreground, bg, unit, _method, source, mapped = project_supply_climate(
        snapshot, revision, _network_manifest())
    assert foreground == pytest.approx(1941.739734)
    assert bg == pytest.approx(101.66666666666667) == pytest.approx(background)  # entry + mid, each counted once
    assert mapped == ["ore-sintering::grid-electricity-in"]
    # Downstream must see ONE row per consumer path (network collapsed), like a leaf.
    assert len(source["suppliers"]) == 1
    assert source["suppliers"][0]["consumer_exchange_id"] == "ore-sintering::grid-electricity-in"
    assert source["suppliers"][0]["contribution_value"] == pytest.approx(101.66666666666667)
    nodes = {row["process_uuid"]: row["contribution_value"] for row in source["suppliers"][0]["network_nodes"]}
    assert nodes == {"supply-process-entry": pytest.approx(61.66666666666667),
                     "supply-process-mid": pytest.approx(40.0)}


def test_closed_network_with_one_uncharacterized_node_aggregates_partial():
    # The real Tiangong grid network: only the generating node carries a climate term, the lossless
    # internal transport node carries none. The engine's per-path sum is authoritative, so the path
    # must report the characterized node's value (not null, not raise) flagged as partial.
    snapshot, revision, _background = _network_source(process_terms=("supply-process-entry",))
    foreground, bg, unit, _method, source, mapped = project_supply_climate(
        snapshot, revision, _network_manifest())
    assert bg == pytest.approx(61.66666666666667)
    supplier = source["suppliers"][0]
    assert supplier["contribution_value"] == pytest.approx(61.66666666666667)
    assert supplier["status"] == "partial_characterization"
    by_node = {row["process_uuid"]: (row["status"], row["contribution_value"])
               for row in supplier["network_nodes"]}
    assert by_node["supply-process-entry"] == ("calculated", pytest.approx(61.66666666666667))
    assert by_node["supply-process-mid"][0] == "contribution_terms_missing"
    assert by_node["supply-process-mid"][1] is None


def test_closed_network_with_no_characterized_node_is_a_gap():
    # If no network node carries any term, the path contributes nothing and the leaf-only method
    # still treats an uncharacterized supplier as a structural mismatch, never a silent zero.
    snapshot, revision, _background = _network_source(process_terms=())
    with pytest.raises(DomainError) as caught:
        project_supply_climate(snapshot, revision, _network_manifest())
    assert caught.value.code == "ORGANIZATION_PROJECT_SUPPLY_TOTAL_MISMATCH"


def test_closed_network_not_claimed_by_official_leaf_only_method():
    snapshot, revision, _background = _network_source()
    with pytest.raises(DomainError) as caught:
        project_supply_climate(snapshot, revision, LEAF_MANIFEST)
    assert caught.value.code in {"ORGANIZATION_PROJECT_SUPPLY_IDENTITY_INVALID",
                                 "ORGANIZATION_PROJECT_SUPPLY_SOURCE_INVALID"}


def test_report_reconciles_network_node_terms_to_group_total():
    # A collapsed network supplier keeps only the boundary process on its row, but the engine
    # receipt emits one term per emitting node. The frozen report must classify every node term
    # into the purchased-energy group so the detail sum reconciles to the group total; before the
    # network-aware fix the non-boundary node fell through as "unassigned", its value dropped, and
    # organization_report raised REPORT_CONTRIBUTIONS_DO_NOT_RECONCILE.
    from nebula_one.analysis.frozen_report import organization_report
    indicator = LEAF_MANIFEST["formula_graph"]["total_indicator_key"]
    graph = {"nodes": [{"id": "steel-node", "process_uuid": "steel-process"},
                       {"id": "bg-entry", "process_uuid": "supply-process-entry"},
                       {"id": "bg-mid", "process_uuid": "supply-process-mid"}]}
    receipt = {"canonical_indicator_key": indicator, "terms": [
        {"process_uuid": "steel-process", "exchange_id": "steel::out", "contribution_value": 100.0,
         "contribution_unit": "kg CO2-Eq", "cf_presence": "explicit_nonzero", "amount": 1, "amount_unit": "kg"},
        {"process_uuid": "supply-process-entry", "exchange_id": "bg-entry::electricity-out",
         "contribution_value": 61.66666666666667, "contribution_unit": "kg CO2-Eq",
         "cf_presence": "explicit_nonzero", "amount": 1, "amount_unit": "kWh"},
        {"process_uuid": "supply-process-mid", "exchange_id": "bg-mid::electricity-out",
         "contribution_value": 40.0, "contribution_unit": "kg CO2-Eq",
         "cf_presence": "explicit_nonzero", "amount": 1, "amount_unit": "kWh"}]}
    snapshot = {"lcia_results": {"indicator_contribution_receipts": [receipt]}}
    result = {
        "activity_basis": {"scale_factor": 1.0},
        "organizational_boundary": {"controlled_process_ids": ["steel-node"]},
        "groups": {
            "on_site_direct": {"value": 100.0, "unit": "kg CO2-Eq", "status": "calculated"},
            "purchased_energy_lifecycle": {"value": 101.66666666666667, "unit": "kg CO2-Eq", "status": "calculated"},
            "other_value_chain": {"value": None, "unit": "kg CO2-Eq", "categories": [], "status": "configured_categories"},
        },
        "coverage": {"missing_categories": []},
        "combined_total": 201.66666666666667,
        "climate_source": {
            "indicator_key": indicator,
            "suppliers": [{"consumer_exchange_id": "ore-sintering::grid-electricity-in",
                           "process_uuid": "supply-process-entry",
                           "network_nodes": [{"process_uuid": "supply-process-entry", "status": "calculated"},
                                             {"process_uuid": "supply-process-mid", "status": "contribution_terms_missing"}]}],
        },
    }
    report = organization_report(result, snapshot, graph, {"fields": []})
    grouped: dict[str, float] = {}
    for row in report["details"]:
        if row["contribution_value"] is not None:
            grouped[row["group"]] = grouped.get(row["group"], 0.0) + row["contribution_value"]
    assert grouped["purchased_energy_lifecycle"] == pytest.approx(101.66666666666667)
    assert grouped["on_site_direct"] == pytest.approx(100.0)
    assert "unassigned" not in grouped


@pytest.mark.parametrize("mutate", [
    # two node rows claim the same expanded node id (missing a distinct network node)
    lambda s: s.provider_receipt["project_background_process_receipts"][1].update(expanded_node_id="bg-entry"),
    # a node row loses the shared network node list (mapping not expressible)
    lambda s: s.provider_receipt["project_background_process_receipts"][1].update(expanded_network_node_ids=["bg-mid"]),
    # two rows point at the same source process (contribution would double count)
    lambda s: s.provider_receipt["project_background_process_receipts"][1].update(source_process_uuid="supply-process-entry"),
    # no row is the declared entry node (boundary to the consumer is ambiguous)
    lambda s: s.provider_receipt["project_background_process_receipts"][0].update(source_node_id="bg-mid"),
])
def test_closed_network_with_missing_or_ambiguous_mapping_is_rejected(mutate):
    snapshot, revision, _background = _network_source()
    mutate(snapshot)
    snapshot.provider_receipt["provenance"]["project_background_pins_hash"] = canonical_json_sha256(
        snapshot.provider_receipt["calculation_basis"]["project_background_pins"])
    with pytest.raises(DomainError):
        project_supply_climate(snapshot, revision, _network_manifest())
