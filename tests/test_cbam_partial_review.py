import json
from pathlib import Path

import pytest

from nebula_one.analysis.cbam_partial_review import build_cbam_partial_review
from nebula_one.errors import DomainError


MANIFEST = json.loads((Path(__file__).resolve().parents[1] / "src" / "nebula_one" /
                       "resources" / "official_methods" / "cbam-steel-partial-review-1.0.1.json")
                      .read_text(encoding="utf-8"))["manifest"]
SOURCE = MANIFEST["formula_graph"]["source_direct_method"]
ELECTRICITY = MANIFEST["formula_graph"]["indirect_activity"]


def _review(sinter_mj=0.6, casting_mj=0.027):
    snapshot = {"id": "snapshot", "content_sha256": "a" * 64,
                "system_revision_id": "revision", "scaled_technosphere_exchanges": [
                    {"exchange_id": ELECTRICITY["consumer_exchange_id"],
                     "process_id": ELECTRICITY["process_uuid"], "flow_uuid": ELECTRICITY["flow_uuid"],
                     "unit": "MJ", "direction": "input", "amount": sinter_mj},
                    {"exchange_id": "continuous-casting::grid-electricity-in",
                     "process_id": "continuous-casting", "flow_uuid": ELECTRICITY["flow_uuid"],
                     "unit": "MJ", "direction": "input", "amount": casting_mj},
                ]}
    direct = {"schema_version": "nebula_one.cbam.trial.v2", "status": "trial_passed",
              "content_sha256": "b" * 64, "method_package": {"ref": SOURCE["reference"],
                                                         "content_sha256": SOURCE["content_sha256"]},
              "source_snapshot": {"id": "snapshot", "content_sha256": "a" * 64},
              "activity_level": {"source_value": "1.0"},
              "reporting_period": {"id": "period"},
              "specific_embedded_emissions": {"value": "1.951739734000",
                                              "unit": "t CO2e/t product"}}
    return build_cbam_partial_review(snapshot=snapshot, direct=direct,
                                     method_ref="cbam.eu.iron-steel.bf-bof-partial-review@1.0.1",
                                     method_hash="c" * 64, manifest=MANIFEST)


def test_sinter_electricity_is_pending_term_and_total_is_not_invented():
    result = _review()
    assert result["components"]["sinter_precursor_indirect"]["electricity_activity"]["value"] == "0.1666666666666666666666666667"
    assert result["components"]["sinter_precursor_indirect"]["eligible_factor"] is None
    assert result["specific_embedded_emissions"]["value"] is None
    assert result["components"]["direct"]["value"] == "1.951739734000"


def test_sinter_activity_changes_pending_term_but_casting_activity_does_not():
    base = _review()
    more_sinter = _review(sinter_mj=0.9)
    more_casting = _review(casting_mj=0.5)
    activity = lambda result: result["components"]["sinter_precursor_indirect"]["electricity_activity"]["value"]
    assert activity(base) != activity(more_sinter)
    assert activity(base) == activity(more_casting)


def test_user_supply_co2_is_separate_trial_evidence_and_never_fills_cbam_total():
    from decimal import Decimal
    co2 = "08a91e70-3ddc-11dd-923d-0050c2490048"
    amount = Decimal("610") / Decimal("3.6") * Decimal("0.5306")
    snapshot = {"id": "snapshot", "content_sha256": "a" * 64, "system_revision_id": "revision",
        "scaled_technosphere_exchanges": [{"exchange_id": ELECTRICITY["consumer_exchange_id"],
            "process_id": ELECTRICITY["process_uuid"], "flow_uuid": ELECTRICITY["flow_uuid"],
            "unit": "MJ", "direction": "input", "amount": 610}],
        "scaled_elementary_exchanges": [{"exchange_id": "expanded::co2", "process_id": "supply-process",
            "flow_uuid": co2, "direction": "output", "unit": "kg", "amount": str(amount)}],
        "provider_receipt": {"project_background_process_receipts": [{
            "pin": {"consumer_exchange_id": ELECTRICITY["consumer_exchange_id"],
                    "project_id": "my-supply", "version": 3},
            "source_graph_hash": "c" * 64, "source_process_uuid": "supply-process",
            "expanded_node_id": "expanded"}],
            "elementary_flow_receipts": [{"exchange_id": "expanded::co2",
                                          "content_hash": "d" * 64, "snapshot_hash": "e" * 64}]}}
    direct = {"schema_version": "nebula_one.cbam.trial.v2", "status": "trial_passed",
        "content_sha256": "b" * 64, "method_package": {"ref": SOURCE["reference"],
            "content_sha256": SOURCE["content_sha256"]},
        "source_snapshot": {"id": "snapshot", "content_sha256": "a" * 64},
        "activity_level": {"source_value": "1000"}, "reporting_period": {"id": "period"},
        "specific_embedded_emissions": {"value": "1.941739734", "unit": "t CO2e/t product"},
        "attributed_emissions": {"direct": {"exchanges": [
            {"flow_identity": {"flow_uuid": co2}}]}}}
    result = build_cbam_partial_review(snapshot=snapshot, direct=direct,
        method_ref="cbam.eu.iron-steel.bf-bof-partial-review@1.0.1", method_hash="f" * 64,
        manifest=MANIFEST)
    trial = result["components"]["user_supply_electricity_trial"]
    assert Decimal(trial["source_amount"]) == amount
    assert Decimal(trial["value"]) == amount / Decimal("1000")
    assert result["components"]["direct"]["value"] == "1.941739734"
    assert result["specific_embedded_emissions"]["value"] is None


def test_direct_method_identity_must_be_exact():
    wrong = json.loads(json.dumps(MANIFEST))
    wrong["formula_graph"]["source_direct_method"]["content_sha256"] = "d" * 64
    with pytest.raises(DomainError) as error:
        snapshot = {"id": "snapshot", "content_sha256": "a" * 64,
                    "system_revision_id": "revision", "scaled_technosphere_exchanges": []}
        direct = {"method_package": {"ref": SOURCE["reference"],
                                     "content_sha256": SOURCE["content_sha256"]}}
        build_cbam_partial_review(snapshot=snapshot, direct=direct, method_ref="ref",
                                  method_hash="c" * 64, manifest=wrong)
    assert error.value.code == "CBAM_PARTIAL_DIRECT_METHOD_MISMATCH"


def test_pinned_eligible_factor_calculates_indirect_and_only_declared_total():
    new_manifest = json.loads((Path(__file__).resolve().parents[1] / "src" / "nebula_one" /
                               "resources" / "official_methods" / "cbam-steel-partial-review-1.0.3.json")
                              .read_text(encoding="utf-8"))["manifest"]
    electricity = new_manifest["formula_graph"]["indirect_activity"]
    snapshot = {"id": "snapshot", "content_sha256": "a" * 64, "system_revision_id": "revision",
                "scaled_technosphere_exchanges": [{"exchange_id": electricity["consumer_exchange_id"],
                    "process_id": electricity["process_uuid"], "flow_uuid": electricity["flow_uuid"],
                    "unit": "MJ", "direction": "input", "amount": 0.6}]}
    direct = {"schema_version": "nebula_one.cbam.trial.v2", "status": "trial_passed",
              "content_sha256": "b" * 64, "method_package": {"ref": SOURCE["reference"],
                  "content_sha256": SOURCE["content_sha256"]},
              "source_snapshot": {"id": "snapshot", "content_sha256": "a" * 64},
              "activity_level": {"source_value": "1.0"},
              "reporting_period": {"id": "period", "start_date": "2026-01-01", "end_date": "2026-12-31"},
              "specific_embedded_emissions": {"value": "1.951739734000", "unit": "t CO2e/t product"}}
    method_ref = "cbam.eu.iron-steel.bf-bof-partial-review@1.0.3"
    factor = {"reference": "test.cbam.factor@1", "content_sha256": "c" * 64,
              "valid_from": "2026-01-01", "valid_to": "2026-12-31", "manifest": {"factor": {
                  "value": "0.42", "unit": "t CO2e/MWh", "good_cn_code": "7207",
                  "process_uuid": electricity["process_uuid"], "flow_uuid": electricity["flow_uuid"],
                  "applies_to": electricity["applies_to"],
                  "boundary": new_manifest["classification_rules"]["factor_boundary"],
                  "eligible_partial_method_ref": method_ref,
                  "source_evidence": {"document_id": "test-only", "sha256": "d" * 64}}}}
    build = lambda **kwargs: build_cbam_partial_review(snapshot=snapshot, direct=direct,
        method_ref=method_ref, method_hash="e" * 64, manifest=new_manifest, **kwargs)
    partial = build(factor_package=factor)
    assert partial["components"]["sinter_precursor_indirect"]["value"] == "0.07000000000000000000000000001"
    assert partial["specific_embedded_emissions"]["value"] is None
    declarations = {key: {"status": new_manifest["formula_graph"]["condition_rules"][key]["allowed_statuses"][0]["code"],
                          "evidence_sha256": "f" * 64}
                    for key in new_manifest["formula_graph"]["required_condition_keys"]}
    complete = build(factor_package=factor, condition_declarations=declarations)
    assert complete["specific_embedded_emissions"]["value"] == "2.021739734000000000000000000"
    assert complete["claim_boundary"]["not_a_cbam_declaration"] is True
    assert complete["claim_boundary"]["complete_cbam_total"] is False
    all_not_applicable = {key: {"status": "not_applicable", "evidence_sha256": "f" * 64}
                          for key in declarations}
    with pytest.raises(DomainError) as error:
        build(factor_package=factor, condition_declarations=all_not_applicable)
    assert error.value.code == "CBAM_PARTIAL_CONDITIONS_INVALID"
    for key in declarations:
        illegal = {**declarations, key: {"status": "satisfied", "evidence_sha256": "f" * 64}}
        with pytest.raises(DomainError) as error:
            build(factor_package=factor, condition_declarations=illegal)
        assert error.value.code == "CBAM_PARTIAL_CONDITIONS_INVALID"
    with pytest.raises(DomainError) as error:
        build(factor_package={**factor, "valid_to": "2026-06-30"}, condition_declarations=declarations)
    assert error.value.code == "CBAM_ELECTRICITY_FACTOR_INAPPLICABLE"
