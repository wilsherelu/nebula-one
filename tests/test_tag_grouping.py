from __future__ import annotations

from nebula_one.analysis.tag_grouping import (
    TAG_SEMANTICS,
    consumer_path_exchanges,
    group_tag_scheme,
    group_tag_schemes,
)


def _exchange(exchange_id: str, *, process_id: str, direction: str = "emission") -> dict:
    return {
        "exchange_id": exchange_id,
        "process_id": process_id,
        "direction": direction,
        "exchange_type": "elementary",
    }


def _rule(process_id: str, exchange_id: str, *, category: str | None = "tag", status: str = "selected") -> dict:
    rule = {
        "process_instance_id": process_id,
        "exchange_id": exchange_id,
        "direction": "emission",
        "boundary_status": status,
        "categories": {"tag": category} if category else {},
    }
    return rule


DIMENSION = {
    "id": "tag",
    "name": "CBAM",
    "requires_full_coverage": False,
    "categories": [
        {"id": "energy", "name": "Energy", "is_leaf": False},
        {"id": "direct", "name": "Direct", "parent_id": "energy", "is_leaf": True},
        {"id": "indirect", "name": "Indirect", "parent_id": "energy", "is_leaf": True},
    ],
}


def test_multi_scheme_union_and_intersection_deduplicate_the_shared_contribution():
    scaled = [
        _exchange("p1::co2", process_id="p1"),
        _exchange("p1::ch4", process_id="p1"),
    ]
    terms = [
        {"exchange_id": "p1::co2", "contribution_value": 100.0},
        {"exchange_id": "p1::ch4", "contribution_value": 30.0},
    ]
    scheme_a = {
        "scheme": {"method_id": "A"},
        "rules": [_rule("p1", "p1::co2"), _rule("p1", "p1::ch4")],
        "dimension": DIMENSION,
    }
    scheme_b = {
        "scheme": {"method_id": "B"},
        "rules": [_rule("p1", "p1::co2")],
        "dimension": DIMENSION,
    }

    union = group_tag_schemes(
        schemes=[scheme_a, scheme_b],
        scaled_exchanges=scaled,
        weighted_terms=terms,
        indicator_unit="kg CO2e",
        mode="union",
    )
    assert union["schemes"][0]["tag_total"]["value"] == 130.0
    assert union["schemes"][1]["tag_total"]["value"] == 100.0
    assert union["union"]["value"] == 130.0
    assert union["union"]["value"] != 230.0
    assert union["overlap"]["multi_scheme_term_count"] == 1
    assert union["intersection"] is None

    intersection = group_tag_schemes(
        schemes=[scheme_a, scheme_b],
        scaled_exchanges=scaled,
        weighted_terms=terms,
        indicator_unit="kg CO2e",
        mode="intersection",
    )
    assert intersection["intersection"]["value"] == 100.0
    assert intersection["intersection"]["exchange_ids"] == ["p1::co2"]
    assert intersection["union"] is None


def test_same_flow_uuid_in_two_processes_stays_two_independent_matches():
    scaled = [
        _exchange("p1::co2", process_id="p1"),
        _exchange("p2::co2", process_id="p2"),
    ]
    for item in scaled:
        item["flow_uuid"] = "same-flow"
    terms = [
        {"exchange_id": "p1::co2", "contribution_value": 100.0},
        {"exchange_id": "p2::co2", "contribution_value": 20.0},
    ]

    grouped = group_tag_scheme(
        rules=[_rule("p1", "p1::co2")],
        scaled_exchanges=scaled,
        weighted_terms=terms,
        dimension=DIMENSION,
        indicator_unit="kg CO2e",
    )
    assert grouped["tag_total"]["value"] == 100.0
    assert grouped["unmatched"]["exchange_ids"] == ["p2::co2"]
    assert grouped["unmatched"]["known_value"] == 20.0


def test_known_zero_missing_pending_and_unmatched_are_reported_apart():
    scaled = [
        _exchange("p1::known", process_id="p1"),
        _exchange("p1::zero", process_id="p1"),
        _exchange("p1::missing", process_id="p1"),
        _exchange("p1::gap", process_id="p1"),
        _exchange("p1::pending", process_id="p1"),
        _exchange("p1::loose", process_id="p1"),
    ]
    terms = [
        {"exchange_id": "p1::known", "contribution_value": 100.0},
        {"exchange_id": "p1::zero", "contribution_value": 0.0},
        {"exchange_id": "p1::missing", "contribution_value": None},
        {"exchange_id": "p1::pending", "contribution_value": 7.0},
        {"exchange_id": "p1::loose", "contribution_value": 5.0},
    ]
    rules = [
        _rule("p1", "p1::known", category="direct"),
        _rule("p1", "p1::zero", category="indirect"),
        _rule("p1", "p1::missing", category="direct"),
        _rule("p1", "p1::gap", category="direct"),
        _rule("p1", "p1::pending", category="indirect", status="pending"),
    ]

    grouped = group_tag_scheme(
        rules=rules,
        scaled_exchanges=scaled,
        weighted_terms=terms,
        dimension=DIMENSION,
        indicator_unit="kg CO2e",
    )

    assert grouped["semantics"] == TAG_SEMANTICS
    assert grouped["tag_total"]["value"] == 100.0
    assert grouped["tag_total"]["term_count"] == 2
    assert grouped["real_zero"]["exchange_ids"] == ["p1::zero"]
    # The zero is inside the tagged range, so the scheme still reconciles its category subtotals.
    assert grouped["reconciled"] is True
    # A tagged path with no weighted value and a tagged path outside the contribution pool are
    # both gaps, never folded into the known subtotal.
    assert grouped["missing"]["exchange_ids"] == ["p1::gap", "p1::missing"]
    assert grouped["missing"]["no_weighted_value_ids"] == ["p1::gap"]
    assert grouped["pending"]["exchange_ids"] == ["p1::pending"]
    assert grouped["unmatched"]["exchange_ids"] == ["p1::loose"]
    assert grouped["coverage"]["complete"] is False
    assert grouped["uncategorized"]["subtotal"] == 0.0


def test_category_leaves_sum_to_tag_total_and_parents_are_not_counted_twice():
    scaled = [
        _exchange("p1::one", process_id="p1"),
        _exchange("p1::two", process_id="p1"),
    ]
    terms = [
        {"exchange_id": "p1::one", "contribution_value": 100.0},
        {"exchange_id": "p1::two", "contribution_value": 30.0},
    ]
    grouped = group_tag_scheme(
        rules=[_rule("p1", "p1::one", category="direct"), _rule("p1", "p1::two", category="indirect")],
        scaled_exchanges=scaled,
        weighted_terms=terms,
        dimension=DIMENSION,
        indicator_unit="kg CO2e",
    )

    rows = {row["id"]: row for row in grouped["dimension"]["categories"]}
    assert rows["direct"]["is_leaf"] is True and rows["direct"]["subtotal"] == 100.0
    assert rows["indirect"]["is_leaf"] is True and rows["indirect"]["subtotal"] == 30.0
    assert rows["energy"]["is_leaf"] is False and rows["energy"]["subtotal"] == 130.0
    leaf_total = sum(row["subtotal"] for row in grouped["dimension"]["categories"] if row["is_leaf"])
    assert leaf_total + grouped["uncategorized"]["subtotal"] == grouped["tag_total"]["value"]


def test_scheme_without_subcategories_reconciles_directly_on_the_tag():
    scaled = [_exchange("p1::co2", process_id="p1")]
    terms = [{"exchange_id": "p1::co2", "contribution_value": 12.5}]
    dimension = {"id": "tag", "name": "CCER", "requires_full_coverage": False, "categories": []}

    grouped = group_tag_scheme(
        rules=[_rule("p1", "p1::co2", category=None)],
        scaled_exchanges=scaled,
        weighted_terms=terms,
        dimension=dimension,
        indicator_unit="kg CO2e",
    )
    assert grouped["dimension"]["categories"] == []
    assert grouped["tag_total"]["value"] == 12.5
    assert grouped["reconciled"] is True


def test_partial_consumer_keeps_known_subtotal_and_gap_without_claiming_real_zero():
    grouped = group_tag_scheme(
        rules=[dict(_rule("p1", "p1::power", category="indirect"), direction="input")],
        scaled_exchanges=[],
        consumer_paths=[dict(_exchange("p1::power", process_id="p1", direction="input"), exchange_type="technosphere")],
        weighted_terms=[{"exchange_id": "p1::power", "contribution_value": 0.0}],
        missing_exchange_ids={"p1::power"},
        dimension=DIMENSION,
        indicator_unit="kg CO2e",
    )
    assert grouped["tag_total"]["value"] == 0.0
    assert grouped["matched"] == {"term_count": 1, "known_term_count": 1}
    assert grouped["missing"]["exchange_ids"] == ["p1::power"]
    assert grouped["real_zero"]["term_count"] == 0
    assert grouped["coverage"]["complete"] is False
    indirect = next(row for row in grouped["dimension"]["categories"] if row["id"] == "indirect")
    assert indirect["subtotal"] == 0.0 and indirect["missing_count"] == 1


def test_unmatched_missing_only_is_not_a_zero_subtotal():
    grouped = group_tag_scheme(
        rules=[], scaled_exchanges=[_exchange("p1::gap", process_id="p1")],
        weighted_terms=[], missing_exchange_ids={"p1::gap"},
        dimension=DIMENSION, indicator_unit="kg CO2e",
    )
    assert grouped["unmatched"]["term_count"] == 1
    assert grouped["unmatched"]["known_term_count"] == 0
    assert grouped["unmatched"]["known_value"] is None
    assert grouped["unmatched"]["missing_count"] == 1


def test_missing_only_union_retains_membership_without_inventing_a_value():
    schemes = [{"scheme": {"method_id": key}, "rules": [_rule("p1", "p1::gap", category="direct")],
                "dimension": DIMENSION} for key in ("a", "b")]
    result = group_tag_schemes(
        schemes=schemes, scaled_exchanges=[_exchange("p1::gap", process_id="p1")],
        weighted_terms=[], missing_exchange_ids={"p1::gap"},
        indicator_unit="kg CO2e", mode="intersection",
    )
    assert result["intersection"]["value"] is None
    assert result["intersection"]["term_count"] == 1
    assert result["intersection"]["missing_count"] == 1


def test_conflicting_matches_for_one_path_are_a_problem_not_a_silent_pick():
    scaled = [_exchange("p1::co2", process_id="p1")]
    terms = [{"exchange_id": "p1::co2", "contribution_value": 100.0}]
    grouped = group_tag_scheme(
        rules=[
            _rule("p1", "p1::co2", category="direct"),
            _rule("p1", "p1::co2", category="indirect"),
        ],
        scaled_exchanges=scaled,
        weighted_terms=terms,
        dimension=DIMENSION,
        indicator_unit="kg CO2e",
    )
    assert grouped["reconciled"] is False
    assert {problem["code"] for problem in grouped["problems"]} == {"TAG_MATCH_CONFLICT"}


def test_consumer_path_terms_bind_background_contributions_to_the_pinned_input():
    receipt = {
        "terms": [
            {
                "exchange_id": "bg::co2",
                "consumer_exchange_id": "fg::electricity",
                "attribution_basis": "background_consumer_path",
                "path_contribution_value": 100.0,
            }
        ]
    }
    consumer_paths = consumer_path_exchanges(receipt)
    assert consumer_paths == [
        {
            "exchange_id": "fg::electricity",
            "direction": "input",
            "exchange_type": "technosphere",
            "process_id": "fg",
        }
    ]

    grouped = group_tag_scheme(
        rules=[_rule("fg", "fg::electricity", category="indirect")],
        scaled_exchanges=[],
        weighted_terms=[{"exchange_id": "fg::electricity", "contribution_value": 100.0}],
        dimension=DIMENSION,
        indicator_unit="kg CO2e",
        consumer_paths=consumer_paths,
    )
    assert grouped["tag_total"]["value"] == 100.0
    assert grouped["unmatched"]["exchange_ids"] == []
