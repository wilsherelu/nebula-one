"""Real HTTP template/tag/engine acceptance. Run only against an owned isolated instance.

Uses the shipped public steel demonstration data, not a measured facility inventory.
Expected numbers come independently from the engine's frozen elementary contributions.
"""
import argparse
import json
import math
from pathlib import Path
import urllib.request
import urllib.error
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--one', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--readback', action='store_true')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    trace = []

    def call(method, route, body=None):
        request = urllib.request.Request(args.one + '/api/v1' + route, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json'})
        try:
            with opener.open(request, timeout=180) as response:
                raw = response.read().decode('utf-8')
                value = json.loads(raw) if 'json' in response.headers.get('Content-Type', '') else raw
                trace.append({'method': method, 'route': route, 'status': response.status, 'result': value})
                (out / 'http.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
                return value
        except urllib.error.HTTPError as exc:
            raise AssertionError((route, exc.code, exc.read().decode('utf-8'))) from exc

    def expect_error(method, route, status, code, body=None):
        request = urllib.request.Request(args.one + '/api/v1' + route, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json'})
        try:
            with opener.open(request, timeout=180) as response:
                raise AssertionError((route, 'expected an error', response.status))
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode('utf-8'))
            trace.append({'method': method, 'route': route, 'status': exc.code, 'result': payload})
            (out / 'http.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
            assert exc.code == status, (route, exc.code, payload)
            assert payload['error']['code'] == code, (route, payload)
            return payload

    if args.readback:
        record = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
        for item in record['persisted']:
            actual = call('GET', item['route'])
            assert actual == item['result'], item['route']
        (out / 'restart-readback.json').write_text(json.dumps({'passed': True, 'reads': len(record['persisted'])}), encoding='utf-8')
        print('restart readback passed')
        return

    template = next(t for t in call('GET', '/project-templates')['items'] if t.get('seed_id') == 'nebula.iron-steel.bf-bof-crude-steel')
    head = call('GET', f"/project-templates/{template['id']}/accounting-methods")['template']
    graph = head['model']['graph_snapshot']
    def emission_ports(n):
        return n.get('emissions', []) + [p for p in n.get('outputs', []) if p.get('type') == 'biosphere']
    node = next(n for n in graph['nodes'] if len(emission_ports(n)) >= 2)
    exchanges = [f"{node['id']}::{p['id']}" for p in emission_ports(node)[:2]]
    source_refs = []
    legacy = None
    for name, chosen in [('Acceptance A', exchanges), ('Acceptance B', exchanges[:1])]:
        detail = call('POST', f"/applications/{head['source_application_id']}/calculation-methods", {
            'name': name + ' ' + uuid4().hex[:8], 'purpose': 'custom',
            'model_revision_id': head['source_revision_id'], 'semantics': 'result_category.v1',
            'reporting_dimensions': [{'id': 'result_category', 'name': name, 'categories': [{'id': 'direct', 'name': 'Direct', 'is_leaf': True}]}],
            'rules': [{'process_instance_id': node['id'], 'exchange_id': e,
                       'direction': 'emission', 'location_role': 'other',
                       'categories': {'result_category': 'direct'}} for e in chosen]})
        mid = detail['method']['id']
        assert call('POST', f'/calculation-methods/{mid}/versions/1/validate')['valid']
        v = call('GET', f'/calculation-methods/{mid}/versions/1')
        assert v['semantics'] == 'result_category.v1'
        assert all(rule['boundary_status'] == 'selected' and rule['classification_basis'] == 'user'
                   and rule['boundary'] is None and rule['cbam_relevant'] is False for rule in v['rules']), v['rules']
        source_refs.append({'method_id': mid, 'version': 1, 'content_sha256': v['content_sha256']})

    # Legacy tag schemes stay frozen and are converted into an independent result-category method.
    legacy = call('POST', f"/applications/{head['source_application_id']}/calculation-methods", {
        'name': 'Legacy acceptance ' + uuid4().hex[:8], 'purpose': 'custom',
        'model_revision_id': head['source_revision_id'], 'semantics': 'flow_tag.v1',
        'reporting_dimensions': [{'id': 'tag', 'name': 'Legacy tag', 'categories': [{'id': 'direct', 'name': 'Direct', 'is_leaf': True}]}],
        'rules': [
            {'process_instance_id': node['id'], 'exchange_id': exchanges[0], 'direction': 'emission',
             'boundary_status': 'selected', 'location_role': 'other', 'categories': {'tag': 'direct'}},
            {'process_instance_id': node['id'], 'exchange_id': exchanges[1], 'direction': 'emission',
             'boundary_status': 'selected', 'location_role': 'other', 'categories': {}},
        ]})
    legacy_id = legacy['method']['id']
    assert call('POST', f'/calculation-methods/{legacy_id}/versions/1/validate')['valid']
    legacy_before = call('GET', f'/calculation-methods/{legacy_id}/versions/1')
    preview = call('GET', f'/calculation-methods/{legacy_id}/versions/1/conversion-preview')
    assert preview['can_convert'] and preview['counts']['assigned'] == 1
    assert preview['counts']['selected_without_category'] == 1
    converted = call('POST', f'/calculation-methods/{legacy_id}/versions/1/convert',
                     {'name': 'Converted acceptance ' + uuid4().hex[:8]})
    converted_id = converted['method']['id']
    assert converted_id != legacy_id and converted['versions'][0]['semantics'] == 'result_category.v1'
    assert converted['versions'][0]['status'] == 'draft'
    assert [rule['exchange_id'] for rule in converted['versions'][0]['rules']] == [exchanges[0]]
    assert call('POST', f'/calculation-methods/{converted_id}/versions/1/validate')['valid']
    legacy_after = call('GET', f'/calculation-methods/{legacy_id}/versions/1')
    assert legacy_after['content_sha256'] == legacy_before['content_sha256']
    assert legacy_after['rules'] == legacy_before['rules']

    # A pre-caliber ordinary method (no semantics) is read-only as well, and its Scope-only
    # history needs an explicit target tree plus a per-flow decision before conversion.
    ordinary = call('POST', f"/applications/{head['source_application_id']}/calculation-methods", {
        'name': 'Legacy ordinary ' + uuid4().hex[:8], 'purpose': 'custom',
        'model_revision_id': head['source_revision_id'], 'semantics': None,
        'reporting_dimensions': [],
        'rules': [
            {'process_instance_id': node['id'], 'exchange_id': exchanges[0], 'direction': 'emission',
             'boundary_status': 'selected', 'location_role': 'onsite', 'scope': 'scope_1'},
            {'process_instance_id': node['id'], 'exchange_id': exchanges[1], 'direction': 'emission',
             'boundary_status': 'pending', 'location_role': 'onsite', 'scope': 'scope_1'},
        ]})
    ordinary_id = ordinary['method']['id']
    assert call('POST', f'/calculation-methods/{ordinary_id}/versions/1/validate')['valid']
    ordinary_capabilities = call('GET', f'/calculation-methods/{ordinary_id}/capabilities')
    assert ordinary_capabilities['legacy_method'] is True
    assert ordinary_capabilities['legacy_tag_scheme'] is False
    assert ordinary_capabilities['conversion_available'] is True
    assert ordinary_capabilities['processing_package_selection'] is False
    assert (ordinary_capabilities['processing_package_reason']['code']
            == 'CALCULATION_METHOD_LEGACY_METHOD_NO_PROCESSING_PACKAGE')
    ordinary_before = call('GET', f'/calculation-methods/{ordinary_id}/versions/1')
    expect_error('PUT', f'/calculation-methods/{ordinary_id}/versions/1', 409,
                 'CALCULATION_METHOD_LEGACY_READ_ONLY',
                 {'name': 'Legacy ordinary renamed', 'rules': ordinary_before['rules'],
                  'reporting_dimensions': [], 'expected_content_sha256': ordinary_before['content_sha256']})
    expect_error('POST', f'/calculation-methods/{ordinary_id}/versions/1/clone', 409,
                 'CALCULATION_METHOD_LEGACY_READ_ONLY',
                 {'name': 'Legacy ordinary clone', 'purpose': 'custom',
                  'model_revision_id': head['source_revision_id']})
    ordinary_preview = call('GET', f'/calculation-methods/{ordinary_id}/versions/1/conversion-preview')
    assert ordinary_preview['source_semantics'] is None
    assert ordinary_preview['can_convert'] is False
    assert ordinary_preview['reason']['code'] == 'TAG_SCHEME_CONVERSION_TARGET_REQUIRED'
    assert ordinary_preview['counts']['invalid_category'] == 1
    assert ordinary_preview['counts']['unresolved_invalid'] == 1
    assert ordinary_preview['counts']['pending'] == 1
    target = {'id': 'legacy_target', 'name': '现场排放', 'categories': [
        {'id': 'onsite', 'name': '现场', 'is_leaf': True},
        {'id': 'purchased', 'name': '外购', 'is_leaf': True},
    ]}
    unmapped = call('POST', f'/calculation-methods/{ordinary_id}/versions/1/conversion-preview',
                    {'target_dimension': target})
    assert unmapped['can_convert'] is False
    assert unmapped['counts']['unresolved_invalid'] == 1
    assert any(problem['code'] == 'TAG_SCHEME_CONVERSION_CATEGORY_REQUIRED'
               for problem in unmapped['problems'])
    expect_error('POST', f'/calculation-methods/{ordinary_id}/versions/1/convert', 422,
                 'TAG_SCHEME_CONVERSION_UNRESOLVED_MAPPING',
                 {'name': 'Scope only result', 'target_dimension': target})
    ordinary_mapped = call('POST', f'/calculation-methods/{ordinary_id}/versions/1/conversion-preview', {
        'target_dimension': target, 'resolutions': [{'rule_index': 0, 'category': 'onsite'}]})
    assert ordinary_mapped['can_convert'] is True
    assert ordinary_mapped['counts']['assigned'] == 1
    assert ordinary_mapped['rules'][0]['resolved'] is True
    expect_error('POST', f'/calculation-methods/{ordinary_id}/versions/1/convert', 409,
                 'TAG_SCHEME_CONVERSION_MAPPING_CHANGED', {
                     'name': 'Scope only result', 'target_dimension': target,
                     'resolutions': [{'rule_index': 0, 'category': 'onsite'}],
                     'expected_mapping_sha256': '0' * 64})
    ordinary_converted = call('POST', f'/calculation-methods/{ordinary_id}/versions/1/convert', {
        'name': 'Scope only result ' + uuid4().hex[:8], 'target_dimension': target,
        'resolutions': [{'rule_index': 0, 'category': 'onsite'}],
        'expected_mapping_sha256': ordinary_mapped['mapping_sha256']})
    ordinary_converted_id = ordinary_converted['method']['id']
    ordinary_version = ordinary_converted['versions'][0]
    assert ordinary_version['semantics'] == 'result_category.v1'
    assert [dimension['id'] for dimension in ordinary_version['reporting_dimensions']] == ['legacy_target']
    assert [rule['categories'] for rule in ordinary_version['rules']] == [{'legacy_target': 'onsite'}]
    assert [rule['exchange_id'] for rule in ordinary_version['rules']] == [exchanges[0]]
    ordinary_after = call('GET', f'/calculation-methods/{ordinary_id}/versions/1')
    assert ordinary_after['content_sha256'] == ordinary_before['content_sha256']
    assert ordinary_after['rules'] == ordinary_before['rules']

    # An invalid legacy category is repaired inside the conversion draft; it is never silently
    # turned into "无", and the source keeps its exact bytes.
    ghost = call('POST', f"/applications/{head['source_application_id']}/calculation-methods", {
        'name': 'Ghost legacy ' + uuid4().hex[:8], 'purpose': 'custom',
        'model_revision_id': head['source_revision_id'], 'semantics': 'flow_tag.v1',
        'reporting_dimensions': [{'id': 'tag', 'name': 'Legacy tag',
                                  'categories': [{'id': 'direct', 'name': 'Direct', 'is_leaf': True}]}],
        'rules': [{'process_instance_id': node['id'], 'exchange_id': exchanges[0], 'direction': 'emission',
                   'boundary_status': 'selected', 'location_role': 'other', 'categories': {'tag': 'ghost'}}]})
    ghost_id = ghost['method']['id']
    ghost_before = call('GET', f'/calculation-methods/{ghost_id}/versions/1')
    ghost_blocked = call('GET', f'/calculation-methods/{ghost_id}/versions/1/conversion-preview')
    assert ghost_blocked['can_convert'] is False
    assert ghost_blocked['counts']['invalid_category'] == 1
    assert ghost_blocked['counts']['unresolved_invalid'] == 1
    assert ghost_blocked['rules'][0]['needs_resolution'] is True
    expect_error('POST', f'/calculation-methods/{ghost_id}/versions/1/convert', 422,
                 'TAG_SCHEME_CONVERSION_UNRESOLVED_MAPPING', {'name': 'Ghost result'})
    ghost_none = call('POST', f'/calculation-methods/{ghost_id}/versions/1/conversion-preview',
                      {'resolutions': [{'rule_index': 0, 'category': None}]})
    assert ghost_none['can_convert'] is True
    assert ghost_none['counts']['resolved_without_category'] == 1
    ghost_mapped = call('POST', f'/calculation-methods/{ghost_id}/versions/1/conversion-preview',
                        {'resolutions': [{'rule_index': 0, 'category': 'direct'}]})
    assert ghost_mapped['can_convert'] is True
    assert ghost_mapped['counts']['assigned'] == 1
    ghost_converted = call('POST', f'/calculation-methods/{ghost_id}/versions/1/convert', {
        'name': 'Ghost result ' + uuid4().hex[:8],
        'resolutions': [{'rule_index': 0, 'category': 'direct'}],
        'expected_mapping_sha256': ghost_mapped['mapping_sha256']})
    ghost_converted_id = ghost_converted['method']['id']
    assert [rule['categories'] for rule in ghost_converted['versions'][0]['rules']] == [{'tag': 'direct'}]
    ghost_after = call('GET', f'/calculation-methods/{ghost_id}/versions/1')
    assert ghost_after['content_sha256'] == ghost_before['content_sha256']
    assert ghost_after['rules'][0]['categories'] == {'tag': 'ghost'}

    plan = call('GET', f"/project-templates/{template['id']}/save-plan")
    ordinary_ref = {'method_id': ordinary_id, 'version': 1, 'content_sha256': ordinary_before['content_sha256']}
    saved = call('POST', f"/project-templates/{template['id']}/save-template", {
        'title': 'Tag acceptance ' + uuid4().hex[:8], 'version': plan['suggested_version'],
        'user_methods': source_refs + [ordinary_ref]})['template']
    created = call('POST', f"/project-templates/{saved['id']}/projects", {
        'name': 'Tag inherited project', 'project_key': str(uuid4()), 'expected_template_sha256': saved['template_sha256']})
    app = created['application_id']
    methods = call('GET', f'/applications/{app}/calculation-methods')
    inherited_ids = {m['origin_method_id']: m['id'] for m in methods}
    ordinary_inherited_id = inherited_ids.get(ordinary_id)
    assert ordinary_inherited_id, 'The template did not freeze the legacy ordinary method'
    initial_revision = methods[0]['model_revision_id']
    initial = call('GET', f'/applications/{app}/workspace/{initial_revision}')
    workspace = call('POST', f'/applications/{app}/workspace/inputs', {
        'revision_id': initial_revision, 'expected_content_sha256': initial['content_sha256'],
        'demand_mode': 'reference_output', 'amounts': [1000],
        'project_background_pins': initial['project_background_pins'],
        'values': {field['key']: field['value'] for field in initial['fields'] if not field['linked']},
        'source': 'Tag template real HTTP acceptance'})
    revision = workspace['revision_id']
    methods = call('GET', f'/applications/{app}/calculation-methods?model_revision_id={revision}')
    refs = []
    for source in source_refs:
        method = next(m for m in methods if m['origin_method_id'] == inherited_ids[source['method_id']])
        mid = method['id']
        v = call('GET', f'/calculation-methods/{mid}/versions/1')
        assert v['semantics'] == 'result_category.v1'
        assert call('POST', f'/calculation-methods/{mid}/versions/1/validate')['valid']
        refs.append({'method_id': mid, 'version': 1, 'content_sha256': v['content_sha256']})
    snapshot = call('POST', f'/applications/{app}/system-revisions/{revision}/solve', {
        'demand': workspace['demand'], 'analysis_task': 'pcf', 'calculation_purpose': 'lca',
        'climate_default': True, 'project_background_pins': workspace['project_background_pins'],
        'idempotency_key': str(uuid4())})
    receipt = next(r for r in snapshot['lcia_results']['indicator_contribution_receipts'] if r['canonical_indicator_key'] == 'climate change')
    terms = {t['exchange_id']: t['contribution_value'] for t in receipt['terms']}
    expected = [sum(terms[e] for e in exchanges), terms[exchanges[0]]]
    grouped = {}
    persisted = []
    for mode in ['separate', 'union', 'intersection']:
        result = call('POST', f'/applications/{app}/tag-grouping', {
            'snapshot_id': snapshot['id'], 'indicator_key': 'climate change', 'schemes': refs, 'mode': mode})
        assert result['available'] and result['reconciled'], result
        assert result['semantics'] == 'result_category.v1'
        assert all(item.get('semantics') == 'result_category.v1'
                   and item.get('populated') is True for item in result['schemes']), result['schemes']
        grouped[mode] = result
        for actual, target in zip(result['schemes'], expected):
            value = actual['tag_total'].get('value', actual['tag_total'].get('subtotal'))
            assert math.isclose(value, target, rel_tol=1e-9), (actual['tag_total'], target)
        if mode != 'separate':
            total = result[mode]
            value = total.get('value', total.get('subtotal'))
            assert math.isclose(value, expected[0 if mode == 'union' else 1], rel_tol=1e-9), total
        if result.get('result_id'):
            route = f"/applications/{app}/tag-grouping-results/{result['result_id']}"
            persisted.append({'route': route, 'result': call('GET', route)})
            for fmt in ['html', 'json']:
                export = call('GET', route + '/export?format=' + fmt)
                if fmt == 'html':
                    assert '结果分类归集结果' in export
                    assert '已分类贡献小计' in export
                else:
                    body = export if isinstance(export, dict) else json.loads(export)
                    assert body['semantics'] == 'result_category.v1'
                (out / f'{mode}.{fmt}').write_text(export if isinstance(export, str) else json.dumps(export, ensure_ascii=False, indent=2), encoding='utf-8')
    assert persisted, 'tag results must be persisted, not only calculated in memory'
    # Archived source schemes must not mutate the independently inherited project or saved results.
    call('POST', f"/calculation-methods/{source_refs[0]['method_id']}/archive")
    assert call('GET', f"/calculation-methods/{refs[0]['method_id']}/versions/1")['status'] == 'ready'
    for item in persisted:
        assert call('GET', item['route']) == item['result']
    summary = {'passed': True, 'data': 'public steel demonstration; real engine receipt',
               'application_id': app, 'template_id': saved['id'], 'snapshot_id': snapshot['id'],
               'revision_id': revision, 'schemes': refs, 'exchanges': exchanges, 'expected': expected,
               'legacy_conversion': {'source_method_id': legacy_id, 'converted_method_id': converted_id,
                                     'preview_counts': preview['counts']},
               'legacy_ordinary': {'source_method_id': ordinary_id, 'converted_method_id': ordinary_converted_id,
                                   'inherited_method_id': ordinary_inherited_id,
                                   'application_id': head['source_application_id'],
                                   'revision_id': head['source_revision_id'],
                                   'initial_revision_id': initial_revision,
                                   'source_content_sha256': ordinary_before['content_sha256'],
                                   'capabilities': ordinary_capabilities,
                                   'preview_counts': ordinary_preview['counts'],
                                   'mapped_counts': ordinary_mapped['counts']},
               'invalid_mapping': {'source_method_id': ghost_id, 'converted_method_id': ghost_converted_id,
                                   'application_id': head['source_application_id'],
                                   'revision_id': head['source_revision_id'],
                                   'source_content_sha256': ghost_before['content_sha256'],
                                   'blocked_counts': ghost_blocked['counts'],
                                   'none_counts': ghost_none['counts'],
                                   'mapped_counts': ghost_mapped['counts']},
               'persisted': persisted}
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'persisted'}))


if __name__ == '__main__':
    main()
