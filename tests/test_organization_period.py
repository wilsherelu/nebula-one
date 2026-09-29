import json
from pathlib import Path

import pytest

from nebula_one.analysis.organization_period import build_organization_period
from nebula_one.errors import DomainError


MANIFEST = json.loads((Path(__file__).resolve().parents[1] / "src" / "nebula_one" / "resources" / "official_methods" /
                       "ghg-organization-period-model-1.0.2.json").read_text(encoding="utf-8"))["manifest"]


def _build(*, output=1000, activity=True, factor_boundary="supplier_cradle_to_gate_excluding_modelled_operations"):
    return build_organization_period(
        application_id="app", revision_id="revision", snapshot_id="snapshot", snapshot_hash="a" * 64,
        period={"id": "period", "name": "2026"}, facility="example facility",
        controlled_process_ids=["sinter", "furnace"], model_process_ids=["sinter", "furnace"],
        baseline_output=1, period_output=output, output_unit="kg", foreground_value=1.9,
        background_value=0.02, climate_unit="kg CO2-Eq", native_method={"content_sha256": "b" * 64},
        method_ref="ghg.iron-steel.organization-period-model@1.0.2", method_hash="c" * 64,
        manifest=MANIFEST, mapped_exchange_ids=["continuous-casting::grid-electricity-in"],
        unmodelled_inputs={"ore-sintering::iron-ore-in": {"amount": 1.49, "unit": "kg"}},
        scope3_activities=[{
            "activity_id": "ore-2026", "category": "purchased_goods_and_services",
            "consumer_exchange_id": "ore-sintering::iron-ore-in", "quantity": 1.49 * output,
            "activity_unit": "kg", "factor_value": 0.1, "factor_unit": "kg CO2-Eq/kg",
            "factor_version": "supplier-v1", "factor_source": "illustrative supplier statement",
            "factor_boundary": factor_boundary, "evidence_sha256": "d" * 64,
            "evidence_role": "demonstration_proxy",
            "outside_model": True,
        }] if activity else [], category_statuses={"fuel_and_energy_related_activities": "missing_activity"},
    )


def test_period_scales_scopes_and_keeps_missing_categories_open():
    first = _build()
    doubled = _build(output=2000)
    assert first["scopes"]["scope_1"]["value"] == 1900
    assert first["scopes"]["scope_2"]["value"] is None
    assert first["scopes"]["scope_2"]["status"] == "missing_generation_only_evidence"
    assert first["unclassified_background_reference"]["value"] == 20
    assert doubled["unclassified_background_reference"]["value"] == 40
    assert first["coverage"]["missing_scope2_generation_evidence"] is True
    assert first["scopes"]["scope_3"]["value"] == 149
    assert doubled["scopes"]["scope_1"]["value"] == 3800
    assert doubled["scopes"]["scope_3"]["value"] == 298
    assert first["combined_total"] is None
    assert first["coverage"]["missing_activity_categories"] == ["fuel_and_energy_related_activities"]


def test_no_supplier_activity_does_not_become_zero():
    result = _build(activity=False)
    assert result["scopes"]["scope_3"]["value"] is None
    assert result["combined_total"] is None


def test_lifecycle_electricity_background_cannot_be_used_as_generation_only_scope2():
    # A 0.02 lifecycle total could include 0.015 generation and 0.005 upstream;
    # the native receipt has no verified split, so neither part is assigned here.
    result = _build(activity=False)
    assert result["unclassified_background_reference"]["value"] == 20
    assert result["scopes"]["scope_2"]["value"] is None
    assert result["scopes"]["scope_3"]["value"] is None
    assert result["combined_total"] is None


def test_factor_boundary_prevents_scope_overlap():
    with pytest.raises(DomainError) as error:
        _build(factor_boundary="includes_onsite_combustion")
    assert error.value.code == "ORGANIZATION_SCOPE3_MODEL_OVERLAP"
