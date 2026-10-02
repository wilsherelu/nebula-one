"""A project template may restate a method package, but only in the ways it declares."""
import json
from pathlib import Path
from types import SimpleNamespace

from nebula_one.hashing import canonical_json_sha256
from nebula_one.services.project_template_profiles import load_profile

SEED_ROOT = Path('cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel')
OLD_PACKAGE = SEED_ROOT / 'methods/cbam-eu-iron-steel-bf-bof-direct-trial-1.0.1.json'
TEMPLATE_PATH = Path('cases/project-templates/steel-bf-bof-inventory/template.json')


def _installation():
    seed = json.loads((SEED_ROOT / 'seed.json').read_text(encoding='utf-8'))
    return SimpleNamespace(seed_id=seed['seed_id'], seed_version=seed['version'],
                           bundle_content_sha256=seed['content_pins']['bundle_content_sha256'])


def _replaced_package():
    return load_profile(['cases'], _installation())[2][0][1].model_dump(mode='json')


def _template():
    return json.loads(TEMPLATE_PATH.read_text(encoding='utf-8'))


def _membership_drift(old_manifest: dict, new_manifest: dict) -> list[tuple[str, str]]:
    """The (flow role, field) pairs the replaced package reads differently, in ledger order."""
    old_records = old_manifest['precursor_rules']['membership_evidence']
    new_records = new_manifest['precursor_rules']['membership_evidence']
    assert [row['flow_role'] for row in old_records] == [row['flow_role'] for row in new_records]
    return [(before['flow_role'], field)
            for before, after in zip(old_records, new_records)
            for field in sorted(set(before) | set(after)) if before.get(field) != after.get(field)]


def test_current_steel_profile_binds_partial_review_without_a_returned_graph(client):
    from nebula_one.models import Application
    from nebula_one.services.official_product_method import bind_official_cbam_partial_method
    profile, digest, _ = load_profile(['cases'], _installation())
    with client.app.state.container.database.session() as db:
        application = Application(id='round2-partial-binding', name='Steel case binding',
            application_type='process_system', context={'seed_template': {'profile': {
                'id': profile['id'], 'version': profile['version'], 'content_sha256': digest}}})
        db.add(application)
        db.flush()
        reference = bind_official_cbam_partial_method(db, application)
        assert reference == 'cbam.eu.iron-steel.bf-bof-partial-review@1.0.6'
        assert reference in application.context['method_package_refs']


def test_steel_inventory_profile_changes_demo_validation_and_the_revised_flow_identity():
    profile, digest, replacements = load_profile(['cases'], _installation())
    previous, package, package_hash = replacements[0]
    new = package.model_dump(mode='json')
    old = json.loads(OLD_PACKAGE.read_text(encoding='utf-8'))
    assert new['version'] == '1.2.0' and previous.endswith('@1.0.1')
    assert profile['version'] == '1.1.3'
    assert digest == canonical_json_sha256(profile)
    assert package_hash == canonical_json_sha256(new)
    assert old['manifest']['validation_rules']['expected_direct_emissions_kg']['value'] == '1940.739734'
    assert 'expected_direct_emissions_kg' not in new['manifest']['validation_rules']
    for section in ('formula_graph', 'classification_rules', 'default_value_rules'):
        assert new['manifest'][section] == old['manifest'][section]
    assert new['manifest']['boundary_schema']['goods_complexity'] == 'complex'
    assert new['manifest']['boundary_schema']['calculation_scope'] == 'direct_component_only'
    assert new['manifest']['boundary_schema']['end_use']['not_a_cbam_good'] == []
    assert not any('conservative upper bound' in item for item in new['manifest']['validation_rules']['limitations'])
    assert _membership_drift(old['manifest'], new['manifest']) == [('grid_electricity', 'flow_uuid')]


def test_steel_inventory_membership_evidence_names_the_flow_the_revision_writes():
    """Membership is a statement about a flow identity and the template revision is what decides
    which flow the electricity port carries, so the two have to agree before any project is built."""
    revision = _template()['identity_revision']['content']
    revised_flows = {entry['after']['flowUuid'] for entry in revision['replacements']}
    assert {entry['exchange_id'] for entry in revision['replacements']} == {
        'ore-sintering::grid-electricity-in', 'continuous-casting::grid-electricity-in'}
    evidence = {row['flow_role']: row for row in
                _replaced_package()['manifest']['precursor_rules']['membership_evidence']}
    assert evidence['grid_electricity']['flow_uuid'] in revised_flows
    # The reading of the Annex I list travels with the flow, not with the port that carries it.
    assert {field: evidence['grid_electricity'][field] for field in
            ('annex_i_listed', 'clause', 'cn_code', 'membership', 'governing_clause', 'gap_ref')} == {
        'annex_i_listed': True, 'clause': 'ST-13', 'cn_code': '2716 00 00',
        'membership': 'listed_governed_elsewhere', 'governing_clause': 'ST-12', 'gap_ref': 'GS-05'}


def test_steel_inventory_profile_stops_matching_a_different_seed_bundle():
    installation = _installation()
    installation.bundle_content_sha256 = '0' * 64
    assert load_profile(['cases'], installation) is None
