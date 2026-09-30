"""An authored template is an exact, immutable model pin for new projects."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from nebula_one.hashing import canonical_content_sha256, canonical_graph_sha256
from nebula_one.models import Application, SystemModel, SystemRevision
from test_api_flow import _attach_model, _create_application


def test_finalized_model_version_creates_new_projects_without_rebinding_the_source(client, monkeypatch):
    source = _create_application(client, "system_analysis")
    attached = _attach_model(client, source["id"])
    revision_id = attached["upstream_receipt"]["base_revision_id"]
    container = client.app.state.container
    with container.database.session() as db:
        application = db.get(Application, source["id"])
        model = db.get(SystemModel, attached["id"])
        revision = db.get(SystemRevision, revision_id)
        graph = deepcopy(revision.graph_snapshot)
        product = next(port for node in graph["nodes"] for port in node["outputs"]
                       if port.get("flowUuid") == "flow-product")
        product.update(isProduct=True, unitGroupUuid="mass-group", unitGroupVersion="01.00.000")
        graph_hash = canonical_graph_sha256(graph)
        context = {**application.context, "template_locked": True,
                   "modeling_template_binding": {"profile": {"id": "reviewed", "version": "1.0.0", "content_sha256": "a" * 64}},
                   "modeling_functional_unit": {"flow_uuid": "flow-product", "amount": 8, "unit": "kg"},
                   "project_capabilities": ["mfa.solved.v1"], "method_package_refs": []}
        application.context = context
        model.graph_snapshot = deepcopy(graph)
        model.graph_sha256 = graph_hash
        model.upstream_receipt = {**model.upstream_receipt, "upstream_graph_hash": graph_hash}
        revision.graph_snapshot = deepcopy(graph)
        revision.graph_sha256 = graph_hash
        revision.application_context = deepcopy(context)
        revision.content_sha256 = canonical_content_sha256(graph, context)
        digest = revision.content_sha256
        db.commit()
    monkeypatch.setattr(container.client, "get_provider_model_snapshot",
                        lambda project_id, version: SimpleNamespace(payload={"graph": deepcopy(graph), "graph_hash": graph_hash}))
    publish = client.post("/api/v1/project-templates/authored", json={
        "title": "Reviewed steel", "version": "1.0.0", "source_application_id": source["id"],
        "source_model_id": attached["id"], "source_revision_id": revision_id,
        "expected_revision_sha256": digest, "methods": [],
    })
    assert publish.status_code == 200, publish.text
    template = publish.json()
    assert template["template_sha256"] and template["source_revision_id"] == revision_id
    assert "pcf.product.v1" in template["capabilities"]
    assert any(item["id"] == template["id"] for item in client.get("/api/v1/project-templates").json()["items"])
    endpoint = f"/api/v1/project-templates/{template['id']}/projects"
    request = {"name": "New plant", "project_key": str(uuid4()),
               "expected_template_sha256": template["template_sha256"]}
    created = client.post(endpoint, json=request)
    assert created.status_code == 200, created.text
    first = created.json()
    assert client.post(endpoint, json=request).json() == first
    assert client.post(endpoint, json={**request, "name": "Different"}).status_code == 409
    assert client.post(endpoint, json={**request, "expected_template_sha256": "0" * 64}).status_code == 409
    own = client.get(f"/api/v1/applications/{first['application_id']}/workspace/{first['revision_id']}")
    assert own.status_code == 200, own.text
    assert own.json()["demand"][0]["amount"] == 8
    with container.database.session() as db:
        original = db.get(Application, source["id"])
        new = db.get(Application, first["application_id"])
        assert original.context.get("authored_template") is None
        assert new.context["authored_template"] == {"id": template["id"], "title": "Reviewed steel",
            "version": "1.0.0", "content_sha256": template["template_sha256"]}
