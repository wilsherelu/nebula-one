"""R5: a user method applied to PCF re-aggregates frozen contributions, never re-solves.

These assert the two-operation boundary the plan requires. Choosing or re-classifying an
already-computed contribution consumes the solve's own contributions and re-buckets them;
it does NOT delete a technosphere node, and a partial selection is never scaled up into a
complete product footprint. The three method versions A/B/C share one exact solve, so the
counted totals reconcile against a single fixed engine contribution pool.
"""

from __future__ import annotations

from nebula_one.analysis.pcf import _attach_pcf_user_method_grouping

PROVIDER = "provider-uuid-process-1"
INDICATOR = "GWP-fossil"
UNIT = "kg CO2e"

SCALED_EXCHANGES = [
    {"exchange_id": "core::co2-a", "process_id": PROVIDER, "flow_uuid": "flow-co2", "direction": "output"},
    {"exchange_id": "bg::co2-b", "process_id": PROVIDER, "flow_uuid": "flow-co2", "direction": "output"},
]


def _analysis():
    return {
        "status": "available",
        "coverage": "exact_exchange_contributions",
        "hotspots": [
            {"exchange_id": "core::co2-a", "contribution_value": 100.0},
            {"exchange_id": "bg::co2-b", "contribution_value": 30.0},
        ],
    }


def _row(exchange_id, value, *, basis, share=None, consumer_process_uuid=None):
    return {
        "exchange_id": exchange_id,
        "path_contribution_value": value,
        "attribution_basis": basis,
        "path_share": share,
        "consumer_exchange_id": f"{consumer_process_uuid}::in" if consumer_process_uuid else None,
        "consumer_process_uuid": consumer_process_uuid,
        "provider_instance_id": exchange_id,
        "process_uuid": PROVIDER,
    }


PATH_TERMS = [
    _row("core::co2-a", 100.0, basis="foreground_direct"),
    _row("bg::co2-b", 10.0, basis="background_consumer_path", share=1/3, consumer_process_uuid="consumer-a"),
    _row("bg::co2-b", 20.0, basis="background_consumer_path", share=2/3, consumer_process_uuid="consumer-b"),
]

LCIA = {"path_weighted_contribution_receipts": [{
    "canonical_indicator_key": INDICATOR,
    "indicator_unit": UNIT,
    "attribution_coverage": "complete",
    "terms": PATH_TERMS,
}]}


def _rule(process_instance_id, exchange_id, *, boundary_status="selected", scope="scope_1"):
    return {
        "process_instance_id": process_instance_id,
        "exchange_id": exchange_id,
        "flow_uuid": None,
        "direction": None,
        "boundary_status": boundary_status,
        "scope": scope,
        "location_role": "onsite",
        "cbam_relevant": False,
        "classification_basis": "user",
    }


def _receipt(rules):
    return {"user_calculation_method": {
        "method_id": "pcf-m", "version": 1, "content_sha256": "b" * 64,
        "model_revision_id": "rev-1",
        "execution_plan_sha256": "d" * 64,
        "compiler_version": "nebula_one.method-compiler.v1",
        "rules": rules,
    }}


def _apply(rules):
    analysis = _analysis()
    out = _attach_pcf_user_method_grouping(
        contribution_analysis=analysis,
        provider_receipt=_receipt(rules),
        scaled_elementary_exchanges=SCALED_EXCHANGES,
        lcia_results=LCIA,
        indicator_key=INDICATOR,
        indicator_unit=UNIT,
    )
    return out["user_method_grouping"]


def test_a_includes_selected_foreground_and_background_paths():
    block = _apply([_rule("core", "core::co2-a"), _rule("bg", "bg::co2-b")])
    assert block["grouping_mode"] == "path_weighted"
    grouping = block["grouping"]
    assert grouping["scopes"]["scope_1"]["value"] == 130.0
    assert grouping["reconciled"] is True
    assert grouping["contribution_total"] == 130.0
    # a method view is never itself a completeness claim for the PCF
    assert block["counts_as_complete_pcf"] is False
    # R6: the PCF grouping identity names the exact compiled plan + compiler it consumed.
    assert block["method"]["execution_plan_sha256"] == "d" * 64
    assert block["method"]["compiler_version"] == "nebula_one.method-compiler.v1"


def test_b_excluding_one_background_path_changes_only_that_counted_amount():
    a = _apply([_rule("core", "core::co2-a"), _rule("bg", "bg::co2-b")])
    b = _apply([_rule("core", "core::co2-a"), _rule("bg", "bg::co2-b", boundary_status="excluded", scope=None)])
    # the whole bg::co2-b emission (both its consumer paths) leaves the counted total
    assert a["grouping"]["scopes"]["scope_1"]["value"] - b["grouping"]["scopes"]["scope_1"]["value"] == 30.0
    assert b["grouping"]["excluded"]["value"] == 30.0
    # the engine pool is fixed across A and B: counted + excluded always equals the known total
    for block in (a, b):
        g = block["grouping"]
        assert g["contribution_total"] == 130.0
        assert g["scopes"]["scope_1"]["value"] + g["excluded"]["value"] + g["unattributed"]["value"] == 130.0


def test_c_reclassifying_a_path_moves_category_but_keeps_the_total():
    a = _apply([_rule("core", "core::co2-a"), _rule("bg", "bg::co2-b", scope="scope_1")])
    c = _apply([_rule("core", "core::co2-a"), _rule("bg", "bg::co2-b", scope="scope_3")])
    assert a["grouping"]["scopes"]["scope_1"]["value"] == 130.0
    assert c["grouping"]["scopes"]["scope_1"]["value"] == 100.0
    assert c["grouping"]["scopes"]["scope_3"]["value"] == 30.0
    # identical totals, only the category moved — and A's result is not overwritten by C
    assert a["grouping"]["contribution_total"] == c["grouping"]["contribution_total"] == 130.0


def test_engine_unattributed_path_is_a_reported_gap_not_folded_into_a_category():
    terms = [
        _row("bg::co2-b", 10.0, basis="background_consumer_path", share=0.5, consumer_process_uuid="consumer-a"),
        _row("bg::co2-b", 20.0, basis="background_unattributed"),
    ]
    lcia = {"path_weighted_contribution_receipts": [{
        "canonical_indicator_key": INDICATOR, "indicator_unit": UNIT,
        "attribution_coverage": "partial", "terms": terms,
    }]}
    block = None
    analysis = _analysis()
    out = _attach_pcf_user_method_grouping(
        contribution_analysis=analysis,
        provider_receipt=_receipt([_rule("bg", "bg::co2-b", scope="scope_3")]),
        scaled_elementary_exchanges=SCALED_EXCHANGES,
        lcia_results=lcia,
        indicator_key=INDICATOR,
        indicator_unit=UNIT,
    )
    block = out["user_method_grouping"]
    g = block["grouping"]
    assert g["scopes"]["scope_3"]["value"] == 10.0
    assert g["engine_gap"]["value"] == 20.0
    assert block["execution_status"] == "executed_partial"
    assert g["reconciled"] is True


def test_no_user_method_leaves_pcf_contributions_untouched():
    analysis = _analysis()
    out = _attach_pcf_user_method_grouping(
        contribution_analysis=analysis,
        provider_receipt={"elementary_flow_receipts": []},
        scaled_elementary_exchanges=SCALED_EXCHANGES,
        lcia_results=LCIA,
        indicator_key=INDICATOR,
        indicator_unit=UNIT,
    )
    assert "user_method_grouping" not in out


def test_coverage_separates_uncharacterized_from_true_zero_and_background_gaps():
    """Four gap reasons stay four rows: no factor, no background link, a true zero, no rule yet.

    The reader must never see them collapsed into one "not set" bucket, and a flow the method
    characterized as zero is a real zero — reporting it as a missing factor would be a false claim.
    """
    scaled = [
        {"exchange_id": "core::co2-a", "process_id": PROVIDER, "flow_uuid": "flow-co2",
         "direction": "output", "amount": 100.0},
        # in the inventory with a real quantity but absent from the receipt: no factor at all
        {"exchange_id": "core::ch4-a", "process_id": PROVIDER, "flow_uuid": "flow-ch4",
         "direction": "output", "amount": 2.0},
        # a zero-quantity flow contributes nothing either way, so it is not a missing factor
        {"exchange_id": "core::n2o-a", "process_id": PROVIDER, "flow_uuid": "flow-n2o",
         "direction": "output", "amount": 0.0},
        {"exchange_id": "bg::co2-b", "process_id": PROVIDER, "flow_uuid": "flow-co2",
         "direction": "output", "amount": 30.0},
    ]
    zero_row = dict(_row("core::sf6-a", 0.0, basis="foreground_direct"), cf_presence="explicit_zero")
    characterized = [dict(row, cf_presence="explicit_nonzero") for row in PATH_TERMS]
    lcia = {"path_weighted_contribution_receipts": [{
        "canonical_indicator_key": INDICATOR,
        "indicator_unit": UNIT,
        "attribution_coverage": "complete",
        "terms": [*characterized, zero_row],
    }]}
    out = _attach_pcf_user_method_grouping(
        contribution_analysis=_analysis(),
        provider_receipt=_receipt([_rule("core", "core::co2-a"), _rule("bg", "bg::co2-b")]),
        scaled_elementary_exchanges=scaled,
        lcia_results=lcia,
        indicator_key=INDICATOR,
        indicator_unit=UNIT,
    )
    coverage = out["user_method_grouping"]["coverage"]
    assert coverage["uncharacterized_exchange_ids"] == ["core::ch4-a"]
    assert coverage["zero_cf_exchange_ids"] == ["core::sf6-a"]
    assert coverage["engine_gap_exchange_ids"] == []
    # the zero-factor flow also has no rule yet; the two reasons are reported side by side, not merged
    assert coverage["unattributed_exchange_ids"] == ["core::sf6-a"]
    # the extra reporting rows are informational: the reconciliation invariant is untouched
    grouping = out["user_method_grouping"]["grouping"]
    assert grouping["reconciled"] is True
    assert grouping["contribution_total"] == 130.0
    assert grouping["scopes"]["scope_1"]["value"] == 130.0
