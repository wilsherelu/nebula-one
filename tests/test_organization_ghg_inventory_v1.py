"""Discriminating tests for the organization inventory consuming user rules (T2 seam).

The engine ``total_footprint`` is the raw whole-product indicator and does NOT change when a user
method excludes or relabels a contribution path. These tests pin that the org inventory counts from
the user method's grouped Scope buckets instead: excluding a non-zero path lowers the org counted
quantity, relabeling moves value between Scopes while the total is preserved, and known-but-unselected
(unattributed) and engine-missing (engine_gap) paths stay out of the counted Scopes and are reported
apart. A source with no user method still falls back to the raw total.
"""

from __future__ import annotations

import pytest

from nebula_one.analysis.organization_ghg_inventory_v1 import (
    build_organization_ghg_inventory_v1,
)
from nebula_one.errors import DomainError

MANIFEST = {
    "output_schema": {"schema_version": "nebula_one.organization-ghg-inventory.v1"},
    "classification_rules": {
        "role_mappings": [
            {"role_pattern": "steel.own.production*", "scope": "scope_1", "category": "own_production"}
        ],
        "required_scopes": ["scope_1", "scope_2", "scope_3"],
    },
}


def _grouping(scopes, excluded=0.0, unattributed=None, engine_gap=None, reconciled=True, coverage=None):
    # Mirror the kernel: a Scope with no term reports value None, not a fabricated 0.0.
    def bucket(value):
        return {"value": value if value else None, "unit": "kg CO2-Eq" if value else None,
                "term_count": 1 if value else 0}
    return {
        "scopes": {
            "scope_1": bucket(scopes[0]),
            "scope_2": bucket(scopes[1]),
            "scope_3": bucket(scopes[2]),
        },
        "excluded": {"value": excluded, "unit": "kg CO2-Eq", "term_count": 1 if excluded else 0},
        "unattributed": {"value": (unattributed or 0.0), "unit": "kg CO2-Eq",
                          "exchange_ids": ["u-1"] if unattributed else []},
        "engine_gap": {"value": (engine_gap or 0.0), "unit": "kg CO2-Eq",
                        "exchange_ids": ["g-1"] if engine_gap else []},
        "coverage_gaps": coverage or [],
        "contribution_total": sum(v for v in scopes if v) + (excluded or 0.0) + (unattributed or 0.0)
        + (engine_gap or 0.0),
        "reconciled": reconciled,
    }


def _pcf(snapshot_id, revision_id, *, grouping=None, total=1940.7397340):
    contribution_analysis = {}
    if grouping is not None:
        contribution_analysis["user_method_grouping"] = {
            "method": {"method_id": "m-1", "version": 1, "content_sha256": "a" * 64},
            "grouping": grouping,
        }
    return {
        "capability_key": "pcf.product.v1",
        "method_package": {"lcia_method": "EF3.1 climate change"},
        "total_footprint": {"value": total, "unit": "kg CO2-Eq"},
        "data_quality": {"database_release": "EF3.1"},
        "source_snapshot": {"id": snapshot_id, "system_revision_id": revision_id},
        "contribution_analysis": contribution_analysis,
        "content_sha256": "b" * 64,
    }


def _binding(binding_id, snapshot_id, revision_id, role="steel.own.production"):
    return {
        "binding_id": binding_id,
        "role": role,
        "system_model_id": "model-1",
        "system_revision_id": revision_id,
        "solved_snapshot_id": snapshot_id,
        "reporting_period_id": "period-1",
        "organizational_boundary_id": "boundary-1",
        "content_sha256": "c" * 64,
    }


def _source(binding_id, snapshot_id, *, grouping=None, total=1940.7397340, revision_id="rev-1"):
    return {
        "binding": _binding(binding_id, snapshot_id, revision_id),
        "pcf": _pcf(snapshot_id, revision_id, grouping=grouping, total=total),
    }


def _build(sources):
    return build_organization_ghg_inventory_v1(
        application_id="app-1",
        sources=sources,
        method_package_ref="ghg.steel.org-inventory.v1@1.0.0",
        method_package_sha256="d" * 64,
        method_package_kind="organization_ghg_inventory",
        manifest=MANIFEST,
    )


def _build_declaring(sources, required_scopes):
    manifest = {
        "output_schema": MANIFEST["output_schema"],
        "classification_rules": {
            "role_mappings": MANIFEST["classification_rules"]["role_mappings"],
            "required_scopes": required_scopes,
        },
    }
    return build_organization_ghg_inventory_v1(
        application_id="app-1",
        sources=sources,
        method_package_ref="ghg.steel.org-inventory.v1@1.0.0",
        method_package_sha256="d" * 64,
        method_package_kind="organization_ghg_inventory",
        manifest=manifest,
    )


def _scope_total(result, scope):
    for item in result["scopes"]:
        if item["scope"] == scope:
            return item["total"]["value"]
    return None


def test_include_exclude_changes_org_counted():
    # Method A counts everything into scope_1; method B excludes one non-zero path (193.4592).
    a = _source("b-a", "snap-a", grouping=_grouping([1940.7397340, 1, 1]))
    b = _source("b-b", "snap-b", grouping=_grouping([1747.2805340, 1, 1], excluded=193.4592))
    result_a, result_b = _build([a]), _build([b])
    delta = result_a["total"]["value"] - result_b["total"]["value"]
    assert delta == pytest.approx(193.4592)
    assert _scope_total(result_a, "scope_1") - _scope_total(result_b, "scope_1") == pytest.approx(193.4592)


def test_reclass_preserves_total_changes_distribution():
    # Same counted total (nothing excluded), one path relabeled from scope_1 to scope_2.
    a = _source("b-a", "snap-a", grouping=_grouping([1000.0, 900.0, 40.7397340]))
    c = _source("b-c", "snap-c", grouping=_grouping([800.0, 1100.0, 40.7397340]))
    result_a, result_c = _build([a]), _build([c])
    assert result_a["total"]["value"] == pytest.approx(result_c["total"]["value"])
    assert _scope_total(result_a, "scope_1") != _scope_total(result_c, "scope_1")
    assert _scope_total(result_c, "scope_1") == pytest.approx(800.0)


def test_unattributed_and_engine_gap_stay_out_of_counted_and_separate():
    source = _source(
        "b-a",
        "snap-a",
        grouping=_grouping([1000.0, 900.0, 40.7397340], unattributed=50.0, engine_gap=30.0),
    )
    result = _build([source])
    assert result["total"]["value"] == pytest.approx(1940.7397340)
    entry = result["attribution"]["sources"][0]
    assert entry["unattributed"]["value"] == pytest.approx(50.0)
    assert entry["unattributed"]["exchange_ids"] == ["u-1"]
    assert entry["engine_gap"]["value"] == pytest.approx(30.0)
    assert entry["engine_gap"]["exchange_ids"] == ["g-1"]


def test_no_user_method_falls_back_to_engine_total():
    # A source without a user grouping still counts its raw total_footprint into the role Scope.
    a = _source("b-a", "snap-a", grouping=_grouping([1000.0, 900.0, 40.7397340]))
    plain = _source("b-plain", "snap-plain", grouping=None, total=10.0)
    result = _build([a, plain])
    # plain total (10.0) landed in scope_1 alongside the grouped 1000.0
    assert _scope_total(result, "scope_1") == pytest.approx(1010.0)
    counted = {(s["binding_id"], s["value"]) for s in result["scopes"][0]["categories"][0]["sources"]}
    assert ("b-plain", 10.0) in counted


def test_unreconciled_grouping_falls_back_not_counted_as_grouped():
    # A partial grouping that does not reconcile must not silently drop value: fall back to raw total.
    a = _source("b-a", "snap-a", grouping=_grouping([1000.0, 900.0, 40.7397340]))
    partial = _source("b-p", "snap-p", grouping=_grouping([5.0, 0.0, 0.0], reconciled=False), total=99.0)
    result = _build([a, partial])
    # partial falls back to its raw 99.0 in scope_1, not the unreconciled 5.0
    assert _scope_total(result, "scope_1") == pytest.approx(1099.0)


def test_empty_grouping_rejected():
    source = _source("b-a", "snap-a", grouping=_grouping([0.0, 0.0, 0.0]))
    with pytest.raises(DomainError) as exc:
        _build([source])
    assert exc.value.code == "ORGANIZATION_GHG_USER_METHOD_EMPTY"


def test_missing_kind_rejected():
    source = _source("b-a", "snap-a", grouping=_grouping([1000.0, 900.0, 40.0]))
    with pytest.raises(DomainError) as exc:
        build_organization_ghg_inventory_v1(
            application_id="app-1",
            sources=[source],
            method_package_ref="x@1",
            method_package_sha256="d" * 64,
            method_package_kind="wrong_kind",
            manifest=MANIFEST,
        )
    assert exc.value.code == "ORGANIZATION_GHG_METHOD_KIND_INVALID"


def test_subset_declaration_allowed_when_present():
    # A foreground-only package that declares just scope_1 succeeds when scope_1 is populated.
    # This is the relaxation: the old gate demanded all three scopes unconditionally.
    source = _source("b-a", "snap-a", grouping=_grouping([1940.7397340, 0.0, 0.0]))
    result = _build_declaring([source], ["scope_1"])
    assert _scope_total(result, "scope_1") == pytest.approx(1940.7397340)
    assert result["attribution"]["counted_total"]["value"] == pytest.approx(1940.7397340)


def test_subset_declaration_still_requires_present_scopes():
    # Relaxing the gate does not relax the presence check: a declared-but-empty scope is rejected.
    source = _source("b-a", "snap-a", grouping=_grouping([1000.0, 0.0, 0.0]))
    with pytest.raises(DomainError) as exc:
        _build_declaring([source], ["scope_1", "scope_2"])
    assert exc.value.code == "ORGANIZATION_GHG_SCOPE_INCOMPLETE"
    assert exc.value.details["missing_scopes"] == ["scope_2"]


def test_declaration_rejects_unknown_scope():
    source = _source("b-a", "snap-a", grouping=_grouping([1000.0, 900.0, 40.0]))
    with pytest.raises(DomainError) as exc:
        _build_declaring([source], ["scope_1", "scope_9"])
    assert exc.value.code == "ORGANIZATION_GHG_SCOPE_RULES_INVALID"


def test_declaration_rejects_empty_scope_list():
    source = _source("b-a", "snap-a", grouping=_grouping([1000.0, 900.0, 40.0]))
    with pytest.raises(DomainError) as exc:
        _build_declaring([source], [])
    assert exc.value.code == "ORGANIZATION_GHG_SCOPE_RULES_INVALID"


def test_declaration_rejects_duplicate_scopes():
    source = _source("b-a", "snap-a", grouping=_grouping([1000.0, 900.0, 40.0]))
    with pytest.raises(DomainError) as exc:
        _build_declaring([source], ["scope_1", "scope_1"])
    assert exc.value.code == "ORGANIZATION_GHG_SCOPE_RULES_INVALID"
