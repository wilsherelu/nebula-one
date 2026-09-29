"""The pinned native climate contract holds public identity only; licensed rows stay upstream."""
from __future__ import annotations

import json
import re
from importlib.resources import files

import pytest
from pydantic import ValidationError

from nebula_one.native_climate_contract import NativeClimateContract

_RESOURCE = json.loads(
    files("nebula_one")
    .joinpath("resources/native_background_climate.json")
    .read_text(encoding="utf-8")
)


def test_shipped_contract_pins_one_exact_method_and_cites_its_source() -> None:
    contract = NativeClimateContract()
    pin = contract.request_payload()
    assert pin["schema_version"] == "provider.native-background-climate-total.request.v1"
    assert pin["database_release"] == "ecoinvent_3.11"
    for field in (
        "method_package_sha256",
        "runtime_manifest_sha256",
        "flow_snapshot_hash",
        "reference_dependency_snapshot_hash",
    ):
        assert re.fullmatch(r"[0-9a-f]{64}", pin[field]), field
    assert re.fullmatch(r"[0-9a-f]{40}", contract.source_contract["commit"])
    assert contract.source_contract["document"] == "docs/PROVIDER_NATIVE_CLIMATE_TOTAL_V1.md"
    # The contract's only indicator is EF v3.1 / climate change / GWP100, so the method selection a
    # provider solve must carry is published with it instead of chosen per request.
    assert contract.solve_methods() == ["EF v3.1"]
    # A moving reference would let an already saved analysis change meaning later.
    assert all(value not in {"latest", "active", "next", "*"} for value in pin.values())


def test_contract_refuses_a_file_without_its_method_selection(tmp_path) -> None:
    payload = json.loads(json.dumps(_RESOURCE))
    payload.pop("provider_solve_request")
    path = tmp_path / "native_background_climate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="lcia_methods"):
        NativeClimateContract(str(path))


def test_contract_refuses_a_file_that_cannot_cite_its_source(tmp_path) -> None:
    payload = dict(_RESOURCE)
    payload.pop("source_contract")
    path = tmp_path / "native_background_climate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="cite its source"):
        NativeClimateContract(str(path))


def test_operator_can_select_a_pinned_native_contract_file(tmp_path, monkeypatch) -> None:
    from nebula_one.config import Settings

    payload = json.loads(json.dumps(_RESOURCE))
    payload["solve_request_pin"]["runtime_manifest_sha256"] = "a" * 64
    path = tmp_path / "native_background_climate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("NEBULA_ONE_NATIVE_CLIMATE_CONTRACT_FILE", str(path))

    contract = NativeClimateContract(Settings.from_env().native_climate_contract_file)
    assert contract.request_payload()["runtime_manifest_sha256"] == "a" * 64


def test_contract_refuses_a_pin_that_is_not_the_engine_request_shape(tmp_path) -> None:
    payload = json.loads(json.dumps(_RESOURCE))
    payload["solve_request_pin"]["method_package_sha256"] = "latest"
    path = tmp_path / "native_background_climate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="method_package_sha256"):
        NativeClimateContract(str(path))
