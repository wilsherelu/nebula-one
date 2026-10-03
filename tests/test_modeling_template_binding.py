"""A model returned by professional modelling must carry the reviewed template it descends from.

The whole-plant extension only reaches an accounting purpose if the returned project names the
template its rules were reviewed against - otherwise no rule package resolves and the calculation
has no basis. That binding is *computed* from the base project the handoff started on and *forwarded*
into the new application; a caller cannot supply it. These are server-side tests over a real HTTP
handoff and a real SQLite session; the derivation they check is the same `resolve_purpose_derivation`
a solve runs, not a mocked stand-in.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from nebula_one.config import Settings
from nebula_one.hashing import canonical_graph_sha256, canonical_json_sha256
from nebula_one.main import create_app
from nebula_one.errors import DomainError
from nebula_one.models import Application, ModelingHandoff, SeedInstallation, SystemModel, SystemRevision, new_id
from nebula_one.runtime_models import MethodPackage
from nebula_one.runtime_schemas import MethodPackageCreate
from nebula_one.services.model_processing_runtime import (
    resolve_purpose_derivation,
    reviewed_template_profile,
    template_identity,
)
from nebula_one.services.returned_projects import ReturnedProjectService
from nebula_one.services.seed_projects import SeedProjectService

from test_steel_model_processing_assets import (
    _graph,
    _method_package,
    _saved_associations,
    _template_profile,
)

import steel_whole_plant_extension as ext

DEMAND = [{"process_uuid": "ea66dbd3-03e1-5ff8-a1d0-9662604392c0", "amount": 1000.0, "unit": "kg"}]


def _profile_identity() -> dict[str, str]:
    profile, digest, _ = _template_profile()
    return {"id": profile["id"], "version": profile["version"], "content_sha256": digest}


BASE_PROJECT = "project-steel"


def _transport(base_graph: dict, plant_graph: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.endswith("/versions/1/snapshot"):
            return httpx.Response(200, json=ext.provider_snapshot(BASE_PROJECT, 1, base_graph))
        if request.method == "GET" and path.endswith("/versions/2/snapshot"):
            return httpx.Response(200, json=ext.provider_snapshot(BASE_PROJECT, 2, plant_graph))
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


def _seed_base(container, *, template_bound: bool) -> str:
    """A stored steel model whose base revision says (or does not say) which template it came from."""
    graph = _graph()
    context = {"seed_template": {"profile": _profile_identity()}} if template_bound else {}
    application_id, model_id, revision_id = new_id(), new_id(), new_id()
    with container.database.session() as db:
        selector_path = Path("src/nebula_one/resources/official_methods/cbam-steel-direct-selector-1.2.2.json")
        selector = MethodPackageCreate.model_validate(json.loads(selector_path.read_text(encoding="utf-8")))
        selector_package = selector.model_dump(mode="json")
        selector_package["content_sha256"] = canonical_json_sha256(selector_package)
        for package in (_method_package(), selector_package):
            registered = db.query(MethodPackage).filter(
                MethodPackage.package_id == package["package_id"],
                MethodPackage.version == package["version"]).first()
            if registered is None:
                db.add(MethodPackage(
                    package_id=package["package_id"], version=package["version"],
                    package_kind=package["package_kind"], jurisdiction=package.get("jurisdiction"),
                    manifest=deepcopy(package["manifest"]), content_sha256=package["content_sha256"],
                    status="registered"))
        db.add(Application(id=application_id, name="Steel base",
                           application_type="standard_lca", context=deepcopy(context)))
        db.flush()
        db.add(SystemModel(
            id=model_id, application_id=application_id, name="Steel base", provider="nebula_lca",
            provider_base_url="http://engine.test", upstream_project_id=BASE_PROJECT,
            upstream_version=1, graph_sha256=canonical_graph_sha256(graph),
            graph_snapshot=deepcopy(graph), upstream_receipt={"base_revision_id": revision_id}))
        db.flush()
        db.add(SystemRevision(
            id=revision_id, system_model_id=model_id, revision_number=1, label="base",
            revision_kind="base", graph_sha256=canonical_graph_sha256(graph),
            content_sha256=canonical_json_sha256(graph), graph_snapshot=deepcopy(graph),
            application_context=deepcopy(context), status="draft"))
        db.commit()
    return model_id


@pytest.fixture()
def plant_client(tmp_path):
    base_graph, plant_graph = _graph(), ext.plant_extension_graph()
    app = create_app(
        Settings(database_url=f"sqlite:///{(tmp_path / 'return.db').as_posix()}",
                 nebula_lca_base_url="http://engine.test", nebula_lca_editor_url="http://editor.test"),
        engine_transport=_transport(base_graph, plant_graph),
    )
    with TestClient(app) as client:
        yield client


def _confirm_returned(client, base_model_id):
    started = client.post("/api/v1/modeling/handoffs",
                          json={"name": "Whole plant", "base_model_id": base_model_id})
    assert started.status_code == 201, started.text
    handoff = started.json()
    candidate = {"project_id": BASE_PROJECT, "base_version": 1, "saved_version": 2,
                 "upstream_graph_hash": canonical_graph_sha256(ext.plant_extension_graph())}
    endpoint = f"/api/v1/modeling/handoffs/{handoff['handoff_id']}"
    credentials = {"state": handoff["state"], "confirmation_token": handoff["confirmation_token"]}
    preview = client.post(f"{endpoint}/preview", json={**candidate, **credentials})
    assert preview.status_code == 200, preview.text
    confirmed = client.post(f"{endpoint}/confirm", json={**candidate, **credentials})
    assert confirmed.status_code == 200, confirmed.text
    return handoff, confirmed.json()


def _load(client, result):
    with client.app.state.container.database.session() as db:
        return (db.get(Application, result["application_id"]),
                db.get(SystemRevision, result["revision_id"]))


# ---- the return flow computes and forwards the binding, never accepts it ------


def test_start_computes_the_binding_from_the_bound_base(plant_client):
    base_model_id = _seed_base(plant_client.app.state.container, template_bound=True)
    started = plant_client.post("/api/v1/modeling/handoffs",
                                json={"name": "Whole plant", "base_model_id": base_model_id})
    handoff = started.json()
    with plant_client.app.state.container.database.session() as db:
        row = db.get(ModelingHandoff, handoff["handoff_id"])
    binding = row.base_identity["template_binding"]
    assert binding["profile"] == _profile_identity()
    assert binding["bound_model_id"] == base_model_id
    assert binding["bound_revision_id"]


def test_catalog_edit_binds_only_the_exact_ready_installed_source(plant_client, monkeypatch):
    container = plant_client.app.state.container
    base_model_id = _seed_base(container, template_bound=False)
    with container.database.session() as db:
        model = db.get(SystemModel, base_model_id)
        db.add(SeedInstallation(
            id=new_id(), seed_id="steel", seed_version="1.1.0", install_key="a" * 64,
            bundle_content_sha256="b" * 64, engine_base_url=container.client.base_url,
            engine_db_digest="c" * 64, engine_openapi_version="3.1.0", status="ready",
            application_id=model.application_id, system_model_id=base_model_id,
        ))
        db.commit()

    def source(_service, db, installation_id):
        installation = db.get(SeedInstallation, installation_id)
        return (installation, db.get(SystemModel, base_model_id),
                db.get(Application, installation.application_id),
                {"profile": _profile_identity(), "identity_revision": {"content": {
                    "display_metadata": [{"exchange_id": "ore-sintering::iron-ore-in", "name_zh": "铁矿石"}]
                }}}, {"template_sha256": "d" * 64}, [])

    monkeypatch.setattr(SeedProjectService, "_source", source)
    started = plant_client.post("/api/v1/modeling/handoffs", json={
        "name": "Installed source edit", "base_model_id": base_model_id,
    })
    assert started.status_code == 201, started.text
    with container.database.session() as db:
        row = db.get(ModelingHandoff, started.json()["handoff_id"])
        binding = row.base_identity["template_binding"]
    assert binding["profile"] == _profile_identity()
    assert binding["source_installation_id"]
    assert binding["template_sha256"] == "d" * 64
    assert binding["display_metadata"][0]["exchange_id"] == "ore-sintering::iron-ore-in"
    handoff = started.json()
    candidate = {
        "state": handoff["state"], "confirmation_token": handoff["confirmation_token"],
        "project_id": BASE_PROJECT, "base_version": 1, "saved_version": 2,
        "upstream_graph_hash": canonical_graph_sha256(ext.plant_extension_graph()),
    }
    route = f"/api/v1/modeling/handoffs/{handoff['handoff_id']}"
    assert plant_client.post(f"{route}/preview", json=candidate).status_code == 200
    confirmed = plant_client.post(f"{route}/confirm", json=candidate)
    assert confirmed.status_code == 200, confirmed.text
    application, _ = _load(plant_client, confirmed.json())
    assert application.context["modeling_template_binding"]["source_installation_id"] == binding["source_installation_id"]


def test_confirm_forwards_the_binding_so_the_returned_model_resolves_its_rules(plant_client):
    base_model_id = _seed_base(plant_client.app.state.container, template_bound=True)
    _, result = _confirm_returned(plant_client, base_model_id)
    application, revision = _load(plant_client, result)
    assert application.context["modeling_template_binding"]["profile"] == _profile_identity()
    assert reviewed_template_profile(application, revision) == _profile_identity()
    assert template_identity(revision, application) == _profile_identity()


def test_returned_model_without_its_own_reviewed_cbam_boundary_does_not_offer_trial(plant_client):
    model_id = _seed_base(plant_client.app.state.container, template_bound=True)
    with plant_client.app.state.container.database.session() as db:
        model = db.get(SystemModel, model_id)
        application = db.get(Application, model.application_id)
        revision = db.get(SystemRevision, model.upstream_receipt["base_revision_id"])
    application.context = {**application.context,
        "modeling_template_binding": {"profile": _profile_identity()}}
    capabilities, blocked = ReturnedProjectService(plant_client.app.state.container)._tasks(
        application, revision, DEMAND, {})
    assert "solve.nebula.v1" in capabilities
    assert "cbam.trial.v2" not in capabilities
    assert any(item["capability"] == "cbam.trial.v2" and item["code"] == "CBAM_REVIEWED_SOURCE_UNAVAILABLE"
               for item in blocked)


def test_the_returned_model_derives_lca_and_refuses_cbam_until_a_boundary_is_reviewed(plant_client):
    base_model_id = _seed_base(plant_client.app.state.container, template_bound=True)
    _, result = _confirm_returned(plant_client, base_model_id)
    application, revision = _load(plant_client, result)
    background, mapped = _saved_associations(_graph())
    with plant_client.app.state.container.database.session() as db:
        lca = resolve_purpose_derivation(
            db, revision=revision, application=application, purpose="lca",
            demand=deepcopy(DEMAND), background_process_pins=deepcopy(background),
            mapped_background_process_pins=deepcopy(mapped))
        assert {node["id"] for node in lca.derived.graph["nodes"]} == \
            {node["id"] for node in ext.plant_extension_graph()["nodes"]}
        with pytest.raises(DomainError) as excinfo:
            resolve_purpose_derivation(
                db, revision=revision, application=application, purpose="cbam",
                demand=deepcopy(DEMAND), background_process_pins=deepcopy(background),
                mapped_background_process_pins=deepcopy(mapped))
    assert excinfo.value.code == "MODEL_CROSS_BOUNDARY_UNDECLARED"


def test_unreviewed_returned_graph_cannot_activate_the_new_cbam_method(plant_client):
    base_model_id = _seed_base(plant_client.app.state.container, template_bound=True)
    _, result = _confirm_returned(plant_client, base_model_id)
    response = plant_client.post(
        f"/api/v1/applications/{result['application_id']}/workspace/{result['revision_id']}/reviewed-cbam")
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "MODEL_CROSS_BOUNDARY_UNDECLARED"
    with plant_client.app.state.container.database.session() as db:
        application = db.get(Application, result["application_id"])
        assert "cbam.eu.iron-steel.bf-bof-direct-trial@1.1.2" not in (
            application.context.get("method_package_refs") or [])


def test_a_base_with_no_template_binding_forwards_nothing(plant_client):
    base_model_id = _seed_base(plant_client.app.state.container, template_bound=False)
    started = plant_client.post("/api/v1/modeling/handoffs",
                                json={"name": "Whole plant", "base_model_id": base_model_id})
    handoff = started.json()
    with plant_client.app.state.container.database.session() as db:
        row = db.get(ModelingHandoff, handoff["handoff_id"])
    assert "template_binding" not in row.base_identity
    _, result = _confirm_returned(plant_client, base_model_id)
    application, revision = _load(plant_client, result)
    assert "modeling_template_binding" not in application.context
    with pytest.raises(DomainError) as excinfo:
        template_identity(revision, application)
    assert excinfo.value.code == "MODEL_PROCESSING_TEMPLATE_UNBOUND"


def test_a_caller_cannot_supply_the_binding(plant_client):
    _seed_base(plant_client.app.state.container, template_bound=True)
    injected = plant_client.post("/api/v1/modeling/handoffs", json={
        "name": "Whole plant", "base_model_id": "does-not-matter",
        "template_binding": {"profile": _profile_identity()}})
    assert injected.status_code == 422
    plant_model_id = _seed_base(plant_client.app.state.container, template_bound=True)
    started = plant_client.post("/api/v1/modeling/handoffs",
                                json={"name": "Whole plant", "base_model_id": plant_model_id})
    handoff = started.json()
    endpoint = f"/api/v1/modeling/handoffs/{handoff['handoff_id']}/preview"
    credentials = {"state": handoff["state"], "confirmation_token": handoff["confirmation_token"]}
    candidate = {"project_id": BASE_PROJECT, "base_version": 1, "saved_version": 2,
                 "upstream_graph_hash": canonical_graph_sha256(ext.plant_extension_graph())}
    refused = plant_client.post(endpoint, json={**candidate, **credentials,
                                               "template_binding": {"profile": _profile_identity()}})
    assert refused.status_code == 422


# ---- the operating loop: a bound return enters the workbench, not "no template" ----

REFERENCE_FLOW = "e31064bf-4268-5617-b79d-8b7f326d966e"
EXTENSION_ELECTRICITY = "scrap-processing-line::grid-electricity-in"


def _workspace(client, result, revision_id=None):
    revision = revision_id or result["revision_id"]
    return client.get(f"/api/v1/applications/{result['application_id']}/workspace/{revision}")


def _payload(workspace, key, amount):
    values = {field["key"]: field["value"] for field in workspace["fields"]}
    values[key] = amount
    return {"revision_id": workspace["revision_id"],
            "expected_content_sha256": workspace["content_sha256"],
            "amounts": [item["amount"] for item in workspace["demand"]],
            "values": values, "source": "现场实测"}


def _save(client, result, payload):
    return client.post(f"/api/v1/applications/{result['application_id']}/workspace/inputs", json=payload)


def test_a_bound_return_opens_the_workbench_on_its_own_inventory(plant_client):
    base_model_id = _seed_base(plant_client.app.state.container, template_bound=True)
    _, result = _confirm_returned(plant_client, base_model_id)
    response = _workspace(plant_client, result)
    assert response.status_code == 200, response.text
    workspace = response.json()
    keys = {field["key"] for field in workspace["fields"]}
    # The process the editor added is opened field by field, not refused for not matching a template.
    assert {"scrap-processing-line::purchased-scrap-in", EXTENSION_ELECTRICITY,
            "scrap-processing-line::processing-vent-out"} <= keys
    assert workspace["inventory_editing"] is True and workspace["saved"] is False
    # Demand is proven from the returned reference product's own identity, never assumed.
    assert workspace["demand"] == [{"reference_flow_uuid": REFERENCE_FLOW, "amount": 1000.0,
        "unit": "kg", "unit_group_uuid": "93a60a57-a4c8-11da-a746-0800200c9a66",
        "unit_group_version": "03.00.003"}]
    assert "mfa.solved.v1" in workspace["capabilities"]
    assert "solve.nebula.v1" in workspace["capabilities"]
    blocked = {item["capability"]: item for item in workspace["blocked_capabilities"]}
    assert blocked["cbam.trial.v2"]["code"] == "MODEL_CROSS_BOUNDARY_UNDECLARED"


def test_edit_a_still_existing_exchange_under_fixed_demand_then_reread(plant_client):
    base_model_id = _seed_base(plant_client.app.state.container, template_bound=True)
    _, result = _confirm_returned(plant_client, base_model_id)
    base = _workspace(plant_client, result).json()
    old = next(f["value"] for f in base["fields"] if f["key"] == EXTENSION_ELECTRICITY)
    saved = _save(plant_client, result, _payload(base, EXTENSION_ELECTRICITY, old + 5))
    assert saved.status_code == 200, saved.text
    after = saved.json()
    assert after["revision_id"] != base["revision_id"] and after["saved"] is True
    assert next(f["value"] for f in after["fields"] if f["key"] == EXTENSION_ELECTRICITY) == old + 5
    # The functional unit is fixed: only the edited exchange moved, the demand did not.
    assert [d["amount"] for d in after["demand"]] == [d["amount"] for d in base["demand"]]
    # The model the editor returned stays byte-for-byte untouched behind the new data version.
    _, revision = _load(plant_client, result)
    assert revision.graph_snapshot == ext.plant_extension_graph()
    # Re-reading through the workbench still succeeds and re-derives the same task set.
    again = _workspace(plant_client, result, after["revision_id"])
    assert again.status_code == 200, again.text
    assert again.json()["capabilities"] == base["capabilities"]


def test_saving_the_same_returned_data_twice_reuses_one_revision(plant_client):
    base_model_id = _seed_base(plant_client.app.state.container, template_bound=True)
    _, result = _confirm_returned(plant_client, base_model_id)
    base = _workspace(plant_client, result).json()
    payload = _payload(base, EXTENSION_ELECTRICITY, 42.0)
    first = _save(plant_client, result, payload).json()
    second = _save(plant_client, result, payload)
    assert second.status_code == 200 and second.json()["revision_id"] == first["revision_id"]


def test_a_stale_returned_data_version_is_refused(plant_client):
    base_model_id = _seed_base(plant_client.app.state.container, template_bound=True)
    _, result = _confirm_returned(plant_client, base_model_id)
    base = _workspace(plant_client, result).json()
    payload = _payload(base, EXTENSION_ELECTRICITY, 40.0)
    payload["expected_content_sha256"] = "0" * 64
    response = _save(plant_client, result, payload)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROJECT_INPUT_CONFLICT"


def test_returned_workspace_cannot_save_another_projects_revision(plant_client):
    container = plant_client.app.state.container
    base_model_id = _seed_base(container, template_bound=True)
    _, first = _confirm_returned(plant_client, base_model_id)
    _, second = _confirm_returned(plant_client, base_model_id)
    workspace = _workspace(plant_client, second).json()
    with container.database.session() as db:
        before = db.query(SystemRevision).count()
    response = _save(plant_client, first, _payload(workspace, EXTENSION_ELECTRICITY, 42.0))
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "PROJECT_REVISION_MISMATCH"
    with container.database.session() as db:
        assert db.query(SystemRevision).count() == before


def test_a_returned_model_with_an_incomplete_reference_product_names_that_gap(plant_client):
    container = plant_client.app.state.container
    base_model_id = _seed_base(container, template_bound=True)
    _, result = _confirm_returned(plant_client, base_model_id)
    with container.database.session() as db:
        application = db.get(Application, result["application_id"])
        application.context = {**application.context, "modeling_functional_unit":
                               {"display_text": "1 kg crude steel", "flow_uuid": REFERENCE_FLOW}}
        db.commit()
    response = _workspace(plant_client, result)
    assert response.status_code == 409
    error = response.json()["error"]
    # The whole project is never thrown back to "no template": the missing identity is named instead.
    assert error["code"] == "MODELING_FUNCTIONAL_UNIT_INCOMPLETE"
    assert sorted(error["details"]["missing_functional_unit_keys"]) == ["amount", "unit"]


def test_an_unbound_return_still_has_no_fillable_template(plant_client):
    base_model_id = _seed_base(plant_client.app.state.container, template_bound=False)
    _, result = _confirm_returned(plant_client, base_model_id)
    response = _workspace(plant_client, result)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PROJECT_TEMPLATE_UNAVAILABLE"
