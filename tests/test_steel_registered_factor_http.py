"""Portable HTTP regression for registered, test-only steel factor evidence."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from nebula_one.models import Application, SystemModel, SystemRevision
from nebula_one.runtime_models import Period, SolvedSystemSnapshot


METHOD_ROOT = Path(__file__).resolve().parents[1] / "src" / "nebula_one" / "resources" / "official_methods"
CBAM_PACKAGE = json.loads((METHOD_ROOT / "cbam-steel-partial-review-1.0.3.json").read_text(encoding="utf-8"))
ORG_PACKAGE = json.loads((METHOD_ROOT / "organization-lifecycle-carbon-steel-1.0.3.json").read_text(encoding="utf-8"))
CBAM_REF = f"{CBAM_PACKAGE['package_id']}@{CBAM_PACKAGE['version']}"
ORG_REF = f"{ORG_PACKAGE['package_id']}@{ORG_PACKAGE['version']}"


def _register(client, package):
    response = client.post("/api/v1/method-packages", json=package)
    assert response.status_code == 201, response.text
    return response.json()


def test_registered_factors_are_pinned_and_checked_through_http(client, monkeypatch):
    rule = CBAM_PACKAGE["manifest"]["formula_graph"]["indirect_activity"]
    with client.app.state.container.database.session() as db:
        db.add(Application(id="steel-factor-app", name="Test steel", application_type="test",
                           context={"method_package_refs": [CBAM_REF, ORG_REF],
                                    "modeling_template_binding": {"profile": CBAM_PACKAGE["manifest"]["template_profile"]}}))
        db.add(SystemModel(id="steel-factor-model", application_id="steel-factor-app", name="Test model",
                           provider="nebula_lca", provider_base_url="http://engine.test",
                           upstream_project_id="test-only", upstream_version=1,
                           graph_sha256="a" * 64, graph_snapshot={"nodes": [], "exchanges": []}))
        db.add(SystemRevision(id="steel-factor-revision", system_model_id="steel-factor-model",
                              revision_number=1, graph_sha256="a" * 64, content_sha256="b" * 64,
                              graph_snapshot={"nodes": [{"id": "sinter"}, {"id": "casting"}], "exchanges": []}))
        db.add(Period(id="steel-factor-period", application_id="steel-factor-app", key="2026", name="2026",
                      start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), resolution="annual"))
        db.add(SolvedSystemSnapshot(
            id="steel-factor-snapshot", application_id="steel-factor-app",
            system_revision_id="steel-factor-revision", solve_hash="c" * 64,
            provider="nebula_lca", provider_receipt={"calculation_basis": {
                "demand": [{"amount": 1, "unit": "kg"}],
                "mapped_background_process_pins": [{"consumer_exchange_id": "continuous-casting::grid-electricity-in"}]}},
            functional_unit={"amount": 1, "unit": "kg"}, database_release="test-only",
            solver_version="test", activity_vector=[], scaled_technosphere_exchanges=[
                {"exchange_id": rule["consumer_exchange_id"], "process_id": rule["process_uuid"],
                 "flow_uuid": rule["flow_uuid"], "unit": "MJ", "direction": "input", "amount": 0.6,
                 "counterparty_process_id": None},
                {"exchange_id": "ore-sintering::iron-ore-in", "process_id": "sinter",
                 "flow_uuid": "ore-flow", "unit": "kg", "direction": "input", "amount": 1.49,
                 "counterparty_process_id": None},
            ], scaled_elementary_exchanges=[], internal_transfers=[], boundary_flows=[],
            process_balance_residuals=[], contribution_graph={}, lcia_results={}, content_sha256="d" * 64))
        db.commit()
    _register(client, CBAM_PACKAGE)
    _register(client, ORG_PACKAGE)
    container = client.app.state.container
    direct = {"schema_version": "nebula_one.cbam.trial.v2", "status": "trial_passed",
              "content_sha256": "e" * 64, "method_package": CBAM_PACKAGE["manifest"]["formula_graph"]["source_direct_method"],
              "source_snapshot": {"id": "steel-factor-snapshot", "content_sha256": "d" * 64},
              "activity_level": {"source_value": "1.0"},
              "reporting_period": {"id": "steel-factor-period", "start_date": "2026-01-01", "end_date": "2026-12-31"},
              "specific_embedded_emissions": {"value": "1.951739734000", "unit": "t CO2e/t product"}}
    direct["method_package"] = {"ref": direct["method_package"]["reference"],
                                "content_sha256": direct["method_package"]["content_sha256"]}
    monkeypatch.setattr(container.cbam_partial_review.direct, "analyze", lambda *_: direct)
    factor = {"value": "0.42", "unit": "t CO2e/MWh", "good_cn_code": "7207",
              "process_uuid": rule["process_uuid"], "flow_uuid": rule["flow_uuid"],
              "applies_to": rule["applies_to"],
              "boundary": CBAM_PACKAGE["manifest"]["classification_rules"]["factor_boundary"],
              "eligible_partial_method_ref": CBAM_REF,
              "source_evidence": {"document_id": "test-only synthetic fixture", "sha256": "f" * 64}}
    package = {"package_id": "test-only.cbam-electricity", "version": "0.0.1",
               "package_kind": "cbam_electricity_factor", "jurisdiction": "EU",
               "valid_from": "2026-01-01", "valid_to": "2026-12-31",
               "manifest": {**CBAM_PACKAGE["manifest"], "factor": factor, "test_only": True}}
    saved = _register(client, package)
    request = {"method_package_ref": CBAM_REF, "reporting_period_id": "steel-factor-period",
               "boundary_definition_id": "test-only-boundary",
               "eligible_electricity_factor_ref": "test-only.cbam-electricity@0.0.1",
               "condition_declarations": {key: {"status": condition["allowed_statuses"][0]["code"],
                                               "evidence_sha256": "1" * 64}
                                          for key, condition in CBAM_PACKAGE["manifest"]["formula_graph"]["condition_rules"].items()}}
    url = "/api/v1/solved-system-snapshots/steel-factor-snapshot/cbam-partial-review"
    response = client.post(url, json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["components"]["sinter_precursor_indirect"]["value"] == "0.07000000000000000000000000001"
    assert result["specific_embedded_emissions"]["value"] == "2.021739734000000000000000000"
    assert result["claim_boundary"]["complete_cbam_total"] is False
    assert result["components"]["sinter_precursor_indirect"]["eligible_factor"]["package_content_sha256"] == saved["content_sha256"]
    assert client.post(url + "/report.md", json=request).status_code == 200
    changed = deepcopy(package)
    changed["manifest"]["factor"]["value"] = "0.99"
    assert client.post("/api/v1/method-packages", json=changed).status_code == 409
    for label, patch in (("flow", {"flow_uuid": "wrong-flow"}),
                         ("method", {"eligible_partial_method_ref": "wrong@1"})):
        bad_package = deepcopy(package)
        bad_package["package_id"] = f"test-only.cbam-{label}"
        bad_package["manifest"]["factor"].update(patch)
        _register(client, bad_package)
        bad_request = {**request, "eligible_electricity_factor_ref": f"test-only.cbam-{label}@0.0.1"}
        assert client.post(url, json=bad_request).status_code == 422

    answer = SimpleNamespace(merge_status="merged", unified_climate_total=1.92,
                             domains={"foreground": SimpleNamespace(contribution_value=1.9),
                                      "native_background": SimpleNamespace(contribution_value=0.02)},
                             indicator=SimpleNamespace(unit="kg CO2-Eq"))
    native_request = SimpleNamespace(method_package_id="native", method_package_version="1",
                                     method_package_sha256="2" * 64, runtime_manifest_sha256="3" * 64)
    monkeypatch.setattr(container.organization_lifecycle.native, "_frozen_answer",
                        lambda *_: (None, None, answer, native_request))
    org_factor = {"consumer_exchange_id": "ore-sintering::iron-ore-in", "reference_flow_uuid": "ore-flow",
                  "value": 0.1, "unit": "kg CO2-Eq/kg",
                  "boundary": "supplier_cradle_to_gate_excluding_modelled_operations",
                  "evidence_role": "supplier_specific",
                  "evidence": {"source": "test-only supplier fixture", "sha256": "4" * 64},
                  "climate_method": {"id": "native", "version": "1", "content_sha256": "2" * 64}}
    org_package = {"package_id": "test-only.organization-factor", "version": "0.0.1",
                   "package_kind": "organization_lifecycle_factor", "jurisdiction": None,
                   "valid_from": "2026-01-01", "valid_to": "2026-12-31",
                   "manifest": {**ORG_PACKAGE["manifest"], "factor": org_factor, "test_only": True}}
    org_saved = _register(client, org_package)
    activity = {"activity_id": "ore", "category": "purchased_iron_ore",
                "consumer_exchange_id": "ore-sintering::iron-ore-in", "quantity": 1490,
                "activity_unit": "kg", "factor_value": 0.1, "factor_unit": "kg CO2-Eq/kg",
                "factor_version": "0.0.1", "factor_source": "test-only supplier fixture",
                "factor_boundary": org_factor["boundary"], "evidence_sha256": "4" * 64,
                "evidence_role": "supplier_specific", "outside_model": True,
                "factor_package_ref": "test-only.organization-factor@0.0.1",
                "factor_method_id": "native", "factor_method_version": "1",
                "factor_method_sha256": "2" * 64, "factor_reference_product": "ore-flow"}
    org_request = {"solved_snapshot_id": "steel-factor-snapshot", "method_package_ref": ORG_REF,
                   "reporting_period_id": "steel-factor-period", "facility": "test-only",
                   "controlled_process_ids": ["sinter", "casting"], "input_basis": "per_unit_product",
                   "period_product_output": 1000, "other_activities": [activity]}
    org_url = "/api/v1/applications/steel-factor-app/organization-lifecycle-inventories"
    response = client.post(org_url, json=org_request)
    assert response.status_code == 201, response.text
    record = response.json()
    ore_row = record["result"]["groups"]["other_value_chain"]["categories"][0]
    assert ore_row["value"] == 149
    assert ore_row["activities"][0]["factor_package_sha256"] == org_saved["content_sha256"]
    assert client.get(org_url + "/" + record["id"]).json()["content_sha256"] == record["content_sha256"]
    assert client.get(org_url + "/" + record["id"] + "/report.html").status_code == 200
    for field, value in (("factor_value", 0.2), ("factor_method_id", "wrong"),
                         ("consumer_exchange_id", "blast-furnace::natural-gas-in")):
        changed_request = deepcopy(org_request)
        changed_request["other_activities"][0][field] = value
        assert client.post(org_url, json=changed_request).status_code == 422
