from __future__ import annotations

from nebula_one.analysis.method_compile import compile_method_rules
from nebula_one.analysis.method_rule_adapter import (
    LC_SCOPE_DIMENSION_ID,
    adapt_rules,
    lc_scope_dimension,
    resolve_rule,
)


def test_v1_selected_and_cbam_relevant_resolves_to_include_with_scope_category():
    shape, problems = resolve_rule(
        {
            "process_instance_id": "furnace",
            "exchange_id": "furnace::co2",
            "direction": "emission",
            "boundary_status": "selected",
            "location_role": "onsite",
            "scope": "scope_1",
            "cbam_relevant": True,
        }
    )
    assert problems == []
    assert shape["boundary"] == "include"
    assert shape["categories"] == {LC_SCOPE_DIMENSION_ID: "scope_1"}
    assert shape["contribution_target"] == "direct"


def test_v1_selected_but_not_cbam_relevant_is_aux_unless_enforced():
    rule = {
        "process_instance_id": "furnace",
        "exchange_id": "furnace::co2",
        "direction": "emission",
        "boundary_status": "selected",
        "scope": "scope_1",
        "cbam_relevant": False,
    }
    # The generic adapter keeps cbam_relevant as an auxiliary attribute.
    shape, problems = resolve_rule(rule)
    assert problems == []
    assert shape["boundary"] == "include"
    # A CBAM-purpose caller forces the two switches to agree.
    _, enforced = resolve_rule(rule, enforce_cbam_relevance=True)
    assert enforced and enforced[0]["code"] == "METHOD_RULE_SWITCH_CONFLICT"


def test_v1_excluded_cbam_relevant_emission_is_a_legal_narrowing_not_a_conflict():
    # cbam_relevant (which flows the regulation reaches) and the accounting boundary (what this
    # method counts) are the core's independent layers: taking a regulated emission OUT is the
    # whole point of a user variant, so it must resolve to exclude with no contradiction.
    shape, problems = resolve_rule(
        {
            "process_instance_id": "furnace",
            "exchange_id": "furnace::co2",
            "direction": "emission",
            "boundary_status": "excluded",
            "cbam_relevant": True,
        },
        enforce_cbam_relevance=True,
    )
    assert problems == []
    assert shape["boundary"] == "exclude"
    assert shape["categories"] == {}


def test_a_cbam_purpose_refuses_counting_a_flow_the_regulation_does_not_reach():
    _, problems = resolve_rule(
        {
            "process_instance_id": "furnace",
            "exchange_id": "furnace::co2",
            "direction": "emission",
            "boundary_status": "selected",
            "cbam_relevant": False,
        },
        enforce_cbam_relevance=True,
    )
    assert any(p["code"] == "METHOD_RULE_SWITCH_CONFLICT" and p["switch"] == "cbam_relevant" for p in problems)


def test_v1_pending_stays_pending_never_defaulted_to_include():
    shape, problems = resolve_rule(
        {
            "process_instance_id": "furnace",
            "exchange_id": "furnace::co2",
            "direction": "emission",
            "boundary_status": "pending",
        }
    )
    assert problems == []
    assert shape["boundary"] == "pending"
    assert shape["categories"] == {}


def test_v2_explicit_boundary_and_categories_pass_through():
    shape, problems = resolve_rule(
        {
            "schema_version": 2,
            "process_instance_id": "furnace",
            "exchange_id": "furnace::gas-in",
            "direction": "input",
            "contribution_target": "upstream_supply",
            "boundary": "include",
            "categories": {LC_SCOPE_DIMENSION_ID: "scope_3"},
        }
    )
    assert problems == []
    assert shape["boundary"] == "include"
    assert shape["contribution_target"] == "upstream_supply"
    assert shape["categories"] == {LC_SCOPE_DIMENSION_ID: "scope_3"}


def test_v2_inherit_defers_so_compiler_uses_the_process_default():
    shape, problems = resolve_rule(
        {
            "schema_version": 2,
            "process_instance_id": "furnace",
            "exchange_id": "furnace::so2",
            "direction": "emission",
            "boundary": "inherit",
        }
    )
    assert problems == []
    # "inherit" is the absence of an override, not a fourth resolved state.
    assert shape["boundary"] == "inherit"


def test_v2_explicit_boundary_contradicting_legacy_status_conflicts():
    _, problems = resolve_rule(
        {
            "schema_version": 2,
            "process_instance_id": "furnace",
            "exchange_id": "furnace::co2",
            "direction": "emission",
            "boundary": "include",
            "boundary_status": "excluded",
        }
    )
    assert any(p["code"] == "METHOD_RULE_SWITCH_CONFLICT" and p["switch"] == "boundary_status" for p in problems)


def test_v2_categories_conflicting_with_legacy_scope_conflicts():
    _, problems = resolve_rule(
        {
            "schema_version": 2,
            "process_instance_id": "furnace",
            "exchange_id": "furnace::co2",
            "direction": "emission",
            "boundary": "include",
            "categories": {LC_SCOPE_DIMENSION_ID: "scope_2"},
            "scope": "scope_1",
        }
    )
    assert any(p["code"] == "METHOD_RULE_SWITCH_CONFLICT" and p["switch"] == "scope" for p in problems)


def test_adapt_rules_partitions_exchange_rules_from_process_defaults():
    adapted = adapt_rules(
        [
            {
                "process_instance_id": "furnace",
                "exchange_id": None,
                "direction": "emission",
                "boundary_status": "excluded",
            },
            {
                "process_instance_id": "furnace",
                "exchange_id": "furnace::co2",
                "direction": "emission",
                "boundary_status": "selected",
                "scope": "scope_1",
                "cbam_relevant": True,
            },
        ]
    )
    assert len(adapted["process_defaults"]) == 1
    assert len(adapted["exchange_rules"]) == 1
    assert adapted["conflicts"] == []
    assert adapted["dimensions"] == [lc_scope_dimension()]


def test_adapter_output_feeds_the_compiler_end_to_end():
    adapted = adapt_rules(
        [
            {"process_instance_id": "furnace", "exchange_id": None, "direction": "emission", "boundary_status": "excluded"},
            {"process_instance_id": "furnace", "exchange_id": "furnace::co2", "direction": "emission", "boundary_status": "selected", "scope": "scope_1", "cbam_relevant": True},
        ]
    )
    targets = [
        {"exchange_id": "furnace::co2", "process_instance_id": "furnace", "contribution_target": "direct"},
        {"exchange_id": "furnace::so2", "process_instance_id": "furnace", "contribution_target": "direct"},
    ]
    compiled = compile_method_rules(
        dimensions=adapted["dimensions"],
        exchange_targets=targets,
        exchange_rules=adapted["exchange_rules"],
        process_defaults=adapted["process_defaults"],
    )
    resolved = {row["exchange_id"]: row for row in compiled["resolved_targets"]}
    assert resolved["furnace::co2"]["boundary"] == "include"
    assert resolved["furnace::co2"]["categories"][LC_SCOPE_DIMENSION_ID]["category"] == "scope_1"
    # so2 inherits the excluded process default.
    assert resolved["furnace::so2"]["boundary"] == "exclude"
    assert compiled["process_status"]["furnace"]["state"] == "partial"
