"""P3-B3 org Scope grouping: rules move the numbers, totals never double.

These assert the gap the earlier provenance-only pass left: an included path's
weighted value is inside its Scope bucket, excluding it moves that exact value out,
and the reconciliation over all terms is preserved in both cases. Provider-uuid
reuse across nodes stays separate, an uncovered path is reported not zeroed, a
Scope whose only members lack a weighted value stays None rather than a fake zero,
and a conflicting classification fails closed.
"""

from __future__ import annotations

from nebula_one.analysis.method_scope_grouping import group_organization_scopes

SHARED_PROVIDER = "provider-uuid-process-1"

ELEMENTARY_EXCHANGES = [
    {"exchange_id": "sinter::co2-a", "process_id": SHARED_PROVIDER, "flow_uuid": "flow-co2", "direction": "output", "exchange_type": "elementary"},
    {"exchange_id": "steel::co2-b", "process_id": SHARED_PROVIDER, "flow_uuid": "flow-co2", "direction": "output", "exchange_type": "elementary"},
    {"exchange_id": "steel::co2-c", "process_id": "provider-uuid-steel", "flow_uuid": "flow-co2", "direction": "output", "exchange_type": "elementary"},
]

TERMS = [
    {"exchange_id": "sinter::co2-a", "contribution_value": 100.0},
    {"exchange_id": "steel::co2-b", "contribution_value": 30.0},
    {"exchange_id": "steel::co2-c", "contribution_value": 10.0},
]

UNIT = "kg CO2e"


def _rule(process_instance_id, exchange_id, *, boundary_status="selected", scope="scope_1", location_role="onsite", **extra):
    rule = {
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
    rule.update(extra)
    return rule


def _group(rules):
    return group_organization_scopes(rules=rules, scaled_exchanges=ELEMENTARY_EXCHANGES, terms=TERMS, indicator_unit=UNIT)


def test_including_every_path_puts_all_value_in_scope_1():
    result = _group([
        _rule("sinter", "sinter::co2-a"),
        _rule("steel", "steel::co2-b"),
        _rule("steel", "steel::co2-c"),
    ])
    assert result["scopes"]["scope_1"]["value"] == 140.0
    assert result["reconciled"] is True
    assert result["problems"] == []


def test_excluding_one_path_moves_exactly_that_value_and_keeps_the_total():
    both = _group([
        _rule("sinter", "sinter::co2-a"),
        _rule("steel", "steel::co2-b"),
    ])
    minus_b = _group([
        _rule("sinter", "sinter::co2-a"),
        _rule("steel", "steel::co2-b", boundary_status="excluded", scope=None),
    ])
    # The Scope-1 difference is exactly the excluded path's contribution.
    assert both["scopes"]["scope_1"]["value"] - minus_b["scopes"]["scope_1"]["value"] == 30.0
    assert minus_b["excluded"]["value"] == 30.0
    # Both snapshots still reconcile to the same all-terms total — nothing doubled.
    assert both["contribution_total"] == minus_b["contribution_total"] == 140.0
    assert both["reconciled"] is True and minus_b["reconciled"] is True


def test_same_provider_uuid_across_nodes_is_counted_once_each():
    # sinter::co2-a and steel::co2-b share a provider process uuid but are distinct paths.
    result = _group([
        _rule("sinter", "sinter::co2-a"),
        _rule("steel", "steel::co2-b"),
    ])
    assert result["scopes"]["scope_1"]["term_count"] == 2
    assert result["scopes"]["scope_1"]["value"] == 130.0


def test_uncovered_path_is_unattributed_not_zeroed_into_a_bucket():
    result = _group([
        _rule("sinter", "sinter::co2-a"),
        _rule("steel", "steel::co2-b"),
    ])
    # steel::co2-c (10.0) has no rule: it stays unattributed, not folded into scope_1.
    assert result["scopes"]["scope_1"]["value"] == 130.0
    assert result["unattributed"]["value"] == 10.0
    assert result["unattributed"]["exchange_ids"] == ["steel::co2-c"]
    assert result["reconciled"] is True


def test_purchased_energy_path_without_weighted_value_is_a_gap_not_a_zero_scope():
    rules = [
        _rule("sinter", "sinter::co2-a"),
        _rule("steel", "steel::electricity-in", scope="scope_2", location_role="purchased_energy"),
    ]
    exchanges = ELEMENTARY_EXCHANGES + [
        {"exchange_id": "steel::electricity-in", "process_id": SHARED_PROVIDER, "flow_uuid": "flow-electricity", "direction": "input", "exchange_type": "technosphere"},
    ]
    result = group_organization_scopes(rules=rules, scaled_exchanges=exchanges, terms=TERMS, indicator_unit=UNIT)
    # Scope 2 has no weighted term yet -> None, never 0.0.
    assert result["scopes"]["scope_2"]["value"] is None
    assert result["scopes"]["scope_2"]["term_count"] == 0
    assert [g["code"] for g in result["coverage_gaps"]] == ["METHOD_RULE_NO_WEIGHTED_CONTRIBUTION"]


def test_conflicting_classification_fails_closed():
    result = _group([
        _rule("sinter", "sinter::co2-a"),
        _rule("sinter", "sinter::co2-a", boundary_status="excluded", scope=None),
    ])
    assert any(p["code"] == "METHOD_SCOPE_CONFLICT" for p in result["problems"])
    assert result["reconciled"] is False


def test_empty_scope_has_no_value():
    result = _group([_rule("sinter", "sinter::co2-a")])
    assert result["scopes"]["scope_3"]["value"] is None
    assert result["scopes"]["scope_3"]["term_count"] == 0
