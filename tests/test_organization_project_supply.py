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
OPTIONAL_MANIFEST = json.loads((Path(__file__).resolve().parents[1] / "src" / "nebula_one" / "resources" /
                                "official_methods" / "organization-lifecycle-carbon-steel-1.0.6.json").read_text(encoding="utf-8"))["manifest"]
NO_CF_MANIFEST = json.loads((Path(__file__).resolve().parents[1] / "src" / "nebula_one" / "resources" /
                             "official_methods" / "organization-lifecycle-carbon-steel-1.0.7.json").read_text(encoding="utf-8"))["manifest"]
CATEGORY_MANIFEST = json.loads((Path(__file__).resolve().parents[1] / "src" / "nebula_one" / "resources" /
                               "official_methods" / "organization-lifecycle-carbon-steel-1.0.9.json").read_text(encoding="utf-8"))["manifest"]


def _rehash(snapshot):
    receipt = snapshot.lcia_results["indicator_contribution_receipts"][0]
    total = sum(term["contribution_value"] for term in receipt["terms"])
    receipt["indicator_value"] = receipt["contribution_total"] = total
    receipt["content_hash"] = canonical_json_sha256({k: v for k, v in receipt.items() if k != "content_hash"})
    snapshot.lcia_results["contribution_receipts_hash"] = canonical_json_sha256([receipt])
    snapshot.lcia_results["indicator_results"][0]["value"] = total
    pins = snapshot.provider_receipt["calculation_basis"]["project_background_pins"]
    snapshot.provider_receipt["provenance"]["project_background_pins_hash"] = canonical_json_sha256(pins)


def _with_category_supplier(port="blast-furnace::coke-in"):
    snapshot, revision = _source()
    # Distinct expansion instances may legally use the same exact supplier project.
    source = deepcopy(snapshot.provider_receipt["project_background_process_receipts"][0])
    source.update(expanded_node_id="project-background-2", source_process_uuid="supply-process-2")
    source["pin"]["consumer_exchange_id"] = port
    snapshot.provider_receipt["project_background_process_receipts"].append(source)
    snapshot.provider_receipt["calculation_basis"]["project_background_pins"].append(source["pin"])
    supplier, consumer = deepcopy(snapshot.internal_transfers)
    supplier.update(exchange_id="project-background-2::electricity-out", process_id="supply-process-2")
    consumer["exchange_id"] = port
    snapshot.internal_transfers.extend([supplier, consumer])
    term = deepcopy(snapshot.lcia_results["indicator_contribution_receipts"][0]["terms"][1])
    term.update(process_uuid="supply-process-2", contribution_value=25)
    snapshot.lcia_results["indicator_contribution_receipts"][0]["terms"].append(term)
    _rehash(snapshot)
    return snapshot, revision


def _category_result(snapshot, revision, manifest=CATEGORY_MANIFEST, scale=1, activities=None):
    foreground, background, unit, method, source, paths = project_supply_climate(snapshot, revision, manifest)
    return build_organization_lifecycle(
        application_id="app", revision_id="revision", snapshot_id="snapshot", snapshot_hash="c" * 64,
        period={"id": "period", "name": "2026"}, facility="steel", controlled_process_ids=["steel-process"],
        model_process_ids=["steel-process"], input_basis="current_model_total" if scale == 1 else "per_unit_product",
        baseline_output=1000, period_output=1000 * scale, foreground_value=foreground, background_value=background,
        climate_unit=unit, native_method=method, method_ref="test@1.0.9", method_hash="d" * 64,
        manifest=manifest, mapped_exchange_ids=paths,
        external_exchanges={port: {"amount": 610, "unit": "MJ", "direction": "input"}
            for port in ["blast-furnace::coke-in", "ore-sintering::coke-breeze-in"]},
        activities=activities or [], climate_source=source)


@pytest.mark.parametrize("scale", [1, 2])
def test_category_receipts_group_shared_supplier_by_port_once_and_preserve_missing_port(scale):
    snapshot, revision = _with_category_supplier()
    result = _category_result(snapshot, revision, scale=scale)
    groups = result["groups"]
    assert groups["on_site_direct"]["value"] == pytest.approx(1941.739734 * scale)
    assert groups["purchased_energy_lifecycle"]["value"] == pytest.approx(101.66666666666667 * scale)
    assert groups["other_value_chain"]["value"] == 25 * scale
    coke = next(row for row in groups["other_value_chain"]["categories"] if row["category"] == "purchased_coke_upstream")
    assert coke["status"] == "partial_activity"
    assert coke["missing_exchange_ids"] == ["ore-sintering::coke-breeze-in"]
    assert coke["supply_receipts"][0]["project_id"] == result["climate_source"]["energy_suppliers"][0]["project_id"]
    assert result["combined_total"] is None
    assert result["activity_basis"]["scale_factor"] == scale


@pytest.mark.parametrize("presence,expected,status", [("explicit_zero", 0, "calculated"), ("implicit_zero", None, "method_has_no_cf")])
def test_supplier_zero_cf_is_distinct_from_absent_cf(presence, expected, status):
    snapshot, revision = _with_category_supplier()
    term = snapshot.lcia_results["indicator_contribution_receipts"][0]["terms"][-1]
    term.update(contribution_value=0, cf_presence=presence, cf_value=0, flow_uuid="non-target-flow",
                exchange_id="supplier::trace-out", cf_source_runtime_ids=[])
    _rehash(snapshot)
    result = _category_result(snapshot, revision)
    assert result["groups"]["other_value_chain"]["value"] == expected
    assert result["climate_source"]["category_suppliers"][0]["status"] == status


def test_category_receipt_partial_characterization_keeps_known_subtotal():
    snapshot, revision = _with_category_supplier()
    _add_no_cf_term(snapshot)
    term = snapshot.lcia_results["indicator_contribution_receipts"][0]["terms"][-1]
    term["process_uuid"] = "supply-process-2"
    _rehash(snapshot)
    result = _category_result(snapshot, revision)
    assert result["groups"]["other_value_chain"]["value"] == 25
    assert result["climate_source"]["category_suppliers"][0]["status"] == "partial_characterization"
    assert result["combined_total"] is None


def test_method_cannot_assign_energy_port_to_nonenergy_category():
    snapshot, revision = _source()
    manifest = deepcopy(CATEGORY_MANIFEST)
    manifest["classification_rules"]["other_value_chain_categories"]["purchased_coke_upstream"]["eligible_consumer_exchange_ids"].append("ore-sintering::grid-electricity-in")
    with pytest.raises(DomainError) as caught:
        project_supply_climate(snapshot, revision, manifest)
    assert caught.value.code == "ORGANIZATION_LIFECYCLE_OVERLAP"


def test_category_contract_keeps_exact_receipt_hash_validation():
    snapshot, revision = _with_category_supplier()
    snapshot.lcia_results["indicator_contribution_receipts"][0]["terms"][-1]["contribution_value"] = 99
    with pytest.raises(DomainError) as caught:
        project_supply_climate(snapshot, revision, CATEGORY_MANIFEST)
    assert caught.value.code == "ORGANIZATION_PROJECT_SUPPLY_CLIMATE_INVALID"


def test_absent_supplier_terms_are_missing_evidence_not_method_no_cf():
    snapshot, revision = _with_category_supplier()
    snapshot.lcia_results["indicator_contribution_receipts"][0]["terms"].pop()
    _rehash(snapshot)
    result = _category_result(snapshot, revision)
    assert result["climate_source"]["category_suppliers"][0]["status"] == "contribution_terms_missing"
    assert result["groups"]["other_value_chain"]["value"] is None


def test_factor_cannot_duplicate_solved_nonenergy_port():
    snapshot, revision = _with_category_supplier()
    with pytest.raises(DomainError) as caught:
        _category_result(snapshot, revision, activities=[{"category": "purchased_coke_upstream",
            "consumer_exchange_id": "blast-furnace::coke-in"}])
    assert caught.value.code == "ORGANIZATION_LIFECYCLE_OVERLAP"


def test_old_method_keeps_nonenergy_unassigned_and_report_keeps_receipt_identity():
    from nebula_one.exports.organization_lifecycle import render_organization_lifecycle_html
    snapshot, revision = _with_category_supplier()
    _, _, _, _, old_source, paths = project_supply_climate(snapshot, revision, NO_CF_MANIFEST, retain_unsupported_paths=True)
    assert old_source["unassigned_suppliers"][0]["consumer_exchange_id"] == "blast-furnace::coke-in"
    assert paths == ["ore-sintering::grid-electricity-in"]
    result = _category_result(snapshot, revision)
    html = render_organization_lifecycle_html({"result": result, "content_sha256": result["content_sha256"]})
    assert "blast-furnace::coke-in" in html and "supply-project@2" in html
    assert "{categories}" not in html


def _add_no_cf_term(snapshot, flow_uuid="non-target-flow", contribution=0):
    receipt = snapshot.lcia_results["indicator_contribution_receipts"][0]
    receipt["terms"].append({"process_uuid": "supply-process", "exchange_id": "supplier::trace-out",
        "flow_uuid": flow_uuid, "flow_version": "01.00.001", "amount": 0.25, "amount_unit": "kg",
        "contribution_value": contribution, "contribution_unit": "kg CO2-Eq", "cf_method": "EF v3.1",
        "cf_presence": "implicit_zero", "cf_value": 0, "cf_source_runtime_ids": [],
        "cf_runtime_assets_hash": "b" * 64})
    receipt["content_hash"] = canonical_json_sha256({k:v for k,v in receipt.items() if k != "content_hash"})
    snapshot.lcia_results["contribution_receipts_hash"] = canonical_json_sha256([receipt])


def test_non_target_no_cf_keeps_inventory_identity_without_blocking_characterized_result():
    snapshot, revision = _source()
    _add_no_cf_term(snapshot)
    foreground, background, _, _, source, _ = project_supply_climate(snapshot, revision, NO_CF_MANIFEST)
    assert foreground == 1941.739734
    assert background == 101.66666666666667
    assert source["uncharacterized_terms"] == [{"process_uuid": "supply-process",
        "exchange_id": "supplier::trace-out", "flow_uuid": "non-target-flow", "flow_version": "01.00.001",
        "amount": 0.25, "amount_unit": "kg", "status": "method_has_no_cf", "numeric_contribution": None}]
    assert len(snapshot.lcia_results["indicator_contribution_receipts"][0]["terms"]) == 3
    with pytest.raises(DomainError) as caught:
        project_supply_climate(snapshot, revision, OPTIONAL_MANIFEST)
    assert caught.value.code == "ORGANIZATION_PROJECT_SUPPLY_CF_INVALID"


@pytest.mark.parametrize('flow, contribution', [('08a91e70-3ddc-11dd-923d-0050c2490048', 0), ('non-target-flow', 1)])
def test_required_climate_flow_or_nonzero_no_cf_cannot_be_accepted_as_zero(flow, contribution):
    snapshot, revision = _source()
    _add_no_cf_term(snapshot, flow, contribution)
    with pytest.raises(DomainError) as caught:
        project_supply_climate(snapshot, revision, NO_CF_MANIFEST)
    assert caught.value.code == "ORGANIZATION_PROJECT_SUPPLY_CF_INVALID"


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


def test_valid_unsupported_supply_keeps_direct_results_and_audited_contribution():
    snapshot, revision = _source()
    manifest = deepcopy(MANIFEST)
    # The source remains valid, but this method has no classification for its path.
    manifest["classification_rules"]["energy_purchase_exchange_ids"] = []
    foreground, background, _, _, source, exchange_ids = project_supply_climate(
        snapshot, revision, manifest, retain_unsupported_paths=True)
    assert foreground == 1941.739734
    assert background == 0
    assert exchange_ids == []
    assert source["unassigned_suppliers"][0]["contribution_value"] == pytest.approx(101.66666666666667)
    assert source["unassigned_suppliers"][0]["numeric_contribution"] is None
    snapshot.lcia_results["contribution_receipts_hash"] = "invalid"
    with pytest.raises(DomainError) as error:
        project_supply_climate(snapshot, revision, manifest, retain_unsupported_paths=True)
    assert error.value.code == "ORGANIZATION_PROJECT_SUPPLY_CLIMATE_INVALID"


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


def test_optional_supply_keeps_foreground_and_marks_unlinked_energy_unknown():
    snapshot, revision = deepcopy(_source())
    snapshot.provider_receipt["calculation_basis"]["project_background_pins"] = []
    snapshot.provider_receipt["project_background_process_receipts"] = []
    snapshot.provider_receipt["provenance"] = {}
    snapshot.internal_transfers = []
    climate = snapshot.lcia_results["indicator_contribution_receipts"][0]
    climate["terms"] = climate["terms"][:1]
    climate["indicator_value"] = climate["contribution_total"] = 1941.739734
    climate.pop("content_hash")
    climate["content_hash"] = canonical_json_sha256(climate)
    snapshot.lcia_results["indicator_results"][0]["value"] = 1941.739734
    snapshot.lcia_results["contribution_receipts_hash"] = canonical_json_sha256([climate])
    foreground, background, unit, method, source, exchange_ids = project_supply_climate(
        snapshot, revision, OPTIONAL_MANIFEST)
    result = build_organization_lifecycle(
        application_id="app", revision_id="revision", snapshot_id="snapshot", snapshot_hash="c" * 64,
        period={"id": "period", "name": "2026"}, facility="steel", controlled_process_ids=["steel-process"],
        model_process_ids=["steel-process"], input_basis="annual_total", baseline_output=1000,
        period_output=1000, foreground_value=foreground, background_value=background,
        climate_unit=unit, native_method=method,
        method_ref="nebula.organization-lifecycle-carbon.steel-model@1.0.6", method_hash="d" * 64,
        manifest=OPTIONAL_MANIFEST, mapped_exchange_ids=exchange_ids,
        external_exchanges={"ore-sintering::iron-ore-in": {"amount": 10, "unit": "kg", "direction": "input"}},
        activities=[], climate_source=source)
    assert result["groups"]["on_site_direct"]["value"] == pytest.approx(1941.739734)
    assert result["groups"]["purchased_energy_lifecycle"]["value"] is None
    assert result["groups"]["purchased_energy_lifecycle"]["status"] == "missing_energy_path"
    assert result["coverage"]["missing_energy_paths"] == sorted(OPTIONAL_MANIFEST["classification_rules"]["energy_purchase_exchange_ids"])
    assert result["combined_total"] is None
    with pytest.raises(DomainError):
        project_supply_climate(snapshot, revision, MANIFEST)


def test_partial_energy_cannot_form_total_even_when_scope_3_is_outside_boundary():
    manifest = deepcopy(OPTIONAL_MANIFEST)
    for rule in manifest["classification_rules"]["other_value_chain_categories"].values():
        rule.update(boundary_status="not_in_boundary", eligible_consumer_exchange_ids=[])
    result = build_organization_lifecycle(
        application_id="app", revision_id="revision", snapshot_id="snapshot", snapshot_hash="c" * 64,
        period={"id": "period", "name": "2026"}, facility="steel", controlled_process_ids=["steel-process"],
        model_process_ids=["steel-process"], input_basis="annual_total", baseline_output=1000,
        period_output=1000, foreground_value=100, background_value=10,
        climate_unit="kg CO2-Eq", native_method={}, method_ref="test@1", method_hash="d" * 64,
        manifest=manifest, mapped_exchange_ids=["ore-sintering::grid-electricity-in"],
        external_exchanges={}, activities=[], climate_source={})
    assert result["coverage"]["missing_categories"] == []
    assert result["coverage"]["missing_energy_paths"] == ["continuous-casting::grid-electricity-in"]
    assert result["groups"]["purchased_energy_lifecycle"]["value"] == 10
    assert result["combined_total"] is None
    assert result["coverage"]["status"] == "partial"


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
