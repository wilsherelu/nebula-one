from copy import deepcopy
import json
from pathlib import Path

from nebula_one.services.case_display import display_project_graph
from nebula_one.services.seed_projects import inventory_fields

ROOT = Path(__file__).resolve().parents[1] / 'cases'


def graph():
    return json.loads((ROOT/'standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/graph.json').read_text(encoding='utf-8'))['graph']


def test_authored_display_retains_originals_and_numeric_identity():
    source = graph(); before = deepcopy(source)
    display, refs = display_project_graph(source, (ROOT,), 'zh')
    assert source == before
    fields = inventory_fields(display)
    assert fields[0]['process'] == '铁矿石烧结'
    assert fields[0]['label'] == '铁矿石（未烧结精矿粉）'
    assert fields[0]['source_process_name'] == source['nodes'][0]['name']
    co2 = [row for row in fields if row.get('description')]
    assert len(co2) == 6
    assert {row['description'] for row in co2[:2]} == {'焦粉燃烧','烧结熔剂中碳酸盐分解'}
    assert refs[0]['version'] == '1.0.0' and len(refs[0]['content_sha256']) == 64
    for original, translated in zip(inventory_fields(source),fields):
        assert {k:v for k,v in original.items() if k not in ['label','process']} == {
            k:translated[k] for k in original if k not in ['label','process']}
    english, _ = display_project_graph(source,(ROOT,),'en')
    assert inventory_fields(english)[0]['label'] == 'Iron ore concentrate (not agglomerated)'


def test_other_versions_and_user_renames_do_not_receive_authored_exchange_explanation():
    source = graph()
    port = next(p for p in source['nodes'][0]['outputs'] if p['id']=='co2-sinter-breeze-out')
    port['flowVersion'] = '99.99.999'
    display, _ = display_project_graph(source,(ROOT,),'zh')
    assert 'display_description' not in next(p for p in display['nodes'][0]['outputs'] if p['id']==port['id'])
    source['nodes'][0]['name'] = 'User renamed process'
    display, _ = display_project_graph(source,(ROOT,),'zh')
    assert display['nodes'][0] == source['nodes'][0]


def test_catalog_source_name_is_preserved_separately_from_short_case_name():
    source = graph()
    display, _ = display_project_graph(source,(ROOT,),'zh',{'ore-sintering::iron-ore-in':'铁矿石（未烧结精矿粉，标准 seed 自建）'})
    first = inventory_fields(display)[0]
    assert 'seed' not in first['label']
    assert '标准 seed 自建' in first['source_catalog_label']
