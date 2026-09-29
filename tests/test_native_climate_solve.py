"""Real HTTP acceptance of the pinned native background climate total, on synthetic evidence.

Every identity below is invented for the fixture; the only carried-over literals are the method and
runtime hashes One is required to send, which come from its own versioned contract resource.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from nebula_one.hashing import canonical_graph_sha256
from nebula_one.native_climate_contract import NativeClimateContract

SOURCE_COMMIT = NativeClimateContract().source_contract["commit"]


def _create_application(client) -> dict:
    response = client.post(
        "/api/v1/applications",
        json={
            "name": "Steel climate study",
            "application_type": "project_carbon",
            "description": "Native background climate acceptance fixture",
            "context": {"geography": "CN-SH"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _steel_like_graph(model_graph: dict) -> dict:
    """Give the preparation process one exact-Tiangong electricity input as its background leaf."""
    graph = copy.deepcopy(model_graph)
    graph["nodes"][0]["inputs"].append(
        {
            "id": "power-in",
            "flowUuid": "synthetic-power",
            "name": "electricity",
            "unit": "kWh",
            "unitGroup": "Units of energy",
            "amount": 1000.0,
            "type": "technosphere",
            "direction": "input",
            "flowSourceNamespace": "tiangong_open_data",
            "flowVersion": "01.00.000",
        }
    )
    return graph


def _attach_model(client, application_id: str, graph: dict) -> dict:
    response = client.post(
        f"/api/v1/applications/{application_id}/system-models/inline",
        json={
            "name": "Steel reference model",
            "provider": "nebula_lca",
            "source_id": "casepack:synthetic-steel",
            "source_version": 1,
            "expected_graph_sha256": canonical_graph_sha256(graph),
            "graph": graph,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _mapped_pin() -> dict:
    return {
        "consumer_exchange_id": "preparation::power-in",
        "source_flow_namespace": "tiangong_open_data",
        "source_flow_uuid": "synthetic-power",
        "source_flow_version": "01.00.000",
        "target_flow_uuid": "synthetic-electricity",
        "source_unit": "kWh",
        "target_unit": "kWh",
        "amount_factor": 1.0,
        "mapping_level": "L2",
        "mapping_status": "user_confirmed",
        "mapping_rule_id": "synthetic-rule",
        "mapping_package_id": "synthetic-mapping",
        "mapping_package_version": "1.0.0",
        "mapping_package_hash": "a" * 64,
        "database_release": "synthetic-release",
        "process_uuid": "synthetic-provider",
        "expected_process_content_hash": "b" * 64,
        "expected_vector_checksum": "c" * 64,
    }


def _solve_payload(**overrides) -> dict:
    payload = {
        "demand": [
            {
                "reference_flow_uuid": "flow-product",
                "amount": 1.0,
                "unit": "kg",
                "unit_group_uuid": "mass",
                "unit_group_version": "1",
            }
        ],
        "mapped_background_process_pins": [_mapped_pin()],
        "idempotency_key": "synthetic-native-solve",
        "native_background_climate": True,
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def native_setup(client, model_graph):
    application = _create_application(client)
    graph = _steel_like_graph(model_graph)
    system_model = _attach_model(client, application["id"], graph)
    return {
        "client": client,
        "application_id": application["id"],
        "revision_id": system_model["upstream_receipt"]["base_revision_id"],
    }


def _solve(setup, **overrides) -> dict:
    response = setup["client"].post(
        "/api/v1/applications/{}/system-revisions/{}/solve".format(
            setup["application_id"], setup["revision_id"]
        ),
        json=_solve_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _solve_requests(upstream_requests) -> list[dict]:
    return [
        item
        for item in upstream_requests
        if item["path"] == "/api/provider/v1/solve"
    ]


def test_native_solve_sends_the_pinned_package_and_freezes_the_answer(
    client, native_setup, upstream_requests
):
    solved = _solve(native_setup)

    forwarded = _solve_requests(upstream_requests)
    assert len(forwarded) == 1
    pin = NativeClimateContract().request_payload()
    assert forwarded[0]["json"]["native_background_climate"] == pin
    # The single indicator's method selection is the contract's, not something the caller dialed in.
    assert "lcia_methods" not in _solve_payload()
    assert forwarded[0]["json"]["lcia_methods"] == ["EF v3.1"]
    assert (
        forwarded[0]["json"]["mapped_background_process_pins"][0]["consumer_exchange_id"]
        == "preparation::power-in"
    )

    envelope = solved["native_background_climate"]
    assert envelope["schema_version"] == "nebula_one.native-background-climate.v1"
    assert envelope["source_contract"]["commit"] == SOURCE_COMMIT
    assert envelope["source_contract"]["document"] == (
        "docs/PROVIDER_NATIVE_CLIMATE_TOTAL_V1.md"
    )
    assert envelope["request"] == pin
    answer = envelope["response"]
    assert answer["merge_status"] == "merged"
    assert answer["unified_climate_total"] == 5.5
    assert answer["indicator"] == {
        "method": "EF v3.1",
        "category": "climate change",
        "name": "GWP100",
        "unit": "kg CO2-Eq",
    }
    assert answer["domains"]["native_background"]["coverage"] == {
        "explicit_nonzero": 83,
        "no_cf": 2654,
    }
    assert answer["domains"]["native_background"]["negative_cf_exchange_count"] == 1
    assert answer["carbon_storage_permanence"] == "not_assessed"
    assert answer["provider_system_model_evidence"] == (
        "not_asserted_by_local_vector_metadata"
    )
    # The engine answer is frozen verbatim, so a field One does not model yet cannot be dropped.
    assert answer["next_contract_field"] == "preserved"

    assert solved["lcia_results"] == {}
    assert solved["provider_receipt"]["calculation_basis"]["native_background_climate"] == pin
    assert solved["provider_receipt"]["provenance"][
        "native_climate_method_package_sha256"
    ] == pin["method_package_sha256"]
    assert [
        item["id"]
        for item in client.get(
            f"/api/v1/applications/{native_setup['application_id']}/solved-system-snapshots"
        ).json()
    ] == [solved["id"]]


def test_native_solve_forwards_two_distinct_mapped_providers(client, model_graph, upstream_requests):
    application = _create_application(client)
    graph = _steel_like_graph(model_graph)
    second_input = copy.deepcopy(graph["nodes"][0]["inputs"][-1])
    second_input["id"] = "power-in-2"
    graph["nodes"][0]["inputs"].append(second_input)
    model = _attach_model(client, application["id"], graph)
    first_pin = _mapped_pin()
    second_pin = {**first_pin, "consumer_exchange_id": "preparation::power-in-2",
                  "process_uuid": "synthetic-provider-2", "expected_vector_checksum": "d" * 64}
    setup = {"client": client, "application_id": application["id"],
             "revision_id": model["upstream_receipt"]["base_revision_id"]}
    solved = _solve(setup, mapped_background_process_pins=[first_pin, second_pin],
                    idempotency_key="synthetic-two-native-providers")

    forwarded = _solve_requests(upstream_requests)
    assert len(forwarded) == 1
    forwarded_pins = forwarded[0]["json"]["mapped_background_process_pins"]
    assert [(item["consumer_exchange_id"], item["process_uuid"]) for item in forwarded_pins] == [
        (first_pin["consumer_exchange_id"], first_pin["process_uuid"]),
        (second_pin["consumer_exchange_id"], second_pin["process_uuid"]),
    ]
    assert solved["provider_receipt"]["calculation_basis"]["mapped_background_process_pins"] == forwarded_pins


def test_native_snapshot_is_reread_without_a_second_solve(
    client, native_setup, upstream_requests
):
    solved = _solve(native_setup)

    for _ in range(2):
        listed = client.get(
            f"/api/v1/applications/{native_setup['application_id']}/solved-system-snapshots"
        )
        assert listed.status_code == 200, listed.text
        assert listed.json() == [solved]
    assert len(_solve_requests(upstream_requests)) == 1


def test_queued_native_solve_keeps_its_mode_through_the_worker(
    client, native_setup, upstream_requests
):
    queued = client.post(
        "/api/v1/applications/{}/system-revisions/{}/solve/queue".format(
            native_setup["application_id"], native_setup["revision_id"]
        ),
        json=_solve_payload(),
    )
    assert queued.status_code == 202, queued.text
    task = queued.json()["task"]

    completed = client.app.state.container.worker.process_one(
        worker_id="test-worker", lease_seconds=30
    )
    assert completed is not None
    assert completed.status == "completed"
    assert len(_solve_requests(upstream_requests)) == 1

    listed = client.get(
        f"/api/v1/applications/{native_setup['application_id']}/solved-system-snapshots"
    )
    assert listed.status_code == 200, listed.text
    snapshots = listed.json()
    assert len(snapshots) == 1
    envelope = snapshots[0]["native_background_climate"]
    assert envelope is not None, "the worker lost the native climate mode of its own run"
    assert envelope["response"]["unified_climate_total"] == 5.5
    assert envelope["request"] == NativeClimateContract().request_payload()


def test_native_mode_never_reuses_the_projection_snapshot(
    client, native_setup, upstream_requests
):
    # Same demand, same mapped provider and the same single indicator: only the mode differs, so a
    # snapshot that ignored the mode would hand back the projection answer for a climate request.
    projection = _solve(
        native_setup,
        native_background_climate=False,
        lcia_methods=NativeClimateContract().solve_methods(),
    )
    native = _solve(native_setup, idempotency_key="synthetic-native-solve-2")

    assert projection["native_background_climate"] is None
    assert native["native_background_climate"] is not None
    assert projection["solve_hash"] != native["solve_hash"]
    assert projection["content_sha256"] != native["content_sha256"]
    assert len(_solve_requests(upstream_requests)) == 2

    listed = client.get(
        f"/api/v1/applications/{native_setup['application_id']}/solved-system-snapshots"
    )
    assert [item["solve_hash"] for item in listed.json()] == [
        projection["solve_hash"],
        native["solve_hash"],
    ]


def test_native_and_projection_modes_share_no_idempotency_key(
    native_setup, upstream_requests
):
    _solve(native_setup)

    refused = native_setup["client"].post(
        "/api/v1/applications/{}/system-revisions/{}/solve".format(
            native_setup["application_id"], native_setup["revision_id"]
        ),
        json=_solve_payload(
            native_background_climate=False,
            lcia_methods=NativeClimateContract().solve_methods(),
        ),
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "ANALYSIS_IDEMPOTENCY_CONFLICT"
    assert len(_solve_requests(upstream_requests)) == 1


def test_native_snapshot_refuses_a_complete_pcf_claim(client, native_setup):
    package = client.post(
        "/api/v1/method-packages",
        json=json.loads(
            Path("examples/pcf-product-gold-standard/method-package.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    assert package.status_code == 201, package.text
    package = package.json()
    solved = _solve(native_setup)

    refused = client.post(
        f"/api/v1/solved-system-snapshots/{solved['id']}/product-carbon-footprint",
        json={"method_package_ref": f"{package['package_id']}@{package['version']}"},
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "PCF_LCIA_RESULT_REQUIRED"


@pytest.mark.parametrize(
    "mutation",
    ["no_mapped_provider", "caller_method", "bare_provider_pin"],
)
def test_native_selection_outside_the_contract_scope_is_refused(
    native_setup, upstream_requests, mutation
):
    if mutation == "no_mapped_provider":
        overrides = {"mapped_background_process_pins": []}
    if mutation == "caller_method":
        # Even the method the contract itself uses is refused when a caller tries to dial it in:
        # the selection must come from the versioned resource, or a withdrawn one can be requested.
        overrides = {"lcia_methods": ["EF v3.1"]}
    if mutation == "bare_provider_pin":
        overrides = {
            "mapped_background_process_pins": [],
            "background_process_pins": [
                {
                    "consumer_exchange_id": "preparation::power-in",
                    "source_namespace": "tiangong_open_data",
                    "process_uuid": "08a91e70-3ddc-11dd-923d-0050c2490048",
                    "version": "01.00.000",
                    "expected_process_content_hash": "b" * 64,
                    "expected_process_snapshot_hash": "c" * 64,
                    "quantitative_reference_exchange_internal_id": "qref",
                    "claim_role": "partial_background_leaf",
                }
            ],
        }

    refused = native_setup["client"].post(
        "/api/v1/applications/{}/system-revisions/{}/solve".format(
            native_setup["application_id"], native_setup["revision_id"]
        ),
        json=_solve_payload(**overrides),
    )
    assert refused.status_code == 422, refused.text
    assert "native background climate total" in str(refused.json())
    assert _solve_requests(upstream_requests) == []
