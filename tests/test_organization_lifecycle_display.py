import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nebula_one.errors import DomainError
from nebula_one.exports.organization_lifecycle import render_organization_lifecycle_html
from nebula_one.hashing import canonical_json_sha256
from nebula_one.organization_lifecycle_display import organization_lifecycle_display
from nebula_one.runtime_schemas import MethodPackageCreate


def _method(version="1.0.5"):
    path = (Path(__file__).resolve().parents[1] / "src" / "nebula_one" / "resources"
            / "official_methods" / f"organization-lifecycle-carbon-steel-{version}.json")
    package = MethodPackageCreate.model_validate(json.loads(path.read_text(encoding="utf-8")))
    return SimpleNamespace(package_id=package.package_id, version=package.version,
                           package_kind=package.package_kind, manifest=package.manifest,
                           content_sha256=canonical_json_sha256(package.model_dump(mode="json")))


def test_english_display_covers_exact_immutable_method():
    method = _method()
    result = organization_lifecycle_display(method, "en")
    assert result["method_package"]["content_sha256"] == method.content_sha256
    assert result["labels"]["categories"]["purchased_iron_ore"] == "Upstream purchased iron ore"
    assert result["labels"]["exchanges"]["ore-sintering::iron-ore-in"] == "Iron ore purchased for sintering"
    assert result["labels"]["group_status"]["partial"] == "Some required data is missing"
    assert organization_lifecycle_display(method, "zh")["labels"]["categories"]["purchased_iron_ore"] == "采购铁矿石上游"


@pytest.mark.parametrize('version', ['1.0.6', '1.0.7', '1.0.11'])
def test_optional_supply_method_has_its_own_exact_display_projection(version):
    method = _method(version)
    display = organization_lifecycle_display(method, "en")
    assert display["method_package"]["content_sha256"] == method.content_sha256
    assert display["labels"]["group_status"]["missing_energy_path"] == "Energy supply not linked; value unknown"


def test_display_refuses_method_hash_drift():
    method = _method()
    method.content_sha256 = "0" * 64
    with pytest.raises(DomainError) as caught:
        organization_lifecycle_display(method, "en")
    assert caught.value.code == "ORGANIZATION_DISPLAY_SOURCE_MISMATCH"


def test_english_report_uses_pinned_category_labels_without_changing_result():
    display = organization_lifecycle_display(_method(), "en")
    record = {"content_sha256": "a" * 64, "result": {
        "facility": "Steel", "reporting_period": {"name": "2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
        "method_package": {"reference": "nebula.organization-lifecycle-carbon.steel-model@1.0.5",
                           "content_sha256": display["method_package"]["content_sha256"]},
        "source_snapshot": {"id": "snapshot", "content_sha256": "b" * 64},
        "activity_basis": {"mode": "per_unit_product", "baseline_output": 1000,
                           "period_output": 1000, "scale_factor": 1},
        "groups": {"on_site_direct": {"value": 1940, "status": "calculated_from_controlled_foreground"},
                   "purchased_energy_lifecycle": {"value": 92, "status": "calculated_from_exclusive_energy_background_paths"},
                   "other_value_chain": {"value": None, "status": "partial", "categories": [
                       {"category": "purchased_iron_ore", "name": "采购铁矿石上游",
                        "boundary_status": "selected", "value": None, "activities": [],
                        "proxy_reference_value": None}]}},
        "combined_total": None,
    }}
    html = render_organization_lifecycle_html(record, english_labels=display["labels"])
    assert "Upstream purchased iron ore" in html
    assert "Scope 1: on site direct emissions" in html
    assert "Some required data is missing" in html
    assert "2026-01-01—2026-12-31" in html
    assert "采购铁矿石上游" not in html
    assert "not a complete lifecycle inventory" in html
