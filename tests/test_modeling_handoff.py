from dataclasses import replace
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

from nebula_one.hashing import canonical_graph_sha256
from nebula_one.models import ModelingHandoff, SystemModel, SystemRevision, utcnow


def begin(client, model_graph, **extra):
    container = client.app.state.container
    container.settings = replace(container.settings, nebula_lca_editor_url="http://editor.test")
    assert client.get("/api/v1/modeling/configuration").json()["editor_url"] == "http://editor.test/"
    response = client.post("/api/v1/modeling/handoffs", json={"name": "Professional project", **extra})
    assert response.status_code == 201, response.text
    row = response.json()
    return row, {"state": row["state"], "confirmation_token": row["confirmation_token"],
        "project_id": "project-1", "saved_version": 3, "upstream_graph_hash": canonical_graph_sha256(model_graph)}


def endpoint(row, action):
    return f"/api/v1/modeling/handoffs/{row['handoff_id']}/{action}"


def test_confirmation_is_explicit_persistent_and_idempotent(client, model_graph, upstream_requests):
    row, payload = begin(client, model_graph)
    assert "confirmation_token" not in row["editor_url"]
    assert parse_qs(urlsplit(row["editor_url"]).query)["return_target"] == ["nebula_one"]
    assert client.get("/api/v1/applications").json() == []
    assert client.post(endpoint(row, "confirm"), json=payload).status_code == 409
    preview = client.post(endpoint(row, "preview"), json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["upstream_graph_hash"] == payload["upstream_graph_hash"]
    assert client.get("/api/v1/applications").json() == []
    # Separate requests/sessions read persistent handoff state; confirmation creates all records.
    created = client.post(endpoint(row, "confirm"), json=payload)
    assert created.status_code == 200, created.text
    assert client.post(endpoint(row, "confirm"), json=payload).json() == created.json()
    assert len(client.get("/api/v1/applications").json()) == 1
    application_id = created.json()["application_id"]
    sources = client.get(f"/api/v1/applications/{application_id}/model-sources").json()
    assert len(sources) == 1 and sources[0]["upstream_version"] == 3
    assert not any("latest" in item["path"] for item in upstream_requests)


def test_untrusted_return_and_expired_state_never_create_projects(client, model_graph):
    row, payload = begin(client, model_graph)
    for key, value in [("state", "x" * 43), ("confirmation_token", "x" * 43), ("upstream_graph_hash", "a" * 64)]:
        response = client.post(endpoint(row, "preview"), json={**payload, key: value})
        assert response.status_code in (403, 409), response.text
    assert client.post(endpoint(row, "preview"), json={**payload, "saved_version": "latest"}).status_code == 422
    assert client.post(endpoint(row, "preview"), json={**payload, "project_id": "../other"}).status_code == 422
    with client.app.state.container.database.session() as db:
        record = db.get(ModelingHandoff, row["handoff_id"])
        record.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.post(endpoint(row, "preview"), json=payload).status_code == 410
    assert client.get("/api/v1/applications").json() == []


def test_cancel_blocks_future_confirmation(client, model_graph):
    row, payload = begin(client, model_graph)
    assert client.post(endpoint(row, "preview"), json=payload).status_code == 200
    credentials = {k: payload[k] for k in ("state", "confirmation_token")}
    assert client.post(endpoint(row, "cancel"), json=credentials).status_code == 200
    assert client.post(endpoint(row, "confirm"), json=payload).status_code == 410
    assert client.get("/api/v1/applications").json() == []


def test_base_version_cannot_silently_change(client, model_graph):
    row, payload = begin(client, model_graph)
    assert client.post(endpoint(row, "preview"), json=payload).status_code == 200
    attached = client.post(endpoint(row, "confirm"), json=payload).json()
    child, candidate = begin(client, model_graph, base_model_id=attached["system_model_id"])
    assert parse_qs(urlsplit(child["editor_url"]).query)["version"] == ["3"]
    for changes in ({"base_version": 2}, {"base_version": 3}, {"base_version": 3, "saved_version": 4, "project_id": "another-project"}):
        assert client.post(endpoint(child, "preview"), json={**candidate, **changes}).status_code == 409
    assert len(client.get("/api/v1/applications").json()) == 1


def test_handoff_freezes_the_selected_revision_rule_pin(client, model_graph):
    row, payload = begin(client, model_graph)
    assert client.post(endpoint(row, "preview"), json=payload).status_code == 200
    attached = client.post(endpoint(row, "confirm"), json=payload).json()
    rule = {"package_id": "rules", "version": "1.0.0", "content_sha256": "a" * 64}
    with client.app.state.container.database.session() as db:
        revision = db.get(SystemRevision, attached["revision_id"])
        revision.application_context = {"project_inputs": {"model_processing_rules_ref": rule}}
        db.commit()
    child, _ = begin(client, model_graph, base_model_id=attached["system_model_id"],
                     base_revision_id=attached["revision_id"])
    with client.app.state.container.database.session() as db:
        saved = db.get(ModelingHandoff, child["handoff_id"]).base_identity
    assert saved["selected_revision_id"] == attached["revision_id"]
    assert saved["model_processing_rules_ref"] == rule
    response = client.post("/api/v1/modeling/handoffs", json={"name": "wrong", "base_model_id": attached["system_model_id"],
                                                              "base_revision_id": "missing-revision"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODELING_BASE_REVISION_INVALID"


def test_exact_model_can_rebind_an_explicitly_trusted_engine_connection(client, model_graph):
    row, payload = begin(client, model_graph)
    assert client.post(endpoint(row, "preview"), json=payload).status_code == 200
    attached = client.post(endpoint(row, "confirm"), json=payload).json()
    model_id = attached["system_model_id"]
    with client.app.state.container.database.session() as db:
        model = db.get(SystemModel, model_id)
        model.provider_base_url = "http://legacy-engine.test"
        db.commit()
    refused = client.post("/api/v1/modeling/handoffs", json={"name": "Revised model", "base_model_id": model_id})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "MODELING_ENGINE_CHANGED"
    container = client.app.state.container
    container.settings = replace(container.settings, nebula_lca_trusted_source_urls=("http://legacy-engine.test",))
    with container.database.session() as db:
        model = db.get(SystemModel, model_id)
        original_graph = model.graph_snapshot
        model.graph_snapshot = {"nodes": [], "exchanges": []}
        db.commit()
    changed = client.post("/api/v1/modeling/handoffs", json={"name": "Revised model", "base_model_id": model_id})
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "MODELING_BASE_CHANGED"
    with container.database.session() as db:
        model = db.get(SystemModel, model_id)
        assert model.provider_base_url == "http://legacy-engine.test"
        model.graph_snapshot = original_graph
        db.commit()
    child, _ = begin(client, model_graph, base_model_id=model_id)
    assert parse_qs(urlsplit(child["editor_url"]).query)["version"] == ["3"]
    with container.database.session() as db:
        model = db.get(SystemModel, model_id)
        assert model.provider_base_url == container.client.base_url
        assert model.upstream_receipt["verified_engine_connections"][-1]["graph_hash"] == canonical_graph_sha256(model_graph)


def test_parallel_confirm_creates_only_one_project(client, model_graph):
    row, payload = begin(client, model_graph)
    assert client.post(endpoint(row, "preview"), json=payload).status_code == 200
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: client.post(endpoint(row, "confirm"), json=payload), range(2)))
    assert all(result.status_code == 200 for result in results), [r.text for r in results]
    assert results[0].json() == results[1].json()
    assert len(client.get("/api/v1/applications").json()) == 1


def test_missing_editor_is_visible_and_configuration_does_not_accept_redirects(client):
    assert client.get("/api/v1/modeling/configuration").json()["available"] is False
    assert client.get("/api/v1/modeling/configuration").json()["editor_url"] is None
    assert client.post("/api/v1/modeling/handoffs", json={"name": "test"}).status_code == 503
    assert client.post("/api/v1/modeling/handoffs", json={"name": "test", "return_url": "https://other.test"}).status_code == 422
    assert client.post("/api/v1/modeling/handoffs", json={"name": "test", "base_model_id": ""}).status_code == 422
