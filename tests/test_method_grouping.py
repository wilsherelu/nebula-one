"""Frozen-core generic grouping: category-driven, per-dimension, known-values-only.

These lock the semantics the org/PCF/CBAM paths will share: leaves carry values and
parents only roll up (never double-summed), dimensions are viewed independently and
never added across, exclusion moves a value out without changing the known total, a
missing value is not a zero, a real zero is kept, and an included-but-unclassified
contribution lands in the unattributed bucket instead of vanishing.
"""

from __future__ import annotations

import pytest

from nebula_one.analysis.method_grouping import normalize_dimensions

from nebula_one.analysis.method_grouping import aggregate_contributions

LC_SCOPE = {
    "id": "lc_scope",
    "mutually_exclusive": True,
    "requires_full_coverage": False,
    "categories": [
        {"id": "scope_1", "name": "Scope 1", "is_leaf": True},
        {"id": "scope_2", "name": "Scope 2", "is_leaf": True},
        {"id": "scope_3", "name": "Scope 3", "is_leaf": True},
    ],
}

# A dimension with a rollup parent over the same three leaves.
LC_SCOPE_ROLLUP = {
    "id": "lc_scope",
    "mutually_exclusive": True,
    "requires_full_coverage": False,
    "categories": [
        {"id": "total", "name": "Total", "is_leaf": False},
        {"id": "scope_1", "name": "Scope 1", "parent_id": "total", "is_leaf": True},
        {"id": "scope_2", "name": "Scope 2", "parent_id": "total", "is_leaf": True},
        {"id": "scope_3", "name": "Scope 3", "parent_id": "total", "is_leaf": True},
    ],
}

STAGE = {
    "id": "stage",
    "mutually_exclusive": True,
    "requires_full_coverage": False,
    "categories": [
        {"id": "combustion", "name": "Onsite combustion", "is_leaf": True},
        {"id": "upstream", "name": "Upstream supply", "is_leaf": True},
    ],
}


def _c(source_key, value, *, boundary="included", categories=None, unit="kg CO2e"):
    return {"source_key": source_key, "value": value, "unit": unit, "boundary": boundary, "categories": categories or {}}


def test_leaf_categories_sum_independently_per_dimension():
    contributions = [
        _c("sinter::co2", 100, categories={"lc_scope": "scope_1", "stage": "combustion"}),
        _c("fuel::co2", 30, categories={"lc_scope": "scope_1", "stage": "upstream"}),
    ]
    result = aggregate_contributions(dimensions=[LC_SCOPE], contributions=contributions, indicator_unit="kg CO2e")
    scope = {row["id"]: row["subtotal"] for row in result["dimensions"]["lc_scope"]["categories"]}
    assert scope["scope_1"] == 130
    assert result["known_total"] == 130
    assert result["reconciled"] is True


def test_parent_rolls_up_from_leaves_without_double_summing():
    contributions = [
        _c("a", 100, categories={"lc_scope": "scope_1"}),
        _c("b", 40, categories={"lc_scope": "scope_2"}),
    ]
    result = aggregate_contributions(dimensions=[LC_SCOPE_ROLLUP], contributions=contributions, indicator_unit="kg CO2e")
    rows = {row["id"]: row for row in result["dimensions"]["lc_scope"]["categories"]}
    assert rows["total"]["subtotal"] == 140
    assert rows["scope_1"]["subtotal"] == 100
    # The dimension total is the known total, not total + leaves.
    assert result["known_total"] == 140
    assert result["dimensions"]["lc_scope"]["reconciled"] is True


def test_two_dimensions_view_the_same_contribution_without_cross_summing():
    contributions = [
        _c("fuel::co2", 50, categories={"lc_scope": "scope_1", "stage": "combustion"}),
    ]
    result = aggregate_contributions(dimensions=[LC_SCOPE, STAGE], contributions=contributions, indicator_unit="kg CO2e")
    assert {r["id"]: r["subtotal"] for r in result["dimensions"]["lc_scope"]["categories"]}["scope_1"] == 50
    assert {r["id"]: r["subtotal"] for r in result["dimensions"]["stage"]["categories"]}["combustion"] == 50
    # known_total is a single caliber, not scope_1 + combustion.
    assert result["known_total"] == 50


def test_excluding_a_path_moves_its_value_out_without_changing_known_total():
    with_include = aggregate_contributions(
        dimensions=[LC_SCOPE],
        contributions=[
            _c("a", 100, categories={"lc_scope": "scope_1"}),
            _c("b", 30, categories={"lc_scope": "scope_1"}),
        ],
        indicator_unit="kg CO2e",
    )
    with_exclude = aggregate_contributions(
        dimensions=[LC_SCOPE],
        contributions=[
            _c("a", 100, categories={"lc_scope": "scope_1"}),
            _c("b", 30, boundary="excluded"),
        ],
        indicator_unit="kg CO2e",
    )
    assert with_include["known_total"] == 130
    assert with_exclude["known_total"] == 100
    assert with_exclude["excluded"]["value"] == 30
    assert with_exclude["reconciled"] is True


def test_missing_value_is_not_zeroed_into_a_category():
    result = aggregate_contributions(
        dimensions=[LC_SCOPE],
        contributions=[
            _c("onsite", 100, categories={"lc_scope": "scope_1"}),
            _c("purchased_elec", None, categories={"lc_scope": "scope_2"}),
        ],
        indicator_unit="kg CO2e",
    )
    rows = {r["id"]: r for r in result["dimensions"]["lc_scope"]["categories"]}
    assert rows["scope_1"]["subtotal"] == 100
    # Scope 2 has only a missing-value member -> no subtotal, one missing, never a fake 0.
    assert rows["scope_2"]["subtotal"] is None
    assert rows["scope_2"]["missing_count"] == 1
    assert result["known_total"] == 100
    assert result["dimensions"]["lc_scope"]["completeness"] == "partial"


def test_real_zero_is_kept_as_a_value():
    result = aggregate_contributions(
        dimensions=[LC_SCOPE],
        contributions=[_c("zero", 0.0, categories={"lc_scope": "scope_1"})],
        indicator_unit="kg CO2e",
    )
    rows = {r["id"]: r for r in result["dimensions"]["lc_scope"]["categories"]}
    assert rows["scope_1"]["subtotal"] == 0.0
    assert rows["scope_1"]["term_count"] == 1
    assert result["known_total"] == 0.0
    assert result["reconciled"] is True


def test_included_but_unclassified_lands_in_unattributed_not_lost():
    result = aggregate_contributions(
        dimensions=[LC_SCOPE],
        contributions=[
            _c("a", 100, categories={"lc_scope": "scope_1"}),
            _c("b", 20, categories={}),
        ],
        indicator_unit="kg CO2e",
    )
    dim = result["dimensions"]["lc_scope"]
    assert dim["unattributed"]["subtotal"] == 20
    assert result["known_total"] == 120
    # attributed + unattributed still equals the known total.
    assert dim["reconciled"] is True


def test_assigning_to_a_parent_is_rejected():
    result = aggregate_contributions(
        dimensions=[LC_SCOPE_ROLLUP],
        contributions=[_c("a", 100, categories={"lc_scope": "total"})],
        indicator_unit="kg CO2e",
    )
    assert any(p["code"] == "GROUPING_PARENT_NOT_LEAF" for p in result["problems"])
    assert result["reconciled"] is False


def test_multiple_contributions_on_one_exchange_all_kept():
    result = aggregate_contributions(
        dimensions=[LC_SCOPE],
        contributions=[
            _c("steel::co2#direct", 70, categories={"lc_scope": "scope_1"}),
            _c("steel::co2#upstream", 30, categories={"lc_scope": "scope_3"}),
        ],
        indicator_unit="kg CO2e",
    )
    rows = {r["id"]: r["subtotal"] for r in result["dimensions"]["lc_scope"]["categories"]}
    assert rows["scope_1"] == 70 and rows["scope_3"] == 30
    assert result["known_total"] == 100


def test_duplicate_source_key_is_flagged():
    result = aggregate_contributions(
        dimensions=[LC_SCOPE],
        contributions=[
            _c("dup", 10, categories={"lc_scope": "scope_1"}),
            _c("dup", 5, categories={"lc_scope": "scope_1"}),
        ],
        indicator_unit="kg CO2e",
    )
    assert any(p["code"] == "GROUPING_DUPLICATE_SOURCE" for p in result["problems"])


def test_unit_mismatch_is_not_summed():
    result = aggregate_contributions(
        dimensions=[LC_SCOPE],
        contributions=[_c("a", 10, categories={"lc_scope": "scope_1"}, unit="kg H2O")],
        indicator_unit="kg CO2e",
    )
    assert any(p["code"] == "GROUPING_UNIT_MISMATCH" for p in result["problems"])
    assert result["known_total"] == 0.0


def test_negative_contributions_are_preserved():
    result = aggregate_contributions(
        dimensions=[LC_SCOPE],
        contributions=[
            _c("credit", -40, categories={"lc_scope": "scope_1"}),
            _c("emit", 100, categories={"lc_scope": "scope_1"}),
        ],
        indicator_unit="kg CO2e",
    )
    rows = {r["id"]: r["subtotal"] for r in result["dimensions"]["lc_scope"]["categories"]}
    assert rows["scope_1"] == 60
    assert result["reconciled"] is True


def test_category_tree_rejects_cycles_and_leaf_parents():
    with pytest.raises(ValueError, match="cycle"):
        normalize_dimensions([{"id": "tag", "categories": [
            {"id": "a", "parent_id": "b", "is_leaf": False},
            {"id": "b", "parent_id": "a", "is_leaf": False},
        ]}])
    with pytest.raises(ValueError, match="leaf"):
        normalize_dimensions([{"id": "tag", "categories": [
            {"id": "a", "is_leaf": True},
            {"id": "b", "parent_id": "a", "is_leaf": True},
        ]}])
