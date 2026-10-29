"""The classification suggestion derivation is an authoring aid, never an authority.

These cases pin the D3 contract: a suggestion cites only structural evidence that already exists, it
keeps a port pending when the energy property cannot be evidenced, it never proposes a Scope for a
foreground internal transfer (that would double-count the path), and it never overrides a rule the
reader already decided. The integration case exercises all three legal Scope sources in one pass.
"""
from __future__ import annotations

from nebula_one.analysis.classification_suggestion import (
    SUGGESTION_STRATEGY_VERSION,
    collect_energy_evidence,
    suggest_classifications,
)


def _port(exchange_id, direction, *, internal=False, name=None, unit="kg", process_id=None):
    return {
        "exchange_id": exchange_id,
        "process_id": process_id or exchange_id.split("::")[0],
        "process_name": "炼钢",
        "port_id": exchange_id.split("::")[-1],
        "name": name or exchange_id,
        "unit": unit,
        "direction": direction,
        "internal": internal,
    }


def _by_id(suggestions):
    return {row["exchange_id"]: row for row in suggestions}


def test_strategy_version_is_stable_identity():
    assert SUGGESTION_STRATEGY_VERSION == "nebula_one.classification-suggestion.v1"


def test_onsite_elementary_emission_suggests_scope_one():
    ports = [_port("p::e-co2", "emission", name="二氧化碳")]
    out = _by_id(suggest_classifications(
        ports=ports, rules=[], energy_exchange_ids=set(), energy_packages=[]))
    row = out["p::e-co2"]
    assert row["status"] == "suggested"
    assert row["confidence"] == "high"
    assert row["rationale"] == "onsite_direct_emission"
    assert row["suggested"] == {
        "boundary_status": "selected", "location_role": "onsite", "scope": "scope_1"}
    assert "contribution_domain.direct" in row["basis"]


def test_resource_direction_also_counts_as_onsite_elementary():
    ports = [_port("p::r-ore", "resource")]
    out = _by_id(suggest_classifications(
        ports=ports, rules=[], energy_exchange_ids=set(), energy_packages=[]))
    assert out["p::r-ore"]["suggested"]["scope"] == "scope_1"


def test_internal_transfer_input_is_not_applicable_no_scope():
    # Fed by another modelled process: its emissions are already counted at the provider.
    ports = [_port("p::in-steel", "input", internal=True)]
    out = _by_id(suggest_classifications(
        ports=ports, rules=[], energy_exchange_ids=set(), energy_packages=[]))
    row = out["p::in-steel"]
    assert row["status"] == "not_applicable"
    assert row["rationale"] == "foreground_internal_transfer"
    assert row["suggested"] is None


def test_purchased_declared_energy_input_suggests_scope_two():
    ports = [_port("p::in-power", "input", name="电力")]
    out = _by_id(suggest_classifications(
        ports=ports, rules=[], energy_exchange_ids={"p::in-power"},
        energy_packages=[{"package_id": "pkg", "version": "1", "content_sha256": "abc",
                          "declared_energy_exchange_ids": ["p::in-power"]}]))
    row = out["p::in-power"]
    assert row["status"] == "suggested"
    assert row["confidence"] == "high"
    assert row["rationale"] == "purchased_energy_path"
    assert row["suggested"] == {
        "boundary_status": "selected", "location_role": "purchased_energy", "scope": "scope_2"}


def test_purchased_non_energy_input_with_bound_package_suggests_scope_three():
    # A package is bound and does not declare this purchase as energy: medium evidence of Scope 3.
    ports = [_port("p::in-ore", "input", name="铁矿石")]
    out = _by_id(suggest_classifications(
        ports=ports, rules=[], energy_exchange_ids=set(),
        energy_packages=[{"package_id": "pkg", "version": "1", "content_sha256": "abc",
                          "declared_energy_exchange_ids": ["p::in-power"]}]))
    row = out["p::in-ore"]
    assert row["status"] == "suggested"
    assert row["confidence"] == "medium"
    assert row["rationale"] == "non_energy_supply_path"
    assert row["suggested"] == {
        "boundary_status": "selected", "location_role": "upstream_supply", "scope": "scope_3"}


def test_purchased_input_without_bound_package_stays_pending():
    # No authoritative declared set: the energy property is unresolved, so never guess a Scope.
    ports = [_port("p::in-power", "input", name="电力")]
    out = _by_id(suggest_classifications(
        ports=ports, rules=[], energy_exchange_ids=set(), energy_packages=[]))
    row = out["p::in-power"]
    assert row["status"] == "pending_evidence"
    assert row["confidence"] == "insufficient"
    assert row["rationale"] == "purchased_input_energy_unresolved"
    assert row["suggested"] == {
        "boundary_status": "pending", "location_role": "other", "scope": None}


def test_technosphere_output_is_not_applicable():
    ports = [_port("p::out-product", "output", name="粗钢")]
    out = _by_id(suggest_classifications(
        ports=ports, rules=[], energy_exchange_ids=set(), energy_packages=[]))
    row = out["p::out-product"]
    assert row["status"] == "not_applicable"
    assert row["rationale"] == "not_an_emission"
    assert row["suggested"] is None


def test_decided_rule_is_already_classified_and_not_overridden():
    ports = [_port("p::e-co2", "emission")]
    rules = [{"exchange_id": "p::e-co2", "boundary_status": "excluded", "scope": "scope_1"}]
    out = _by_id(suggest_classifications(
        ports=ports, rules=rules, energy_exchange_ids=set(), energy_packages=[]))
    row = out["p::e-co2"]
    assert row["status"] == "already_classified"
    assert row["confidence"] == "none"
    assert row["suggested"] is None
    # The reader's own decision is echoed for preview, never replaced.
    assert row["current"] == {
        "boundary_status": "excluded", "location_role": "other", "scope": "scope_1"}


def test_pending_rule_still_receives_a_suggestion():
    # A rule that only marks the port pending is not a decision, so the aid still proposes.
    ports = [_port("p::e-co2", "emission")]
    rules = [{"exchange_id": "p::e-co2", "boundary_status": "pending", "scope": None}]
    out = _by_id(suggest_classifications(
        ports=ports, rules=rules, energy_exchange_ids=set(), energy_packages=[]))
    assert out["p::e-co2"]["status"] == "suggested"
    assert out["p::e-co2"]["current"]["boundary_status"] == "pending"


def test_port_without_exchange_id_is_skipped():
    ports = [{"exchange_id": "", "direction": "emission", "internal": False}]
    assert suggest_classifications(
        ports=ports, rules=[], energy_exchange_ids=set(), energy_packages=[]) == []


def test_integration_case_all_three_scope_sources_in_one_pass():
    ports = [
        _port("p::e-co2", "emission", name="二氧化碳"),
        _port("p::e-ch4", "emission", name="甲烷"),
        _port("p::in-power", "input", name="购入电力"),
        _port("p::in-ore", "input", name="外购铁矿石"),
        _port("p::in-internal", "input", internal=True, name="前道工序钢材"),
        _port("p::out-steel", "output", name="粗钢"),
    ]
    energy_ids = {"p::in-power"}
    packages = [{"package_id": "pkg", "version": "2", "content_sha256": "def",
                 "declared_energy_exchange_ids": ["p::in-power"]}]
    out = _by_id(suggest_classifications(
        ports=ports, rules=[], energy_exchange_ids=energy_ids, energy_packages=packages))
    assert out["p::e-co2"]["suggested"]["scope"] == "scope_1"
    assert out["p::e-ch4"]["suggested"]["scope"] == "scope_1"
    assert out["p::in-power"]["suggested"]["scope"] == "scope_2"
    assert out["p::in-ore"]["suggested"]["scope"] == "scope_3"
    assert out["p::in-internal"]["suggested"] is None
    assert out["p::out-steel"]["suggested"] is None


def test_collect_energy_evidence_unions_both_declared_keys_and_records_source():
    manifests = [
        ({"classification_rules": {"energy_purchase_exchange_ids": ["a::p1"]}},
         "pkg-a", "1", "hash-a"),
        ({"classification_rules": {"scope2_purchase_exchange_ids": ["b::p2", "b::p3"]}},
         "pkg-b", "2", "hash-b"),
        ({"classification_rules": {}}, "pkg-empty", "1", "hash-empty"),
    ]
    ids, packages = collect_energy_evidence(manifests)
    assert ids == {"a::p1", "b::p2", "b::p3"}
    # A package that declares nothing is not recorded as an energy source.
    assert [pkg["package_id"] for pkg in packages] == ["pkg-a", "pkg-b"]
    assert packages[1]["declared_energy_exchange_ids"] == ["b::p2", "b::p3"]
    assert packages[1]["content_sha256"] == "hash-b"


def test_collect_energy_evidence_empty_when_no_package_declares_energy():
    ids, packages = collect_energy_evidence([({"classification_rules": {}}, "pkg", "1", "h")])
    assert ids == set()
    assert packages == []
