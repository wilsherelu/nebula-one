import json

import pytest

from nebula_one.casepacks.catalog import CasePackCatalog
from nebula_one.errors import DomainError
from nebula_one.release_catalog import ReleaseCatalog


def test_public_manifest_pins_only_the_steel_seed():
    catalog = ReleaseCatalog('deploy/public-catalog.v1.json')
    assert len(catalog.seeds) == 1
    assert list(catalog.seeds.values()) == ['高炉—转炉钢铁']
    assert catalog.casepacks == set()


def test_the_steel_seed_declares_a_short_name_for_every_release_language():
    # The canonical title stays authoritative; the display map only adds the language the operator authored.
    catalog = ReleaseCatalog('deploy/public-catalog.v1.json')
    row = type('Row', (), {'seed_id': 'nebula.iron-steel.bf-bof-crude-steel', 'seed_version': '1.1.0',
        'bundle_content_sha256': '0a2a553ae4ca42bbb221d7b16d55a631c12091caa37aa00cc6c4e1f2231ee07e'})()
    assert catalog.seed_title(row) == '高炉—转炉钢铁'
    assert catalog.seed_display_name(row) == {'zh': '高炉—转炉钢铁', 'en': 'Blast furnace – BOF steel'}


def test_an_incomplete_display_map_is_refused(tmp_path):
    document = json.loads(json.dumps({
        'schema_version': 'nebula_one.release_catalog.v1',
        'seed_templates': [{'seed_id': 's', 'version': '1', 'bundle_content_sha256': 'f' * 64,
            'title': 'T', 'display_name': {'zh': '标题'}}],
        'casepacks': []}))
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps(document), encoding='utf-8')
    with pytest.raises(ValueError, match='incomplete'):
        ReleaseCatalog(str(path))


def test_release_catalog_hides_casepacks_from_listing_and_direct_materialization(tmp_path):
    manifest = tmp_path / 'release.json'
    manifest.write_text(json.dumps({'schema_version': 'nebula_one.release_catalog.v1',
        'seed_templates': [], 'casepacks': []}), encoding='utf-8')
    catalog = CasePackCatalog(('cases',), ReleaseCatalog(str(manifest)))
    assert catalog.list().items == ()
    with pytest.raises(DomainError) as error:
        catalog.load_exact('petrochemical-refinery-reference', '0.4.0')
    assert error.value.status_code == 404
