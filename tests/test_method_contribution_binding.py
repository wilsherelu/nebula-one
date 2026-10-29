"""P3-B1 identity seam: rules bind to exact consumption paths, never merged by provider uuid.

These are deterministic, engine-free checks of the correspondence the later
grouping rests on. They assert that a rule resolves by ``exchange_id``
(``node::port``), that two nodes sharing one provider ``process_id`` stay
distinct, that ambiguity/absence/inconsistency return structured problems rather
than a guess, and that a path without a per-exchange weighted value is reported
as a coverage gap instead of being zeroed.
"""

from __future__ import annotations

import pytest

from nebula_one.analysis.method_contribution_binding import node_prefix, resolve_method_identities


# Two different model nodes ("ore-sintering", "steel-making") consume the same
# provider process uuid. The engine keeps them apart via node::port exchange ids.
SHARED_PROVIDER = "provider-uuid-electricity"

EXCHANGES = [
    {
        "exchange_id": "ore-sintering::electricity-in",
        "process_id": SHARED_PROVIDER,
        "flow_uuid": "flow-electricity",
        "direction": "input",
        "exchange_type": "technosphere",
    },
    {
        "exchange_id": "steel-making::electricity-in",
        "process_id": SHARED_PROVIDER,
        "flow_uuid": "flow-electricity",
        "direction": "input",
        "exchange_type": "technosphere",
    },
    {
        "exchange_id": "ore-sintering::co2-out",
        "process_id": "provider-uuid-ore-sintering",
        "flow_uuid": "flow-co2",
        "direction": "output",
        "exchange_type": "elementary",
    },
]


def _rule(process_instance_id, exchange_id=None, flow_uuid=None, direction=None, **overrides):
    rule = {
        "process_instance_id": process_instance_id,
        "exchange_id": exchange_id,
        "flow_uuid": flow_uuid,
        "direction": direction,
        "boundary_status": "selected",
        "location_role": "onsite",
        "scope": "scope_1",
        "cbam_relevant": False,
        "classification_basis": "user",
    }
    rule.update(overrides)
    return rule


def test_node_prefix_splits_the_model_node_from_the_port():
    assert node_prefix("ore-sintering::co2-out") == "ore-sintering"


def test_exchange_id_rule_binds_to_one_exact_path():
    result = resolve_method_identities(rules=[_rule("ore-sintering", "ore-sintering::co2-out")], scaled_exchanges=EXCHANGES)
    assert result["problems"] == []
    assert [b["exchange_id"] for b in result["bindings"]] == ["ore-sintering::co2-out"]
    assert result["bindings"][0]["matched_by"] == "exchange_id"


def test_same_provider_uuid_across_two_nodes_stays_split_per_path():
    # A process/flow/direction rule (no exchange id) on one node must not absorb the
    # sibling node that happens to consume the same provider uuid.
    result = resolve_method_identities(
        rules=[_rule("ore-sintering", flow_uuid="flow-electricity", direction="input")],
        scaled_exchanges=EXCHANGES,
    )
    assert result["problems"] == []
    assert [b["exchange_id"] for b in result["bindings"]] == ["ore-sintering::electricity-in"]
    # The other node's identical provider/flow remains unclaimed, not merged away.
    assert "steel-making::electricity-in" in result["uncovered_exchange_ids"]


def test_process_level_rule_over_two_ports_is_ambiguous_not_guessed():
    # "ore-sintering" has two ports; a rule with only the node id cannot pick one.
    result = resolve_method_identities(rules=[_rule("ore-sintering")], scaled_exchanges=EXCHANGES)
    assert [p["code"] for p in result["problems"]] == ["METHOD_RULE_TARGET_AMBIGUOUS"]
    assert result["bindings"] == []
    assert result["problems"][0]["candidates"] == ["ore-sintering::co2-out", "ore-sintering::electricity-in"]


def test_rule_targeting_an_absent_path_reports_not_found():
    result = resolve_method_identities(rules=[_rule("rolling-mill", "rolling-mill::co2-out")], scaled_exchanges=EXCHANGES)
    assert [p["code"] for p in result["problems"]] == ["METHOD_RULE_TARGET_NOT_FOUND"]


def test_declared_default_on_an_absent_process_remains_an_identity_problem():
    result = resolve_method_identities(
        rules=[_rule("missing-process", direction="emission", contribution_target="direct")],
        scaled_exchanges=EXCHANGES,
    )
    assert [p["code"] for p in result["problems"]] == ["METHOD_RULE_TARGET_NOT_FOUND"]
    assert result["bindings"] == []


def test_rule_citing_node_and_mismatched_exchange_is_inconsistent():
    result = resolve_method_identities(rules=[_rule("steel-making", "ore-sintering::co2-out")], scaled_exchanges=EXCHANGES)
    assert [p["code"] for p in result["problems"]] == ["METHOD_RULE_IDENTITY_INCONSISTENT"]
    assert result["bindings"] == []


def test_selected_path_without_weighted_value_is_a_gap_not_zero():
    # The elementary co2 path has a weighted contribution; the technosphere
    # electricity path (a purchased-energy consumption) does not. Grouping must
    # refuse to move a value that the engine never returned, not invent one.
    result = resolve_method_identities(
        rules=[
            _rule("ore-sintering", "ore-sintering::co2-out", location_role="onsite", scope="scope_1"),
            _rule("steel-making", "steel-making::electricity-in", location_role="purchased_energy", scope="scope_2"),
        ],
        scaled_exchanges=EXCHANGES,
        weighted_exchange_ids={"ore-sintering::co2-out"},
    )
    assert result["problems"] == []
    assert [g["exchange_id"] for g in result["coverage_gaps"]] == ["steel-making::electricity-in"]
    assert result["coverage_gaps"][0]["code"] == "METHOD_RULE_NO_WEIGHTED_CONTRIBUTION"
    # The gap path is still bound for identity, but flagged; nothing was zeroed.
    bound_ids = {b["exchange_id"] for b in result["bindings"]}
    assert bound_ids == {"ore-sintering::co2-out", "steel-making::electricity-in"}


def test_uncovered_paths_are_listed_for_coverage():
    result = resolve_method_identities(
        rules=[_rule("ore-sintering", "ore-sintering::co2-out")],
        scaled_exchanges=EXCHANGES,
    )
    assert result["uncovered_exchange_ids"] == ["ore-sintering::electricity-in", "steel-making::electricity-in"]


def test_duplicate_exchange_ids_are_rejected():
    with pytest.raises(ValueError):
        resolve_method_identities(rules=[], scaled_exchanges=[EXCHANGES[0], dict(EXCHANGES[0])])
