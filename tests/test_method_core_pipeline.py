"""Core pipeline composition: compile the rules, then group the engine's numbers.

The compiler resolves each consumption path's boundary and category; those resolved
targets become the grouping kernel's input alongside the weighted contribution values.
This proves the two frozen-core primitives compose end to end: a process default of
exclude with one exchange included counts only that path (the rest excluded) and the
process is partial, and a fuel's upstream supply versus its onsite combustion land in
different categories while the known total still reconciles.
"""

from __future__ import annotations

from nebula_one.analysis.method_compile import compile_method_rules
from nebula_one.analysis.method_grouping import aggregate_contributions

DIMENSIONS = [{
    "id": "lc_scope",
    "categories": [
        {"id": "scope_1", "is_leaf": True},
        {"id": "scope_3", "is_leaf": True},
    ],
}]
UNIT = "kg CO2e"


def _contributions(resolved, values):
    boundary_map = {"include": "included", "exclude": "excluded", "pending": "pending"}
    contributions = []
    for target in resolved:
        key = f"{target['exchange_id']}#{target['contribution_target']}"
        contributions.append({
            "source_key": key,
            "value": values.get(key),
            "unit": UNIT,
            "boundary": boundary_map[target["boundary"]],
            "categories": {dim: info["category"] for dim, info in target["categories"].items() if info["category"]},
        })
    return contributions


def _categories(resolved, dimension="lc_scope"):
    return {row["id"]: row["subtotal"] for row in resolved["dimensions"][dimension]["categories"]}


def test_process_default_exclude_with_one_included_exchange_counts_only_that_path():
    resolved = compile_method_rules(
        dimensions=DIMENSIONS,
        exchange_targets=[
            {"exchange_id": "furnace::co2", "process_instance_id": "furnace", "contribution_target": "direct"},
            {"exchange_id": "furnace::so2", "process_instance_id": "furnace", "contribution_target": "direct"},
        ],
        process_defaults=[{"process_instance_id": "furnace", "contribution_target": "direct", "boundary": "exclude"}],
        exchange_rules=[{"exchange_id": "furnace::co2", "process_instance_id": "furnace", "contribution_target": "direct", "boundary": "include", "categories": {"lc_scope": "scope_1"}}],
    )
    assert resolved["valid"] is True
    assert resolved["process_status"]["furnace"]["state"] == "partial"

    values = {"furnace::co2#direct": 100.0, "furnace::so2#direct": 25.0}
    grouped = aggregate_contributions(
        dimensions=DIMENSIONS,
        contributions=_contributions(resolved["resolved_targets"], values),
        indicator_unit=UNIT,
    )
    assert _categories(grouped)["scope_1"] == 100.0
    # so2 stayed excluded (not silently counted), and its value is reported as excluded.
    assert grouped["excluded"]["value"] == 25.0
    assert grouped["known_total"] == 100.0
    assert grouped["reconciled"] is True


def test_fuel_upstream_and_onsite_combustion_land_in_different_categories():
    resolved = compile_method_rules(
        dimensions=DIMENSIONS,
        exchange_targets=[
            {"exchange_id": "furnace::gas-in", "process_instance_id": "furnace", "contribution_target": "upstream_supply"},
            {"exchange_id": "furnace::co2", "process_instance_id": "furnace", "contribution_target": "direct"},
        ],
        exchange_rules=[
            {"exchange_id": "furnace::gas-in", "process_instance_id": "furnace", "contribution_target": "upstream_supply", "boundary": "include", "categories": {"lc_scope": "scope_3"}},
            {"exchange_id": "furnace::co2", "process_instance_id": "furnace", "contribution_target": "direct", "boundary": "include", "categories": {"lc_scope": "scope_1"}},
        ],
    )
    values = {"furnace::gas-in#upstream_supply": 40.0, "furnace::co2#direct": 90.0}
    grouped = aggregate_contributions(
        dimensions=DIMENSIONS,
        contributions=_contributions(resolved["resolved_targets"], values),
        indicator_unit=UNIT,
    )
    assert _categories(grouped)["scope_1"] == 90.0
    assert _categories(grouped)["scope_3"] == 40.0
    assert grouped["known_total"] == 130.0
    assert grouped["reconciled"] is True
