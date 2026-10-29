"""R3 One-side consumption of LCA's path-weighted contribution receipts.

Covers the primitive (grouping by user rules over path rows) and the persistence seam
(the field flows through provider_solve's lcia_results freeze verbatim so consumers can
reach it from a snapshot)."""

from __future__ import annotations

import pytest

from nebula_one.analysis.method_path_grouping import (
    group_path_weighted_scopes,
    select_path_weighted_receipt,
)


BG_PROCESS = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
STEEL_PROCESS = "11111111-1111-4111-9111-111111111111"
CO2_UUID = "00000000-0000-4000-8000-0000000000c0"
CONSUMER_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CONSUMER_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _path_row(
    *,
    process_uuid: str,
    exchange_id: str,
    contribution: float,
    share: float,
    basis: str,
    consumer_exchange_id: str | None = None,
    consumer_process_uuid: str | None = None,
    provider_instance_id: str | None = None,
) -> dict:
    return {
        "schema_version": "provider.lcia.path-weighted-contribution-term.v1",
        "attribution_basis": basis,
        "consumer_exchange_id": consumer_exchange_id,
        "consumer_process_uuid": consumer_process_uuid,
        "provider_instance_id": provider_instance_id,
        "process_uuid": process_uuid,
        "exchange_id": exchange_id,
        "source_namespace": "ecoinvent",
        "flow_uuid": CO2_UUID,
        "flow_version": "01.00.000",
        "amount": contribution,
        "amount_unit": "kg",
        "direction": "output",
        "compartment": "air/fossil",
        "cf_method": "EF v3.1",
        "cf_database_release": "EF3.1",
        "cf_indicator_key": "gwp100-new",
        "cf_version": "EF3.1",
        "cf_presence": "explicit_nonzero",
        "cf_value": 1.0,
        "cf_hash": "cf-hash",
        "path_share": share,
        "consumer_attributed_activity_amount": (share * 3.0) if basis == "background_consumer_path" else None,
        "shared_process_total_activity_amount": 3.0 if basis == "background_consumer_path" else None,
        "contribution_value": contribution / share if share else 0.0,
        "path_contribution_value": contribution,
        "contribution_unit": "kg CO2-Eq",
        "snapshot_hash": "consumer-graph-hash",
        "provider_graph_hash": "provider-graph-hash",
        "solve_hash": "solve-hash",
        "provider_commit": "commit-abc",
    }


def _receipt(terms: list[dict], *, coverage: str = "complete", unattributed: float = 0.0) -> dict:
    total = sum(item["path_contribution_value"] for item in terms)
    return {
        "schema_version": "provider.lcia.path-weighted-contribution-receipt.v1",
        "method": "EF v3.1",
        "database_release": "EF3.1",
        "canonical_indicator_key": "gwp100-new",
        "indicator_unit": "kg CO2-Eq",
        "indicator_value": total,
        "source_contribution_total": total,
        "path_weighted_total": total,
        "reconciliation_delta": 0.0,
        "attribution_coverage": coverage,
        "unattributed_contribution_value": unattributed,
        "terms": terms,
        "processes_without_path_attribution": [],
        "snapshot_hash": "consumer-graph-hash",
        "provider_graph_hash": "provider-graph-hash",
        "solve_hash": "solve-hash",
        "provider_commit": "commit-abc",
        "content_hash": "receipt-hash",
    }


def _selected_rule(exchange_id: str, scope: str) -> dict:
    return {
        "process_instance_id": exchange_id.split("::", 1)[0],
        "exchange_id": exchange_id,
        "direction": "output",
        "boundary_status": "selected",
        "location_role": "onsite",
        "scope": scope,
        "cbam_relevant": False,
        "classification_basis": "user",
    }


def _excluded_rule(exchange_id: str) -> dict:
    rule = _selected_rule(exchange_id, "scope_3")
    rule["boundary_status"] = "excluded"
    rule["scope"] = None
    return rule


def _scaled(*exchange_ids: str) -> list[dict]:
    return [
        {
            "exchange_id": exchange_id,
            "process_id": exchange_id.split("::", 1)[0],
            "flow_uuid": CO2_UUID,
            "direction": "output",
            "exchange_type": "elementary",
            "scaled_amount": 1.0,
        }
        for exchange_id in exchange_ids
    ]


def test_process_default_groups_real_emissions_and_exchange_exclusion_overrides_it():
    ids = ["blast-furnace::co2-a", "blast-furnace::co2-b", "other-node::co2"]
    receipt = _receipt([_path_row(process_uuid=STEEL_PROCESS, exchange_id=eid,
                                contribution=value, share=1.0, basis="foreground_direct")
                        for eid, value in zip(ids, [100.0, 20.0, 7.0])])
    default = {"process_instance_id": "blast-furnace", "exchange_id": None, "flow_uuid": None,
               "direction": "emission", "contribution_target": "direct", "boundary_status": "selected",
               "scope": "scope_1", "location_role": "onsite"}
    a = group_path_weighted_scopes(rules=[default], scaled_exchanges=_scaled(*ids),
                                   path_receipt=receipt, indicator_unit="kg CO2-Eq")
    assert a["scopes"]["scope_1"]["value"] == 120
    assert a["unattributed"]["value"] == 7
    assert a["reconciled"] is True
    b = group_path_weighted_scopes(rules=[default, _excluded_rule(ids[1])],
                                   scaled_exchanges=_scaled(*ids), path_receipt=receipt,
                                   indicator_unit="kg CO2-Eq")
    assert b["scopes"]["scope_1"]["value"] == 100
    assert b["excluded"]["value"] == 20
    assert b["unattributed"]["value"] == 7
    assert b["reconciled"] is True
    pending = {**default, "boundary_status": "pending"}
    c = group_path_weighted_scopes(rules=[pending], scaled_exchanges=_scaled(*ids),
                                   path_receipt=receipt, indicator_unit="kg CO2-Eq")
    assert c["scopes"]["scope_1"]["value"] is None
    assert c["unattributed"]["value"] == 127


def test_excluded_rule_retaining_a_scope_still_buckets_as_excluded():
    # An excluded flow may keep the Scope it carried for tracking, but the grouping must read the
    # boundary first: the retained Scope never re-enters a bucket or the total.
    ids = ["blast-furnace::co2-a", "blast-furnace::co2-b"]
    receipt = _receipt([_path_row(process_uuid=STEEL_PROCESS, exchange_id=eid,
                                contribution=value, share=1.0, basis="foreground_direct")
                        for eid, value in zip(ids, [100.0, 20.0])])
    retained = _selected_rule(ids[1], "scope_1")
    retained["boundary_status"] = "excluded"
    result = group_path_weighted_scopes(rules=[retained], scaled_exchanges=_scaled(*ids),
                                        path_receipt=receipt, indicator_unit="kg CO2-Eq")
    assert result["scopes"]["scope_1"]["value"] is None
    assert result["excluded"]["value"] == 20
    assert result["unattributed"]["value"] == 100
    assert result["reconciled"] is True


def test_select_path_weighted_receipt_returns_only_the_matching_indicator():
    lcia_results = {
        "path_weighted_contribution_receipts": [
            {"canonical_indicator_key": "gwp100-new", "terms": []},
            {"canonical_indicator_key": "adp", "terms": []},
        ]
    }
    assert select_path_weighted_receipt(lcia_results, canonical_indicator_key="gwp100-new") is not None
    assert select_path_weighted_receipt(lcia_results, canonical_indicator_key="unknown") is None
    # Absent field must be reported as "not available" so the caller falls back, not fabricates.
    assert select_path_weighted_receipt(None, canonical_indicator_key="gwp100-new") is None
    assert select_path_weighted_receipt({}, canonical_indicator_key="gwp100-new") is None


def test_group_path_weighted_scopes_partitions_shared_background_across_consumers():
    steel = _path_row(
        process_uuid=STEEL_PROCESS,
        exchange_id="steel::co2",
        contribution=5.0,
        share=1.0,
        basis="foreground_direct",
    )
    bg_a = _path_row(
        process_uuid=BG_PROCESS,
        exchange_id="bg::co2",
        contribution=1.0,
        share=1.0 / 3.0,
        basis="background_consumer_path",
        consumer_exchange_id="consumer-a::coal-in",
        consumer_process_uuid=CONSUMER_A,
        provider_instance_id="prov-1",
    )
    bg_b = _path_row(
        process_uuid=BG_PROCESS,
        exchange_id="bg::co2",
        contribution=2.0,
        share=2.0 / 3.0,
        basis="background_consumer_path",
        consumer_exchange_id="consumer-b::coal-in",
        consumer_process_uuid=CONSUMER_B,
        provider_instance_id="prov-1",
    )
    receipt = _receipt([steel, bg_a, bg_b])
    result = group_path_weighted_scopes(
        rules=[_selected_rule("steel::co2", "scope_1"), _selected_rule("bg::co2", "scope_3")],
        scaled_exchanges=_scaled("steel::co2", "bg::co2"),
        path_receipt=receipt,
        indicator_unit="kg CO2-Eq",
    )
    assert result["available"] is True
    # Scope 1 gets the foreground term exactly as-is; Scope 3 aggregates the two background
    # paths, so a shared background contributes the FULL emission across both consumers.
    assert result["scopes"]["scope_1"]["value"] == 5.0
    assert result["scopes"]["scope_3"]["value"] == 3.0
    assert result["scopes"]["scope_3"]["term_count"] == 2
    # Every path row's identity survives: the engine's per-consumer attribution is visible to One.
    assert [(p["consumer_exchange_id"], p["path_share"], p["path_contribution_value"]) for p in result["paths"]] == [
        (None, 1.0, 5.0),
        ("consumer-a::coal-in", 1.0 / 3.0, 1.0),
        ("consumer-b::coal-in", 2.0 / 3.0, 2.0),
    ]
    assert result["paths"][1]["provider_instance_id"] == "prov-1"
    # Reconciliation invariant: Σ buckets == Σ path_contribution_value == parent total.
    assert result["contribution_total"] == 8.0
    assert result["reconciled"] is True
    assert result["excluded"]["value"] == 0.0
    assert result["unattributed"]["value"] == 0.0
    assert result["engine_gap"]["value"] == 0.0
    # One's user grouping is never a compliance or factor claim.
    assert result["scope_1_2_3_statement"] is False


def test_excluding_one_elementary_exchange_moves_every_path_of_it_out_without_dropping_another():
    steel = _path_row(
        process_uuid=STEEL_PROCESS,
        exchange_id="steel::co2",
        contribution=5.0,
        share=1.0,
        basis="foreground_direct",
    )
    bg_a = _path_row(
        process_uuid=BG_PROCESS,
        exchange_id="bg::co2",
        contribution=1.0,
        share=1.0 / 3.0,
        basis="background_consumer_path",
        consumer_exchange_id="consumer-a::coal-in",
        consumer_process_uuid=CONSUMER_A,
    )
    bg_b = _path_row(
        process_uuid=BG_PROCESS,
        exchange_id="bg::co2",
        contribution=2.0,
        share=2.0 / 3.0,
        basis="background_consumer_path",
        consumer_exchange_id="consumer-b::coal-in",
        consumer_process_uuid=CONSUMER_B,
    )
    result = group_path_weighted_scopes(
        rules=[
            _selected_rule("steel::co2", "scope_1"),
            _excluded_rule("bg::co2"),
        ],
        scaled_exchanges=_scaled("steel::co2", "bg::co2"),
        path_receipt=_receipt([steel, bg_a, bg_b]),
        indicator_unit="kg CO2-Eq",
    )
    # A user rule excluding the whole elementary exchange moves BOTH path rows of that exchange
    # out of Scope buckets together; the foreground rule's Scope 1 value stays verbatim.
    assert result["scopes"]["scope_1"]["value"] == 5.0
    assert result["scopes"]["scope_3"]["value"] is None
    assert result["excluded"]["value"] == 3.0
    assert result["excluded"]["term_count"] == 2
    assert result["contribution_total"] == 8.0
    assert result["reconciled"] is True
    # Path detail still enumerates both excluded rows so the report can show which consumers lost.
    excluded_paths = [p for p in result["paths"] if p["decision"] == "excluded"]
    assert {p["consumer_exchange_id"] for p in excluded_paths} == {
        "consumer-a::coal-in",
        "consumer-b::coal-in",
    }


def test_engine_unattributed_rows_land_in_engine_gap_never_in_a_user_scope_bucket():
    steel = _path_row(
        process_uuid=STEEL_PROCESS,
        exchange_id="steel::co2",
        contribution=4.0,
        share=1.0,
        basis="foreground_direct",
    )
    bg_partial = _path_row(
        process_uuid=BG_PROCESS,
        exchange_id="bg::co2",
        contribution=3.0,
        share=0.75,
        basis="background_unattributed",
    )
    result = group_path_weighted_scopes(
        rules=[_selected_rule("steel::co2", "scope_1"), _selected_rule("bg::co2", "scope_2")],
        scaled_exchanges=_scaled("steel::co2", "bg::co2"),
        path_receipt=_receipt([steel, bg_partial], coverage="partial", unattributed=3.0),
        indicator_unit="kg CO2-Eq",
    )
    # The engine labelled this row `background_unattributed`; One must NOT silently include it in
    # scope_2 even though the user selected scope_2 for that exchange.
    assert result["scopes"]["scope_1"]["value"] == 4.0
    assert result["scopes"]["scope_2"]["value"] is None
    assert result["engine_gap"]["value"] == 3.0
    assert result["engine_gap"]["exchange_ids"] == ["bg::co2"]
    # Totals still reconcile — the gap is reported, not dropped.
    assert result["contribution_total"] == 7.0
    assert result["reconciled"] is True
    decisions = {p["exchange_id"]: p["decision"] for p in result["paths"]}
    assert decisions == {"steel::co2": "scope_1", "bg::co2": "engine_gap"}


def test_group_path_weighted_scopes_reports_missing_receipt_so_caller_falls_back():
    result = group_path_weighted_scopes(
        rules=[],
        scaled_exchanges=[],
        path_receipt=None,
        indicator_unit="kg CO2-Eq",
    )
    # When the engine did not emit the R3 view, One must not fabricate a grouping — the caller
    # is expected to fall back to the flat characterized terms.
    assert result["available"] is False
    assert result["reason"] == "path_weighted_receipt_not_emitted"
    assert result["reconciled"] is False
    assert result["problems"][0]["code"] == "PATH_WEIGHTED_RECEIPT_MISSING"


def test_unclaimed_path_stays_in_unattributed_not_silently_bucketed():
    steel = _path_row(
        process_uuid=STEEL_PROCESS,
        exchange_id="steel::co2",
        contribution=6.0,
        share=1.0,
        basis="foreground_direct",
    )
    result = group_path_weighted_scopes(
        rules=[],
        scaled_exchanges=_scaled("steel::co2"),
        path_receipt=_receipt([steel]),
        indicator_unit="kg CO2-Eq",
    )
    # No rule claims this exchange → its path row lands in `unattributed`, never in a Scope.
    assert result["scopes"]["scope_1"]["value"] is None
    assert result["unattributed"]["value"] == 6.0
    assert result["unattributed"]["exchange_ids"] == ["steel::co2"]
    assert result["reconciled"] is True


def _consumer_rule(consumer_exchange_id: str, scope: str, location: str) -> dict:
    # A Scope 2/3 rule for a user-pinned closed-leaf background binds to the selectable consumer
    # input, not to the engine-expanded background node (which is not in One's inventory boundary).
    return {
        "process_instance_id": consumer_exchange_id.split("::", 1)[0],
        "exchange_id": consumer_exchange_id,
        "direction": "input",
        "boundary_status": "selected",
        "location_role": location,
        "scope": scope,
        "cbam_relevant": False,
        "classification_basis": "user",
    }


def test_pinned_project_background_groups_into_scope2_by_consumer_input():
    steel = _path_row(
        process_uuid=STEEL_PROCESS,
        exchange_id="steel::co2",
        contribution=1940.739734,
        share=1.0,
        basis="foreground_direct",
    )
    bg = _path_row(
        process_uuid=BG_PROCESS,
        exchange_id="project-background-x::1",
        contribution=94.732787,
        share=1.0,
        basis="background_consumer_path",
        consumer_exchange_id="ore-sintering::grid-electricity-in",
    )
    result = group_path_weighted_scopes(
        rules=[
            _selected_rule("steel::co2", "scope_1"),
            _consumer_rule("ore-sintering::grid-electricity-in", "scope_2", "purchased_energy"),
        ],
        scaled_exchanges=_scaled("steel::co2"),
        path_receipt=_receipt([steel, bg]),
        indicator_unit="kg CO2-Eq",
    )
    assert result["available"] is True
    assert result["scopes"]["scope_1"]["value"] == 1940.739734
    # The background lands in Scope 2 through the consumer input, not silently dropped or
    # mis-bucketed into Scope 1.
    assert result["scopes"]["scope_2"]["value"] == 94.732787
    assert result["unattributed"]["value"] == 0.0
    assert result["engine_gap"]["value"] == 0.0
    assert result["coverage_gaps"] == []
    assert result["reconciled"] is True
    assert result["contribution_total"] == 1940.739734 + 94.732787


def test_one_aggregation_lands_scope_1_2_and_3_all_nonzero_from_the_same_receipt():
    # P3 gate 三类非零: a single real aggregation over ONE path-weighted receipt must be able to
    # fill Scope 1, Scope 2 and Scope 3 simultaneously. The receipt is a constructed fixture
    # (labelled synthetic, tests-only — never an official seed) but it exercises the real
    # group_path_weighted_scopes kernel with the engine's R3 row shapes: an onsite foreground
    # emission, a purchased-energy background reached through its consumer input, and an
    # upstream-supply background reached through a different consumer input.
    steel = _path_row(
        process_uuid=STEEL_PROCESS,
        exchange_id="steel::co2",
        contribution=1940.739734,
        share=1.0,
        basis="foreground_direct",
    )
    power_bg = _path_row(
        process_uuid=BG_PROCESS,
        exchange_id="project-background-power::1",
        contribution=94.732787,
        share=1.0,
        basis="background_consumer_path",
        consumer_exchange_id="ore-sintering::grid-electricity-in",
    )
    coke_bg = _path_row(
        process_uuid=BG_PROCESS,
        exchange_id="project-background-coke::1",
        contribution=310.5,
        share=1.0,
        basis="background_consumer_path",
        consumer_exchange_id="blast-furnace::coke-in",
    )
    result = group_path_weighted_scopes(
        rules=[
            _selected_rule("steel::co2", "scope_1"),
            _consumer_rule("ore-sintering::grid-electricity-in", "scope_2", "purchased_energy"),
            _consumer_rule("blast-furnace::coke-in", "scope_3", "upstream_supply"),
        ],
        scaled_exchanges=_scaled("steel::co2"),
        path_receipt=_receipt([steel, power_bg, coke_bg]),
        indicator_unit="kg CO2-Eq",
    )
    assert result["available"] is True
    # All three Scopes present and non-zero from the same call — none collapsed into another.
    assert result["scopes"]["scope_1"]["value"] == 1940.739734
    assert result["scopes"]["scope_2"]["value"] == 94.732787
    assert result["scopes"]["scope_3"]["value"] == 310.5
    assert all(result["scopes"][s]["term_count"] == 1 for s in ("scope_1", "scope_2", "scope_3"))
    # Nothing leaked: no unattributed, no engine gap, and the total is exactly the three buckets.
    assert result["unattributed"]["value"] == 0.0
    assert result["engine_gap"]["value"] == 0.0
    assert result["coverage_gaps"] == []
    assert result["contribution_total"] == 1940.739734 + 94.732787 + 310.5
    assert result["reconciled"] is True
    # Each path keeps its own identity: the two backgrounds stay separate by consumer input.
    decisions = {p["source_exchange_id"]: p["decision"] for p in result["paths"]}
    assert decisions == {
        "steel::co2": "scope_1",
        "project-background-power::1": "scope_2",
        "project-background-coke::1": "scope_3",
    }
    assert result["scope_1_2_3_statement"] is False


def test_pinned_project_background_without_a_consumer_rule_is_unattributed_not_guessed():
    steel = _path_row(
        process_uuid=STEEL_PROCESS,
        exchange_id="steel::co2",
        contribution=1940.739734,
        share=1.0,
        basis="foreground_direct",
    )
    bg = _path_row(
        process_uuid=BG_PROCESS,
        exchange_id="project-background-x::1",
        contribution=94.732787,
        share=1.0,
        basis="background_consumer_path",
        consumer_exchange_id="ore-sintering::grid-electricity-in",
    )
    result = group_path_weighted_scopes(
        rules=[_selected_rule("steel::co2", "scope_1")],
        scaled_exchanges=_scaled("steel::co2"),
        path_receipt=_receipt([steel, bg]),
        indicator_unit="kg CO2-Eq",
    )
    # No rule claims the consumer input, so the background is honestly reported unattributed
    # (never fabricated into a Scope) and the totals still reconcile. The unclaimed contribution
    # is reported under its elementary exchange id, the same shape as an unclaimed foreground term.
    assert result["scopes"]["scope_2"]["value"] is None
    assert result["unattributed"]["value"] == 94.732787
    assert result["unattributed"]["exchange_ids"] == ["project-background-x::1"]
    assert result["reconciled"] is True
