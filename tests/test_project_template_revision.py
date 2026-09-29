import json
from copy import deepcopy
from pathlib import Path

import pytest

from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.services.project_template_revision import apply_template_revision


def fixture():
    root = Path('cases')
    graph = json.loads((root / 'standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/graph.json').read_text(encoding='utf-8'))['graph']
    profile = json.loads((root / 'project-templates/steel-bf-bof-inventory/template.json').read_text(encoding='utf-8'))
    return graph, profile['identity_revision']


def test_published_identity_revision_matches_upstream_graph_without_reminting():
    graph, upgrade = fixture()
    before = deepcopy(graph)
    result = apply_template_revision(graph, upgrade)
    assert graph == before
    assert canonical_json_sha256(result) == upgrade['content']['upstream_exact_graph_sha256']
    for old, new in zip(graph['nodes'], result['nodes']):
        assert old['process_uuid'] == new['process_uuid']
        for a, b in zip(old['inputs'], new['inputs']):
            assert a['amount'] == b['amount']
    assert result['exchanges'] == graph['exchanges']


@pytest.mark.parametrize('mutation', ['hash', 'quantity', 'process-slot', 'duplicate', 'unit', 'extra-field', 'biosphere',
                                      'display-name', 'display-projection-hash', 'display-artifact', 'display-schema',
                                      'display-both-hashes-missing', 'display-both-hashes-invalid'])
def test_identity_revision_rejects_changes_outside_reviewed_contract(mutation):
    graph, upgrade = fixture()
    rows = upgrade['content']['replacements']
    if mutation == 'hash': upgrade['content_sha256'] = '0' * 64
    if mutation == 'quantity': rows[0]['amount_preserved'] += 1
    if mutation == 'process-slot': rows[0]['exchange_id'] = 'missing::power'
    if mutation == 'duplicate': rows.append(deepcopy(rows[0]))
    if mutation == 'unit': rows[0]['after']['unit'] = 'kg'
    if mutation == 'extra-field': rows[0]['after']['amount'] = 42
    if mutation == 'biosphere':
        port = next(p for n in graph['nodes'] if n['id'] == 'ore-sintering' for p in n['inputs'] if p['id'] == 'grid-electricity-in')
        port['type'] = 'biosphere'
    displayed = upgrade['content']['display_metadata'][0]
    if mutation == 'display-name': displayed['name_zh'] = '  '
    if mutation == 'display-projection-hash': displayed['display_projection']['flow_payload_content_hash'] = '0' * 64
    if mutation == 'display-artifact': del displayed['display_projection']['artifact_sha256']
    if mutation == 'display-schema': displayed['display_projection']['schema_version'] = 'nebula.tiangong-flow-display-metadata.v2'
    if mutation == 'display-both-hashes-missing':
        del displayed['content_hash']
        del displayed['display_projection']['flow_payload_content_hash']
    if mutation == 'display-both-hashes-invalid':
        displayed['content_hash'] = displayed['display_projection']['flow_payload_content_hash'] = 'invalid'
    if mutation != 'hash': upgrade['content_sha256'] = canonical_json_sha256(upgrade['content'])
    with pytest.raises(DomainError):
        apply_template_revision(graph, upgrade)


def test_published_display_labels_are_pinned_to_the_upstream_metadata_artifact():
    _, upgrade = fixture()
    metadata = upgrade['content']['display_metadata']
    assert [row['exchange_id'] for row in metadata] == [row['exchange_id'] for row in upgrade['content']['replacements']]
    for row in metadata:
        projection = row['display_projection']
        # The literals are the pin: One holds no second copy of the upstream projection, so a
        # re-worded label has to fail here rather than reach an operator screen.
        assert row['name_zh'] == '交流电'
        assert projection['schema_version'] == 'nebula.tiangong-flow-display-metadata.v1'
        assert projection['artifact_path'] == 'nebula-lca-api/data/provider_profiles/steel_electricity_tiangong_metadata.v1.json'
        assert projection['artifact_sha256'] == 'e26ab67d8c31dbc5b7608f13e913cb8285e1d41675347ed72eed651c06cbff75'
        assert projection['source_commit'] == '9db3f8a'
        assert projection['flow_payload_content_hash'] == row['content_hash']
