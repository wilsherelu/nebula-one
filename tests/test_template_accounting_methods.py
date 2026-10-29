"""The template workspace may only list what an exact template version really binds."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from nebula_one.hashing import canonical_content_sha256, canonical_graph_sha256, canonical_json_sha256
from nebula_one.models import Application, SeedInstallation, SystemModel, SystemRevision
from nebula_one.runtime_models import MethodPackage
from nebula_one.services.template_accounting_methods import TemplateAccountingMethodsService
from test_api_flow import _attach_model, _create_application

PROFILE = {"id": "reviewed", "version": "1.0.0", "content_sha256": "a" * 64}
ORGANIZATION_MANIFEST = {
    "template_profile": PROFILE,
    "boundary_schema": {"complete_corporate_inventory": False},
    "classification_rules": {
        "scope2_purchase_exchange_ids": ["product::material-in"],
        "pending_activity_rules": {"preparation::ore-in": {"clause": "ST-12", "reason": "等待合格因子"}},
    },
    "default_value_rules": {"allowed": False, "basis": "缺证据时拒绝而不是编造默认值"},
    "validation_rules": {"limitations": ["背景是生命周期总量，不是发电口径因子"]},
    "provenance": {"scope2_source": "https://ghgprotocol.org/scope-2-guidance", "owner": "Nebula One"},
    "assurance_level": "demonstration",
}
PCF_MANIFEST = {
    "template_profile": PROFILE,
    "boundary_schema": {"complete_product_declaration": False},
    "classification_rules": {"domains": ["foreground", "native_background"]},
    "default_value_rules": {"allowed": False},
    "validation_rules": {},
    "provenance": {"owner": "Nebula One"},
    "assurance_level": "demonstration",
}


def _package(package_id: str, version: str, package_kind: str, manifest: dict) -> dict:
    return {"package_id": package_id, "version": version, "package_kind": package_kind,
            "manifest": manifest, "content_sha256": canonical_json_sha256(manifest)}


def _published_template(client, monkeypatch, *, packages: list[dict], bound: list[dict],
                        title: str = "Reviewed steel", before_publish=None) -> dict:
    """Publish an authored template whose frozen content binds exactly `bound`."""
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
                   "modeling_template_binding": {"profile": PROFILE},
                   "modeling_functional_unit": {"flow_uuid": "flow-product", "amount": 8, "unit": "kg"},
                   "project_capabilities": ["mfa.solved.v1"],
                   "method_package_refs": [f"{item['package_id']}@{item['version']}" for item in packages]}
        application.context = context
        model.graph_snapshot = deepcopy(graph)
        model.graph_sha256 = graph_hash
        model.upstream_receipt = {**model.upstream_receipt, "upstream_graph_hash": graph_hash}
        revision.graph_snapshot = deepcopy(graph)
        revision.graph_sha256 = graph_hash
        revision.application_context = deepcopy(context)
        revision.content_sha256 = canonical_content_sha256(graph, context)
        digest = revision.content_sha256
        for item in packages:
            db.add(MethodPackage(package_id=item["package_id"], version=item["version"],
                                 package_kind=item["package_kind"], jurisdiction="EU",
                                 manifest=deepcopy(item["manifest"]),
                                 content_sha256=item["content_sha256"], status="registered"))
        db.commit()
    monkeypatch.setattr(container.client, "get_provider_model_snapshot",
                        lambda project_id, version: SimpleNamespace(
                            payload={"graph": deepcopy(graph), "graph_hash": graph_hash}))
    created = client.post(f"/api/v1/applications/{source['id']}/calculation-methods", json={
        "name": "模板自带规则", "purpose": "pcf", "model_revision_id": revision_id,
        "rules": [{"process_instance_id": "product", "exchange_id": "product::product-out",
                   "direction": "emission", "boundary_status": "selected", "location_role": "onsite",
                   "scope": "scope_1", "classification_basis": "user"}]})
    assert created.status_code == 201, created.text
    method = created.json()
    assert client.post(
        f"/api/v1/calculation-methods/{method['method']['id']}/versions/1/validate").json()["valid"]
    if before_publish is not None:
        before_publish(client, source["id"], revision_id)
    published = client.post("/api/v1/project-templates/authored", json={
        "title": title, "version": "1.0.0", "source_application_id": source["id"],
        "source_model_id": attached["id"], "source_revision_id": revision_id,
        "expected_revision_sha256": digest,
        "methods": [{"package_id": item["package_id"], "version": item["version"],
                     "content_sha256": item["content_sha256"]} for item in bound],
        "user_methods": [{"method_id": method["method"]["id"], "version": 1,
                          "content_sha256": method["versions"][0]["content_sha256"]}]})
    assert published.status_code == 200, published.text
    return published.json()


def test_aggregation_reports_declared_exchanges_and_the_packages_own_gaps(client, monkeypatch):
    organization = _package("ghg.demo.organization-period-model", "1.0.4",
                            "organization_period_inventory", ORGANIZATION_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[organization], bound=[organization])
    response = client.get(f"/api/v1/project-templates/{template['id']}/accounting-methods")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "nebula_one.template-accounting-methods.v1"
    described = body["template"]
    assert described["kind"] == "authored" and described["official"] is False
    assert described["editable"] is True and described["template_sha256"] == template["template_sha256"]
    assert described["model"]["process_count"] == 2 and described["model"]["port_count"] == 5
    assert described["model"]["graph_basis"] == "source_revision"
    assert len(described["model"]["graph_sha256"]) == 64
    # Template-rule editing needs the exact inventory even when the source has no fillable binding.
    assert described["model"]["graph_snapshot"]["nodes"]
    container = client.app.state.container
    with container.database.session() as db:
        source = db.get(SystemRevision, described["source_revision_id"])
        assert canonical_graph_sha256(source.graph_snapshot) == described["model"]["graph_sha256"]
        assert {node["id"] for node in source.graph_snapshot["nodes"]} == {
            node["id"] for node in described["model"]["graph_snapshot"]["nodes"]}
    official = next(item for item in body["methods"] if item["origin"] == "official_package")
    assert official["purpose"] == "organization_period_inventory"
    assert official["method_group"] == "organization"
    assert official["editable"] is False and official["actions"] == ["view", "copy_and_adjust"]
    assert official["base_method_ref"] == {"package_id": organization["package_id"],
                                           "version": "1.0.4",
                                           "content_sha256": organization["content_sha256"]}
    source = official["rule_source"]
    assert source["kind"] == "official_package_classification"
    # A pending rule names its subject as a mapping key, so it is a declaration too: the package
    # says the port is applicable and still waits for a factor. It must not be silently dropped.
    assert source["declared"] == [
        {"exchange_id": "preparation::ore-in", "rule_paths": ["pending_activity_rules.preparation::ore-in"]},
        {"exchange_id": "product::material-in", "rule_paths": ["scope2_purchase_exchange_ids.0"]}]
    assert source["declared_count"] == 2 and source["port_count"] == 5
    assert source["undeclared_port_count"] == 3
    assert source["declared_but_absent_from_model"] == []
    assert any(entry.get("url") == "https://ghgprotocol.org/scope-2-guidance"
               for entry in source["provenance"])
    codes = {gap["code"] for gap in official["coverage_gaps"]}
    assert {"PACKAGE_DECLARED_LIMITATION", "PACKAGE_PENDING_RULE", "PACKAGE_REFUSES_DEFAULT_VALUES",
            "PACKAGE_DECLARED_INCOMPLETE_BOUNDARY"} <= codes
    pending = next(gap for gap in official["coverage_gaps"] if gap["code"] == "PACKAGE_PENDING_RULE")
    assert pending["exchange_id"] == "preparation::ore-in" and pending["clause"] == "ST-12"
    assert official["check"]["status"] == "gap"
    assert official["check"]["status_basis"] == "official_package_declaration"
    user = next(item for item in body["methods"] if item["origin"] == "template_user_method")
    assert user["editable"] is True and "save_draft" in user["actions"]
    assert user["display_name"] == {"zh": "模板自带规则", "en": "模板自带规则"}
    assert user["user_method"]["version"] == 1 and user["user_method"]["rule_count"] == 1
    assert user["rule_source"]["declared"] == [{"exchange_id": "product::product-out",
                                                "rule_paths": ["rules[0]"]}]
    assert user["check"]["status"] == "not_validated"


def test_template_rule_inventory_does_not_require_a_fillable_source_application(client, monkeypatch):
    template = _published_template(client, monkeypatch, packages=[], bound=[])
    with client.app.state.container.database.session() as db:
        source = db.get(Application, template["source_application_id"])
        source.context = {key: value for key, value in source.context.items()
                          if key not in {"template_locked", "modeling_template_binding", "case_pack_id", "seed_template"}}
        db.commit()
    worksheet = client.get(f"/api/v1/applications/{template['source_application_id']}/workspace/{template['source_revision_id']}")
    assert worksheet.status_code == 422
    assert worksheet.json()["error"]["code"] == "PROJECT_TEMPLATE_UNAVAILABLE"
    response = client.get(f"/api/v1/project-templates/{template['id']}/accounting-methods")
    assert response.status_code == 200, response.text
    model = response.json()["template"]["model"]
    assert model["graph_basis"] == "source_revision"
    assert model["graph_snapshot"]["nodes"]


def test_registered_but_unbound_package_is_not_reported_as_a_template_method(client, monkeypatch):
    organization = _package("ghg.demo.organization-period-model", "1.0.4",
                            "organization_period_inventory", ORGANIZATION_MANIFEST)
    unbound = _package("ghg.demo.organization-period-model", "1.0.9",
                       "organization_period_inventory", ORGANIZATION_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[organization, unbound],
                                   bound=[organization], title="Only bound counts")
    body = client.get(f"/api/v1/project-templates/{template['id']}/accounting-methods").json()
    refs = [item["base_method_ref"]["version"] for item in body["methods"]
            if item["origin"] == "official_package"]
    assert refs == ["1.0.4"]
    assert body["template"]["unresolved_method_package_refs"] == []


def test_template_read_refuses_registered_method_hash_drift(client, monkeypatch):
    from sqlalchemy import select
    package = _package('ghg.demo.hash-pin', '1.0.0', 'organization_period_inventory', ORGANIZATION_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[package], bound=[package], title='Frozen method hash')
    with client.app.state.container.database.session() as db:
        row = db.scalar(select(MethodPackage).where(MethodPackage.package_id == package['package_id']))
        row.content_sha256 = 'f' * 64
        db.commit()
    response = client.get(f"/api/v1/project-templates/{template['id']}/accounting-methods")
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'TEMPLATE_METHOD_PIN_MISMATCH'


def test_package_without_per_flow_rules_reports_a_named_gap(client, monkeypatch):
    pcf = _package("pcf.demo.native-model-boundary", "1.0.3", "product_carbon_footprint", PCF_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[pcf], bound=[pcf],
                                   title="PCF without flow rules")
    body = client.get(f"/api/v1/project-templates/{template['id']}/accounting-methods").json()
    official = next(item for item in body["methods"] if item["origin"] == "official_package")
    assert official["method_group"] == "product"
    assert official["rule_source"]["kind"] == "none"
    assert official["rule_source"]["declared"] == []
    assert official["rule_source"]["undeclared_port_count"] == 5
    gaps = {gap["code"] for gap in official["coverage_gaps"]}
    assert "NO_PER_FLOW_DECLARATION" in gaps and "PACKAGE_DECLARED_INCOMPLETE_BOUNDARY" in gaps


def test_declaration_absent_from_the_model_is_reported_not_dropped(client, monkeypatch):
    manifest = deepcopy(ORGANIZATION_MANIFEST)
    manifest["classification_rules"]["scope2_purchase_exchange_ids"] = ["ghost::port"]
    ghost = _package("ghg.demo.ghost", "1.0.0", "organization_period_inventory", manifest)
    template = _published_template(client, monkeypatch, packages=[ghost], bound=[ghost],
                                   title="Ghost declaration")
    body = client.get(f"/api/v1/project-templates/{template['id']}/accounting-methods").json()
    official = next(item for item in body["methods"] if item["origin"] == "official_package")
    assert official["rule_source"]["declared_but_absent_from_model"] == ["ghost::port"]
    assert official["rule_source"]["undeclared_port_count"] == 4
    assert "DECLARED_PORT_ABSENT_FROM_MODEL" in {gap["code"] for gap in official["coverage_gaps"]}


def test_unknown_template_is_refused_instead_of_falling_back(client, monkeypatch):
    organization = _package("ghg.demo.organization-period-model", "1.0.4",
                            "organization_period_inventory", ORGANIZATION_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[organization], bound=[organization],
                                   title="Fallback probe")
    missing = client.get(f"/api/v1/project-templates/{uuid4()}/accounting-methods")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "PROJECT_TEMPLATE_NOT_FOUND"
    assert client.get(f"/api/v1/project-templates/{template['id']}/accounting-methods").status_code == 200


def test_data_defined_official_selector_copies_into_the_same_edit_validate_save_contract(client, monkeypatch):
    manifest = deepcopy(ORGANIZATION_MANIFEST)
    manifest["accounting_rule_definition"] = {
        "schema_version": "nebula_one.accounting-rule-definition.v1",
        "selectors": [{"id": "declared-direct", "match": {
            "exchange_ids": ["preparation::waste-out"], "directions": ["output"]},
            "classification": {"boundary_status": "selected", "scope": "scope_1", "location_role": "onsite"}}]}
    package = _package("organization.data-defined", "1.0.0", "organization_period_inventory", manifest)
    template = _published_template(client, monkeypatch, packages=[package], bound=[package], title="Selector copy")
    url = f"/api/v1/project-templates/{template['id']}/accounting-methods"
    official = next(item for item in client.get(url).json()["methods"] if item["origin"] == "official_package")
    assert [item["exchange_id"] for item in official["rule_source"]["declared"]] == ["preparation::waste-out"]
    copied = client.post(url + "/copy", json={"method_key": official["method_key"], "name": "Identity selector"})
    assert copied.status_code == 201, copied.text
    body = copied.json()
    assert body["transcription"]["definition_sha256"] == canonical_json_sha256(manifest["accounting_rule_definition"])
    assert body["transcription"]["rule_sources"] == [{"exchange_id": "preparation::waste-out", "selector_ids": ["declared-direct"]}]
    detail = body["method"]
    version = detail["versions"][0]
    assert len(version["rules"]) == 1
    assert version["rules"][0]["scope"] == "scope_1"
    method_id = detail["method"]["id"]
    assert client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate").json()["valid"]
    changed = deepcopy(version["rules"])
    changed[0]["boundary_status"] = "excluded"
    saved = client.put(f"/api/v1/calculation-methods/{method_id}/versions/1", json={
        "expected_content_sha256": version["content_sha256"], "name": detail["method"]["name"],
        "rules": changed, "reporting_dimensions": []})
    assert saved.status_code == 200, saved.text
    read = client.get(f"/api/v1/calculation-methods/{method_id}").json()
    versions = {item["version"]: item for item in read["versions"]}
    assert versions[1]["rules"][0]["boundary_status"] == "selected"
    assert versions[2]["rules"][0]["boundary_status"] == "excluded"
    assert versions[1]["content_sha256"] != versions[2]["content_sha256"]


def test_a_frozen_working_method_is_listed_once_and_a_new_draft_is_reopenable(client, monkeypatch):
    organization = _package("ghg.demo.organization-period-model", "1.0.4",
                            "organization_period_inventory", ORGANIZATION_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[organization], bound=[organization],
                                   title="Listing probe")
    url = f"/api/v1/project-templates/{template['id']}/accounting-methods"
    before = client.get(url).json()["methods"]
    # The method frozen into the template is reported as the template's own snapshot, never twice.
    assert [item["origin"] for item in before] == ["official_package", "template_user_method"]
    copied = client.post(f"{url}/copy", json={"method_key": before[0]["method_key"],
                                             "name": "组织范围·我的调整"})
    assert copied.status_code == 201, copied.text
    after = client.get(url).json()["methods"]
    draft = next(item for item in after if item["origin"] == "source_user_method")
    assert draft["editable"] is True and draft["actions"] == ["view", "edit", "save_draft", "check"]
    assert draft["method_group"] == "organization" and draft["purpose"] == "organization"
    assert draft["display_name"] == {"zh": "组织范围·我的调整", "en": "组织范围·我的调整"}
    assert draft["user_method"]["method_id"] == copied.json()["method"]["method"]["id"]
    assert draft["user_method"]["version"] == 1 and draft["check"]["status"] == "not_validated"
    assert [item["origin"] for item in after] == ["official_package", "template_user_method",
                                                 "source_user_method"]


def test_copying_an_official_scheme_transcribes_only_what_the_package_declares(client, monkeypatch):
    organization = _package("ghg.demo.organization-period-model", "1.0.4",
                            "organization_period_inventory", ORGANIZATION_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[organization], bound=[organization],
                                   title="Organization copy")
    url = f"/api/v1/project-templates/{template['id']}/accounting-methods"
    response = client.post(f"{url}/copy", json={"method_key": f"official:{organization['package_id']}@1.0.4",
                                                "name": "组织范围·我的调整"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["schema_version"] == "nebula_one.template-method-copy.v1"
    transcription = body["transcription"]
    assert transcription["purpose"] == "organization" and transcription["cbam_boundary_ref"] is None
    assert transcription["base_method_ref"] == {"package_id": organization["package_id"],
                                                "version": "1.0.4",
                                                "content_sha256": organization["content_sha256"]}
    # Two declared ports become two rules; the three undeclared ports get none, so they stay 待确认.
    assert transcription["rule_count"] == 2 and transcription["port_count"] == 5
    assert transcription["undeclared_port_count"] == 3
    assert transcription["declared_exchange_ids"] == ["preparation::ore-in", "product::material-in"]
    rules = body["method"]["versions"][0]["rules"]
    purchased = next(rule for rule in rules if rule["exchange_id"] == "product::material-in")
    assert (purchased["boundary_status"], purchased["scope"], purchased["location_role"]) == (
        "selected", "scope_2", "purchased_energy")
    assert purchased["classification_basis"] == "package"
    assert purchased["base_method_ref"] == f"{organization['package_id']}@1.0.4"
    # The model feeds this input from another modelled process, so the engine's domain is `direct`;
    # the copy states the domain the engine will really use and names the disagreement.
    assert purchased["contribution_target"] == "direct"
    conflict = next(note for note in transcription["notes"]
                    if note["code"] == "PACKAGE_ROLE_CONFLICTS_WITH_MODEL")
    assert conflict["exchange_id"] == "product::material-in"
    pending = next(rule for rule in rules if rule["exchange_id"] == "preparation::ore-in")
    assert pending["boundary_status"] == "pending" and pending["scope"] is None
    assert pending["contribution_target"] == "upstream"
    assert any(note["code"] == "PACKAGE_PENDING_RULE" and note["clause"] == "ST-12"
               for note in transcription["notes"])
    assert body["method"]["method"]["purpose"] == "organization"
    # The copy response carries the ordinary method detail contract, so the editor can open it
    # without a second read shape.
    assert client.get(f"/api/v1/calculation-methods/{body['method']['method']['id']}").json() == body["method"]
    assert client.post(
        f"/api/v1/calculation-methods/{body['method']['method']['id']}/versions/1/validate"
    ).json()["valid"]


def test_copying_a_scheme_without_per_flow_rules_yields_an_empty_named_draft(client, monkeypatch):
    pcf = _package("pcf.demo.native-model-boundary", "1.0.3", "product_carbon_footprint", PCF_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[pcf], bound=[pcf],
                                   title="PCF copy")
    response = client.post(f"/api/v1/project-templates/{template['id']}/accounting-methods/copy",
                           json={"method_key": f"official:{pcf['package_id']}@1.0.3", "name": "产品碳足迹·我的调整"})
    assert response.status_code == 201, response.text
    transcription = response.json()["transcription"]
    assert transcription["purpose"] == "pcf" and transcription["rule_count"] == 0
    assert transcription["undeclared_port_count"] == 5
    assert any(note["code"] == "NO_PER_FLOW_DECLARATION" for note in transcription["notes"])


CBAM_MANIFEST = {
    "template_profile": PROFILE,
    "boundary_schema": {},
    "classification_rules": {
        "direct_emissions": [{"exchange_id": "preparation::waste-out", "flow_uuid": "flow-waste",
                              "direction": "output"}],
        "product": {"exchange_id": "product::product-out"},
        "pending_activity_rules": {"preparation::ore-in": {"clause": "ST-12", "reason": "等待合格因子"}},
    },
    "default_value_rules": {"allowed": False, "basis": "缺证据时拒绝"},
    "validation_rules": {},
    "provenance": {"owner": "Nebula One"},
    "assurance_level": "demonstration",
}


def _freeze_cbam_boundary(client, application_id: str, revision_id: str) -> str:
    revision = client.get(f"/api/v1/system-revisions/{revision_id}").json()
    created = client.post(f"/api/v1/applications/{application_id}/boundaries", json={
        "name": "CBAM 冻结边界", "boundary_type": "cbam_trial",
        "included_process_ids": ["preparation"],
        "geographic_scope": {"graph_sha256": revision["graph_sha256"]}})
    assert created.status_code == 201, created.text
    boundary_id = created.json()["id"]
    assert client.post(f"/api/v1/boundaries/{boundary_id}/freeze").status_code == 200
    return boundary_id


def test_copying_a_cbam_scheme_resolves_the_one_frozen_boundary_and_keeps_the_reference_product_out(
        client, monkeypatch):
    cbam = _package("cbam.demo.trial", "1.2.3", "cbam_trial", CBAM_MANIFEST)
    captured = {}

    def freeze(client_, application_id, revision_id):
        captured["id"] = _freeze_cbam_boundary(client_, application_id, revision_id)

    template = _published_template(client, monkeypatch, packages=[cbam], bound=[cbam],
                                   title="CBAM copy", before_publish=freeze)
    response = client.post(f"/api/v1/project-templates/{template['id']}/accounting-methods/copy",
                           json={"method_key": f"official:{cbam['package_id']}@1.2.3",
                                 "name": "CBAM·我的调整"})
    assert response.status_code == 201, response.text
    body = response.json()
    transcription = body["transcription"]
    assert transcription["purpose"] == "cbam"
    assert transcription["cbam_boundary_ref"] == captured["id"]
    assert body["method"]["versions"][0]["cbam_boundary_ref"] == captured["id"]
    rules = body["method"]["versions"][0]["rules"]
    # The reference product is a project demand, not a flow rule: it must never enter the copy.
    assert transcription["reference_product_exchange_id"] == "product::product-out"
    assert all(rule["exchange_id"] != "product::product-out" for rule in rules)
    assert any(note["code"] == "REFERENCE_PRODUCT_NOT_A_RULE" for note in transcription["notes"])
    direct = next(rule for rule in rules if rule["exchange_id"] == "preparation::waste-out")
    assert (direct["boundary_status"], direct["scope"], direct["location_role"]) == (
        "selected", "scope_1", "onsite")
    assert direct["cbam_relevant"] is True and direct["flow_uuid"] == "flow-waste"
    assert direct["direction"] == "output" and direct["contribution_target"] == "direct"
    assert len(rules) == 2
    assert client.post(
        f"/api/v1/calculation-methods/{body['method']['method']['id']}/versions/1/validate"
    ).json()["valid"]


def test_copying_a_cbam_scheme_without_a_frozen_boundary_is_refused_not_guessed(client, monkeypatch):
    cbam = _package("cbam.demo.trial", "1.2.3", "cbam_trial", CBAM_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[cbam], bound=[cbam],
                                   title="CBAM without boundary")
    url = f"/api/v1/project-templates/{template['id']}/accounting-methods/copy"
    missing = client.post(url, json={"method_key": f"official:{cbam['package_id']}@1.2.3",
                                     "name": "CBAM·无边界"})
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "TEMPLATE_METHOD_COPY_BOUNDARY_MISSING"
    wrong = client.post(url, json={"method_key": f"official:{cbam['package_id']}@1.2.3",
                                   "name": "CBAM·错边界", "cbam_boundary_ref": str(uuid4())})
    assert wrong.status_code == 404
    assert wrong.json()["error"]["code"] == "TEMPLATE_METHOD_COPY_BOUNDARY_NOT_FOUND"
    assert client.get(f"/api/v1/project-templates/{template['id']}/accounting-methods").json()[
        "methods"][-1]["origin"] == "template_user_method"


def test_copying_refuses_an_unbound_scheme_and_a_duplicate_name(client, monkeypatch):
    organization = _package("ghg.demo.organization-period-model", "1.0.4",
                            "organization_period_inventory", ORGANIZATION_MANIFEST)
    other = _package("ghg.demo.organization-period-model", "1.0.9",
                     "organization_period_inventory", ORGANIZATION_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[organization, other],
                                   bound=[organization], title="Copy refusals")
    url = f"/api/v1/project-templates/{template['id']}/accounting-methods/copy"
    unbound = client.post(url, json={"method_key": "official:ghg.demo.organization-period-model@1.0.9",
                                     "name": "未绑定的方案"})
    assert unbound.status_code == 404
    error = unbound.json()["error"]
    assert error["code"] == "TEMPLATE_METHOD_COPY_SOURCE_NOT_FOUND"
    assert error["details"]["bound"] == ["ghg.demo.organization-period-model@1.0.4"]
    unknown = client.post(url, json={"method_key": "official:ghg.demo.ghost@1.0.0", "name": "不存在的方案"})
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "TEMPLATE_METHOD_COPY_SOURCE_NOT_FOUND"
    # A double submit must not create a second copy under the same name on the same revision.
    first = client.post(url, json={"method_key": f"official:{organization['package_id']}@1.0.4",
                                   "name": "组织范围·我的调整"})
    assert first.status_code == 201, first.text
    again = client.post(url, json={"method_key": f"official:{organization['package_id']}@1.0.4",
                                   "name": "组织范围·我的调整"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "CALCULATION_METHOD_NAME_CONFLICT"
    existing = client.post(url, json={"method_key": f"official:{organization['package_id']}@1.0.4",
                                      "name": "模板自带规则"})
    assert existing.status_code == 409
    assert existing.json()["error"]["code"] == "CALCULATION_METHOD_NAME_CONFLICT"


def test_only_a_cbam_copy_may_name_a_frozen_boundary(client, monkeypatch):
    organization = _package("ghg.demo.organization-period-model", "1.0.4",
                            "organization_period_inventory", ORGANIZATION_MANIFEST)
    captured = {}
    template = _published_template(
        client, monkeypatch, packages=[organization], bound=[organization], title="Boundary scope",
        before_publish=lambda client_, application_id, revision_id: captured.setdefault(
            "id", _freeze_cbam_boundary(client_, application_id, revision_id)))
    response = client.post(f"/api/v1/project-templates/{template['id']}/accounting-methods/copy",
                           json={"method_key": f"official:{organization['package_id']}@1.0.4",
                                 "name": "组织范围·带边界", "cbam_boundary_ref": captured["id"]})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "TEMPLATE_METHOD_COPY_BOUNDARY_NOT_ALLOWED"


def _installed_seed_template(client, *, packages: list[dict]) -> dict:
    """Install a real seed template row, so the workspace reads it through the seed source path."""
    source = _create_application(client, "cbam")
    attached = _attach_model(client, source["id"])
    _freeze_cbam_boundary(client, source["id"], attached["upstream_receipt"]["base_revision_id"])
    container = client.app.state.container
    with container.database.session() as db:
        application = db.get(Application, source["id"])
        application.context = {**application.context, "method_package_refs": [
            f"{item['package_id']}@{item['version']}" for item in packages]}
        for item in packages:
            db.add(MethodPackage(package_id=item["package_id"], version=item["version"],
                                 package_kind=item["package_kind"], jurisdiction="EU",
                                 manifest=deepcopy(item["manifest"]),
                                 content_sha256=item["content_sha256"], status="registered"))
        db.add(SeedInstallation(id="steel-install", seed_id="steel", seed_version="1.1.0",
                                install_key="a" * 64, bundle_content_sha256="b" * 64,
                                engine_base_url=container.client.base_url, engine_db_digest="c" * 64,
                                engine_openapi_version="3.1.0", status="ready",
                                application_id=source["id"], system_model_id=attached["id"]))
        db.commit()
    return next(item for item in client.get("/api/v1/project-templates").json()["items"]
                if item["seed_id"] == "steel")


def test_an_installed_seed_template_lists_its_own_schemes_and_copies_one(client):
    organization = _package("ghg.demo.organization-period-model", "1.0.4",
                            "organization_period_inventory", ORGANIZATION_MANIFEST)
    template = _installed_seed_template(client, packages=[organization])
    response = client.get(f"/api/v1/project-templates/{template['id']}/accounting-methods?lang=zh")
    assert response.status_code == 200, response.text
    described = response.json()["template"]
    assert described["kind"] == "seed" and described["official"] is True
    assert described["editable"] is False
    for key in ("id", "title", "version", "template_sha256", "source_application_id",
                "source_model_id", "source_revision_id", "installed_application_id"):
        assert described[key] == template[key], key
    # The bundle identity is recorded only on the installation row, so it is read from there.
    assert described["seed"] == {"seed_id": "steel", "seed_version": "1.1.0",
                                 "bundle_content_sha256": "b" * 64}
    assert described["method_package_refs"] == [f"{organization['package_id']}@1.0.4"]
    assert described["unresolved_method_package_refs"] == []
    assert described["model"]["graph_basis"] == "source_revision"
    methods = response.json()["methods"]
    official = next(item for item in methods if item["origin"] == "official_package")
    assert official["rule_source"]["declared_count"] == 2
    assert official["rule_source"]["port_count"] == described["model"]["port_count"]
    copied = client.post(f"/api/v1/project-templates/{template['id']}/accounting-methods/copy",
                         json={"method_key": official["method_key"], "name": "组织范围·seed 复制"})
    assert copied.status_code == 201, copied.text
    method = copied.json()["method"]["method"]
    assert method["model_revision_id"] == described["source_revision_id"]
    assert len(copied.json()["method"]["versions"][0]["rules"]) == 2
    # The copy is a working method on the seed's own source, listed next to the official scheme.
    listed = client.get(f"/api/v1/project-templates/{template['id']}/accounting-methods").json()
    assert {item["origin"] for item in listed["methods"]} == {"official_package", "source_user_method"}
    assert next(item for item in listed["methods"]
                if item["origin"] == "source_user_method")["user_method"]["method_id"] == method["id"]



STEEL_PROFILE = {"id": "steel-bf-bof-inventory", "version": "1.1.4",
                 "content_sha256": "70a62e4442d8fa127d25fce2b19c1110ec6bd82afaa47fa2df6b5ca93caa8829"}


def _steel_methods():
    """The four official entries a fresh steel library binds, plus a CBAM copy and a custom scheme."""
    def official(ref, group):
        package_id, version = ref.split("@")
        return {"method_key": f"official:{ref}", "origin": "official_package", "method_group": group,
                "base_method_ref": {"package_id": package_id, "version": version, "content_sha256": "0" * 64}}
    return [
        official("pcf.iron-steel.ef31-model@1.0.0", "product"),
        official("ghg.iron-steel.organization-period-model@1.0.6", "organization"),
        official("nebula.organization-lifecycle-carbon.steel-model@1.0.11", "organization"),
        official("cbam.eu.iron-steel.bf-bof-partial-review@1.0.7", "cbam"),
        {"method_key": "user:cbam-copy@2", "origin": "template_user_method", "method_group": "cbam"},
        {"method_key": "source:custom@1", "origin": "source_user_method", "method_group": "user"},
    ]


def test_task_view_collapses_internal_packages_into_three_reader_tasks():
    """F1: the two organization packages become one scope task, not two side-by-side cards."""
    service = TemplateAccountingMethodsService(None)
    # An older install carries no task declaration; it re-resolves from the structural profile so it
    # still gets the task view as long as the current library covers the same exact packages.
    declaration = service._task_declaration(
        {"accounting_library": {"version": "1.1.6", "tasks": None}, "template_profile": STEEL_PROFILE})
    assert [task["role"] for task in declaration] == ["complete_model", "cbam", "scope_classification"]
    tasks, other = service._task_view(_steel_methods(), declaration)
    by_role = {task["role"]: task for task in tasks}
    assert [task["role"] for task in tasks] == ["complete_model", "cbam", "scope_classification"]
    # The scope task names the lifecycle preset first and keeps the GHG period package as another 口径
    # of the SAME task, so the workspace shows one row instead of two organization cards.
    assert by_role["scope_classification"]["preset_keys"] == [
        "official:nebula.organization-lifecycle-carbon.steel-model@1.0.11",
        "official:ghg.iron-steel.organization-period-model@1.0.6"]
    assert by_role["scope_classification"]["default_ref"] == "nebula.organization-lifecycle-carbon.steel-model@1.0.11"
    assert by_role["complete_model"]["preset_keys"] == ["official:pcf.iron-steel.ef31-model@1.0.0"]
    assert by_role["cbam"]["preset_keys"] == ["official:cbam.eu.iron-steel.bf-bof-partial-review@1.0.7"]
    # A user copy joins its own task's selector instead of standing beside the official card.
    assert by_role["cbam"]["user_scheme_keys"] == ["user:cbam-copy@2"]
    assert by_role["complete_model"]["user_scheme_keys"] == []
    # A purely custom scheme no task owns is still surfaced, never hidden.
    assert other == ["source:custom@1"]


def test_bound_legacy_packages_remain_readable_without_becoming_task_choices():
    service = TemplateAccountingMethodsService(None)
    methods = _steel_methods()
    legacy = dict(methods[3], method_key="official:legacy@1",
                  base_method_ref={"package_id": "legacy", "version": "1"})
    methods.append(legacy)
    tasks, other = service._task_view(methods, [{"role": "cbam",
        "default_ref": "cbam.eu.iron-steel.bf-bof-partial-review@1.0.7",
        "refs": ["cbam.eu.iron-steel.bf-bof-partial-review@1.0.7"]}])
    assert tasks[0]["preset_keys"] == [methods[3]["method_key"]]
    assert legacy in methods
    assert legacy["method_key"] not in other


def test_task_view_is_absent_without_a_task_declaring_library():
    """A template whose profile matches no library keeps the flat per-package view (old projects readable)."""
    service = TemplateAccountingMethodsService(None)
    assert service._task_declaration({"template_profile": {"id": "reviewed", "version": "1.0.0",
                                                           "content_sha256": "a" * 64}}) is None
    tasks, other = service._task_view(_steel_methods(), None)
    assert tasks is None and other == []


def test_read_exposes_task_view_keys_for_a_bound_template(client, monkeypatch):
    """The aggregation always carries the task-view keys so the workspace contract is stable."""
    organization = _package("ghg.demo.organization-period-model", "1.0.4",
                            "organization_period_inventory", ORGANIZATION_MANIFEST)
    template = _published_template(client, monkeypatch, packages=[organization], bound=[organization],
                                   title="Task view keys")
    body = client.get(f"/api/v1/project-templates/{template['id']}/accounting-methods").json()
    # The demo profile binds no task-declaring library, so the flat view stays and tasks is null.
    assert body["tasks"] is None
    assert body["other_scheme_keys"] == []
    assert len(body["methods"]) >= 1
