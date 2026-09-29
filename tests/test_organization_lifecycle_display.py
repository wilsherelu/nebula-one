import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.organization_lifecycle_display import organization_lifecycle_display
from nebula_one.runtime_schemas import MethodPackageCreate


def _method():
    path = (Path(__file__).resolve().parents[1] / "src" / "nebula_one" / "resources"
            / "official_methods" / "organization-lifecycle-carbon-steel-1.0.5.json")
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


def test_display_refuses_method_hash_drift():
    method = _method()
    method.content_sha256 = "0" * 64
    with pytest.raises(DomainError) as caught:
        organization_lifecycle_display(method, "en")
    assert caught.value.code == "ORGANIZATION_DISPLAY_SOURCE_MISMATCH"
