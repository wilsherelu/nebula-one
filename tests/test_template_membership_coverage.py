"""A method package reads Annex I membership by flow identity; a template revision moves flows.

D5 was exactly that drift: the steel template rewrites the two grid-electricity ports onto the
standard TIDAS electricity flow, while the CBAM package kept its membership record pinned to the
seed's legacy flow. The solve refused with an undecided precursor after a full engine run, because
nothing compared the two before the project was built.
"""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from nebula_one.analysis.cbam_trial_v2 import (
    is_multi_process_v2,
    precursor_membership_coverage_gaps,
)
from nebula_one.hashing import canonical_json_sha256
from nebula_one.models import Application, SeedInstallation
from nebula_one.runtime_models import MethodPackage
from nebula_one.runtime_schemas import MethodPackageCreate
from nebula_one.services.project_template_profiles import load_profile
from nebula_one.services.project_template_revision import apply_template_revision
from test_api_flow import _attach_inline_model, _create_application
from test_project_template_revision import fixture as steel_fixture

SEED_ROOT = Path('cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel')
OLD_PACKAGE = SEED_ROOT / 'methods/cbam-eu-iron-steel-bf-bof-direct-trial-1.0.1.json'
CROSSING_INPUT_PORTS = 10
MEMBERSHIP_RECORDS = 8
ELECTRICITY_EXCHANGES = {
    'ore-sintering::grid-electricity-in', 'continuous-casting::grid-electricity-in'}


def _package(path):
    return MethodPackageCreate.model_validate(json.loads(path.read_text(encoding='utf-8')))


def _seed_project_row(client, installation_id):
    container = client.app.state.container
    with container.database.session() as db:
        return db.get(SeedInstallation, installation_id)


def _install_package(client, package: MethodPackageCreate):
    container = client.app.state.container
    ref = f'{package.package_id}@{package.version}'
    with container.database.session() as db:
        application = db.get(Application, _seed_project_row(client, 'steel-install').application_id)
        application.context = {**application.context, 'method_package_refs': [ref]}
        db.add(MethodPackage(**package.model_dump(mode='python'),
                             content_sha256=canonical_json_sha256(package.model_dump(mode='json')),
                             status='registered'))
        db.commit()
    return ref


@pytest.fixture
def template(client):
    """The released steel seed installed over its real model graph and its released method package.

    The shared seed fixture keeps a two-process stand-in graph, in which the identity revision
    cannot even find the ports it rewrites, so it can only exercise the loader's error paths. This
    gate reads the graph a revision produces, so the fixture has to carry that graph.
    """
    application = _create_application(client)
    graph = json.loads((SEED_ROOT / 'model/graph.json').read_text(encoding='utf-8'))['graph']
    model = _attach_inline_model(client, application['id'], graph)
    boundary = client.post(f"/api/v1/applications/{application['id']}/boundaries", json={
        'name': 'Steel classification', 'boundary_type': 'cbam_trial',
        'included_process_ids': ['ore-sintering'],
        'geographic_scope': {'graph_sha256': model['graph_sha256']}}).json()
    assert client.post(f"/api/v1/boundaries/{boundary['id']}/freeze").status_code == 200
    seed = json.loads((SEED_ROOT / 'seed.json').read_text(encoding='utf-8'))
    container = client.app.state.container
    with container.database.session() as db:
        db.add(SeedInstallation(id='steel-install', seed_id=seed['seed_id'],
            seed_version=seed['version'], install_key='a' * 64,
            bundle_content_sha256=seed['content_pins']['bundle_content_sha256'],
            engine_base_url=container.client.base_url, engine_db_digest='c' * 64,
            engine_openapi_version='3.1.0', status='ready',
            application_id=application['id'], system_model_id=model['id']))
        db.commit()
    released = seed['method_package_refs'][0]
    assert _install_package(client, _package(SEED_ROOT / released['path'])) == (
        f"{released['package_id']}@{released['version']}")
    assert canonical_json_sha256(_package(OLD_PACKAGE).model_dump(mode='json')) == released['content_sha256']
    # Reaching the catalog through the unpatched profile is the published chain: template @1.1.2,
    # package @1.1.1, real revision applied.
    return client.get('/api/v1/project-templates').json()['items'][0]


def _revised_graph():
    graph, revision = steel_fixture()
    return apply_template_revision(deepcopy(graph), revision)


def _current_package():
    seed = json.loads((SEED_ROOT / 'seed.json').read_text(encoding='utf-8'))
    installation = SimpleNamespace(
        seed_id=seed['seed_id'], seed_version=seed['version'],
        bundle_content_sha256=seed['content_pins']['bundle_content_sha256'])
    return load_profile(['cases'], installation)[2][0][1]


def test_the_current_package_covers_every_crossing_input_of_the_revised_graph():
    """No gap may be reported, and the ledger has to be what closes it: dropping any single record
    has to re-open one, or the pass would only say the graph was never inspected."""
    manifest = _current_package().manifest
    assert is_multi_process_v2(manifest)
    assert len(manifest['precursor_rules']['membership_evidence']) == MEMBERSHIP_RECORDS
    assert precursor_membership_coverage_gaps(_revised_graph(), manifest) == []
    ports, flows = set(), set()
    for index in range(MEMBERSHIP_RECORDS):
        narrowed = deepcopy(manifest)
        narrowed['precursor_rules']['membership_evidence'].pop(index)
        gaps = precursor_membership_coverage_gaps(_revised_graph(), narrowed)
        ports |= {gap['exchange_id'] for gap in gaps}
        flows |= {gap['flow_uuid'] for gap in gaps}
    assert (len(ports), len(flows)) == (CROSSING_INPUT_PORTS, MEMBERSHIP_RECORDS)


def _revised_electricity_flows():
    revision = json.loads(Path(
        'cases/project-templates/steel-bf-bof-inventory/template.json').read_text(encoding='utf-8'))
    return {entry['after']['flowUuid'] for entry in revision['identity_revision']['content']['replacements']}


def test_a_membership_record_left_on_the_pre_revision_flow_is_reported():
    """The D5 fixture: the same graph, the same eight crossing inputs, the old electricity identity."""
    stale = deepcopy(_current_package().manifest)
    records = stale['precursor_rules']['membership_evidence']
    legacy = next(row for row in records if row['flow_role'] == 'grid_electricity')
    legacy['flow_uuid'] = '222665f3-76a4-5894-a34a-27107e793f08'
    gaps = precursor_membership_coverage_gaps(_revised_graph(), stale)
    assert {gap['exchange_id'] for gap in gaps} == ELECTRICITY_EXCHANGES
    assert {gap['flow_uuid'] for gap in gaps} == _revised_electricity_flows()


def test_the_superseded_package_still_covers_the_graph_it_was_written_for():
    """The refusal must be about the revision, not about the old package being unusable."""
    graph, _ = steel_fixture()
    old = _package(OLD_PACKAGE)
    assert is_multi_process_v2(old.manifest)
    assert precursor_membership_coverage_gaps(graph, old.manifest) == []
    moved = precursor_membership_coverage_gaps(_revised_graph(), old.manifest)
    assert [gap['exchange_id'] for gap in moved] == sorted(ELECTRICITY_EXCHANGES)
    assert {gap['flow_uuid'] for gap in moved} == _revised_electricity_flows()


def test_an_input_the_package_names_no_record_for_is_reported_whatever_flow_it_carries():
    """The refusal is about a missing record, not about electricity: any unnamed crossing input
    raises it, and the reported identity is the one the revised graph actually carries."""
    graph = _revised_graph()
    port = next(port for node in graph['nodes'] if node['id'] == 'blast-furnace'
                for port in node['inputs'] if port['id'] == 'coke-in')
    port['flowUuid'] = '0f7c1c2b-1e3d-5b6a-9c8d-7e2f3a4b5c6d'
    assert precursor_membership_coverage_gaps(graph, _current_package().manifest) == [
        {'exchange_id': 'blast-furnace::coke-in', 'flow_uuid': '0f7c1c2b-1e3d-5b6a-9c8d-7e2f3a4b5c6d'}]


def _profile_for(monkeypatch, replacement_ref: str, package: MethodPackageCreate, *, revised=True):
    profile = json.loads(
        Path('cases/project-templates/steel-bf-bof-inventory/template.json').read_text(encoding='utf-8'))
    if not revised:
        del profile['identity_revision']
    digest = canonical_json_sha256(package.model_dump(mode='json'))
    monkeypatch.setattr('nebula_one.services.seed_projects.load_profile', lambda *args: (
        profile, canonical_json_sha256(profile), [(replacement_ref, package, digest)]))


def test_a_project_template_whose_revision_moves_a_pinned_flow_is_refused(client, template, monkeypatch):
    """The gate has to fire where the revised graph and the effective packages meet, on the route the
    workspace actually calls, rather than only when a unit test happens to invoke it."""
    stale = _package(OLD_PACKAGE)
    ref = f'{stale.package_id}@{stale.version}'
    _profile_for(monkeypatch, ref, stale)
    refused = client.get('/api/v1/project-templates')
    assert refused.status_code == 409
    error = refused.json()['error']
    assert error['code'] == 'SEED_TEMPLATE_PRECURSOR_EVIDENCE_STALE'
    assert error['details']['method_package_ref'] == ref
    assert {gap['exchange_id'] for gap in error['details']['gaps']} == ELECTRICITY_EXCHANGES

    _profile_for(monkeypatch, ref, _current_package())
    items = client.get('/api/v1/project-templates').json()['items']
    assert [item['id'] for item in items] == ['steel-install']


def test_the_refusal_follows_the_revision_not_the_package(client, template, monkeypatch):
    """The same superseded package is accepted when no revision moves a flow out from under it."""
    stale = _package(OLD_PACKAGE)
    _profile_for(monkeypatch, f'{stale.package_id}@{stale.version}', stale, revised=False)
    assert client.get('/api/v1/project-templates').status_code == 200
