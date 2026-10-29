"""Accounting equivalence at the rule/weighted-contribution seam, not live-engine proof."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nebula_one.analysis.method_path_grouping import group_path_weighted_scopes
from nebula_one.analysis.organization_lifecycle import build_organization_lifecycle
from nebula_one.analysis.organization_user_method import apply_organization_user_method
from nebula_one.analysis.method_selectors import compile_accounting_selectors, SCHEMA_VERSION
from nebula_one.errors import DomainError
from nebula_one.services.template_accounting_methods import model_ports, transcribe_official_rules

ROOT = Path(__file__).resolve().parents[1]


def test_official_controlled_foreground_copy_preserves_scope1_and_energy_scopes():
    graph = json.loads((ROOT / "cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/graph.json").read_text(encoding="utf-8"))["graph"]
    package = json.loads((ROOT / "src/nebula_one/resources/official_methods/organization-lifecycle-carbon-steel-1.0.10.json").read_text(encoding="utf-8"))
    ports = model_ports(graph)
    before = deepcopy(package)
    copied = transcribe_official_rules(package["package_kind"], package["manifest"], ports, "official@1.0.10")
    direct = [p for p in ports if p["direction"] == "emission"]
    rules = {r["exchange_id"]: r for r in copied["rules"]}
    assert direct
    assert all(rules[p["exchange_id"]]["scope"] == "scope_1" for p in direct)
    assert all(rules[p["exchange_id"]]["contribution_target"] == "direct" for p in direct)
    energy = package["manifest"]["classification_rules"]["energy_purchase_exchange_ids"]
    assert all(rules[key]["scope"] == "scope_2" for key in energy)
    assert not any(rules.get(p["exchange_id"], {}).get("scope") == "scope_1"
                   for p in ports if p["direction"] in {"input", "output"})

    # Same already-characterized numbers enter both paths. No factors or engine are mocked here:
    # these are synthetic receipt values to isolate classification from characterization.
    values = {p["exchange_id"]: index + 1.0 for index, p in enumerate(direct)}
    rows = [{"exchange_id": key, "path_contribution_value": value,
             "attribution_basis": "foreground_direct"} for key, value in values.items()]
    rows.extend({"exchange_id": f"supplier-{i}::co2", "consumer_exchange_id": key,
                 "path_contribution_value": value, "attribution_basis": "background_consumer_path"}
                for i, (key, value) in enumerate(zip(energy, [3.947199, 94.732787])))
    scaled = [{"exchange_id": p["exchange_id"], "process_id": p["process_id"],
               "flow_uuid": p["flow_uuid"], "direction": "output", "exchange_type": "elementary"}
              for p in direct]
    result = group_path_weighted_scopes(rules=copied["rules"], scaled_exchanges=scaled,
                                       path_receipt={"terms": rows}, indicator_unit="kg CO2-Eq")
    assert result["scopes"]["scope_1"]["value"] == sum(values.values())
    assert result["scopes"]["scope_2"]["value"] == pytest.approx(98.679986)
    assert result["excluded"]["value"] == 0
    assert result["unattributed"]["value"] == 0
    assert result["reconciled"]
    assert package == before


def test_unsupported_control_mode_is_reported_instead_of_silently_omitting_scope1():
    copied = transcribe_official_rules("organization_lifecycle_carbon",
        {"classification_rules": {"controlled_process_mode": "guess_from_process_name"}}, [], "official@1")
    assert "PACKAGE_CONTROL_MODE_UNSUPPORTED" in {note["code"] for note in copied["notes"]}


def test_official_cbam_direct_universe_equals_a_data_defined_selector_without_source_widening():
    graph = json.loads((ROOT / "cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/graph.json").read_text(encoding="utf-8"))["graph"]
    profile = json.loads((ROOT / "cases/project-templates/steel-bf-bof-inventory/template.json").read_text(encoding="utf-8"))
    manifest = next(item["package"]["manifest"] for item in profile["method_replacements"]
                    if item["package"]["package_kind"] == "cbam_trial")
    ports = model_ports(graph)
    declarations = manifest["classification_rules"]["direct_emissions"]
    definition = {"schema_version": SCHEMA_VERSION, "selectors": [{"id": "direct", "match": {
        "exchange_ids": sorted(item["exchange_id"] for item in declarations), "directions": ["emission"]},
        "classification": {"boundary_status": "selected", "scope": "scope_1", "location_role": "onsite", "cbam_relevant": True}}]}
    compiled = compile_accounting_selectors(definition, ports, "official@1")
    copied = transcribe_official_rules("cbam_trial", manifest, ports, "official@1")
    direct = [rule for rule in copied["rules"] if rule["cbam_relevant"]]
    assert len(direct) == 6
    assert sorted(direct, key=lambda rule: rule["exchange_id"]) == compiled["rules"]
    product = copied["reference_product_exchange_id"]
    assert product not in {rule["exchange_id"] for rule in compiled["rules"]}
    broken = deepcopy(manifest)
    broken["classification_rules"]["direct_emissions"][0]["flow_uuid"] = "another-gas"
    with pytest.raises(DomainError) as error:
        transcribe_official_rules("cbam_trial", broken, ports, "official@1")
    assert error.value.code == "ACCOUNTING_SELECTOR_MATCH_EMPTY"


@pytest.mark.parametrize("basis,baseline,output", [("current_model_total", 1000, 1000),
                                                  ("per_unit_product", 1000, 2000)])
def test_official_organization_and_transcribed_method_have_equal_groups_and_period_basis(basis, baseline, output):
    graph = json.loads((ROOT / "cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/graph.json").read_text(encoding="utf-8"))["graph"]
    package = json.loads((ROOT / "src/nebula_one/resources/official_methods/organization-lifecycle-carbon-steel-1.0.10.json").read_text(encoding="utf-8"))
    manifest = package["manifest"]
    ports = model_ports(graph)
    transcribed = transcribe_official_rules(package["package_kind"], manifest, ports, "official@1.0.10")
    direct = [p for p in ports if p["direction"] == "emission"]
    direct_values = {p["exchange_id"]: i + 1.0 for i, p in enumerate(direct)}
    categories = manifest["classification_rules"]["other_value_chain_categories"]
    suppliers = [dict(category=category, consumer_exchange_id=key, status="calculated", contribution_value=10.0)
                 for category, rule in categories.items() for key in rule["eligible_consumer_exchange_ids"]]
    energy_ids = manifest["classification_rules"]["energy_purchase_exchange_ids"]
    energy = [dict(consumer_exchange_id=key, status="calculated", contribution_value=3.0) for key in energy_ids]
    rows = [dict(exchange_id=key, path_contribution_value=value, attribution_basis="foreground_direct")
            for key, value in direct_values.items()]
    rows += [dict(exchange_id=f"supplier-{i}::co2", consumer_exchange_id=row["consumer_exchange_id"],
                  path_contribution_value=row["contribution_value"], attribution_basis="background_consumer_path")
             for i, row in enumerate([*energy, *suppliers])]
    source = dict(indicator_key="climate", suppliers=[*energy, *suppliers], energy_suppliers=energy,
                  category_suppliers=suppliers)
    old = build_organization_lifecycle(application_id="app", revision_id="rev", snapshot_id="snap",
        snapshot_hash="a" * 64, period={"id": "period"}, facility="site",
        controlled_process_ids=[n["id"] for n in graph["nodes"]],
        model_process_ids=[n["id"] for n in graph["nodes"]], input_basis=basis,
        baseline_output=baseline, period_output=output, foreground_value=sum(direct_values.values()),
        background_value=sum(row["contribution_value"] for row in energy), climate_unit="kg CO2-Eq",
        native_method={}, method_ref="official@1.0.10", method_hash="b" * 64, manifest=manifest,
        mapped_exchange_ids=energy_ids, external_exchanges={p["exchange_id"]: p for p in ports if p["direction"] == "input"},
        activities=[], climate_source=source)
    snapshot = SimpleNamespace(system_revision_id="rev", provider_receipt={"user_calculation_method": {
        "purpose": "organization", "model_revision_id": "rev", "method_id": "copy", "version": 1,
        "content_sha256": "c" * 64, "rules": transcribed["rules"],
        "reporting_dimensions": transcribed["reporting_dimensions"]}},
        scaled_elementary_exchanges=[dict(exchange_id=p["exchange_id"], process_id=p["process_id"],
            flow_uuid=p["flow_uuid"], direction="output", exchange_type="elementary") for p in direct],
        lcia_results={"path_weighted_contribution_receipts": [dict(canonical_indicator_key="climate", terms=rows)]})
    result = apply_organization_user_method(deepcopy(old), snapshot)
    for key in ("on_site_direct", "purchased_energy_lifecycle", "other_value_chain"):
        assert result["groups"][key]["value"] == old["groups"][key]["value"]
    assert result["activity_basis"] == old["activity_basis"]
    assert result["combined_total"] == old["combined_total"]
    assert result["user_method_grouping"]["grouping"]["excluded"]["value"] == 0
    assert result["user_method_grouping"]["grouping"]["unattributed"]["value"] == 0
