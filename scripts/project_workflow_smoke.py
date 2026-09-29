"""Exercise project data editing on an explicitly supplied isolated HTTP instance."""
import argparse
import json
from pathlib import Path
from uuid import uuid4

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--case', default='resource-efficiency-scenarios')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with httpx.Client(base_url=args.url.rstrip('/'), timeout=180, trust_env=False) as c:
        def call(method, path, **kw):
            r = c.request(method, path, **kw)
            assert r.is_success, (path, r.status_code, r.text)
            return r.json()
        pack = call('GET', '/api/v1/casepacks')['items'][0]
        case = next(x for x in pack['applications'] if x['id'] == args.case)
        packages = call('GET', '/api/v1/method-packages')
        project = call('POST', f"/api/v1/casepacks/{pack['id']}/versions/{pack['version']}/application-cases/{case['id']}/versions/{case['version']}/materialize", json={
            'expected_case_pack_sha256': pack['case_pack_sha256'], 'expected_resolved_case_sha256': case['resolved_case_sha256'],
            'project_name': 'Production data workflow acceptance', 'project_key': str(uuid4()),
        })
        aid = project['application']['id']
        prefix = f'/api/v1/applications/{aid}'
        original = call('GET', f"{prefix}/workspace/{project['base_revision']['id']}")
        packages = call('GET', '/api/v1/method-packages')
        refs = project['application']['context']['method_package_refs']
        pcf_method = next((p for p in packages if p['package_kind'] == 'product_carbon_footprint' and f"{p['package_id']}@{p['version']}" in refs), None)
        method_ref = f"{pcf_method['package_id']}@{pcf_method['version']}" if pcf_method else None
        def analysis(snapshot):
            return call('POST', f"/api/v1/solved-system-snapshots/{snapshot['id']}/product-carbon-footprint", json={'method_package_ref': method_ref}) if method_ref else call('GET', f"/api/v1/solved-system-snapshots/{snapshot['id']}/mfa")
        records = []
        current = original
        for index in range(2):
            values = {f['key']: f['value'] for f in current['fields']}
            if index and 'cracker_feed_amount' in values:
                values['cracker_feed_amount'] *= 0.95
            saved = call('POST', f'{prefix}/workspace/inputs', json={
                'revision_id': current['revision_id'], 'expected_content_sha256': current['content_sha256'],
                'amounts': [2 + index], 'values': values, 'source': 'Isolated workflow verification; not plant measurements',
            })
            snapshot = call('POST', f"{prefix}/system-revisions/{saved['revision_id']}/solve", json={
                'demand': saved['demand'], 'idempotency_key': f'workflow-{uuid4()}',
                **({'lcia_methods': [pcf_method['manifest']['formula_graph']['lcia_method']]} if pcf_method else {}),
            })
            mfa = call('GET', f"/api/v1/solved-system-snapshots/{snapshot['id']}/mfa")
            pcf = analysis(snapshot)
            assert call('GET', f"{prefix}/workspace/{saved['revision_id']}") == saved
            records.append(dict(inputs=saved, snapshot=snapshot, mfa=mfa, pcf=pcf))
            current = saved
        assert records[0]['snapshot']['id'] != records[1]['snapshot']['id']
        revisions = call('GET', f"/api/v1/system-models/{project['system_model']['id']}/revisions")
        by_id = {r['id']: r for r in revisions}
        if original['fields']:
            assert by_id[records[0]['inputs']['revision_id']]['graph_sha256'] != by_id[records[1]['inputs']['revision_id']]['graph_sha256']
        assert records[0]['snapshot']['boundary_flows'] != records[1]['snapshot']['boundary_flows']
        if method_ref:
            assert records[0]['pcf']['total_footprint']['value'] != records[1]['pcf']['total_footprint']['value']
        assert records[0]['pcf']['content_sha256'] != records[1]['pcf']['content_sha256']
        assert call('GET', f"{prefix}/workspace/{original['revision_id']}") == original
        assert analysis(records[0]['snapshot']) == records[0]['pcf']
        assert len(call('GET', f'{prefix}/solved-system-snapshots')) == 2
        receipt = dict(application_id=aid, model_id=project['system_model']['id'], original=original, runs=records)
        (args.output/'http.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'application_id': aid, 'snapshots': [r['snapshot']['id'] for r in records], 'status': 'passed'}))


if __name__ == '__main__':
    main()
