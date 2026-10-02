import json
from pathlib import Path

import pytest

from nebula_one.analysis.organization_lifecycle import build_organization_lifecycle
from nebula_one.errors import DomainError


MANIFEST = json.loads((Path(__file__).resolve().parents[1] / "src" / "nebula_one" / "resources" / "official_methods" /
                       "organization-lifecycle-carbon-steel-1.0.2.json").read_text(encoding="utf-8"))["manifest"]
ENERGY_SUBSET_MANIFEST = json.loads((Path(__file__).resolve().parents[1] / "src" / "nebula_one" / "resources" /
                                     "official_methods" / "organization-lifecycle-carbon-steel-1.0.4.json").read_text(encoding="utf-8"))["manifest"]


def _build(*, input_basis="per_unit_product", baseline=1, output=1000, mapped=None, activities=None,
           foreground=1.9, background=0.02, external=None, manifest=None):
    return build_organization_lifecycle(
        application_id="app", revision_id="revision", snapshot_id="snapshot", snapshot_hash="a" * 64,
        period={"id": "period", "name": "2026"}, facility="steel example",
        controlled_process_ids=["sinter", "casting"], model_process_ids=["sinter", "casting"],
        input_basis=input_basis, baseline_output=baseline, period_output=output,
        foreground_value=foreground, background_value=background, climate_unit="kg CO2-Eq",
        native_method={"id": "native", "version": "1", "content_sha256": "b" * 64},
        method_ref="nebula.organization-lifecycle-carbon.steel-model@1.0.2", method_hash="c" * 64,
        manifest=manifest or MANIFEST,
        mapped_exchange_ids=mapped if mapped is not None else ["continuous-casting::grid-electricity-in"],
        external_exchanges=external if external is not None else {"ore-sintering::iron-ore-in": {"amount": 1.49, "unit": "kg", "direction": "input", "flow_uuid": "ore-flow"}},
        activities=activities if activities is not None else [{
            "activity_id": "ore", "category": "purchased_iron_ore", "consumer_exchange_id": "ore-sintering::iron-ore-in",
            "quantity": 1.49 * output / baseline if input_basis == "per_unit_product" else 1.49,
            "activity_unit": "kg", "factor_value": 0.1, "factor_unit": "kg CO2-Eq/kg",
            "factor_version": "source-v1", "factor_source": "illustrative source",
            "factor_boundary": "supplier_cradle_to_gate_excluding_modelled_operations",
            "evidence_sha256": "d" * 64, "evidence_role": "demonstration_proxy", "outside_model": True,
        }],
    )


def test_per_unit_model_scales_each_domain_once_and_keeps_missing_total_open():
    result = _build()
    assert result["groups"]["on_site_direct"]["value"] == 1900
    assert result["groups"]["purchased_energy_lifecycle"]["value"] == 20
    assert result["groups"]["other_value_chain"]["value"] is None
    assert result["groups"]["other_value_chain"]["categories"][0]["proxy_reference_value"] == pytest.approx(149)
    assert result["combined_total"] is None
    assert "natural_gas_upstream" in result["coverage"]["missing_categories"]


def test_annual_total_is_not_scaled_again():
    result = _build(input_basis="annual_total", baseline=1000, output=1000)
    assert result["activity_basis"]["scale_factor"] == 1
    assert result["groups"]["on_site_direct"]["value"] == 1.9
    with pytest.raises(DomainError) as error:
        _build(input_basis="annual_total", baseline=1000, output=2000)
    assert error.value.code == "ORGANIZATION_LIFECYCLE_ANNUAL_RESCALE"


def test_current_model_total_does_not_annualize_or_scale_twice():
    result = _build(input_basis="current_model_total", baseline=2000, output=2000)
    assert result["activity_basis"]["scale_factor"] == 1
    assert result["groups"]["on_site_direct"]["value"] == 1.9
    assert result["reporting_period"]["role"] == "project_context_not_annual_inventory"
    with pytest.raises(DomainError) as error:
        _build(input_basis="current_model_total", baseline=1000, output=2000)
    assert error.value.code == "ORGANIZATION_LIFECYCLE_MODEL_RESCALE"


def test_non_energy_background_and_double_counted_activity_fail_closed():
    with pytest.raises(DomainError) as error:
        _build(mapped=["continuous-casting::grid-electricity-in", "ore-sintering::iron-ore-in"])
    assert error.value.code == "ORGANIZATION_LIFECYCLE_ENERGY_PATH_MISMATCH"
    activity = _build()["groups"]["other_value_chain"]["categories"][0]["proxy_activities"][0]
    with pytest.raises(DomainError) as error:
        _build(activities=[activity, activity])
    assert error.value.code == "ORGANIZATION_LIFECYCLE_OVERLAP"


def test_reviewed_sinter_or_casting_electricity_paths_are_versioned_subsets():
    for mapped in (["ore-sintering::grid-electricity-in"],
                   ["continuous-casting::grid-electricity-in"],
                   ["ore-sintering::grid-electricity-in", "continuous-casting::grid-electricity-in"]):
        result = _build(mapped=mapped, activities=[], manifest=ENERGY_SUBSET_MANIFEST)
        assert result["groups"]["purchased_energy_lifecycle"]["exchange_ids"] == sorted(mapped)
    for mapped in ([], ["ore-sintering::iron-ore-in"],
                   ["ore-sintering::grid-electricity-in", "ore-sintering::grid-electricity-in"]):
        with pytest.raises(DomainError) as error:
            _build(mapped=mapped, activities=[], manifest=ENERGY_SUBSET_MANIFEST)
        assert error.value.code == "ORGANIZATION_LIFECYCLE_ENERGY_PATH_MISMATCH"
    with pytest.raises(DomainError) as error:
        _build(mapped=["ore-sintering::grid-electricity-in"], activities=[], manifest=MANIFEST)
    assert error.value.code == "ORGANIZATION_LIFECYCLE_ENERGY_PATH_MISMATCH"


def test_energy_and_direct_changes_only_affect_their_own_groups():
    first = _build()
    changed_electricity = _build(background=0.03)
    changed_direct = _build(foreground=2.0)
    assert changed_electricity["groups"]["purchased_energy_lifecycle"]["value"] == 30
    assert changed_electricity["groups"]["on_site_direct"] == first["groups"]["on_site_direct"]
    assert changed_electricity["groups"]["other_value_chain"] == first["groups"]["other_value_chain"]
    assert changed_direct["groups"]["on_site_direct"]["value"] == 2000
    assert changed_direct["groups"]["purchased_energy_lifecycle"] == first["groups"]["purchased_energy_lifecycle"]


def test_directly_purchased_fuel_upstream_enters_lc_scope_3_not_energy_group():
    gas = {
        "activity_id": "gas", "category": "natural_gas_upstream",
        "consumer_exchange_id": "blast-furnace::natural-gas-in", "quantity": 8,
        "activity_unit": "kg", "factor_value": 0.2, "factor_unit": "kg CO2-Eq/kg",
        "factor_version": "supplier-v1", "factor_source": "supplier statement",
        "factor_boundary": "upstream_fuel_to_delivery_excluding_onsite_use",
        "evidence_sha256": "e" * 64, "evidence_role": "supplier_specific", "outside_model": True,
        "factor_method_id": "native", "factor_method_version": "1", "factor_method_sha256": "b" * 64,
        "factor_reference_product": "gas-flow",
    }
    result = _build(activities=[gas], external={"blast-furnace::natural-gas-in": {"amount": 0.008, "unit": "kg", "direction": "input", "flow_uuid": "gas-flow"}})
    assert result["groups"]["other_value_chain"]["value"] == pytest.approx(1.6)
    assert result["groups"]["purchased_energy_lifecycle"]["value"] == 20
    mismatched = dict(gas, factor_method_sha256="0" * 64)
    with pytest.raises(DomainError) as error:
        _build(activities=[mismatched], external={"blast-furnace::natural-gas-in": {"amount": 0.008, "unit": "kg", "direction": "input", "flow_uuid": "gas-flow"}})
    assert error.value.code == "ORGANIZATION_LIFECYCLE_METHOD_MISMATCH"
    with pytest.raises(DomainError) as error:
        _build(mapped=["blast-furnace::natural-gas-in"], activities=[])
    assert error.value.code == "ORGANIZATION_LIFECYCLE_ENERGY_PATH_MISMATCH"


def test_declared_external_treatment_can_be_counted_without_counting_internal_link():
    from copy import deepcopy

    manifest = deepcopy(MANIFEST)
    rule = manifest["classification_rules"]["other_value_chain_categories"]["external_waste_treatment"]
    rule["eligible_consumer_exchange_ids"] = ["casting::external-waste-out"]
    waste = {
        "activity_id": "waste", "category": "external_waste_treatment",
        "consumer_exchange_id": "casting::external-waste-out", "quantity": 20,
        "activity_unit": "kg", "factor_value": 0.5, "factor_unit": "kg CO2-Eq/kg",
        "factor_version": "treatment-v1", "factor_source": "external facility statement",
        "factor_boundary": "external_treatment_excluding_modelled_operations",
        "evidence_sha256": "f" * 64, "evidence_role": "supplier_specific", "outside_model": True,
        "factor_method_id": "native", "factor_method_version": "1", "factor_method_sha256": "b" * 64,
        "factor_reference_product": "waste-flow",
    }
    result = _build(activities=[waste], manifest=manifest, external={"casting::external-waste-out": {"amount": 0.02, "unit": "kg", "direction": "output", "flow_uuid": "waste-flow"}})
    assert result["groups"]["other_value_chain"]["value"] == 10
    with pytest.raises(DomainError) as error:
        _build(activities=[waste], manifest=manifest, external={"casting::external-waste-out": {"amount": 0.02, "unit": "kg", "direction": "input"}})
    assert error.value.code == "ORGANIZATION_LIFECYCLE_OVERLAP"


def test_two_distinct_purchases_are_not_deduplicated_by_supplier_identity():
    def coke(activity_id, exchange_id, amount):
        return {
            "activity_id": activity_id, "category": "purchased_coke_upstream",
            "consumer_exchange_id": exchange_id, "quantity": amount * 1000,
            "activity_unit": "kg", "factor_value": 0.2, "factor_unit": "kg CO2-Eq/kg",
            "factor_version": "supplier-v1", "factor_source": "same supplier for both purchases",
            "factor_boundary": "upstream_fuel_to_delivery_excluding_onsite_use",
            "evidence_sha256": "f" * 64, "evidence_role": "supplier_specific", "outside_model": True,
            "factor_method_id": "native", "factor_method_version": "1", "factor_method_sha256": "b" * 64,
            "factor_reference_product": "coke-flow",
        }

    external = {
        "blast-furnace::coke-in": {"amount": 0.4, "unit": "kg", "direction": "input", "flow_uuid": "coke-flow"},
        "ore-sintering::coke-breeze-in": {"amount": 0.06, "unit": "kg", "direction": "input", "flow_uuid": "coke-flow"},
    }
    partial = _build(activities=[coke("furnace", "blast-furnace::coke-in", 0.4)], external=external)
    category = next(row for row in partial["groups"]["other_value_chain"]["categories"]
                    if row["category"] == "purchased_coke_upstream")
    assert category["status"] == "partial_activity"
    complete = _build(activities=[coke("furnace", "blast-furnace::coke-in", 0.4),
                                  coke("sinter", "ore-sintering::coke-breeze-in", 0.06)], external=external)
    category = next(row for row in complete["groups"]["other_value_chain"]["categories"]
                    if row["category"] == "purchased_coke_upstream")
    assert category["value"] == pytest.approx(92)
    assert category["status"] == "calculated"


def test_explicit_boundary_excludes_empty_categories_without_claiming_full_lifecycle():
    from copy import deepcopy

    manifest = deepcopy(json.loads((Path(__file__).resolve().parents[1] / "src" / "nebula_one" /
                                   "resources" / "official_methods" /
                                   "organization-lifecycle-carbon-steel-1.0.3.json").read_text(encoding="utf-8"))["manifest"])
    categories = manifest["classification_rules"]["other_value_chain_categories"]
    manifest["classification_rules"]["other_value_chain_categories"] = {
        key: categories[key] for key in ("external_waste_treatment", "downstream_use")}
    result = _build(manifest=manifest, activities=[], external={})
    assert result["combined_total"] == pytest.approx(1920)
    assert result["coverage"]["missing_categories"] == []
    assert result["coverage"]["not_in_boundary_categories"] == ["external_waste_treatment", "downstream_use"]
    assert result["coverage"]["not_a_complete_lifecycle_inventory"] is True
    categories["external_waste_treatment"]["boundary_status"] = "required_missing"
    result = _build(manifest=manifest, activities=[], external={})
    assert result["combined_total"] is None
    assert result["coverage"]["missing_categories"] == ["external_waste_treatment"]
