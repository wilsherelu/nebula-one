"""Frozen-core compiler: independent inheritance, partial overrides, conflicts.

These lock the semantics that a saved checkbox is only meaningful once resolution is
unambiguous: the boundary layer and the attribution layer inherit separately down
exchange > process > method > pending; a process default that a single exchange
overrides reports "partial" with the exception listed rather than double-counting;
same-priority rules that disagree raise a conflict instead of picking by array order;
an included contribution missing a required-category dimension is refused; and
excluding a contribution never demands a category.
"""

from __future__ import annotations

from nebula_one.analysis.method_compile import compile_method_rules

LC_SCOPE_DIM = [{"id": "lc_scope", "categories": [{"id": "scope_1", "is_leaf": True}, {"id": "scope_2", "is_leaf": True}]}]


def _resolve(result, exchange_id, contribution_target="direct"):
    for item in result["resolved_targets"]:
        if item["exchange_id"] == exchange_id and item["contribution_target"] == contribution_target:
            return item
    raise AssertionError(f"target {exchange_id}/{contribution_target} not resolved")


def test_exchange_rule_overrides_process_default_boundary():
    result = compile_method_rules(
        dimensions=LC_SCOPE_DIM,
        exchange_targets=[
            {"exchange_id": "sinter::co2", "process_instance_id": "sinter", "contribution_target": "direct"},
            {"exchange_id": "sinter::so2", "process_instance_id": "sinter", "contribution_target": "direct"},
        ],
        process_defaults=[{"process_instance_id": "sinter", "contribution_target": "direct", "boundary": "include", "categories": {"lc_scope": "scope_1"}}],
        exchange_rules=[{"exchange_id": "sinter::so2", "process_instance_id": "sinter", "contribution_target": "direct", "boundary": "exclude"}],
    )
    assert _resolve(result, "sinter::so2")["boundary"] == "exclude"
    assert _resolve(result, "sinter::so2")["boundary_source"] == "exchange"
    # the other exchange follows the process default -> "沿用过程"
    assert _resolve(result, "sinter::co2")["boundary"] == "include"
    assert _resolve(result, "sinter::co2")["boundary_source"] == "process"
    assert _resolve(result, "sinter::co2")["categories"]["lc_scope"]["source"] == "process"


def test_boundary_and_category_inherit_separately():
    result = compile_method_rules(
        dimensions=LC_SCOPE_DIM,
        exchange_targets=[{"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct"}],
        process_defaults=[{"process_instance_id": "a", "contribution_target": "direct", "boundary": "include", "categories": {"lc_scope": "scope_1"}}],
        exchange_rules=[{"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct", "categories": {"lc_scope": "scope_2"}}],
    )
    item = _resolve(result, "a::x")
    # exchange set only the category; boundary still comes from the process default
    assert item["boundary"] == "include" and item["boundary_source"] == "process"
    assert item["categories"]["lc_scope"]["category"] == "scope_2" and item["categories"]["lc_scope"]["source"] == "exchange"


def test_process_exclude_overridden_by_one_exchange_is_partial():
    result = compile_method_rules(
        dimensions=LC_SCOPE_DIM,
        exchange_targets=[
            {"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct"},
            {"exchange_id": "a::y", "process_instance_id": "a", "contribution_target": "direct"},
        ],
        process_defaults=[{"process_instance_id": "a", "contribution_target": "direct", "boundary": "exclude"}],
        exchange_rules=[{"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct", "boundary": "include", "categories": {"lc_scope": "scope_1"}}],
    )
    # the exception inherits nothing for boundary; the rest follow process exclude
    assert _resolve(result, "a::y")["boundary"] == "exclude"
    assert result["process_status"]["a"]["state"] == "partial"
    assert [e["exchange_id"] for e in result["process_status"]["a"]["exceptions"]] == ["a::x"]


def test_method_default_is_the_bottom_fallback():
    result = compile_method_rules(
        dimensions=LC_SCOPE_DIM,
        exchange_targets=[{"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct"}],
        method_default={"boundary": "include", "categories": {"lc_scope": "scope_1"}},
    )
    item = _resolve(result, "a::x")
    assert item["boundary"] == "include" and item["boundary_source"] == "method"
    assert item["categories"]["lc_scope"]["source"] == "method"


def test_nothing_set_resolves_to_pending_not_include_or_zero():
    result = compile_method_rules(
        dimensions=LC_SCOPE_DIM,
        exchange_targets=[{"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct"}],
    )
    item = _resolve(result, "a::x")
    assert item["boundary"] == "pending" and item["boundary_source"] == "pending"
    assert item["categories"]["lc_scope"]["category"] is None


def test_same_priority_opposite_rules_conflict():
    result = compile_method_rules(
        dimensions=LC_SCOPE_DIM,
        exchange_targets=[{"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct"}],
        exchange_rules=[
            {"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct", "boundary": "include", "categories": {"lc_scope": "scope_1"}},
            {"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct", "boundary": "exclude"},
        ],
    )
    assert any(p["code"] == "METHOD_COMPILE_CONFLICT" for p in result["problems"])
    assert result["valid"] is False


def test_included_without_required_category_is_refused():
    result = compile_method_rules(
        dimensions=LC_SCOPE_DIM,
        exchange_targets=[{"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct"}],
        exchange_rules=[{"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct", "boundary": "include"}],
        required_category_dimensions=["lc_scope"],
    )
    assert any(p["code"] == "METHOD_COMPILE_REQUIRED_CATEGORY" for p in result["problems"])


def test_excluded_does_not_require_a_category():
    result = compile_method_rules(
        dimensions=LC_SCOPE_DIM,
        exchange_targets=[{"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct"}],
        exchange_rules=[{"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct", "boundary": "exclude"}],
        required_category_dimensions=["lc_scope"],
    )
    assert result["problems"] == []
    assert _resolve(result, "a::x")["boundary"] == "exclude"


def test_direct_and_upstream_supply_are_separate_targets():
    # Fuel's upstream production and its onsite combustion are classified apart.
    result = compile_method_rules(
        dimensions=LC_SCOPE_DIM,
        exchange_targets=[
            {"exchange_id": "furnace::gas-in", "process_instance_id": "furnace", "contribution_target": "upstream_supply"},
            {"exchange_id": "furnace::co2", "process_instance_id": "furnace", "contribution_target": "direct"},
        ],
        exchange_rules=[
            {"exchange_id": "furnace::gas-in", "process_instance_id": "furnace", "contribution_target": "upstream_supply", "boundary": "include", "categories": {"lc_scope": "scope_3"}},
            {"exchange_id": "furnace::co2", "process_instance_id": "furnace", "contribution_target": "direct", "boundary": "include", "categories": {"lc_scope": "scope_1"}},
        ],
    )
    assert _resolve(result, "furnace::gas-in", "upstream_supply")["categories"]["lc_scope"]["category"] == "scope_3"
    assert _resolve(result, "furnace::co2", "direct")["categories"]["lc_scope"]["category"] == "scope_1"


def test_plan_hash_is_deterministic_and_sensitive_to_decisions():
    base = dict(
        dimensions=LC_SCOPE_DIM,
        exchange_targets=[{"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct"}],
        exchange_rules=[{"exchange_id": "a::x", "process_instance_id": "a", "contribution_target": "direct", "boundary": "include", "categories": {"lc_scope": "scope_1"}}],
    )
    first = compile_method_rules(**base)
    again = compile_method_rules(**base)
    assert first["execution_plan_sha256"] == again["execution_plan_sha256"]
    changed = compile_method_rules(
        **{**base, "exchange_rules": [{**base["exchange_rules"][0], "categories": {"lc_scope": "scope_2"}}]}
    )
    assert changed["execution_plan_sha256"] != first["execution_plan_sha256"]
