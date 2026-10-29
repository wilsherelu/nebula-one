from copy import deepcopy
import json

import pytest

from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.services.template_method_libraries import load_template_method_library, LIBRARY_ROOT
from nebula_one.services.official_product_method import _bind
from types import SimpleNamespace


def shipped():
    return json.loads((LIBRARY_ROOT / 'steel-1.1.9.json').read_text(encoding='utf-8'))


def test_library_has_exact_existing_method_pins_and_distinct_structural_revision():
    declaration = shipped()
    identity, packages = load_template_method_library(declaration['template_profile'])
    assert identity['version'] == '1.1.9'
    assert identity['template_profile']['version'] == '1.1.4'
    assert identity['content_sha256'] == canonical_json_sha256(declaration)
    assert {p.package_kind for p, _ in packages} == {'product_carbon_footprint', 'cbam_partial_review',
        'organization_period_inventory', 'organization_lifecycle_carbon'}
    assert {digest for _, digest in packages} == {pin['content_sha256'] for pin in identity['methods']}
    # The reader-facing task grouping is declared by the library, one default preset per task; the
    # two organization packages collapse into a single scope-classification task.
    assert [task['role'] for task in identity['tasks']] == [
        'complete_model', 'cbam', 'scope_classification']
    scope_task = next(task for task in identity['tasks'] if task['role'] == 'scope_classification')
    assert scope_task['default_ref'] == 'nebula.organization-lifecycle-carbon.steel-model@1.0.11'
    assert set(scope_task['refs']) == {'nebula.organization-lifecycle-carbon.steel-model@1.0.11',
                                       'ghg.iron-steel.organization-period-model@1.0.6'}
    assert load_template_method_library(dict(declaration['template_profile'], content_sha256='f' * 64)) is None


def test_ghg_copy_declares_direct_scope_without_weakening_generation_only_factor_requirement():
    from nebula_one.services.template_accounting_methods import transcribe_official_rules
    _, packages = load_template_method_library(shipped()['template_profile'])
    package, _ = next((p, h) for p, h in packages if p.package_kind == 'organization_period_inventory')
    assert package.version == '1.0.6'
    ports = [dict(exchange_id='site::co2', process_id='site', direction='emission', flow_uuid='co2', internal=False)]
    copied = transcribe_official_rules(package.package_kind, package.manifest, ports, 'ghg@1.0.6')
    assert copied['rules'][0]['scope'] == 'scope_1'
    assert package.manifest['classification_rules']['scope2_allocation'] == 'generation_only_evidence_required'


def test_both_organization_methods_copy_both_purchase_paths_without_changing_their_basis():
    from nebula_one.services.template_accounting_methods import transcribe_official_rules
    purchases = ['ore-sintering::grid-electricity-in', 'continuous-casting::grid-electricity-in']
    ports = [dict(exchange_id=key, process_id=key.split('::')[0], direction='input',
                  flow_uuid='electricity', internal=False) for key in purchases]
    _, packages = load_template_method_library(shipped()['template_profile'])
    for package, _ in packages:
        if package.package_kind not in ('organization_period_inventory', 'organization_lifecycle_carbon'):
            continue
        copied = transcribe_official_rules(package.package_kind, package.manifest, ports,
                                          f'{package.package_id}@{package.version}')
        scope2 = [r for r in copied['rules'] if r['scope'] == 'scope_2']
        assert {r['exchange_id'] for r in scope2} == set(purchases)
        assert all(r['boundary_status'] == 'selected' for r in scope2)
        if package.package_kind == 'organization_lifecycle_carbon':
            # The user's lifecycle grouping remains available and unchanged.
            assert package.version == '1.0.11'
            assert package.manifest['formula_graph']['total_indicator_key'] == 'climate change'
            original = json.loads((LIBRARY_ROOT.parent / 'official_methods/organization-lifecycle-carbon-steel-1.0.10.json').read_text(encoding='utf-8'))
            assert canonical_json_sha256(original) == '0f223a844ab95e50a01a72bd7e5de5944484a5ff36a32d4977c2a2142dd8ae4f'


def test_archived_library_replays_old_exact_method_pins(tmp_path):
    # The archive keeps every superseded release byte-for-byte, so it holds more than one library for
    # the same structural profile; an audit replays one named release in isolation, not the whole dir.
    isolated = tmp_path / 'only-116'
    isolated.mkdir()
    (isolated / 'steel-1.1.6.json').write_bytes((LIBRARY_ROOT / 'archive' / 'steel-1.1.6.json').read_bytes())
    declaration = json.loads((isolated / 'steel-1.1.6.json').read_text(encoding='utf-8'))
    identity, packages = load_template_method_library(declaration['template_profile'], library_root=isolated)
    assert identity['version'] == '1.1.6'
    assert identity['tasks'] is None
    package, digest = next((p, h) for p, h in packages if p.package_kind == 'organization_period_inventory')
    assert package.version == '1.0.6'
    assert digest == '04b6ebb78952a8be54d2ffe78bc931ddbb923de0e59ff651e27613eeff8f3cd6'


@pytest.mark.parametrize('change,code', [
    ('hash', 'TEMPLATE_METHOD_LIBRARY_PIN_MISMATCH'),
    ('version', 'TEMPLATE_METHOD_LIBRARY_PACKAGE_UNRESOLVED'),
    ('duplicate', 'TEMPLATE_METHOD_LIBRARY_DUPLICATE'),
    ('schema', 'TEMPLATE_METHOD_LIBRARY_INVALID'),
])
def test_bad_library_refuses_instead_of_selecting_latest(tmp_path, change, code):
    declaration = shipped()
    # These cases probe method-pin and schema handling, so drop the task grouping that would otherwise
    # flag an unpinned ref first; task validation has its own case below.
    declaration.pop('tasks', None)
    original_profile = deepcopy(declaration['template_profile'])
    if change == 'hash': declaration['methods'][0]['content_sha256'] = 'f' * 64
    if change == 'version': declaration['methods'][0]['version'] = '99.0.0'
    if change == 'duplicate': declaration['methods'].append(deepcopy(declaration['methods'][0]))
    if change == 'schema': declaration['schema_version'] = 'unknown'
    (tmp_path / 'library.json').write_text(json.dumps(declaration), encoding='utf-8')
    with pytest.raises(DomainError) as error:
        load_template_method_library(original_profile, library_root=tmp_path)
    assert error.value.code == code


def test_task_referencing_an_unpinned_method_is_invalid(tmp_path):
    declaration = shipped()
    declaration['tasks'][0]['refs'].append('ghost.package@9.9.9')
    (tmp_path / 'library.json').write_text(json.dumps(declaration), encoding='utf-8')
    with pytest.raises(DomainError) as error:
        load_template_method_library(declaration['template_profile'], library_root=tmp_path)
    assert error.value.code == 'TEMPLATE_METHOD_LIBRARY_INVALID'


def test_multiple_default_libraries_are_ambiguous(tmp_path):
    declaration = shipped()
    for name in ('a', 'b'):
        (tmp_path / f'{name}.json').write_text(json.dumps(declaration), encoding='utf-8')
    with pytest.raises(DomainError) as error:
        load_template_method_library(declaration['template_profile'], library_root=tmp_path)
    assert error.value.code == 'TEMPLATE_METHOD_LIBRARY_AMBIGUOUS'


def test_new_project_binding_uses_frozen_library_not_newer_matching_package(client, tmp_path, monkeypatch):
    import nebula_one.services.official_product_method as M
    declaration = shipped()
    identity, packages = load_template_method_library(declaration['template_profile'])
    package, digest = next((p, h) for p, h in packages if p.package_kind == 'organization_lifecycle_carbon')
    original = package.model_dump(mode='json')
    (tmp_path / 'exact.json').write_text(json.dumps(original), encoding='utf-8')
    newer = dict(original, version='99.0.0')
    (tmp_path / 'newer.json').write_text(json.dumps(newer), encoding='utf-8')
    monkeypatch.setattr(M, 'METHOD_ROOT', tmp_path)
    context = {'seed_template': {'profile': declaration['template_profile'], 'accounting_library': identity}}
    app = SimpleNamespace(context=deepcopy(context))
    with client.app.state.container.database.session() as db:
        reference = _bind(db, app, 'organization_lifecycle_carbon')
        assert reference == f'{package.package_id}@{package.version}'
        assert f'{package.package_id}@99.0.0' not in app.context['method_package_refs']
        # An older project keeps the legacy binding behavior, without writing its context via a library read.
        before = deepcopy(app.context)
        load_template_method_library(declaration['template_profile'])
        assert app.context == before
