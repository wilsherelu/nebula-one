from __future__ import annotations

import copy

from nebula_one.hashing import canonical_graph_sha256


def _create_application(client, application_type="zero_carbon_park") -> dict:
    response = client.post(
        "/api/v1/applications",
        json={
            "name": "Shanghai park study",
            "application_type": application_type,
            "description": "Backend acceptance fixture",
            "context": {"geography": "CN-SH"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _attach_model(client, application_id: str) -> dict:
    response = client.post(
        f"/api/v1/applications/{application_id}/system-models",
        json={
            "name": "Pinned system model",
            "provider": "nebula_lca",
            "upstream_project_id": "project-1",
            "upstream_version": 3,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _attach_inline_model(client, application_id: str, graph: dict) -> dict:
    response = client.post(
        f"/api/v1/applications/{application_id}/system-models/inline",
        json={
            "name": "Inline CasePack model",
            "provider": "nebula_lca",
            "source_id": "casepack:petrochemical-refinery-reference",
            "source_version": 1,
            "expected_graph_sha256": canonical_graph_sha256(graph),
            "graph": graph,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health_engine_profiles_and_capabilities(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["database"] == "ready"

    engine = client.get("/api/v1/engine")
    assert engine.status_code == 200
    assert engine.json()["status"] == "ready"
    assert engine.json()["contracts"] == {
        "exact_model_version": True,
        "lcia_run": True,
        "provider_model_snapshot": True,
        "provider_solve": True,
        "provider_catalog_resolve": True,
        "tidas_bundle_import": True,
        "native_bundle_restore": True,
        "native_bundle_export": True,
    }

    capabilities = client.get("/api/v1/capabilities").json()
    assert {item["key"]: item["status"] for item in capabilities["items"]} == {
        "mfa.declared.v1": "ready",
        "mfa.solved.v1": "ready",
            "energy.carrier.solved.v1": "ready",
            "energy.flow.solved.v1": "ready",
            "water.balance.solved.v1": "ready",
        "energy.period-total.v1": "ready",
        "energy.period-trend.v1": "ready",
        "energy.scenario-comparison.v1": "ready",
        "electricity.province-scenario.v1": "ready",
            "cbam.complex-trial.v1": "ready",
            "cbam.trial.v1": "ready",
            "ghg.inventory.trial.v1": "ready",
            "organization.ghg-inventory.v1": "ready",
            "pcf.product.v1": "ready",
        "lcia.nebula.v1": "ready",
        "solve.nebula.v1": "ready",
        "spatial.aggregate.v1": "ready",
        "spatial.distribution.v1": "ready",
        "spatial.energy-flow.v1": "ready",
        "spatial.energy.v1": "ready",
    }

    profiles = client.get("/api/v1/application-profiles").json()["profiles"]
    assert {item["key"] for item in profiles} == {
        "system_analysis",
        "zero_carbon_park",
        "enterprise_esg",
        "project_carbon",
        "cbam",
    }

    snapshot = client.get(
        "/api/v1/provider/models/project-1/versions/3/snapshot"
    )
    assert snapshot.status_code == 200
    assert snapshot.json()["graph_hash"] == canonical_graph_sha256(
        snapshot.json()["graph"]
    )

    catalog = client.post(
        "/api/v1/provider/catalog/resolve",
        json={
            "schema_version": "provider.catalog.resolve.request.v1",
            "flows": [],
            "flow_properties": [],
            "unit_groups": [],
            "units": [],
        },
    )
    assert catalog.status_code == 200
    assert catalog.json()["items"] == []


def test_exact_model_pin_and_persisted_mfa_run(client):
    application = _create_application(client)
    system_model = _attach_model(client, application["id"])

    assert len(system_model["graph_sha256"]) == 64
    assert system_model["upstream_project_id"] == "project-1"
    assert system_model["upstream_version"] == 3
    assert system_model["upstream_receipt"]["etag"] == '"graph-v3"'
    assert system_model["upstream_receipt"]["functional_unit"] == "8 kg product"
    assert system_model["upstream_receipt"]["node_count"] == 2
    assert system_model["upstream_receipt"]["exchange_count"] == 1

    response = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs",
        json={
            "capability_key": "mfa.declared.v1",
            "parameters": {},
            "idempotency_key": "declared-mfa-acceptance",
        },
    )
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "succeeded"
    assert run["model_graph_sha256"] == system_model["graph_sha256"]
    assert run["result"]["series"][0]["totals"] == {
        "internal_flow": 8.0,
        "boundary_in": 10.0,
        "boundary_out": 10.0,
    }
    assert run["idempotency_key"] == "declared-mfa-acceptance"
    assert len(run["request_sha256"]) == 64

    replay = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs",
        json={
            "capability_key": "mfa.declared.v1",
            "parameters": {},
            "idempotency_key": "declared-mfa-acceptance",
        },
    )
    assert replay.status_code == 201, replay.text
    assert replay.json() == run

    conflict = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs",
        json={
            "capability_key": "mfa.declared.v1",
            "parameters": {"tolerance": 1e-6},
            "idempotency_key": "declared-mfa-acceptance",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "ANALYSIS_IDEMPOTENCY_CONFLICT"

    persisted = client.get(f"/api/v1/analysis-runs/{run['id']}")
    assert persisted.status_code == 200
    assert persisted.json() == run

    listed = client.get(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs"
    )
    assert [item["id"] for item in listed.json()] == [run["id"]]


def test_inline_casepack_model_attaches_without_provider_write_and_solves(
    client, model_graph, upstream_requests
):
    application = _create_application(client)
    system_model = _attach_inline_model(client, application["id"], model_graph)

    assert upstream_requests == []
    assert system_model["upstream_project_id"] == (
        "casepack:petrochemical-refinery-reference"
    )
    assert system_model["upstream_receipt"]["source_kind"] == "inline_casepack"
    revision_id = system_model["upstream_receipt"]["base_revision_id"]
    response = client.post(
        f"/api/v1/applications/{application['id']}/system-revisions/{revision_id}/solve",
        json={
            "demand": [
                {
                    "reference_flow_uuid": "flow-product",
                    "amount": 1.0,
                    "unit": "kg",
                    "unit_group_uuid": "mass",
                    "unit_group_version": "1",
                }
            ]
        },
    )
    assert response.status_code == 201, response.text
    forwarded = [
        item for item in upstream_requests if item["path"] == "/api/provider/v1/solve"
    ]
    assert len(forwarded) == 1
    assert "base_snapshot_ref" not in forwarded[0]["json"]["inline_snapshot"]


def test_inline_casepack_model_rejects_hash_drift_and_lcia(client, model_graph):
    application = _create_application(client)
    mismatch = client.post(
        f"/api/v1/applications/{application['id']}/system-models/inline",
        json={
            "name": "Drifted inline model",
            "source_id": "casepack:drifted",
            "source_version": 1,
            "expected_graph_sha256": "0" * 64,
            "graph": model_graph,
        },
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "INLINE_MODEL_HASH_MISMATCH"

    system_model = _attach_inline_model(client, application["id"], model_graph)
    lcia = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs",
        json={"capability_key": "lcia.nebula.v1", "parameters": {}},
    )
    assert lcia.status_code == 422
    assert lcia.json()["error"]["code"] == "INLINE_MODEL_LCIA_UNSUPPORTED"


def test_lcia_is_forwarded_to_nebula_and_receipt_is_persisted(client, upstream_requests):
    application = _create_application(client, "project_carbon")
    system_model = _attach_model(client, application["id"])

    response = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs",
        json={
            "capability_key": "lcia.nebula.v1",
            "parameters": {"lcia_methods": ["EF v3.1"]},
        },
    )
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "succeeded"
    assert run["provider_receipt"]["upstream_run_id"] == "nebula-run-1"
    assert run["result"]["lci_result"]["Climate change"] == 12.5

    forwarded = [
        item for item in upstream_requests if item["path"] == "/api/model/run"
    ]
    assert len(forwarded) == 1
    assert forwarded[0]["json"]["project_id"] == "project-1"
    assert forwarded[0]["json"]["lcia_methods"] == ["EF v3.1"]
    assert forwarded[0]["json"]["graph"]["functionalUnit"] == "8 kg product"


def test_provider_solve_uses_inline_revision_and_persists_exact_response(
    client, upstream_requests
):
    application = _create_application(client)
    system_model = _attach_model(client, application["id"])
    revision_id = system_model["upstream_receipt"]["base_revision_id"]

    response = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs",
        json={
            "capability_key": "solve.nebula.v1",
            "system_revision_id": revision_id,
            "parameters": {
                "demand": [
                    {
                        "reference_flow_uuid": "flow-product",
                        "amount": 1.0,
                        "unit": "kg",
                        "unit_group_uuid": "mass",
                        "unit_group_version": "1",
                    }
                ],
                "lcia_methods": ["EF v3.1"],
            },
        },
    )
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "succeeded"
    assert run["result"]["run_id"] == "provider-run-1"
    assert run["result"]["activity_vector"][0]["activity_amount"] == 1.0
    assert run["provider_receipt"]["endpoint"] == "/api/provider/v1/solve"

    forwarded = [
        item for item in upstream_requests if item["path"] == "/api/provider/v1/solve"
    ]
    assert len(forwarded) == 1
    assert forwarded[0]["json"]["inline_snapshot"]["graph_hash"] == system_model[
        "graph_sha256"
    ]
    assert forwarded[0]["json"]["operation_hash"] == client.get(
        f"/api/v1/system-revisions/{revision_id}"
    ).json()["content_sha256"]
    assert forwarded[0]["json"]["idempotency_key"] == (
        f"nebula-one:analysis-run:{run['id']}"
    )
    assert forwarded[0]["json"]["elementary_flows"] == []
    assert run["provider_receipt"]["provider_idempotency_key"] == (
        forwarded[0]["json"]["idempotency_key"]
    )
    assert run["provider_receipt"]["provider_request_hash"] == "a" * 64


def test_provider_solve_forwards_exact_elementary_flow_refs(
    client, model_graph, upstream_requests
):
    graph = copy.deepcopy(model_graph)
    elementary_ref = {
        "exchange_id": "preparation::carbon-dioxide-out",
        "source_namespace": "tiangong_open_data",
        "flow_uuid": "08a91e70-3ddc-11dd-923d-0050c2490048",
        "version": "03.00.004",
        "flow_property_uuid": "93a60a56-a3c8-11da-a746-0800200b9a66",
        "flow_property_version": "03.00.003",
        "unit_group_uuid": "93a60a57-a4c8-11da-a746-0800200c9a66",
        "unit_group_version": "03.00.003",
        "unit": "kg",
        "direction": "output",
        "compartment": "Emissions to air, unspecified",
    }
    graph["nodes"][0]["outputs"].append(
        {
            "id": "carbon-dioxide-out",
            "flowUuid": elementary_ref["flow_uuid"],
            "flowSourceNamespace": elementary_ref["source_namespace"],
            "flowVersion": elementary_ref["version"],
            "flowPropertyUuid": elementary_ref["flow_property_uuid"],
            "flowPropertyVersion": elementary_ref["flow_property_version"],
            "unitGroupUuid": elementary_ref["unit_group_uuid"],
            "unitGroupVersion": elementary_ref["unit_group_version"],
            "name": "carbon dioxide (fossil)",
            "unit": elementary_ref["unit"],
            "unitGroup": "Mass",
            "amount": 1.0,
            "type": "biosphere",
            "direction": elementary_ref["direction"],
        }
    )
    graph["nodes"][0]["outputs"].append({
        **graph["nodes"][0]["outputs"][-1],
        "id": "second-carbon-dioxide-out",
        "amount": 0.25,
    })
    graph["metadata"]["elementary_flow_refs"] = [elementary_ref]
    application = _create_application(client)
    system_model = _attach_inline_model(client, application["id"], graph)
    revision_id = system_model["upstream_receipt"]["base_revision_id"]

    response = client.post(
        f"/api/v1/applications/{application['id']}/system-revisions/{revision_id}/solve",
        json={
            "demand": [
                {
                    "reference_flow_uuid": "flow-product",
                    "amount": 1.0,
                    "unit": "kg",
                    "unit_group_uuid": "mass",
                    "unit_group_version": "1",
                }
            ],
            "lcia_methods": ["EF v3.1"],
        },
    )

    assert response.status_code == 201, response.text
    forwarded = [
        item for item in upstream_requests if item["path"] == "/api/provider/v1/solve"
    ]
    assert forwarded[-1]["json"]["elementary_flows"] == [
        elementary_ref,
        {**elementary_ref, "exchange_id": "preparation::second-carbon-dioxide-out"},
    ]


def test_provider_solve_rejects_missing_elementary_flow_ref(client, model_graph):
    graph = copy.deepcopy(model_graph)
    graph["nodes"][0]["outputs"].append(
        {
            "id": "carbon-dioxide-out",
            "flowUuid": "08a91e70-3ddc-11dd-923d-0050c2490048",
            "flowSourceNamespace": "tiangong_open_data",
            "flowVersion": "03.00.004",
            "flowPropertyUuid": "93a60a56-a3c8-11da-a746-0800200b9a66",
            "flowPropertyVersion": "03.00.003",
            "unitGroupUuid": "93a60a57-a4c8-11da-a746-0800200c9a66",
            "unitGroupVersion": "03.00.003",
            "name": "carbon dioxide (fossil)",
            "unit": "kg",
            "unitGroup": "Mass",
            "amount": 1.0,
            "type": "biosphere",
            "direction": "output",
        }
    )
    application = _create_application(client)
    system_model = _attach_inline_model(client, application["id"], graph)
    revision_id = system_model["upstream_receipt"]["base_revision_id"]

    response = client.post(
        f"/api/v1/applications/{application['id']}/system-revisions/{revision_id}/solve",
        json={
            "demand": [
                {
                    "reference_flow_uuid": "flow-product",
                    "amount": 1.0,
                    "unit": "kg",
                    "unit_group_uuid": "mass",
                    "unit_group_version": "1",
                }
            ],
            "lcia_methods": ["EF v3.1"],
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "ELEMENTARY_FLOW_REFERENCE_REQUIRED"


def test_provider_solve_can_freeze_the_solved_revision(client):
    application = _create_application(client)
    system_model = _attach_model(client, application["id"])
    revision_id = system_model["upstream_receipt"]["base_revision_id"]

    response = client.post(
        f"/api/v1/applications/{application['id']}/system-revisions/{revision_id}/solve",
        json={
            "demand": [
                {
                    "reference_flow_uuid": "flow-product",
                    "amount": 1.0,
                    "unit": "kg",
                    "unit_group_uuid": "mass",
                    "unit_group_version": "1",
                }
            ],
            "lcia_methods": ["EF v3.1"],
        },
    )
    assert response.status_code == 201, response.text
    solved = response.json()
    assert solved["system_revision_id"] == revision_id
    assert solved["activity_vector"] == [
        {"process_id": "product", "value": 1.0, "unit": "kg"}
    ]
    assert solved["database_release"] == "fixture-release"
    assert solved["solver_version"] == "nebula_hybrid_matrix_v1"
    assert solved["provider_receipt"]["upstream_run_id"] == "provider-run-1"
    assert solved["contribution_graph"]["analysis_run_id"]

    listed = client.get(
        f"/api/v1/applications/{application['id']}/solved-system-snapshots"
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [solved["id"]]

    mfa = client.get(f"/api/v1/solved-system-snapshots/{solved['id']}/mfa")
    assert mfa.status_code == 200, mfa.text
    result = mfa.json()
    assert result["schema_version"] == "nebula_one.mfa.solved.v1"
    assert result["audit"]["status"] == "passed"
    assert result["audit"]["checks"] == {
        "series_count": 1,
        "link_count": 4,
        "traceable_link_count": 4,
        "error_count": 0,
        "warning_count": 0,
        "open_boundary_process_count": 0,
    }
    assert result["series"][0]["totals"] == {
        "internal": 8.0,
        "boundary_input": 10.0,
        "boundary_output": 10.0,
    }

    svg = client.get(
        f"/api/v1/solved-system-snapshots/{solved['id']}/mfa/sankey.svg"
    )
    assert svg.status_code == 200, svg.text
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert "flow-material" in svg.text
    assert "preparation::material-out" in svg.text
    assert ">ore<title" in svg.text
    assert ">material<title" in svg.text
    assert "→ 10 kg" in svg.text
    assert "→ 8 kg" in svg.text
    assert "系统输出" in svg.text


def test_unknown_profile_and_non_executable_capability_fail_explicitly(client):
    unknown_profile = client.post(
        "/api/v1/applications",
        json={"name": "Invalid", "application_type": "unknown"},
    )
    assert unknown_profile.status_code == 422
    assert unknown_profile.json()["error"]["code"] == "APPLICATION_PROFILE_NOT_FOUND"

    application = _create_application(client, "cbam")
    system_model = _attach_model(client, application["id"])
    unavailable = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs",
        json={"capability_key": "cbam.reporting.v1", "parameters": {}},
    )
    assert unavailable.status_code == 422
    assert unavailable.json()["error"]["code"] == "CAPABILITY_NOT_EXECUTABLE"


def test_duplicate_exact_pin_is_rejected(client):
    application = _create_application(client)
    _attach_model(client, application["id"])

    duplicate = client.post(
        f"/api/v1/applications/{application['id']}/system-models",
        json={
            "name": "Duplicate",
            "provider": "nebula_lca",
            "upstream_project_id": "project-1",
            "upstream_version": 3,
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "SYSTEM_MODEL_PIN_ALREADY_ATTACHED"


def test_changed_graph_for_same_upstream_version_is_rejected(client, model_graph):
    application = _create_application(client)
    _attach_model(client, application["id"])
    model_graph["functionalUnit"] = "mutated upstream graph"

    changed = client.post(
        f"/api/v1/applications/{application['id']}/system-models",
        json={
            "name": "Changed",
            "provider": "nebula_lca",
            "upstream_project_id": "project-1",
            "upstream_version": 3,
        },
    )
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "UPSTREAM_MODEL_VERSION_MUTATED"


def test_failed_calculation_is_persisted_with_run_id(client):
    application = _create_application(client, "enterprise_esg")
    system_model = _attach_model(client, application["id"])

    request_payload = {
        "capability_key": "lcia.nebula.v1",
        "idempotency_key": "invalid-lcia-methods",
        "parameters": {"lcia_methods": []},
    }
    failed = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs",
        json=request_payload,
    )
    assert failed.status_code == 422
    error = failed.json()["error"]
    assert error["code"] == "LCIA_METHODS_INVALID"
    run_id = error["details"]["run_id"]

    persisted = client.get(f"/api/v1/analysis-runs/{run_id}")
    assert persisted.status_code == 200
    run = persisted.json()
    assert run["status"] == "failed"
    assert run["error"]["code"] == "LCIA_METHODS_INVALID"
    assert run["result"] is None

    replay = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs",
        json=request_payload,
    )
    assert replay.status_code == 422
    assert replay.json()["error"]["details"]["idempotent_replay"] is True
    runs = client.get(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs"
    ).json()
    assert len(runs) == 1


def test_queued_analysis_is_durable_idempotent_and_worker_executable(client):
    application = _create_application(client, "enterprise_esg")
    system_model = _attach_model(client, application["id"])
    payload = {
        "capability_key": "mfa.declared.v1",
        "idempotency_key": "queued-mfa-run",
        "parameters": {"unit_groups": ["Units of mass"]},
    }

    queued = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs/queue",
        json=payload,
    )
    replay = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs/queue",
        json=payload,
    )
    assert queued.status_code == replay.status_code == 202
    first = queued.json()
    assert replay.json() == first
    assert first["run"]["status"] == "pending"
    assert first["task"]["status"] == "pending"
    assert first["task"]["aggregate_id"] == first["run"]["id"]

    conflict = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs/queue",
        json={**payload, "parameters": {"unit_groups": ["Units of energy"]}},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "ANALYSIS_IDEMPOTENCY_CONFLICT"

    completed_task = client.app.state.container.worker.process_one(
        worker_id="test-worker",
        lease_seconds=30,
    )
    assert completed_task is not None
    assert completed_task.id == first["task"]["id"]
    assert completed_task.status == "completed"
    run = client.get(f"/api/v1/analysis-runs/{first['run']['id']}")
    assert run.status_code == 200
    assert run.json()["status"] == "succeeded"
    task = client.get(f"/api/v1/outbox-events/{first['task']['id']}")
    assert task.status_code == 200
    assert task.json()["status"] == "completed"


def test_inline_replay_claims_a_pending_queued_run(client):
    application = _create_application(client, "enterprise_esg")
    system_model = _attach_model(client, application["id"])
    payload = {
        "capability_key": "mfa.declared.v1",
        "idempotency_key": "pending-inline-replay",
        "parameters": {"unit_groups": ["Units of mass"]},
    }
    queued = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs/queue",
        json=payload,
    )
    assert queued.status_code == 202

    completed = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs",
        json=payload,
    )
    assert completed.status_code == 201
    assert completed.json()["id"] == queued.json()["run"]["id"]
    assert completed.json()["status"] == "succeeded"
    task = client.get(f"/api/v1/outbox-events/{queued.json()['task']['id']}")
    assert task.json()["status"] == "completed"


def test_queued_analysis_retries_transient_execution_with_same_run_id(
    client, monkeypatch
):
    from datetime import datetime, timedelta

    from nebula_one.errors import DomainError

    application = _create_application(client, "enterprise_esg")
    system_model = _attach_model(client, application["id"])
    queued = client.post(
        f"/api/v1/system-models/{system_model['id']}/analysis-runs/queue",
        json={
            "capability_key": "mfa.declared.v1",
            "idempotency_key": "queued-transient-retry",
            "parameters": {},
        },
    ).json()
    analysis_runs = client.app.state.container.analysis_runs
    original_execute = analysis_runs._execute
    calls = 0

    def fail_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise DomainError(
                code="TRANSIENT_ANALYSIS_FAILURE",
                message="temporary failure",
                status_code=503,
            )
        return original_execute(**kwargs)

    monkeypatch.setattr(analysis_runs, "_execute", fail_once)
    started = datetime.fromisoformat(
        queued["task"]["available_at"].replace("Z", "+00:00")
    ) + timedelta(microseconds=1)
    retry_wait = client.app.state.container.worker.process_one(
        worker_id="retry-worker-1",
        lease_seconds=30,
        now=started,
    )
    assert retry_wait is not None
    assert retry_wait.status == "retry_wait"
    assert retry_wait.aggregate_id == queued["run"]["id"]

    completed = client.app.state.container.worker.process_one(
        worker_id="retry-worker-2",
        lease_seconds=30,
        now=started + timedelta(seconds=2),
    )
    assert completed is not None
    assert completed.id == retry_wait.id
    assert completed.status == "completed"
    assert completed.attempt_count == 2
    assert calls == 2
    run = client.get(f"/api/v1/analysis-runs/{queued['run']['id']}").json()
    assert run["id"] == queued["run"]["id"]
    assert run["status"] == "succeeded"
