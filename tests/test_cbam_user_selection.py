"""CBAM user-variant narrowing may only take emissions OUT of a reviewed boundary.

The exclusion must actually leave the counted set, untouched decisions stay verbatim, the
exclusion is traceable to the exact source version + content hash, and widening the regulated
universe or naming an undeclared emission fails closed instead of guessing.
"""

from __future__ import annotations

from nebula_one.analysis.cbam_user_selection import narrow_elementary_flow_decisions

SOURCE = {"method_id": "cbam-steel", "version": 3, "content_sha256": "a" * 64}


def _decision(exchange_id, disposition="include", clause="REVIEWED base clause"):
    return {
        "exchange_id": exchange_id,
        "process_uuid": "uuid-" + exchange_id.rsplit("::", 1)[0],
        "disposition": disposition,
        "clause": clause,
        "greenhouse_gas": "CO2",
        "flow_uuid": "flow-co2",
    }


def _rule(exchange_id, boundary_status, cbam=True, process_instance_id=None):
    node = exchange_id.rsplit("::", 1)[0] if exchange_id else None
    return {
        "process_instance_id": process_instance_id or node,
        "exchange_id": exchange_id,
        "contribution_target": "direct",
        "boundary_status": boundary_status,
        "cbam_relevant": cbam,
        "scope": "scope_1" if boundary_status == "selected" else None,
    }


BASE = [
    _decision("sinter::co2-a"),
    _decision("steel::co2-b"),
    _decision("steel::co2-c"),
]


def _by(result):
    return {item["exchange_id"]: item for item in result["decisions"]}


def _codes(result):
    return [problem["code"] for problem in result["problems"]]


def test_excluding_one_included_emission_moves_it_out_and_keeps_the_rest_verbatim():
    result = narrow_elementary_flow_decisions(BASE, user_rules=[_rule("steel::co2-b", "excluded")], source=SOURCE)
    assert result["valid"] is True
    assert result["problems"] == []
    assert result["excluded_exchange_ids"] == ["steel::co2-b"]
    assert _by(result)["steel::co2-b"]["disposition"] == "exclude"
    expected = "user-variant-exclusion@%s@%s#%s" % (SOURCE["method_id"], SOURCE["version"], SOURCE["content_sha256"])
    assert _by(result)["steel::co2-b"]["clause"] == expected
    assert _by(result)["sinter::co2-a"] == BASE[0]
    assert _by(result)["steel::co2-c"] == BASE[2]


def test_counting_an_emission_the_base_excluded_refuses_as_scope_widening():
    base = [_decision("sinter::co2-a"), _decision("steel::co2-b", disposition="exclude")]
    result = narrow_elementary_flow_decisions(base, user_rules=[_rule("steel::co2-b", "selected")], source=SOURCE)
    assert "CBAM_USER_SCOPE_WIDENING" in _codes(result)
    assert result["valid"] is False


def test_pointing_at_an_undeclared_emission_is_unknown():
    result = narrow_elementary_flow_decisions(BASE, user_rules=[_rule("blast::co2-z", "excluded")], source=SOURCE)
    assert "CBAM_USER_TARGET_EXCHANGE_UNKNOWN" in _codes(result)
    assert result["valid"] is False


def test_redundant_exclusion_of_an_already_excluded_emission_is_a_no_op():
    base = [_decision("sinter::co2-a"), _decision("steel::co2-b", disposition="exclude")]
    result = narrow_elementary_flow_decisions(base, user_rules=[_rule("steel::co2-b", "excluded")], source=SOURCE)
    assert result["valid"] is True
    assert result["excluded_exchange_ids"] == []


def test_a_variant_with_no_exclusions_reproduces_the_reviewed_base_exactly():
    result = narrow_elementary_flow_decisions(BASE, user_rules=[_rule("sinter::co2-a", "selected")], source=SOURCE)
    assert result["valid"] is True
    assert result["excluded_exchange_ids"] == []
    assert result["decisions"] == BASE


def test_process_default_exclusion_takes_every_reviewed_emission_of_that_process():
    result = narrow_elementary_flow_decisions(BASE, user_rules=[_rule(None, "excluded", process_instance_id="steel")], source=SOURCE)
    assert result["valid"] is True
    assert result["excluded_exchange_ids"] == ["steel::co2-b", "steel::co2-c"]


def test_exchange_level_exclusion_overrides_a_process_default_include():
    result = narrow_elementary_flow_decisions(
        BASE,
        user_rules=[
            _rule(None, "selected", process_instance_id="steel"),
            _rule("steel::co2-b", "excluded"),
        ],
        source=SOURCE,
    )
    assert result["valid"] is True
    assert result["excluded_exchange_ids"] == ["steel::co2-b"]


def test_exchange_level_include_overrides_a_process_default_exclusion():
    result = narrow_elementary_flow_decisions(
        BASE,
        user_rules=[
            _rule(None, "excluded", process_instance_id="steel"),
            _rule("steel::co2-c", "selected"),
        ],
        source=SOURCE,
    )
    assert result["valid"] is True
    # co2-c keeps the base inclusion via the higher-priority exchange rule; only co2-b leaves.
    assert result["excluded_exchange_ids"] == ["steel::co2-b"]


def test_pending_selection_defers_to_the_reviewed_boundary():
    result = narrow_elementary_flow_decisions(BASE, user_rules=[_rule("steel::co2-b", "pending", cbam=False)], source=SOURCE)
    assert result["valid"] is True
    assert result["excluded_exchange_ids"] == []
    assert result["decisions"] == BASE


def test_selected_but_not_cbam_relevant_conflicts_under_a_cbam_purpose():
    result = narrow_elementary_flow_decisions(BASE, user_rules=[_rule("steel::co2-b", "selected", cbam=False)], source=SOURCE)
    assert "METHOD_RULE_SWITCH_CONFLICT" in _codes(result)
    assert result["valid"] is False


def test_a_variant_that_names_no_exact_source_version_or_hash_is_refused():
    result = narrow_elementary_flow_decisions(BASE, user_rules=[_rule("steel::co2-b", "excluded")], source={"method_id": "cbam-steel"})
    assert "CBAM_USER_SOURCE_REF_INCOMPLETE" in _codes(result)
    assert result["valid"] is False
