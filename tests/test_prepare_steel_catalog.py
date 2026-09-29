import json
from pathlib import Path
from types import SimpleNamespace
from io import BytesIO
from zipfile import ZipFile

import pytest

from nebula_one.errors import UpstreamError
from nebula_one.seeds.prepare_steel_catalog import _reference_flow_missing
from nebula_one.seeds.prepare_open_supply_flow import ensure_open_supply_flow, open_flow_pins
from nebula_one.services.seed_autoload import SeedAutoloadService
from nebula_one.seeds.standard_seed_bundle import SeedBuild, resolve_seed_directory
from nebula_one.seeds.steel_catalog_prerequisite import load_steel_catalog_prerequisite


def test_steel_autoload_declares_both_exact_open_tiangong_flows() -> None:
    manifest = json.loads((Path(__file__).resolve().parents[1] / "deploy/seeds/steel-demo.json").read_text(encoding="utf-8"))
    flow_steps = [step for step in manifest["steps"] if step["kind"] == "ensure_open_tiangong_flows"]
    assert len(flow_steps) == 1
    assert flow_steps[0]["flows"] == open_flow_pins()
    assert {item["flow_uuid"] for item in flow_steps[0]["flows"]} == {
        "3d76981f-964a-4865-b588-0e067a2a1163",
        "08a91e70-3ddc-11dd-923d-0050c2490048",
    }


def test_steel_open_flow_autoload_accepts_the_pinned_list(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = json.loads((Path(__file__).resolve().parents[1] / "deploy/seeds/steel-demo.json").read_text(encoding="utf-8"))
    step = next(item for item in manifest["steps"] if item["kind"] == "ensure_open_tiangong_flows")
    service = SeedAutoloadService.__new__(SeedAutoloadService)
    service.seed_installation = SimpleNamespace(client=object())
    monkeypatch.setattr("nebula_one.services.seed_autoload.ensure_open_supply_flow", lambda client: {
        "status": "present", "co2_flow": {"status": "present"},
    })
    assert service._dispatch(step["kind"], step)[0] == "replayed"


def test_only_upstream_404_means_catalog_flow_is_missing() -> None:
    missing = UpstreamError(
        code="NEBULA_LCA_REJECTED",
        message="Nebula LCA returned HTTP 404",
        status_code=422,
        details={"upstream_status": 404},
    )
    invalid = UpstreamError(
        code="NEBULA_LCA_REJECTED",
        message="Nebula LCA returned HTTP 422",
        status_code=422,
        details={"upstream_status": 422},
    )
    assert _reference_flow_missing(missing)
    assert not _reference_flow_missing(invalid)


def test_public_steel_resource_contains_only_two_exact_catalog_flows() -> None:
    steel = SeedBuild(resolve_seed_directory("iron-steel-bf-bof-crude-steel", None))
    descriptor, payload, rows = load_steel_catalog_prerequisite()
    expected = {row["flow_uuid"]: row for row in steel.flow_dependencies["dependencies"]
                if row.get("provided_by")}
    assert descriptor["source_bundle_content_sha256"] == next(
        row["provided_by"]["bundle_content_sha256"] for row in expected.values())
    assert {row["flow_uuid"] for row in rows} == set(expected)
    assert all(all(row.get(key) == value for key, value in expected[row["flow_uuid"]]["observed"].items())
               for row in rows)
    with ZipFile(BytesIO(payload)) as archive:
        assert set(archive.namelist()) == {"manifest.json", "catalog/flows.json"}


def test_steel_build_validates_without_the_hydrogen_seed_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    original_is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda path: False if path.as_posix().endswith(
        "cases/standard-lca-seeds/hydrogen-natural-gas-smr/seed.json") else original_is_file(path))
    steel = SeedBuild(resolve_seed_directory("iron-steel-bf-bof-crude-steel", None))
    steel.validate()


class FlowClient:
    def __init__(self, *, present: bool = False, drift: bool = False) -> None:
        self.present = set(("3d76981f-964a-4865-b588-0e067a2a1163", "08a91e70-3ddc-11dd-923d-0050c2490048")) if present else set()
        self.drift = drift
        self.calls: list[bool] = []
        self.current_flow = ""

    def get_reference_flow(self, flow_uuid: str) -> dict:
        if flow_uuid not in self.present:
            raise UpstreamError(code="NEBULA_LCA_REJECTED", message="missing", status_code=422,
                                details={"upstream_status": 404})
        is_co2 = flow_uuid == "08a91e70-3ddc-11dd-923d-0050c2490048"
        return {
            "flow_uuid": flow_uuid, "source_namespace": "tiangong_open_data",
            "source_version": "03.00.004" if is_co2 else "01.01.003",
            "tidas_flow_property_uuid": "93a60a56-a3c8-11da-a746-0800200b9a66" if is_co2 else "93a60a56-a3c8-11da-a746-0800200c9a66",
            "default_unit": "other" if self.drift else ("kg" if is_co2 else "MJ"),
            "unit_group": "Units of mass" if is_co2 else "Units of energy",
        }

    def get_flow_version(self, namespace: str, flow_uuid: str, version: str) -> dict:
        if flow_uuid not in self.present:
            raise UpstreamError(code="NEBULA_LCA_REJECTED", message="missing", status_code=422,
                                details={"upstream_status": 404})
        return {
            "flow_id": flow_uuid, "source_namespace": namespace, "source_version": version,
            "unit": "kg", "unit_group": "Units of mass",
            "tidas_flow_property_uuid": "93a60a56-a3c8-11da-a746-0800200b9a66",
            "content_hash": "86be2befdb9df9d22cd49aa03d3c9b982cd7ad8bff855235d35a0110581160cc",
        }

    def import_tidas_flows(self, *, filename: str, payload: bytes, dry_run: bool) -> SimpleNamespace:
        assert filename.endswith(".import.json")
        self.current_flow = "08a91e70-3ddc-11dd-923d-0050c2490048" if "carbon-dioxide" in filename else "3d76981f-964a-4865-b588-0e067a2a1163"
        assert self.current_flow.encode() in payload
        self.calls.append(dry_run)
        if not dry_run:
            self.present.add(self.current_flow)
        return SimpleNamespace(payload={"inserted": 1, "total_records": 1, "failed": 0, "errors": [], "warnings": []})


def test_open_supply_flow_is_imported_through_formal_api_only_when_missing() -> None:
    client = FlowClient()
    assert ensure_open_supply_flow(client)["status"] == "imported"
    assert client.calls == [True, False, True, False]
    assert ensure_open_supply_flow(client)["status"] == "present"
    assert client.calls == [True, False, True, False]


def test_open_supply_flow_refuses_catalog_identity_drift() -> None:
    client = FlowClient(present=True, drift=True)
    with pytest.raises(ValueError, match="default_unit"):
        ensure_open_supply_flow(client)
    assert client.calls == []
