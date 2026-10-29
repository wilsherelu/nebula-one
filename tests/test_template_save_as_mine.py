"""Saving a template version as the reader's own, and what a new project then inherits."""
from copy import deepcopy
from uuid import uuid4

import pytest

from nebula_one.runtime_models import MethodPackage
from test_template_accounting_methods import ORGANIZATION_MANIFEST, _package, _published_template


def _revision_sha(client, revision_id: str) -> str:
    return client.get(f"/api/v1/system-revisions/{revision_id}").json()["content_sha256"]


def _ready_copy(client, template: dict, package: dict, name: str = "组织范围·我的调整") -> dict:
    """Copy one official scheme of this template and pass its check, as the workspace does."""
    copied = client.post(f"/api/v1/project-templates/{template['id']}/accounting-methods/copy",
                         json={"method_key": f"official:{package['package_id']}@{package['version']}",
                               "name": name})
    assert copied.status_code == 201, copied.text
    method = copied.json()["method"]["method"]
    checked = client.post(f"/api/v1/calculation-methods/{method['id']}/versions/1/validate").json()
    assert checked["valid"], checked
    return copied.json()["method"]


def test_saving_a_template_freezes_the_checked_copy_and_a_new_project_inherits_an_independent_draft(
        client, monkeypatch):
    organization = _package("ghg.demo.organization-period-model", "1.0.4",
                            "organization_period_inventory", ORGANIZATION_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[organization], bound=[organization],
                                   title="Save steel")
    detail = _ready_copy(client, template, organization)
    method_id = detail["method"]["id"]

    plan = client.get(f"/api/v1/project-templates/{template['id']}/save-plan")
    assert plan.status_code == 200, plan.text
    described = plan.json()
    assert described["schema_version"] == "nebula_one.template-save.v1"
    assert described["template_id"] == template["id"] and described["kind"] == "authored"
    assert described["official"] is False and described["suggested_title"] == "Save steel"
    # The plan states the exact source, so the reader never re-picks an application, model or package.
    assert described["source_application_id"] == template["source_application_id"]
    assert described["source_revision_id"] == template["source_revision_id"]
    assert described["expected_revision_sha256"] == _revision_sha(client, template["source_revision_id"])
    assert described["method_pins"] == [{"package_id": organization["package_id"], "version": "1.0.4",
                                        "content_sha256": organization["content_sha256"]}]
    assert described["unresolved_method_package_refs"] == []
    # The source template already occupies 1.0.0 under this title, so the suggestion is the next one.
    assert described["suggested_version"] == "1.0.1"
    candidates = {item["method_id"]: item for item in described["user_methods"]}
    assert candidates[method_id]["savable"] is True and candidates[method_id]["blocking_reason"] is None
    assert candidates[method_id]["status"] == "ready" and candidates[method_id]["rule_count"] == 2
    carried = next(item for item in described["user_methods"] if item["already_frozen_in_template"])
    assert carried["savable"] is False and carried["blocking_reason"] == "METHOD_ALREADY_IN_TEMPLATE"

    saved = client.post(f"/api/v1/project-templates/{template['id']}/save-template", json={
        "title": "Save steel", "version": described["suggested_version"],
        "user_methods": [{"method_id": method_id, "version": 1,
                          "content_sha256": candidates[method_id]["content_sha256"]}]})
    assert saved.status_code == 201, saved.text
    body = saved.json()
    mine = body["template"]
    assert mine["id"] != template["id"] and mine["kind"] == "authored"
    assert mine["title"] == "Save steel" and mine["version"] == "1.0.1"
    assert mine["user_method_count"] == 1
    assert body["source_template"]["template_id"] == template["id"]
    assert body["frozen_user_methods"] == [{"method_id": method_id, "version": 1,
                                            "content_sha256": candidates[method_id]["content_sha256"]}]

    # The saved template lists the frozen copy once, as a template method, and shows the working
    # method it did not carry as a separate loose draft instead of pretending it was frozen too.
    methods = client.get(f"/api/v1/project-templates/{mine['id']}/accounting-methods").json()["methods"]
    frozen_entries = [item for item in methods
                      if item["user_method"] and item["user_method"]["method_id"] == method_id]
    assert [item["origin"] for item in frozen_entries] == ["template_user_method"]
    assert {item["origin"] for item in methods} == {
        "official_package", "template_user_method", "source_user_method"}
    # The suggestion follows the title's own numeric line, so the version just taken is never offered.
    assert client.get(f"/api/v1/project-templates/{template['id']}/save-plan"
                      ).json()["suggested_version"] == "1.0.2"
    assert client.get(f"/api/v1/project-templates/{mine['id']}/save-plan"
                      ).json()["suggested_version"] == "1.0.2"

    project = client.post(f"/api/v1/project-templates/{mine['id']}/projects", json={
        "name": "验收项目·继承方案", "project_key": str(uuid4()),
        "expected_template_sha256": mine["template_sha256"]})
    assert project.status_code == 200, project.text
    application_id = project.json()["application_id"]
    listed = client.get(f"/api/v1/applications/{application_id}/calculation-methods").json()
    inherited = next(item for item in listed if item["origin_method_id"] == method_id)
    # A new project gets its own draft copy: a ready mark from another context is never inherited.
    assert inherited["id"] != method_id and inherited["status"] == "draft"
    inherited_rules = client.get(
        f"/api/v1/calculation-methods/{inherited['id']}/versions/1").json()["rules"]
    assert inherited_rules == detail["versions"][0]["rules"]
    assert client.post(f"/api/v1/calculation-methods/{inherited['id']}/versions/1/validate"
                       ).json()["valid"]

    # Editing the working method afterwards changes neither the saved template nor the old project.
    edited = client.put(f"/api/v1/calculation-methods/{method_id}/versions/1", json={
        "rules": [{**deepcopy(detail["versions"][0]["rules"][0]), "boundary_status": "excluded",
                   "scope": None}],
        "expected_content_sha256": detail["versions"][0]["content_sha256"]})
    assert edited.status_code == 200, edited.text
    assert client.get(f"/api/v1/project-templates/{mine['id']}/accounting-methods"
                      ).json()["template"]["template_sha256"] == mine["template_sha256"]
    assert client.get(f"/api/v1/calculation-methods/{inherited['id']}/versions/1"
                      ).json()["rules"] == inherited_rules
    frozen_after = next(item for item in client.get(
        f"/api/v1/project-templates/{mine['id']}/accounting-methods").json()["methods"]
        if item["origin"] == "template_user_method")
    assert frozen_after["rule_source"]["declared_count"] == 2


def test_saving_refuses_a_method_that_has_not_passed_its_check(client, monkeypatch):
    organization = _package("ghg.demo.organization-period-model", "1.0.4",
                            "organization_period_inventory", ORGANIZATION_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[organization], bound=[organization],
                                   title="Unchecked save")
    copied = client.post(f"/api/v1/project-templates/{template['id']}/accounting-methods/copy",
                         json={"method_key": f"official:{organization['package_id']}@1.0.4",
                               "name": "组织范围·未检查"})
    assert copied.status_code == 201, copied.text
    method = copied.json()["method"]["method"]
    version = copied.json()["method"]["versions"][0]
    described = client.get(f"/api/v1/project-templates/{template['id']}/save-plan").json()
    candidate = next(item for item in described["user_methods"] if item["method_id"] == method["id"])
    # The plan says why it cannot be frozen, instead of letting the reader hit a raw refusal later.
    assert candidate["savable"] is False and candidate["status"] == "draft"
    assert candidate["blocking_reason"] == "METHOD_NOT_VALIDATED"
    response = client.post(f"/api/v1/project-templates/{template['id']}/save-template", json={
        "title": "Unchecked save", "version": described["suggested_version"],
        "user_methods": [{"method_id": method["id"], "version": 1,
                          "content_sha256": version["content_sha256"]}]})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "TEMPLATE_USER_METHOD_NOT_READY"


@pytest.mark.parametrize("semantics", ["result_category.v1", "flow_tag.v1"])
def test_caliber_survives_template_freeze_and_independent_project_inheritance(client, monkeypatch, semantics):
    template = _published_template(client, monkeypatch, packages=[], bound=[], title="Tagged template")
    source_id = template["source_application_id"]
    revision_id = template["source_revision_id"]
    created = client.post(f"/api/v1/applications/{source_id}/calculation-methods", json={
        "name": "User-defined grouping", "purpose": "custom", "model_revision_id": revision_id,
        "semantics": semantics,
        "reporting_dimensions": [{"id": "custom", "name": "User grouping", "categories": [
            {"id": "materials", "name": "Materials", "is_leaf": True}]}],
        "rules": [{"process_instance_id": "preparation", "exchange_id": "preparation::ore-in",
                   "direction": "input", "boundary_status": "selected", "location_role": "other",
                   "categories": {"custom": "materials"}}]})
    assert created.status_code == 201, created.text
    detail = created.json()
    method_id = detail["method"]["id"]
    version = detail["versions"][0]
    checked = client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate")
    assert checked.status_code == 200 and checked.json()["valid"], checked.text
    plan = client.get(f"/api/v1/project-templates/{template['id']}/save-plan").json()
    candidate = next(item for item in plan["user_methods"] if item["method_id"] == method_id)
    assert candidate["savable"] and candidate["semantics"] == semantics
    ref = {"method_id": method_id, "version": 1, "content_sha256": version["content_sha256"]}
    saved = client.post(f"/api/v1/project-templates/{template['id']}/save-template", json={
        "title": "Frozen caliber template", "version": "1.0.0", "user_methods": [ref]})
    assert saved.status_code == 201, saved.text
    mine = saved.json()["template"]
    methods = client.get(f"/api/v1/project-templates/{mine['id']}/accounting-methods").json()["methods"]
    frozen = next(item["user_method"] for item in methods if item["origin"] == "template_user_method")
    assert frozen["semantics"] == semantics
    assert frozen["reporting_dimensions"] == version["reporting_dimensions"]

    def new_project():
        response = client.post(f"/api/v1/project-templates/{mine['id']}/projects", json={
            "name": "Project with frozen calibers", "project_key": str(uuid4()),
            "expected_template_sha256": mine["template_sha256"]})
        assert response.status_code == 200, response.text
        project = response.json()
        listed = client.get(f"/api/v1/applications/{project['application_id']}/calculation-methods").json()
        inherited = next(item for item in listed if item["origin_method_id"] == method_id)
        copy = client.get(f"/api/v1/calculation-methods/{inherited['id']}/versions/1").json()
        assert inherited["id"] != method_id and inherited["model_revision_id"] == project["revision_id"]
        assert inherited["application_id"] == project["application_id"]
        assert copy["semantics"] == semantics and copy["status"] == "draft"
        assert copy["rules"] == version["rules"]
        assert copy["reporting_dimensions"] == version["reporting_dimensions"]
        assert copy["content_sha256"] == version["content_sha256"]
        validation = client.post(f"/api/v1/calculation-methods/{inherited['id']}/versions/1/validate")
        assert validation.status_code == 200 and validation.json()["valid"], validation.text
        ready = client.get(f"/api/v1/calculation-methods/{inherited['id']}/versions/1").json()
        assert ready["status"] == "ready"
        return inherited

    first = new_project()
    # A user's first input save creates a new exact model revision. The caliber must follow it
    # independently, otherwise the usable template loses every custom method before solve.
    workspace_path = f"/api/v1/applications/{first['application_id']}/workspace"
    workspace = client.get(f"{workspace_path}/{first['model_revision_id']}").json()
    values = {field["key"]: field["value"] for field in workspace["fields"]}
    values[next(iter(values))] *= 1.2
    inputs = {"revision_id": workspace["revision_id"],
              "expected_content_sha256": workspace["content_sha256"], "values": values,
              "amounts": [item["amount"] for item in workspace["demand"]],
              "source": "Measured input ledger"}
    saved_inputs = client.post(f"{workspace_path}/inputs", json=inputs)
    assert saved_inputs.status_code == 200, saved_inputs.text
    saved_workspace = saved_inputs.json()
    new_revision_id = saved_workspace["revision_id"]
    assert new_revision_id != first["model_revision_id"]
    assert client.post(f"{workspace_path}/inputs", json=inputs).json() == saved_workspace
    continued = client.get(
        f"/api/v1/applications/{first['application_id']}/calculation-methods",
        params={"model_revision_id": new_revision_id}).json()
    assert len(continued) == 1
    carried = continued[0]
    assert carried["id"] != first["id"] and carried["origin_method_id"] == first["id"]
    carried_version = client.get(f"/api/v1/calculation-methods/{carried['id']}/versions/1").json()
    assert carried_version["status"] == "draft" and carried_version["semantics"] == semantics
    assert carried_version["rules"] == version["rules"]
    assert carried_version["reporting_dimensions"] == version["reporting_dimensions"]
    checked_inputs = client.post(f"/api/v1/calculation-methods/{carried['id']}/versions/1/validate")
    assert checked_inputs.status_code == 200 and checked_inputs.json()["valid"], checked_inputs.text
    assert client.get(f"/api/v1/calculation-methods/{first['id']}/versions/1").json()["status"] == "ready"
    if semantics == "result_category.v1":
        # A later source change never rewrites what the frozen template already carries.
        changed = client.put(f"/api/v1/calculation-methods/{method_id}/versions/1", json={
            "rules": [], "reporting_dimensions": version["reporting_dimensions"],
            "expected_content_sha256": version["content_sha256"]})
        assert changed.status_code == 200, changed.text
    else:
        # A legacy tag scheme is read-only at the source; only its conversion creates a new caliber.
        changed = client.put(f"/api/v1/calculation-methods/{method_id}/versions/1", json={
            "rules": [], "reporting_dimensions": version["reporting_dimensions"],
            "expected_content_sha256": version["content_sha256"]})
        assert changed.status_code == 409
        assert changed.json()["error"]["code"] == "CALCULATION_METHOD_LEGACY_READ_ONLY"
    second = new_project()
    assert second["id"] != first["id"]
    assert client.get(f"/api/v1/calculation-methods/{first['id']}/versions/1").json()["rules"] == version["rules"]
    assert client.get(f"/api/v1/project-templates/{mine['id']}/accounting-methods").json()[
        "template"]["template_sha256"] == mine["template_sha256"]
    # Archiving a method prevents new template references even to a formerly ready version;
    # already frozen templates still instantiate their own original content.
    archived = client.post(f"/api/v1/calculation-methods/{method_id}/archive")
    assert archived.status_code == 200, archived.text
    rejected = client.post(f"/api/v1/project-templates/{template['id']}/save-template", json={
        "title": "Archived reference", "version": "1.0.0", "user_methods": [ref]})
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "TEMPLATE_USER_METHOD_NOT_READY"
    new_project()


def test_saving_refuses_when_a_bound_scheme_can_no_longer_be_resolved(client, monkeypatch):
    organization = _package("ghg.demo.organization-period-model", "1.0.4",
                            "organization_period_inventory", ORGANIZATION_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[organization], bound=[organization],
                                   title="Unresolved save")
    container = client.app.state.container
    with container.database.session() as db:
        row = db.query(MethodPackage).filter_by(package_id=organization["package_id"],
                                                version="1.0.4").one()
        db.delete(row)
        db.commit()
    described = client.get(f"/api/v1/project-templates/{template['id']}/save-plan").json()
    # The missing scheme is named, not dropped: a template must not be saved narrower than it reads.
    assert described["method_pins"] == []
    assert described["unresolved_method_package_refs"] == [f"{organization['package_id']}@1.0.4"]
    response = client.post(f"/api/v1/project-templates/{template['id']}/save-template", json={
        "title": "Unresolved save", "version": described["suggested_version"], "user_methods": []})
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "TEMPLATE_SAVE_METHOD_UNRESOLVED"
    assert error["details"]["unresolved"] == [f"{organization['package_id']}@1.0.4"]


def test_repeating_the_same_save_request_never_creates_a_second_template(client, monkeypatch):
    organization = _package("ghg.demo.organization-period-model", "1.0.4",
                            "organization_period_inventory", ORGANIZATION_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[organization], bound=[organization],
                                   title="Repeat save")
    detail = _ready_copy(client, template, organization)
    method_id = detail["method"]["id"]
    described = client.get(f"/api/v1/project-templates/{template['id']}/save-plan").json()
    candidate = next(item for item in described["user_methods"] if item["method_id"] == method_id)
    url = f"/api/v1/project-templates/{template['id']}/save-template"
    payload = {"title": "Repeat save", "version": described["suggested_version"],
               "user_methods": [{"method_id": method_id, "version": 1,
                                 "content_sha256": candidate["content_sha256"]}]}
    first = client.post(url, json=payload)
    assert first.status_code == 201, first.text
    # A double-clicked submit reads back the same saved version instead of publishing a twin.
    second = client.post(url, json=payload)
    assert second.status_code == 201, second.text
    assert second.json()["template"]["id"] == first.json()["template"]["id"]
    assert second.json()["template"]["template_sha256"] == first.json()["template"]["template_sha256"]
    catalog = client.get("/api/v1/project-templates").json()["items"]
    twins = [item for item in catalog
             if item["title"] == "Repeat save" and item["version"] == payload["version"]]
    assert len(twins) == 1
    # A title longer than the stored column is refused at the contract, not truncated silently.
    assert client.post(url, json={**payload, "title": "长" * 256, "version": "9.9.9"}
                       ).status_code == 422
    assert [item for item in client.get("/api/v1/project-templates").json()["items"]
            if item["version"] == "9.9.9"] == []
