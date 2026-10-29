"""R1: a referenced user method must actually move the reported org Scope numbers.

The provenance-only pass recorded the user's rules but never consumed them here. These
assert the vertical seam inside ``build_carbon_management``'s own attribution output: the
method's include/exclude is grouped over the SAME weighted per-exchange contributions the
engine returned, an excluded path's value leaves the Scope bucket and lands in ``excluded``
(no technosphere node is deleted, nothing is zeroed), a path without a weighted value is a
reported coverage gap, and a snapshot with no user method keeps its exact prior shape.
"""

from __future__ import annotations

from nebula_one.analysis.carbon_management import _attach_user_method_grouping

SHARED_PROVIDER = "provider-uuid-process-1"

SCALED_EXCHANGES = [
    {"exchange_id": "sinter::co2-a", "process_id": SHARED_PROVIDER, "flow_uuid": "flow-co2", "direction": "output"},
    {"exchange_id": "steel::co2-b", "process_id": SHARED_PROVIDER, "flow_uuid": "flow-co2", "direction": "output"},
]

# carbon_attribution.hotspots is what _contribution_attribution already validated one-to-one
# against the scaled elementary exchanges and the frozen LCIA contribution total.
def _attribution(hotspots):
    return {
        "coverage": "exact_contributions",
        "indicator_receipt": {"unit": "kg CO2e", "term_count": len(hotspots)},
        "categories": [
            {"category": "direct", "value": sum(h["contribution_value"] for h in hotspots), "unit": "kg CO2e"}
        ],
        "hotspots": hotspots,
        "scope_1_2_3_statement": False,
    }


HOTSPOTS = [
    {"exchange_id": "sinter::co2-a", "contribution_value": 100.0},
    {"exchange_id": "steel::co2-b", "contribution_value": 30.0},
]


def _rule(process_instance_id, exchange_id, *, boundary_status="selected", scope="scope_1", location_role="onsite"):
    return {
        "process_instance_id": process_instance_id,
        "exchange_id": exchange_id,
        "flow_uuid": None,
        "direction": None,
        "boundary_status": boundary_status,
        "scope": scope,
        "location_role": location_role,
        "cbam_relevant": False,
        "classification_basis": "user",
    }


def _method(rules, *, method_id="m1", version=1, content_sha256="a" * 64):
    return {
        "user_calculation_method": {
            "method_id": method_id,
            "version": version,
            "content_sha256": content_sha256,
            "model_revision_id": "rev-1",
            "execution_plan_sha256": "c" * 64,
            "compiler_version": "nebula_one.method-compiler.v1",
            "rules": rules,
        }
    }


def _attach(provider_receipt, scaled=SCALED_EXCHANGES, *, lcia_results=None, indicator_key=None):
    attribution = _attach_user_method_grouping(
        carbon_attribution=_attribution(HOTSPOTS),
        provider_receipt=provider_receipt,
        scaled_elementary_exchanges=scaled,
        lcia_results=lcia_results,
        indicator_key=indicator_key,
    )
    return attribution


def _path_row(exchange_id, value, *, basis, share=None, consumer_exchange_id=None, consumer_process_uuid=None):
    return {
        "exchange_id": exchange_id,
        "path_contribution_value": value,
        "attribution_basis": basis,
        "path_share": share,
        "consumer_exchange_id": consumer_exchange_id,
        "consumer_process_uuid": consumer_process_uuid,
        "provider_instance_id": exchange_id,
        "process_uuid": SHARED_PROVIDER,
    }


def _lcia_path_receipt(terms, *, indicator_key="GWP-fossil", coverage="complete"):
    return {
        "path_weighted_contribution_receipts": [{
            "canonical_indicator_key": indicator_key,
            "indicator_unit": "kg CO2e",
            "attribution_coverage": coverage,
            "terms": terms,
        }]
    }


def test_run_without_a_user_method_keeps_the_exact_prior_shape():
    attribution = _attach({"elementary_flow_receipts": []})
    assert "user_method_grouping" not in attribution


def test_including_every_path_reports_a_full_grouping_of_the_engine_values():
    attribution = _attach(_method([_rule("sinter", "sinter::co2-a"), _rule("steel", "steel::co2-b")]))
    block = attribution["user_method_grouping"]
    assert block["execution_status"] == "executed_full"
    assert block["method"]["method_id"] == "m1"
    assert block["grouping"]["scopes"]["scope_1"]["value"] == 130.0
    assert block["grouping"]["reconciled"] is True
    # R6: the grouping identity names the exact compiled plan + compiler that produced it.
    assert block["method"]["execution_plan_sha256"] == "c" * 64
    assert block["method"]["compiler_version"] == "nebula_one.method-compiler.v1"


def test_excluding_one_path_moves_exactly_that_contribution_out_of_the_scope():
    included = _attach(_method([_rule("sinter", "sinter::co2-a"), _rule("steel", "steel::co2-b")]))
    excluded = _attach(
        _method([_rule("sinter", "sinter::co2-a"), _rule("steel", "steel::co2-b", boundary_status="excluded", scope=None)])
    )
    scope_before = included["user_method_grouping"]["grouping"]["scopes"]["scope_1"]["value"]
    scope_after = excluded["user_method_grouping"]["grouping"]["scopes"]["scope_1"]["value"]
    assert scope_before - scope_after == 30.0
    assert excluded["user_method_grouping"]["grouping"]["excluded"]["value"] == 30.0
    # The engine's own totals are untouched by the grouping — only the bucket moved.
    assert included["user_method_grouping"]["grouping"]["contribution_total"] == excluded["user_method_grouping"]["grouping"]["contribution_total"] == 130.0


def test_referenced_purchased_energy_path_without_weighted_value_is_partial_not_zero():
    rules = [
        _rule("sinter", "sinter::co2-a"),
        _rule("steel", "steel::electricity-in", scope="scope_2", location_role="purchased_energy"),
    ]
    scaled = SCALED_EXCHANGES + [
        {"exchange_id": "steel::electricity-in", "process_id": SHARED_PROVIDER, "flow_uuid": "flow-electricity", "direction": "input"},
    ]
    attribution = _attach(_method(rules), scaled=scaled)
    block = attribution["user_method_grouping"]
    assert block["execution_status"] == "executed_partial"
    assert block["grouping"]["scopes"]["scope_2"]["value"] is None
    assert [gap["code"] for gap in block["coverage"]["coverage_gaps"]] == ["METHOD_RULE_NO_WEIGHTED_CONTRIBUTION"]


def test_method_without_any_weighted_contribution_is_reported_not_fabricated():
    attribution = _attach_user_method_grouping(
        carbon_attribution=_attribution([]),
        provider_receipt=_method([_rule("sinter", "sinter::co2-a")]),
        scaled_elementary_exchanges=SCALED_EXCHANGES,
    )
    block = attribution["user_method_grouping"]
    assert block["execution_status"] == "no_weighted_contributions"
    assert block["grouping"] is None


def test_path_weighted_receipt_decomposes_a_shared_background_without_collapsing_paths():
    """With R3 path rows, Scope 1 totals the engine value but keeps every consumption path separate.

    The same background emission ``steel::co2-b`` is split across two consumer paths; both must
    survive (not overwrite by exchange id), and the Scope bucket must equal the engine total.
    """
    lcia = _lcia_path_receipt([
        _path_row("sinter::co2-a", 100.0, basis="foreground_direct"),
        _path_row("steel::co2-b", 10.0, basis="background_consumer_path", share=1/3, consumer_exchange_id="a::in", consumer_process_uuid="consumer-a"),
        _path_row("steel::co2-b", 20.0, basis="background_consumer_path", share=2/3, consumer_exchange_id="b::in", consumer_process_uuid="consumer-b"),
    ])
    attribution = _attach(
        _method([_rule("sinter", "sinter::co2-a"), _rule("steel", "steel::co2-b")]),
        lcia_results=lcia,
        indicator_key="GWP-fossil",
    )
    block = attribution["user_method_grouping"]
    assert block["grouping_mode"] == "path_weighted"
    grouping = block["grouping"]
    assert grouping["available"] is True
    assert grouping["scopes"]["scope_1"]["value"] == 130.0
    assert grouping["reconciled"] is True
    assert grouping["contribution_total"] == 130.0
    # both background paths are preserved as separate detail rows
    bg = [row for row in grouping["paths"] if row["exchange_id"] == "steel::co2-b"]
    assert {row["consumer_process_uuid"] for row in bg} == {"consumer-a", "consumer-b"}
    assert sum(row["path_contribution_value"] for row in bg) == 30.0


def test_excluding_a_shared_background_path_moves_both_paths_out_of_the_scope():
    """Excluding the elementary exchange applies to every path that shares it, and the excluded
    total equals the sum of those path values, while the engine total stays fixed."""
    terms = [
        _path_row("sinter::co2-a", 100.0, basis="foreground_direct"),
        _path_row("steel::co2-b", 10.0, basis="background_consumer_path", share=1/3, consumer_process_uuid="consumer-a"),
        _path_row("steel::co2-b", 20.0, basis="background_consumer_path", share=2/3, consumer_process_uuid="consumer-b"),
    ]
    included = _attach(
        _method([_rule("sinter", "sinter::co2-a"), _rule("steel", "steel::co2-b")]),
        lcia_results=_lcia_path_receipt(terms), indicator_key="GWP-fossil",
    )
    excluded = _attach(
        _method([_rule("sinter", "sinter::co2-a"), _rule("steel", "steel::co2-b", boundary_status="excluded", scope=None)]),
        lcia_results=_lcia_path_receipt(terms), indicator_key="GWP-fossil",
    )
    inc, exc = included["user_method_grouping"]["grouping"], excluded["user_method_grouping"]["grouping"]
    assert inc["scopes"]["scope_1"]["value"] - exc["scopes"]["scope_1"]["value"] == 30.0
    assert exc["excluded"]["value"] == 30.0
    assert exc["reconciled"] is True
    assert inc["contribution_total"] == exc["contribution_total"] == 130.0


def test_engine_unattributed_path_lands_in_engine_gap_not_a_user_scope():
    """A path the engine itself could not attribute must not be folded into the user's Scope."""
    terms = [
        _path_row("steel::co2-b", 10.0, basis="background_consumer_path", share=0.5, consumer_process_uuid="consumer-a"),
        _path_row("steel::co2-b", 20.0, basis="background_unattributed"),
    ]
    attribution = _attach(
        _method([_rule("steel", "steel::co2-b", scope="scope_3")]),
        lcia_results=_lcia_path_receipt(terms, coverage="partial"), indicator_key="GWP-fossil",
    )
    block = attribution["user_method_grouping"]
    grouping = block["grouping"]
    assert block["grouping_mode"] == "path_weighted"
    assert grouping["scopes"]["scope_3"]["value"] == 10.0
    assert grouping["engine_gap"]["value"] == 20.0
    assert block["execution_status"] == "executed_partial"
    assert grouping["reconciled"] is True
    assert grouping["contribution_total"] == 30.0


def test_no_path_receipt_for_the_indicator_falls_back_to_exchange_weighted_grouping():
    """An older snapshot without a matching path receipt keeps the foreground grouping, not a gap."""
    lcia = _lcia_path_receipt([_path_row("x", 1, basis="foreground_direct")], indicator_key="OTHER")
    attribution = _attach(
        _method([_rule("sinter", "sinter::co2-a"), _rule("steel", "steel::co2-b")]),
        lcia_results=lcia, indicator_key="GWP-fossil",
    )
    block = attribution["user_method_grouping"]
    assert block["grouping_mode"] == "exchange_weighted"
    assert block["grouping"]["scopes"]["scope_1"]["value"] == 130.0

