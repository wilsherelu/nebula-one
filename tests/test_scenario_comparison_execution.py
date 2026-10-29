from __future__ import annotations

from datetime import datetime, timedelta, timezone

from test_calculation_methods import _setup

from nebula_one.errors import DomainError

_DEMAND = [{"reference_flow_uuid": "flow-product", "amount": 1.0, "unit": "kg"}]


def _create_frozen_scenario(client, application_id: str, revision_id: str, name: str):
    created = client.post(
        f"/api/v1/applications/{application_id}/scenarios",
        json={"name": name, "base_revision_id": revision_id, "system_revision_id": revision_id},
    )
    assert created.status_code == 201, created.text
    scenario_id = created.json()["id"]
    frozen = client.post(f"/api/v1/scenarios/{scenario_id}/freeze")
    assert frozen.status_code == 200, frozen.text
    return scenario_id, frozen.json()["content_sha256"]


def test_two_distinct_scenarios_on_one_revision_run_as_a_comparison(client, model_graph):
    """S1: two different scenarios may bind the same revision and share the numeric snapshot.

    The whole point of a scenario comparison is to let one frozen model revision be reviewed
    under two distinct scenario identities. Rejecting it because the revision repeats a
    legitimate comparison; the only real constraint is that the member scenario IDs are unique.
    The numeric result may be reused for both members, but each member must still carry its own
    scenario identity, and the baseline and ordering must survive the reuse.
    """
    application, revision_id = _setup(client, model_graph)
    scenario_a, hash_a = _create_frozen_scenario(client, application["id"], revision_id, "Scenario A")
    scenario_b, hash_b = _create_frozen_scenario(client, application["id"], revision_id, "Scenario B")
    # two distinct scenario identities may bind one and the same frozen revision; identical
    # computational basis gives them an identical content hash, which is exactly the reuse case.
    assert scenario_a != scenario_b
    assert hash_a == hash_b

    comparison = client.post(
        f"/api/v1/applications/{application['id']}/comparisons",
        json={"name": "Same revision, two scenarios", "scenario_ids": [scenario_a, scenario_b]},
    )
    assert comparison.status_code == 201, comparison.text
    comparison_body = comparison.json()
    assert comparison_body["comparability"]["compatible"] is True

    executed = client.post(
        f"/api/v1/comparisons/{comparison_body['id']}/execute",
        json={"baseline_scenario_id": scenario_a, "demand": _DEMAND, "idempotency_key": "s1-same-revision"},
    )
    assert executed.status_code == 201, executed.text
    run = executed.json()
    assert run["status"] == "succeeded", run
    assert run["baseline_scenario_id"] == scenario_a

    members = run["scenario_results"]
    assert [m["scenario_id"] for m in members] == [scenario_a, scenario_b]
    assert [m["scenario_hash"] for m in members] == [hash_a, hash_b]
    # identical computational basis on one revision shares a single numeric snapshot
    assert members[0]["solved_snapshot_id"] == members[1]["solved_snapshot_id"]
    # each member keeps its own scenario identity even though the numeric result is reused
    assert members[0]["provider_receipt"]["scenario_id"] == scenario_a
    assert members[1]["provider_receipt"]["scenario_id"] == scenario_b


def test_repeated_identical_request_does_not_duplicate_the_association(client, model_graph):
    """S1: an identical retry replays the same run instead of creating a second association."""
    application, revision_id = _setup(client, model_graph)
    scenario_a, _ = _create_frozen_scenario(client, application["id"], revision_id, "Scenario A")
    scenario_b, _ = _create_frozen_scenario(client, application["id"], revision_id, "Scenario B")
    comparison = client.post(
        f"/api/v1/applications/{application['id']}/comparisons",
        json={"name": "Retry", "scenario_ids": [scenario_a, scenario_b]},
    )
    assert comparison.status_code == 201, comparison.text
    comparison_id = comparison.json()["id"]
    body = {"baseline_scenario_id": scenario_a, "demand": _DEMAND, "idempotency_key": "s1-retry"}

    first = client.post(f"/api/v1/comparisons/{comparison_id}/execute", json=body)
    assert first.status_code == 201, first.text
    second = client.post(f"/api/v1/comparisons/{comparison_id}/execute", json=body)
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]

    runs = client.get(
        f"/api/v1/applications/{application['id']}/scenario-comparison-runs"
    ).json()
    assert [r["id"] for r in runs if r["comparison_id"] == comparison_id] == [first.json()["id"]]


def test_duplicate_scenario_member_is_refused_at_execution(client, model_graph):
    """S1 guard: the real constraint on comparison members is distinct scenario IDs, not revisions.

    The create schema already blocks duplicate members, so a duplicated member can only reach
    execution through a legacy or corrupted comparison row; the execution context must still refuse
    it rather than silently solve the same scenario twice.
    """
    from nebula_one.runtime_models import Comparison

    application, revision_id = _setup(client, model_graph)
    scenario_a, _ = _create_frozen_scenario(client, application["id"], revision_id, "Scenario A")
    container = client.app.state.container
    with container.database.session() as db:
        duplicate = Comparison(
            application_id=application["id"],
            name="Duplicate member",
            scenario_ids=[scenario_a, scenario_a],
            comparability={"compatible": True},
            content_sha256="0" * 64,
        )
        db.add(duplicate)
        db.commit()
        db.refresh(duplicate)
        comparison_id = duplicate.id

    executed = client.post(
        f"/api/v1/comparisons/{comparison_id}/execute",
        json={"baseline_scenario_id": scenario_a, "demand": _DEMAND, "idempotency_key": "s1-dup"},
    )
    assert executed.status_code == 409, executed.text
    assert executed.json()["error"]["code"] == "COMPARISON_SCENARIO_DUPLICATE"


def _submit_comparison(client, application_id: str, scenario_ids: list[str], name: str = "Comparison") -> str:
    comparison = client.post(
        f"/api/v1/applications/{application_id}/comparisons",
        json={"name": name, "scenario_ids": scenario_ids},
    )
    assert comparison.status_code == 201, comparison.text
    return comparison.json()["id"]


def _queue(client, comparison_id: str, body: dict) -> dict:
    queued = client.post(f"/api/v1/comparisons/{comparison_id}/execute/queue", json=body)
    assert queued.status_code == 202, queued.text
    return queued.json()


def test_comparison_forwards_shared_demand_once_for_every_member(client, model_graph):
    """S2 (2): the requested demand enters each member's solve basis once, at the requested amount.

    A comparison applies one shared demand across comparable members. The scenario coverage is
    carried by the frozen revision already bound to each member; One must forward the requested
    demand into the solve basis exactly once rather than applying an extra scaling pass per scenario.
    """
    application, revision_id = _setup(client, model_graph)
    scenario_a, _ = _create_frozen_scenario(client, application["id"], revision_id, "Scenario A")
    scenario_b, _ = _create_frozen_scenario(client, application["id"], revision_id, "Scenario B")
    comparison_id = _submit_comparison(client, application["id"], [scenario_a, scenario_b])

    doubled = [{"reference_flow_uuid": "flow-product", "amount": 2.0, "unit": "kg"}]
    executed = client.post(
        f"/api/v1/comparisons/{comparison_id}/execute",
        json={"baseline_scenario_id": scenario_a, "demand": doubled, "idempotency_key": "s2-demand"},
    )
    assert executed.status_code == 201, executed.text
    members = executed.json()["scenario_results"]
    assert [m["scenario_id"] for m in members] == [scenario_a, scenario_b]
    for member in members:
        basis = member["provider_receipt"]["calculation_basis"]
        assert [(d["reference_flow_uuid"], d["amount"]) for d in basis["demand"]] == [
            ("flow-product", 2.0)
        ]


def test_member_transient_failure_retains_progress_and_recovers_without_rewriting(
    client, model_graph, monkeypatch
):
    """S2 (3+4): a failing member is localized, its siblings survive, and recovery does not re-run them.

    Driven through the real queue API + worker. On the first worker pass the baseline member solves
    and the second member hits a transient engine error: the run is marked failed, the completed
    member is retained, and the failure is attributed to the failing member - never presented as a
    whole-comparison success. On the retry pass the worker re-claims the queued run, skips the
    already-persisted member, and only the failed member is solved again.
    """
    application, revision_id = _setup(client, model_graph)
    scenario_a, _ = _create_frozen_scenario(client, application["id"], revision_id, "Scenario A")
    scenario_b, _ = _create_frozen_scenario(client, application["id"], revision_id, "Scenario B")
    comparison_id = _submit_comparison(client, application["id"], [scenario_a, scenario_b])
    queued = _queue(
        client,
        comparison_id,
        {"baseline_scenario_id": scenario_a, "demand": _DEMAND, "idempotency_key": "s2-recover"},
    )
    run_id = queued["run"]["id"]

    solves = client.app.state.container.scenario_comparisons.provider_solves
    original = solves.solve_and_freeze
    calls = {"a": 0, "b": 0}

    def flaky(application_id, system_revision_id, payload):
        if payload.scenario_id == scenario_a:
            calls["a"] += 1
        elif payload.scenario_id == scenario_b:
            calls["b"] += 1
            if calls["b"] == 1:
                raise DomainError(
                    code="TRANSIENT_ENGINE", message="engine unavailable", status_code=503
                )
        return original(application_id, system_revision_id, payload)

    monkeypatch.setattr(solves, "solve_and_freeze", flaky)
    worker = client.app.state.container.worker

    base = datetime.now(timezone.utc)
    first = worker.process_one(worker_id="w1", lease_seconds=30, now=base)
    assert first.status == "retry_wait"
    run = client.get(f"/api/v1/scenario-comparison-runs/{run_id}").json()
    assert run["status"] == "failed"
    assert [m["scenario_id"] for m in run["scenario_results"]] == [scenario_a]
    assert run["error"]["code"] == "TRANSIENT_ENGINE"
    assert run["error"]["details"]["scenario_id"] == scenario_b
    assert calls == {"a": 1, "b": 1}

    second = worker.process_one(
        worker_id="w2", lease_seconds=30, now=base + timedelta(seconds=30)
    )
    assert second.status == "completed"
    run = client.get(f"/api/v1/scenario-comparison-runs/{run_id}").json()
    assert run["status"] == "succeeded"
    assert [m["scenario_id"] for m in run["scenario_results"]] == [scenario_a, scenario_b]
    # the completed member was never solved again during recovery; only the failed one retried
    assert calls == {"a": 1, "b": 2}


def test_frozen_scenario_drift_after_submit_is_rejected_not_silently_reselected(
    client, model_graph
):
    """S2 (5): real drift in a frozen member's content invalidates the queued run rather than
    letting the worker quietly recompute against the changed basis."""
    from nebula_one.runtime_models import Scenario

    application, revision_id = _setup(client, model_graph)
    scenario_a, _ = _create_frozen_scenario(client, application["id"], revision_id, "Scenario A")
    scenario_b, _ = _create_frozen_scenario(client, application["id"], revision_id, "Scenario B")
    comparison_id = _submit_comparison(client, application["id"], [scenario_a, scenario_b])
    queued = _queue(
        client,
        comparison_id,
        {"baseline_scenario_id": scenario_a, "demand": _DEMAND, "idempotency_key": "s2-drift"},
    )
    run_id = queued["run"]["id"]

    # simulate the frozen scenario content actually drifting after the run was queued
    container = client.app.state.container
    with container.database.session() as db:
        db.get(Scenario, scenario_a).content_sha256 = "f" * 64
        db.commit()

    processed = container.worker.process_one(
        worker_id="w1", lease_seconds=30, now=datetime.now(timezone.utc)
    )
    assert processed.status == "failed"
    run = client.get(f"/api/v1/scenario-comparison-runs/{run_id}").json()
    assert run["status"] == "failed"
    assert run["error"]["code"] == "COMPARISON_RUN_CONTEXT_CHANGED"


def test_unfrozen_duplicate_and_foreign_baseline_comparisons_are_refused(client, model_graph):
    """S2 (6): the real member/baseline constraints are enforced before any solve."""
    application, revision_id = _setup(client, model_graph)
    frozen_a, _ = _create_frozen_scenario(client, application["id"], revision_id, "Scenario A")
    frozen_b, _ = _create_frozen_scenario(client, application["id"], revision_id, "Scenario B")
    draft = client.post(
        f"/api/v1/applications/{application['id']}/scenarios",
        json={"name": "Draft", "base_revision_id": revision_id, "system_revision_id": revision_id},
    ).json()["id"]

    duplicate = client.post(
        f"/api/v1/applications/{application['id']}/comparisons",
        json={"name": "Duplicate", "scenario_ids": [frozen_a, frozen_a]},
    )
    assert duplicate.status_code == 422, duplicate.text

    unfrozen = client.post(
        f"/api/v1/applications/{application['id']}/comparisons",
        json={"name": "Unfrozen", "scenario_ids": [frozen_a, draft]},
    )
    assert unfrozen.status_code == 409, unfrozen.text
    assert unfrozen.json()["error"]["code"] == "SCENARIO_NOT_FROZEN"

    comparison_id = _submit_comparison(client, application["id"], [frozen_a, frozen_b])
    foreign_baseline = client.post(
        f"/api/v1/comparisons/{comparison_id}/execute",
        json={"baseline_scenario_id": draft, "demand": _DEMAND, "idempotency_key": "s2-base"},
    )
    assert foreign_baseline.status_code == 409, foreign_baseline.text
    assert foreign_baseline.json()["error"]["code"] == "COMPARISON_BASELINE_NOT_INCLUDED"



