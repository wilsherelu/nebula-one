from __future__ import annotations

import pytest

from nebula_one.hashing import canonical_graph_sha256
from nebula_one.runtime_models import SolvedSystemSnapshot


def _create_application_graph(client, model_graph: dict, suffix: str) -> dict:
    application = client.post(
        "/api/v1/applications",
        json={
            "name": f"Application {suffix}",
            "application_type": "system_analysis",
        },
    ).json()
    model = client.post(
        f"/api/v1/applications/{application['id']}/system-models/inline",
        json={
            "name": f"Model {suffix}",
            "source_id": f"system-binding-{suffix}",
            "source_version": 1,
            "expected_graph_sha256": canonical_graph_sha256(model_graph),
            "graph": model_graph,
        },
    ).json()
    revision = client.get(
        f"/api/v1/system-models/{model['id']}/revisions"
    ).json()[0]
    snapshot = SolvedSystemSnapshot(
        application_id=application["id"],
        system_revision_id=revision["id"],
        solve_hash=(suffix.encode("utf-8").hex() + "0" * 64)[:64],
        provider="nebula_lca",
        provider_receipt={},
        functional_unit={"amount": 1.0, "unit": "kg"},
        database_release="test-release",
        solver_version="test-solver",
        activity_vector=[],
        scaled_technosphere_exchanges=[],
        scaled_elementary_exchanges=[],
        internal_transfers=[],
        boundary_flows=[],
        process_balance_residuals=[],
        contribution_graph={},
        lcia_results={},
        content_sha256="a" * 64,
    )
    with client.app.state.container.database.session() as db:
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
    period = client.post(
        f"/api/v1/applications/{application['id']}/periods",
        json={
            "key": "2026",
            "name": "Reporting year 2026",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "resolution": "year",
        },
    ).json()
    boundary = client.post(
        f"/api/v1/applications/{application['id']}/boundaries",
        json={
            "name": "Organizational boundary",
            "boundary_type": "operational_control",
            "included_process_ids": ["process-preparation"],
            "period_id": period["id"],
        },
    ).json()
    return {
        "application": application,
        "model": model,
        "revision": revision,
        "snapshot": {"id": snapshot.id},
        "period": period,
        "boundary": boundary,
    }


def _binding_payload(graph: dict, binding_id: str, role: str, **updates) -> dict:
    payload = {
        "binding_id": binding_id,
        "role": role,
        "system_model_id": graph["model"]["id"],
        "system_revision_id": graph["revision"]["id"],
        "solved_snapshot_id": graph["snapshot"]["id"],
        "study_frame_id": "annual-refinery-frame",
        "reporting_period_id": graph["period"]["id"],
        "organizational_boundary_id": graph["boundary"]["id"],
        "demand": [
            {"process_uuid": "process-product", "amount": 1.0, "unit": "kg"}
        ],
        "capabilities": ["organization.ghg-inventory.v1"],
        "dependencies": [],
        "status": "draft",
    }
    payload.update(updates)
    return payload


def _binding_url(application_id: str, binding_id: str | None = None) -> str:
    base = f"/api/v1/applications/{application_id}/system-bindings"
    return f"{base}/{binding_id}" if binding_id else base


def test_system_binding_crud_and_dependency_protection(client, model_graph) -> None:
    graph = _create_application_graph(client, model_graph, "crud")
    application_id = graph["application"]["id"]
    root_payload = _binding_payload(graph, "scope-1", "scope_1")
    root = client.post(_binding_url(application_id), json=root_payload)
    assert root.status_code == 201
    root_body = root.json()
    assert root_body["binding_id"] == "scope-1"
    assert len(root_body["content_sha256"]) == 64

    child_payload = _binding_payload(
        graph, "scope-2", "scope_2", dependencies=["scope-1"]
    )
    child = client.post(_binding_url(application_id), json=child_payload)
    assert child.status_code == 201
    assert {
        item["binding_id"]
        for item in client.get(_binding_url(application_id)).json()
    } == {"scope-1", "scope-2"}
    assert (
        client.get(_binding_url(application_id, "scope-2")).json()["dependencies"]
        == ["scope-1"]
    )

    update_payload = {
        key: value for key, value in child_payload.items() if key != "binding_id"
    }
    update_payload["status"] = "active"
    update_payload["capabilities"] = [
        "organization.ghg-inventory.v1",
        "pcf.product.v1",
    ]
    updated = client.put(
        _binding_url(application_id, "scope-2"), json=update_payload
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "active"
    assert updated.json()["content_sha256"] != child.json()["content_sha256"]

    blocked = client.delete(_binding_url(application_id, "scope-1"))
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "SYSTEM_BINDING_IN_USE"
    assert client.delete(_binding_url(application_id, "scope-2")).status_code == 204
    assert client.delete(_binding_url(application_id, "scope-1")).status_code == 204
    assert client.get(_binding_url(application_id)).json() == []


def test_system_binding_identity_and_role_are_unique_per_application(
    client, model_graph
) -> None:
    first = _create_application_graph(client, model_graph, "unique-a")
    first_id = first["application"]["id"]
    assert (
        client.post(
            _binding_url(first_id),
            json=_binding_payload(first, "scope-1", "scope_1"),
        ).status_code
        == 201
    )
    for payload in (
        _binding_payload(first, "scope-1", "scope_2"),
        _binding_payload(first, "scope-2", "scope_1"),
    ):
        response = client.post(_binding_url(first_id), json=payload)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SYSTEM_BINDING_CONFLICT"

    second = _create_application_graph(client, model_graph, "unique-b")
    response = client.post(
        _binding_url(second["application"]["id"]),
        json=_binding_payload(second, "scope-1", "scope_1"),
    )
    assert response.status_code == 201


@pytest.mark.parametrize(
    ("field", "error_code"),
    [
        ("system_model_id", "SYSTEM_MODEL_APPLICATION_MISMATCH"),
        ("system_revision_id", "SYSTEM_BINDING_REVISION_MODEL_MISMATCH"),
        (
            "solved_snapshot_id",
            "SOLVED_SYSTEM_SNAPSHOT_APPLICATION_MISMATCH",
        ),
        ("reporting_period_id", "REPORTING_PERIOD_APPLICATION_MISMATCH"),
        (
            "organizational_boundary_id",
            "ORGANIZATIONAL_BOUNDARY_APPLICATION_MISMATCH",
        ),
    ],
)
def test_system_binding_rejects_cross_application_references(
    client, model_graph, field: str, error_code: str
) -> None:
    first = _create_application_graph(client, model_graph, f"cross-a-{field}")
    second = _create_application_graph(client, model_graph, f"cross-b-{field}")
    foreign_ids = {
        "system_model_id": second["model"]["id"],
        "system_revision_id": second["revision"]["id"],
        "solved_snapshot_id": second["snapshot"]["id"],
        "reporting_period_id": second["period"]["id"],
        "organizational_boundary_id": second["boundary"]["id"],
    }
    payload = _binding_payload(first, "scope-1", "scope_1")
    payload[field] = foreign_ids[field]
    response = client.post(
        _binding_url(first["application"]["id"]), json=payload
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == error_code


@pytest.mark.parametrize(
    ("dependencies", "error_code"),
    [
        (["scope-1"], "SYSTEM_BINDING_SELF_DEPENDENCY"),
        (["missing"], "SYSTEM_BINDING_DEPENDENCY_NOT_FOUND"),
    ],
)
def test_system_binding_rejects_invalid_dependencies(
    client, model_graph, dependencies: list[str], error_code: str
) -> None:
    graph = _create_application_graph(client, model_graph, error_code.lower())
    response = client.post(
        _binding_url(graph["application"]["id"]),
        json=_binding_payload(
            graph, "scope-1", "scope_1", dependencies=dependencies
        ),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == error_code
