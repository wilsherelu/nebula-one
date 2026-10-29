import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from nebula_one.models import SeedInstallation
from nebula_one.release_catalog import ReleaseCatalog
from nebula_one.services.seed_projects import same_editor_source_graph, pin_editor_model_receipt
from test_api_flow import _attach_model, _create_application


@pytest.fixture
def model_graph():
    graph = json.loads(Path('cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/graph.json').read_text(encoding='utf-8'))['graph']
    # Match the shared fake provider's structured functional unit; never used as live evidence.
    graph['nodes'][-1]['outputs'][0]['flowUuid'] = 'flow-product'
    return graph


@pytest.fixture
def template(client):
    app = _create_application(client)
    model = _attach_model(client, app['id'])
    boundary = client.post(f"/api/v1/applications/{app['id']}/boundaries", json={
        'name': 'Steel classification', 'boundary_type': 'cbam_trial',
        'included_process_ids': ['ore-sintering'], 'geographic_scope': {'graph_sha256': model['graph_sha256']},
    }).json()
    assert client.post(f"/api/v1/boundaries/{boundary['id']}/freeze").status_code == 200
    c = client.app.state.container
    with c.database.session() as db:
        db.add(SeedInstallation(id='steel-install', seed_id='steel', seed_version='1.1.0',
            install_key='a'*64, bundle_content_sha256='b'*64, engine_base_url=c.client.base_url,
            engine_db_digest='c'*64, engine_openapi_version='3.1.0', status='ready',
            application_id=app['id'], system_model_id=model['id']))
        db.commit()
    return client.get('/api/v1/project-templates').json()['items'][0]


def create(client, template):
    url = f"/api/v1/project-templates/{template['id']}/projects"
    body = {'name': 'Steel actual inventory', 'project_key': str(uuid4()), 'expected_template_sha256': template['template_sha256']}
    r = client.post(url, json=body)
    assert r.status_code == 200, r.text
    return r.json(), url, body


def test_installed_template_can_finalize_user_rules_without_a_modeling_roundtrip(client, template):
    revision = client.get(f"/api/v1/system-revisions/{template['source_revision_id']}").json()
    method = client.post(f"/api/v1/applications/{template['source_application_id']}/calculation-methods", json={
        "name": "Steel template PCF", "purpose": "pcf", "model_revision_id": template["source_revision_id"],
        "rules": [{"process_instance_id": "ore-sintering", "direction": "emission",
                   "boundary_status": "selected", "location_role": "onsite",
                   "scope": "scope_1", "classification_basis": "user"}]}).json()
    method_id = method["method"]["id"]
    assert client.post(f"/api/v1/calculation-methods/{method_id}/versions/1/validate").json()["valid"]
    from sqlalchemy import select
    from nebula_one.runtime_models import BoundaryDefinition
    with client.app.state.container.database.session() as db:
        boundary = db.scalar(select(BoundaryDefinition).where(
            BoundaryDefinition.application_id == template["source_application_id"]))
        boundary_id = boundary.id
    cbam = client.post(f"/api/v1/applications/{template['source_application_id']}/calculation-methods", json={
        "name": "Steel template CBAM", "purpose": "cbam", "model_revision_id": template["source_revision_id"],
        "cbam_boundary_ref": boundary_id,
        "rules": [{"process_instance_id": "ore-sintering", "direction": "emission", "cbam_relevant": True,
                   "boundary_status": "selected", "location_role": "onsite",
                   "scope": "scope_1", "classification_basis": "user"}]}).json()
    cbam_id = cbam["method"]["id"]
    assert client.post(f"/api/v1/calculation-methods/{cbam_id}/versions/1/validate").json()["valid"]
    payload = {"title": "Steel with own rules", "version": "1.0.0",
        "source_application_id": template["source_application_id"],
        "source_model_id": template["source_model_id"], "source_revision_id": template["source_revision_id"],
        "expected_revision_sha256": revision["content_sha256"], "methods": [],
        "user_methods": [{"method_id": method_id, "version": 1,
                          "content_sha256": method["versions"][0]["content_sha256"]},
                         {"method_id": cbam_id, "version": 1,
                          "content_sha256": cbam["versions"][0]["content_sha256"]}]}
    published = client.post("/api/v1/project-templates/authored", json=payload)
    assert published.status_code == 200, published.text
    target, _, _ = create(client, published.json())
    copies = client.get(f"/api/v1/applications/{target['application_id']}/calculation-methods").json()
    assert len(copies) == 2 and {copy["origin_method_id"] for copy in copies} == {method_id, cbam_id}
    cbam_copy = next(copy for copy in copies if copy["purpose"] == "cbam")
    cbam_version = client.get(f"/api/v1/calculation-methods/{cbam_copy['id']}").json()["versions"][0]
    assert cbam_version["cbam_boundary_ref"] != boundary_id
    with client.app.state.container.database.session() as db:
        target_boundary = db.get(BoundaryDefinition, cbam_version["cbam_boundary_ref"])
        assert target_boundary.application_id == target["application_id"]
    assert client.post(f"/api/v1/calculation-methods/{cbam_copy['id']}/versions/1/validate").json()["valid"]
    assert client.post("/api/v1/project-templates/authored", json={**payload,
        "source_application_id": target["application_id"], "source_model_id": target["system_model_id"],
        "source_revision_id": target["revision_id"]}).status_code == 422


def test_default_backgrounds_never_replace_saved_user_inputs(client, template):
    from nebula_one.services.demo_background_defaults import ensure_demo_backgrounds
    from nebula_one.models import Application, SystemRevision
    created, _, _ = create(client, template)
    c = client.app.state.container
    with c.database.session() as db:
        app = db.get(Application, created['application_id'])
        app.context = {**app.context, 'resource_purpose': 'demo_project'}
        revision = db.get(SystemRevision, created['revision_id'])
        inputs = {'demand_mode': 'explicit', 'demand': [{'amount': 7}], 'project_background_pins': []}
        revision.application_context = {**revision.application_context, 'project_inputs': inputs}
        old_hash = revision.content_sha256
        db.commit()
    assert ensure_demo_backgrounds(c, created, [{'invalid': 'must not be resolved'}]) == {
        'outcome': 'preserved_existing_inputs'}
    with c.database.session() as db:
        revision = db.get(SystemRevision, created['revision_id'])
        assert revision.application_context['project_inputs'] == inputs
        assert revision.content_sha256 == old_hash


def test_editor_source_accepts_only_engine_serialization_changes(model_graph):
    saved = deepcopy(model_graph)
    saved['metadata']['storage_schema_version'] = 'graph_slim_v1'
    for edge in saved['exchanges']:
        edge['sourceHandle'] = f"out:{edge['sourcePortId']}"
        edge['targetHandle'] = f"in:{edge['targetPortId']}"
    assert same_editor_source_graph(model_graph, saved)
    saved['nodes'][0]['inputs'][0]['amount'] += 1
    assert not same_editor_source_graph(model_graph, saved)


def test_editor_receipt_names_new_version_and_preserves_installed_source():
    class Model:
        upstream_receipt = {'endpoint': '/api/projects/p/versions/1', 'base_revision_id': 'r'}

    model = Model()
    editor = {'engine_project_id': 'p', 'engine_version': 2}
    exact = {'source_policy': 'open_mixed', 'allowed_lcia_scope': 'ef31_only',
             'functional_unit': {'display_text': '1 kg steel'}}
    assert pin_editor_model_receipt(model, exact, editor)
    assert model.upstream_receipt['endpoint'] == '/api/projects/p/versions/2'
    assert model.upstream_receipt['template_installed_source']['endpoint'] == '/api/projects/p/versions/1'
    assert not pin_editor_model_receipt(model, exact, editor)


def test_pinned_template_instances_and_identity_refusals(client, template):
    assert template['source_application_id']
    assert template['source_model_id']
    source = client.get(f"/api/v1/applications/{template['source_application_id']}/system-models").json()
    assert any(model['id'] == template['source_model_id'] for model in source)
    first, url, body = create(client, template)
    second, _, _ = create(client, template)
    assert first['application_id'] != second['application_id']
    assert client.post(url, json=body).json() == first
    assert client.post(url, json={**body, 'name': 'Changed request'}).status_code == 409
    assert client.post(url, json={**body, 'expected_template_sha256': '0'*64}).status_code == 409
    path = f"/api/v1/applications/{first['application_id']}/workspace/{first['revision_id']}"
    workspace = client.get(path).json()
    assert workspace['inventory_editing'] and len(workspace['fields']) == 28
    assert len({f['process_id'] for f in workspace['fields']}) == 5
    assert client.get(f"/api/v1/applications/{second['application_id']}/workspace/{first['revision_id']}").status_code == 409


def test_release_catalog_filters_existing_installations_and_direct_create(client, template, tmp_path):
    container = client.app.state.container
    with container.database.session() as db:
        db.add(SeedInstallation(id='other-install', seed_id='other-sector', seed_version='1.0.0',
            install_key='d'*64, bundle_content_sha256='e'*64, engine_base_url=container.client.base_url,
            engine_db_digest='f'*64, engine_openapi_version='3.1.0', status='ready',
            application_id=template['source_application_id'], system_model_id=template['source_model_id']))
        db.commit()
    manifest = tmp_path / 'release.json'
    manifest.write_text(json.dumps({'schema_version': 'nebula_one.release_catalog.v1',
        'seed_templates': [{'seed_id': 'steel', 'version': '1.1.0',
                            'bundle_content_sha256': 'b'*64, 'title': '高炉—转炉钢铁'}],
        'casepacks': []}), encoding='utf-8')
    container.release_catalog = ReleaseCatalog(str(manifest))
    before = client.get('/api/v1/applications').json()
    items = client.get('/api/v1/project-templates').json()['items']
    assert [item['id'] for item in items] == ['steel-install']
    assert items[0]['title'] == '高炉—转炉钢铁'
    assert items[0]['installed_application_id'] == template['source_application_id']
    assert client.post('/api/v1/project-templates/other-install/projects', json={
        'name': 'other', 'project_key': str(uuid4()), 'expected_template_sha256': '0'*64,
    }).status_code == 404
    assert client.get('/api/v1/applications').json() == before


def test_template_edit_handoff_targets_its_exact_source_project_version(client, template):
    container = client.app.state.container
    container.settings = replace(container.settings, nebula_lca_editor_url='http://editor.test')
    source = client.get(f"/api/v1/system-models/{template['source_model_id']}").json()
    before = client.get('/api/v1/applications').json()
    payload = {'name': 'Steel model revision', 'base_model_id': template['source_model_id']}
    if template['source_revision_id']:
        payload['base_revision_id'] = template['source_revision_id']
    response = client.post('/api/v1/modeling/handoffs', json=payload)
    assert response.status_code == 201, response.text
    target = urlsplit(response.json()['editor_url'])
    assert target.path == f"/projects/{source['upstream_project_id']}"
    assert parse_qs(target.query)['version'] == [str(source['upstream_version'])]
    assert client.get('/api/v1/applications').json() == before
    assert client.get('/api/v1/project-templates').json()['items'][0]['template_sha256'] == template['template_sha256']


def test_quantity_edits_keep_structure_history_and_boundary_pins(client, template):
    project, _, _ = create(client, template)
    aid, rid = project['application_id'], project['revision_id']
    path = f'/api/v1/applications/{aid}/workspace'
    original = client.get(f'{path}/{rid}').json()
    graph = client.get(f'/api/v1/system-revisions/{rid}').json()['graph_snapshot']
    values = {f['key']: f['value'] for f in original['fields']}
    shared = next(f['key'] for f in original['fields'] if f['linked'])
    values[shared] *= 1.1
    body = dict(revision_id=rid, expected_content_sha256=original['content_sha256'], values=values, amounts=[1000], source='Measured ledger')
    response = client.post(f'{path}/inputs', json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert [f['value'] for f in saved['fields'] if f['key'] == shared] == [values[shared]]*2
    assert client.get(f'{path}/{rid}').json() == original
    assert client.post(f'{path}/inputs', json=body).json() == saved
    revision = client.get(f"/api/v1/system-revisions/{saved['revision_id']}").json()
    changed = deepcopy(revision['graph_snapshot'])
    # Only amounts may differ; process/flow identities, units, modes and topology stay exact.
    for before, after in zip(graph['nodes'], changed['nodes']):
        for group in ('inputs', 'outputs', 'emissions'):
            for bp, ap in zip(before.get(group, []), after.get(group, [])):
                ap['amount'] = bp['amount']
    for before, after in zip(graph['exchanges'], changed['exchanges']):
        for key in ('amount', 'providerAmount', 'consumerAmount'):
            after[key] = before[key]
    assert changed == graph
    boundaries = client.get(f'/api/v1/applications/{aid}/boundaries').json()
    assert len(boundaries) == 2
    assert {b['geographic_scope']['graph_sha256'] for b in boundaries} == {revision['graph_sha256'], template_graph_hash(client, rid)}
    for changes in ({'values': {**values, 'invented-flow': 1}}, {'expected_content_sha256': '0'*64}, {'source': ' '}):
        assert client.post(f'{path}/inputs', json={**body, **changes}).status_code in (409, 422)
    # Saving unchanged values from successive versions must not recursively clone boundaries.
    for _ in range(2):
        body.update(revision_id=saved['revision_id'], expected_content_sha256=saved['content_sha256'])
        saved = client.post(f'{path}/inputs', json=body).json()
    assert len(client.get(f'/api/v1/applications/{aid}/boundaries').json()) == 4


def test_batch_demand_follows_final_product_output_and_explicit_override_is_separate(client, template):
    project, _, _ = create(client, template)
    path = f"/api/v1/applications/{project['application_id']}/workspace"
    initial = client.get(f"{path}/{project['revision_id']}").json()
    final = [field for field in initial['fields'] if field['group'] == 'outputs'
             and field['reference_product']
             and field['flow_uuid'] == initial['demand'][0]['reference_flow_uuid']]
    assert len(final) == 1
    assert initial['demand'][0]['amount'] == final[0]['value'] == 1000
    assert initial['demand_mode'] == 'reference_output'
    values = {field['key']: field['value'] for field in initial['fields']}
    values[final[0]['key']] = 1500
    body = dict(revision_id=initial['revision_id'], expected_content_sha256=initial['content_sha256'],
                amounts=[1], demand_mode='reference_output', values=values, source='Batch ledger')
    response = client.post(f'{path}/inputs', json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['demand'][0]['amount'] == 1500
    assert next(field for field in saved['fields'] if field['key'] == final[0]['key'])['value'] == 1500
    assert client.get(f"{path}/{saved['revision_id']}").json()['demand'][0]['amount'] == 1500
    override = client.post(f'{path}/inputs', json={**body, 'demand_mode': 'explicit',
        'revision_id': saved['revision_id'], 'expected_content_sha256': saved['content_sha256']})
    assert override.status_code == 200, override.text
    assert override.json()['demand'][0]['amount'] == 1


def template_graph_hash(client, rid):
    return client.get(f'/api/v1/system-revisions/{rid}').json()['graph_sha256']


def test_identity_upgrade_creates_independent_revision_and_preserves_existing_project(client, template, monkeypatch):
    from test_project_template_revision import fixture
    from nebula_one.hashing import canonical_json_sha256
    from nebula_one.models import Application, SystemModel
    old, _, _ = create(client, template)
    old_path = f"/api/v1/applications/{old['application_id']}/workspace/{old['revision_id']}"
    old_workspace = client.get(old_path).json()
    _, upgrade = fixture()
    profile = {'id': 'test-upgrade', 'version': '1.1.0', 'title': 'Reviewed steel', 'identity_revision': upgrade}
    monkeypatch.setattr('nebula_one.services.seed_projects.load_profile', lambda *args: (profile, canonical_json_sha256(profile), []))
    new_template = client.get('/api/v1/project-templates').json()['items'][0]
    assert new_template['template_sha256'] != template['template_sha256']
    project, url, body = create(client, new_template)
    assert client.post(url, json=body).json() == project
    revision = client.get(f"/api/v1/system-revisions/{project['revision_id']}").json()
    with client.app.state.container.database.session() as db:
        model = db.get(SystemModel, project['system_model_id'])
        base = deepcopy(model.graph_snapshot)
    graph = revision['graph_snapshot']
    for replacement in upgrade['content']['replacements']:
        node_id, port_id = replacement['exchange_id'].split('::')
        for document, expected in ((base, replacement['before']), (graph, replacement['after'])):
            port = next(p for n in document['nodes'] if n['id'] == node_id for p in n['inputs'] if p['id'] == port_id)
            assert all(port[k] == value for k, value in expected.items())
    assert client.get(old_path).json() == old_workspace
    boundary = client.get(f"/api/v1/applications/{project['application_id']}/boundaries").json()[0]
    assert boundary['geographic_scope']['graph_sha256'] == revision['graph_sha256']
    path = f"/api/v1/applications/{project['application_id']}/workspace"
    workspace = client.get(f"{path}/{project['revision_id']}").json()
    labels = {r['exchange_id']: r['name_zh'] for r in upgrade['content']['display_metadata']}
    english = {r['exchange_id']: r['name_en'] for r in upgrade['content']['display_metadata']}
    assert len(labels) == 2 and set(labels.values()) != set(english.values())
    projected_fields = [f for f in workspace['fields'] if f['key'] in labels]
    projected_ports = [p for p in workspace['background_ports'] if p['exchange_id'] in labels]
    assert len(projected_fields) == len(projected_ports) == 2
    assert [f['label'] for f in projected_fields] == [labels[f['key']] for f in projected_fields]
    assert [p['label'] for p in projected_ports] == [labels[p['exchange_id']] for p in projected_ports]
    response = client.post(f'{path}/inputs', json=dict(revision_id=project['revision_id'],
        expected_content_sha256=workspace['content_sha256'], values={f['key']: f['value'] for f in workspace['fields']},
        amounts=[1000], source='Synthetic revision test'))
    assert response.status_code == 200, response.text
    saved = response.json()
    assert client.get(f"{path}/{saved['revision_id']}").json() == saved
    assert client.get(f"/api/v1/system-revisions/{saved['revision_id']}").json()['graph_snapshot'] == graph
    # A project stored before the Chinese projection keeps the label its own template version pinned.
    with client.app.state.container.database.session() as db:
        stored = db.get(Application, project['application_id'])
        legacy_context = deepcopy(stored.context)
        for row in legacy_context['seed_template']['identity_revision']['content']['display_metadata']:
            del row['name_zh']
        stored.context = legacy_context
        db.commit()
    legacy = client.get(f"{path}/{saved['revision_id']}").json()
    legacy_fields = [f for f in legacy['fields'] if f['key'] in english]
    legacy_ports = [p for p in legacy['background_ports'] if p['exchange_id'] in english]
    assert len(legacy_fields) == len(legacy_ports) == 2
    assert [f['label'] for f in legacy_fields] == [english[f['key']] for f in legacy_fields]
    assert [p['label'] for p in legacy_ports] == [english[p['exchange_id']] for p in legacy_ports]


def test_the_reader_language_selects_the_pinned_projection_without_rewriting_history(client, template, monkeypatch):
    # Read and write the same data version under two languages: only the read-side projection changes,
    # the stored revision content and its hash stay identical, and nothing is translated locally.
    from test_project_template_revision import fixture
    from nebula_one.hashing import canonical_json_sha256
    old, _, _ = create(client, template)
    _, upgrade = fixture()
    profile = {'id': 'test-language', 'version': '1.1.0', 'title': 'Reviewed steel', 'identity_revision': upgrade}
    monkeypatch.setattr('nebula_one.services.seed_projects.load_profile', lambda *args: (profile, canonical_json_sha256(profile), []))
    new_template = client.get('/api/v1/project-templates').json()['items'][0]
    project, _, _ = create(client, new_template)
    path = f"/api/v1/applications/{project['application_id']}/workspace"
    zh_labels = {r['exchange_id']: r['name_zh'] for r in upgrade['content']['display_metadata']}
    en_labels = {r['exchange_id']: r['name_en'] for r in upgrade['content']['display_metadata']}
    assert set(zh_labels.values()) != set(en_labels.values())

    chinese = client.get(f"{path}/{project['revision_id']}", params={'lang': 'zh'}).json()
    english = client.get(f"{path}/{project['revision_id']}", params={'lang': 'en'}).json()
    # A template that declares no short display names keeps its one canonical title in every language.
    assert chinese['template_title'] == english['template_title'] == 'Reviewed steel'
    # A background port is named by the projection in the requested language, chosen only from the pinned data.
    assert {p['exchange_id']: p['label'] for p in chinese['background_ports'] if p['exchange_id'] in zh_labels} == zh_labels
    assert {p['exchange_id']: p['label'] for p in english['background_ports'] if p['exchange_id'] in en_labels} == en_labels
    # The two languages describe the same version, so the content hash they are pinned to is identical.
    assert english['content_sha256'] == chinese['content_sha256']

    saved = client.post(f'{path}/inputs', params={'lang': 'en'}, json=dict(
        revision_id=project['revision_id'], expected_content_sha256=english['content_sha256'],
        values={f['key']: f['value'] for f in english['fields']}, amounts=[1000], source='Language test')).json()
    # The response after a save is projected in the requested language too, and it is a new version.
    assert {p['exchange_id']: p['label'] for p in saved['background_ports'] if p['exchange_id'] in en_labels} == en_labels
    assert saved['revision_id'] != project['revision_id']


def test_mapped_pins_persist_preserve_and_remove_by_revision(client, template, monkeypatch):
    from test_project_mapped_background import receipt_fixture
    from nebula_one.services.project_mapped_background import ProjectMappedBackgroundService
    _, pin, _ = receipt_fixture()
    calls = []
    monkeypatch.setattr(ProjectMappedBackgroundService, 'validate', lambda self, graph, pins: calls.append(pins))
    project, _, _ = create(client, template)
    path = f"/api/v1/applications/{project['application_id']}/workspace"
    original = client.get(f"{path}/{project['revision_id']}").json()
    def save(previous, **extra):
        response = client.post(f'{path}/inputs', json=dict(revision_id=previous['revision_id'],
            expected_content_sha256=previous['content_sha256'], amounts=[1000],
            values={f['key']: f['value'] for f in previous['fields']}, source='Synthetic fixture', **extra))
        assert response.status_code == 200, response.text
        return response.json()
    bound = save(original, mapped_background_process_pins=[pin.model_dump(mode='json')])
    preserved = save(bound)
    removed = save(preserved, mapped_background_process_pins=[])
    assert bound['mapped_background_process_pins'] == preserved['mapped_background_process_pins'] == [pin.model_dump(mode='json')]
    assert removed['mapped_background_process_pins'] == []
    # The native climate task is offered exactly while the data version has one shared mapped
    # provider; without one there is nothing to answer for, and the template must not imply there is.
    assert original['native_climate'] is None
    assert bound['native_climate'] == preserved['native_climate'] == {'available': True, 'provider_count': 1}
    assert removed['native_climate'] is None
    assert client.get(f"{path}/{bound['revision_id']}").json() == bound
    assert calls[-3:] == [[pin], [pin], []]


UNRESOLVED_FLOW = 'b32061b1-8d24-4663-b10d-0a1c705f2937'


def _engine_mapping_refusal():
    from nebula_one.errors import UpstreamError
    detail = {'code': 'MAPPED_BACKGROUND_ELEMENTARY_MAPPING_NOT_FOUND',
              'message': 'elementary flow has no accepted identity mapping',
              'details': {'ecoinvent_flow_uuid': UNRESOLVED_FLOW}}
    return UpstreamError(code='NEBULA_LCA_REJECTED', status_code=422,
        message='MAPPED_BACKGROUND_ELEMENTARY_MAPPING_NOT_FOUND: elementary flow has no accepted identity mapping',
        details={'method': 'POST', 'path': '/api/provider/v1/solve', 'upstream_status': 422, 'upstream_detail': detail})


def test_unverified_background_mapping_refusal_keeps_inputs_and_produces_no_snapshot(client, template, monkeypatch):
    from test_project_mapped_background import receipt_fixture
    from nebula_one.services.project_mapped_background import ProjectMappedBackgroundService
    _, pin, _ = receipt_fixture()
    monkeypatch.setattr(ProjectMappedBackgroundService, 'validate', lambda self, graph, pins: None)
    project, _, _ = create(client, template)
    path = f"/api/v1/applications/{project['application_id']}/workspace"
    original = client.get(f"{path}/{project['revision_id']}").json()
    response = client.post(f'{path}/inputs', json=dict(revision_id=original['revision_id'],
        expected_content_sha256=original['content_sha256'], amounts=[1000],
        values={f['key']: f['value'] for f in original['fields']}, source='Synthetic fixture',
        mapped_background_process_pins=[pin.model_dump(mode='json')]))
    assert response.status_code == 200, response.text
    saved = response.json()
    engine = client.app.state.container.client
    def refuse(payload):
        assert payload['mapped_background_process_pins'] == [pin.model_dump(mode='json')]
        raise _engine_mapping_refusal()
    monkeypatch.setattr(engine, 'solve_provider', refuse)
    solve = f"/api/v1/applications/{project['application_id']}/system-revisions/{saved['revision_id']}/solve"
    body = {'demand': saved['demand'], 'mapped_background_process_pins': [pin.model_dump(mode='json')]}
    refused = client.post(solve, json=body)
    assert refused.status_code == 422, refused.text
    error = refused.json()['error']
    assert error['code'] == 'PROJECT_BACKGROUND_ELEMENTARY_MAPPING_UNVERIFIED'
    assert '背景排放流映射待核实' in error['message']
    gap = error['details']['dependency_gap']
    assert gap['schema_version'] == 'nebula_one.dependency-gap.v1'
    assert gap['affects']['results_produced'] is False
    assert gap['evidence']['unresolved_elementary_flows'] == {'ecoinvent_flow_uuid': UNRESOLVED_FLOW}
    assert error['details']['upstream_detail']['code'] == 'MAPPED_BACKGROUND_ELEMENTARY_MAPPING_NOT_FOUND'
    # The operator-facing message stays free of the unresolved identity; it lives in the evidence only.
    assert UNRESOLVED_FLOW not in error['message']
    assert UNRESOLVED_FLOW not in gap['what_missing']['required_identity']
    # A refusal is not a result: nothing is frozen, and the retry of the same run replays the same gap.
    assert client.get(f"/api/v1/applications/{project['application_id']}/solved-system-snapshots").json() == []
    replay = client.post(solve, json=body)
    assert replay.status_code == 422
    assert replay.json()['error']['code'] == 'PROJECT_BACKGROUND_ELEMENTARY_MAPPING_UNVERIFIED'
    assert replay.json()['error']['details']['dependency_gap']['evidence'] == gap['evidence']
    reread = client.get(f"{path}/{saved['revision_id']}").json()
    assert reread == saved
    assert reread['mapped_background_process_pins'] == [pin.model_dump(mode='json')]
    assert reread['saved'] and reread['source'] == 'Synthetic fixture'
    assert all(f['value'] == original_field['value']
               for f, original_field in zip(reread['fields'], original['fields']))


def test_unrelated_engine_refusal_is_not_relabelled_as_a_mapping_gap(client, template, monkeypatch):
    from test_project_mapped_background import receipt_fixture
    from nebula_one.errors import UpstreamError
    from nebula_one.services.project_mapped_background import ProjectMappedBackgroundService
    _, pin, _ = receipt_fixture()
    monkeypatch.setattr(ProjectMappedBackgroundService, 'validate', lambda self, graph, pins: None)
    project, _, _ = create(client, template)
    path = f"/api/v1/applications/{project['application_id']}/workspace"
    original = client.get(f"{path}/{project['revision_id']}").json()
    saved = client.post(f'{path}/inputs', json=dict(revision_id=original['revision_id'],
        expected_content_sha256=original['content_sha256'], amounts=[1000],
        values={f['key']: f['value'] for f in original['fields']}, source='Synthetic fixture',
        mapped_background_process_pins=[pin.model_dump(mode='json')])).json()
    def refuse(payload):
        raise UpstreamError(code='NEBULA_LCA_REJECTED', status_code=422, message='SOLVE_DEMAND_INVALID: bad demand',
            details={'method': 'POST', 'path': '/api/provider/v1/solve', 'upstream_status': 422,
                     'upstream_detail': {'code': 'SOLVE_DEMAND_INVALID', 'message': 'bad demand', 'details': {}}})
    monkeypatch.setattr(client.app.state.container.client, 'solve_provider', refuse)
    response = client.post(f"/api/v1/applications/{project['application_id']}/system-revisions/{saved['revision_id']}/solve",
        json={'demand': saved['demand'], 'mapped_background_process_pins': [pin.model_dump(mode='json')]})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'NEBULA_LCA_REJECTED'
    assert 'dependency_gap' not in response.json()['error']['details']
    assert client.get(f"/api/v1/applications/{project['application_id']}/solved-system-snapshots").json() == []


def test_two_electricity_inputs_share_one_provider_process_without_rewriting_history(client, template, monkeypatch):
    from test_project_mapped_background import receipt_fixture
    from nebula_one.services.project_mapped_background import ProjectMappedBackgroundService
    _, pin, _ = receipt_fixture()
    monkeypatch.setattr(ProjectMappedBackgroundService, 'validate', lambda self, graph, pins: None)
    project, _, _ = create(client, template)
    path = f'/api/v1/applications/{project["application_id"]}/workspace'
    first = client.get(f"{path}/{project['revision_id']}").json()
    ports = sorted(p['exchange_id'] for p in first['background_ports'] if p['exchange_id'].endswith('::grid-electricity-in'))
    assert ports == ['continuous-casting::grid-electricity-in', 'ore-sintering::grid-electricity-in']
    shared = [pin.model_copy(update={'consumer_exchange_id': exchange_id}) for exchange_id in ports]

    def save(previous, **extra):
        response = client.post(f'{path}/inputs', json=dict(revision_id=previous['revision_id'],
            expected_content_sha256=previous['content_sha256'], amounts=[1000],
            values={f['key']: f['value'] for f in previous['fields']}, source='Synthetic fixture', **extra))
        assert response.status_code == 200, response.text
        return response.json()

    both = save(first, mapped_background_process_pins=[p.model_dump(mode='json') for p in shared])
    assert [p['consumer_exchange_id'] for p in both['mapped_background_process_pins']] == ports
    assert {p['process_uuid'] for p in both['mapped_background_process_pins']} == {pin.process_uuid}
    removed = save(both, mapped_background_process_pins=[shared[1].model_dump(mode='json')])
    assert [p['consumer_exchange_id'] for p in removed['mapped_background_process_pins']] == [ports[1]]
    assert client.get(f"{path}/{both['revision_id']}").json() == both
    duplicate = client.post(f'{path}/inputs', json=dict(revision_id=both['revision_id'],
        expected_content_sha256=both['content_sha256'], amounts=[1000],
        values={f['key']: f['value'] for f in both['fields']}, source='Synthetic fixture',
        mapped_background_process_pins=[shared[1].model_dump(mode='json')]*2))
    assert duplicate.status_code == 422
    assert duplicate.json()['error']['code'] == 'PROJECT_BACKGROUND_DUPLICATE'


def _release_example(client):
    from nebula_one.services.seed_projects import SeedProjectService

    return SeedProjectService(client.app.state.container)


def test_the_release_example_project_is_created_once_and_shows_as_a_project(client, template):
    service = _release_example(client)
    names = {'zh': '钢铁示例', 'en': 'Steel example'}

    outcome, created = service.ensure_demo_project('steel', '1.1.0', 'b' * 64, 'steel-bf-bof-2026', names)
    assert outcome == 'executed'
    replay, again = service.ensure_demo_project('steel', '1.1.0', 'b' * 64, 'steel-bf-bof-2026', names)
    assert replay == 'replayed'
    assert again['application_id'] == created['application_id']

    listed = client.get('/api/v1/applications').json()
    assert [item['id'] for item in listed] == [created['application_id']]
    assert listed[0]['context']['resource_purpose'] == 'demo_project'
    assert listed[0]['context']['display_name'] == names
    assert listed[0]['name'] == '钢铁示例'
    workspace = client.get(
        f"/api/v1/applications/{created['application_id']}/workspace/{created['revision_id']}")
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()['template_title'] == template['title']

    renamed = {'zh': '新的钢铁示例标题', 'en': 'Renamed steel example'}
    replay, preserved = service.ensure_demo_project('steel', '1.1.0', 'b' * 64, 'steel-bf-bof-2026', renamed)
    assert replay == 'replayed'
    assert preserved == again
    assert client.get('/api/v1/applications').json() == listed


def test_the_release_example_refuses_a_seed_that_is_not_the_pinned_one(client, template):
    service = _release_example(client)
    with pytest.raises(Exception) as refused:
        service.ensure_demo_project('steel', '1.1.0', 'e' * 64, 'steel-bf-bof-2026',
                                    {'zh': '钢铁示例', 'en': 'Steel example'})
    assert refused.value.code == 'SEED_TEMPLATE_SOURCE_UNAVAILABLE'
    assert client.get('/api/v1/applications').json() == []
