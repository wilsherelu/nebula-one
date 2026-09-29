from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nebula_one.analysis.organization_lifecycle import build_organization_lifecycle
from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.services.organization_project_supply import project_supply_climate


MANIFEST = json.loads((Path(__file__).resolve().parents[1] / "src" / "nebula_one" / "resources" /
                       "official_methods" / "organization-lifecycle-carbon-steel-1.0.5.json").read_text(encoding="utf-8"))["manifest"]


def _source():
    pin = {"schema_version": "provider.project-background-pin.v1",
           "consumer_exchange_id": "ore-sintering::grid-electricity-in", "project_id": "supply-project",
           "version": 2, "expected_graph_hash": "a" * 64, "reference_port_id": "electricity-out",
           "provider_amount_per_consumer_unit": 1 / 3.6,
           "claim_role": "user_declared_partial_background_leaf"}
    source = {"pin": pin, "expanded_node_id": "project-background-1",
              "source_process_uuid": "supply-process", "source_graph_hash": "a" * 64,
              "reference_flow_uuid": "electricity-flow", "reference_unit": "kWh",
              "consumer_unit": "MJ", "unit_conversion_factor": 1 / 3.6,
              "activity_amount": 610 / 3.6}
    key = MANIFEST["formula_graph"]["total_indicator_key"]
    terms = [{"process_uuid": "steel-process", "contribution_value": 1941.739734,
              "contribution_unit": "kg CO2-Eq", "cf_method": "EF v3.1",
              "cf_presence": "explicit_nonzero", "cf_runtime_assets_hash": "b" * 64},
             {"process_uuid": "supply-process", "contribution_value": 101.66666666666667,
              "contribution_unit": "kg CO2-Eq", "cf_method": "EF v3.1",
              "cf_presence": "explicit_nonzero", "cf_runtime_assets_hash": "b" * 64}]
    climate = {"schema_version": "provider.lcia.indicator-contribution-receipt.v1",
               "canonical_indicator_key": key, "method": "EF v3.1", "indicator_unit": "kg CO2-Eq",
               "indicator_value": 2043.4064006666667, "contribution_total": 2043.4064006666667,
               "terms": terms}
    climate["content_hash"] = canonical_json_sha256(climate)
    snapshot = SimpleNamespace(
        native_background_climate=None,
        internal_transfers=[{"exchange_id": "project-background-1::electricity-out",
                             "process_id": "supply-process", "flow_uuid": "electricity-flow",
                             "direction": "output", "unit_group": "energy", "unit": "kWh", "amount": 610 / 3.6},
                            {"exchange_id": "ore-sintering::grid-electricity-in",
                             "process_id": "steel-process", "flow_uuid": "electricity-flow",
                             "direction": "input", "unit_group": "energy", "unit": "MJ", "amount": 610}],
        provider_receipt={"calculation_basis": {"project_background_pins": [pin]},
                          "project_background_process_receipts": [source],
                          "provenance": {"project_background_pins_hash": canonical_json_sha256([pin])}},
        lcia_results={"method": "EF v3.1", "database_release": "EF3.1",
                      "runtime_assets_hash": "b" * 64,
                      "indicator_contribution_receipts": [climate],
                      "contribution_receipts_hash": canonical_json_sha256([climate]),
                      "indicator_results": [{"canonical_indicator_key": key,
                                             "unit": "kg CO2-Eq", "value": 2043.4064006666667}]},
    )
    revision = SimpleNamespace(graph_snapshot={"nodes": [{"process_uuid": "steel-process"}]})
    return snapshot, revision


def test_project_supply_groups_exact_climate_once_and_keeps_scope_3_missing():
    snapshot, revision = _source()
    foreground, background, unit, method, source, exchange_ids = project_supply_climate(snapshot, revision, MANIFEST)
    result = build_organization_lifecycle(
        application_id="app", revision_id="revision", snapshot_id="snapshot", snapshot_hash="c" * 64,
        period={"id": "period", "name": "2026"}, facility="steel", controlled_process_ids=["steel-process"],
        model_process_ids=["steel-process"], input_basis="annual_total", baseline_output=1000,
        period_output=1000, foreground_value=foreground, background_value=background,
        climate_unit=unit, native_method=method,
        method_ref="nebula.organization-lifecycle-carbon.steel-model@1.0.5", method_hash="d" * 64,
        manifest=MANIFEST, mapped_exchange_ids=exchange_ids,
        external_exchanges={"ore-sintering::iron-ore-in": {"amount": 10, "unit": "kg", "direction": "input"}},
        activities=[], climate_source=source)
    assert result["schema_version"] == "nebula_one.organization-lifecycle-carbon.v2"
    assert result["groups"]["on_site_direct"]["value"] == pytest.approx(1941.739734)
    assert result["groups"]["purchased_energy_lifecycle"]["value"] == pytest.approx(101.66666666666667)
    assert result["groups"]["other_value_chain"]["value"] is None
    assert result["combined_total"] is None
    assert result["climate_source"]["suppliers"][0]["version"] == 2


@pytest.mark.parametrize("mutate", [
    lambda s: s.provider_receipt["project_background_process_receipts"][0].update(source_graph_hash="0" * 64),
    lambda s: s.lcia_results["indicator_contribution_receipts"][0]["terms"][1].update(process_uuid="unknown"),
    lambda s: s.lcia_results["indicator_contribution_receipts"][0]["terms"][1].update(cf_presence="implicit_zero"),
])
def test_project_supply_refuses_drift_and_unclassified_climate(mutate):
    snapshot, revision = deepcopy(_source())
    mutate(snapshot)
    with pytest.raises(DomainError):
        project_supply_climate(snapshot, revision, MANIFEST)
