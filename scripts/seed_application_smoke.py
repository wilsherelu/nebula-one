"""Exercise an installed seed through real HTTP. Use only a dedicated acceptance instance.

Without --snapshot this creates a frozen solve. With --snapshot it only reads derived results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-url', required=True)
    parser.add_argument('--application-id', required=True)
    parser.add_argument('--seed-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--snapshot', help='replay this existing snapshot without solving')
    parser.add_argument('--pcf-method-ref', required=True, help='exact installed product carbon footprint package id@version')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    seed = json.loads((args.seed_dir / 'seed.json').read_text(encoding='utf-8'))
    graph = json.loads((args.seed_dir / 'model/graph.json').read_text(encoding='utf-8'))['graph']
    def save(name, value):
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    with httpx.Client(base_url=args.app_url, trust_env=False, timeout=180) as client:
        def call(method, path, **kwargs):
            response = client.request(method, '/api/v1' + path, **kwargs)
            response.raise_for_status()
            return response.json()
        app_path = '/applications/' + args.application_id
        models = call('GET', app_path + '/system-models')
        boundaries = call('GET', app_path + '/boundaries')
        periods = call('GET', app_path + '/periods')
        packages = seed['method_package_refs']
        cbam_ref = next(p['package_id']+'@'+p['version'] for p in packages if p['package_kind']=='cbam_trial')
        boundary = next(b for b in boundaries if b['boundary_type']=='cbam_trial' and b['status']=='frozen' and b['method_package_ref']==cbam_ref)
        if args.snapshot:
            snapshot_id = args.snapshot
        else:
            assert len(models)==1, 'acceptance application must own exactly one model'
            revisions = call('GET', '/system-models/'+models[0]['id']+'/revisions')
            reference = graph['metadata']['reference_exchange_id']
            node, port_id = reference.split('::')
            port = next(p for n in graph['nodes'] if n['id']==node for p in n['outputs'] if p['id']==port_id)
            payload = {'demand':[{'reference_flow_uuid':port['flowUuid'],'amount':port['amount'],'unit':port['unit'],
                'unit_group_uuid':port['unitGroupUuid'],'unit_group_version':port['unitGroupVersion']}],
                'lcia_methods':['EF v3.1'], 'idempotency_key':'release-smoke-'+seed['seed_id']+'-'+seed['version']}
            save('solve-request.json',payload)
            snapshot = call('POST', app_path+'/system-revisions/'+revisions[0]['id']+'/solve',json=payload)
            save('solve.json',snapshot)
            snapshot_id = snapshot['id']
        prefix='/solved-system-snapshots/'+snapshot_id
        request={'method_package_ref':cbam_ref,'reporting_period_id':periods[0]['id'],'boundary_definition_id':boundary['id']}
        cbam=call('POST',prefix+'/cbam-trial',json=request)
        pcf=call('POST',prefix+'/product-carbon-footprint',json={'method_package_ref':args.pcf_method_ref})
        mfa=call('GET',prefix+'/mfa')
        save('cbam.json',cbam);save('pcf.json',pcf);save('mfa.json',mfa)
        assert cbam['source_snapshot']['id']==snapshot_id
        expected = json.loads((args.seed_dir/'acceptance/expected-values.json').read_text(encoding='utf-8'))
        reference = expected['cbam']['functional_unit_result']
        assert Decimal(cbam['specific_embedded_emissions']['value']) == Decimal(reference['authored_sum'])
        assert cbam['specific_embedded_emissions']['unit'] == 't CO2e/t product'
        assert cbam['audit']['checks']['every_port_classified_once'] is True
        pcf_expected = expected['pcf']['foreground_boundary_co2']
        assert pcf['functional_unit']['unit'] == 'kg'
        expected_batch = Decimal(pcf_expected['authored_sum']) * Decimal(str(pcf['functional_unit']['amount']))
        assert abs(Decimal(str(pcf['total_footprint']['value'])) - expected_batch) < Decimal('0.000001')
        assert pcf['total_footprint']['unit'] == 'kg CO2-Eq'
        assert pcf['boundary_claim']['coverage'] == 'foreground_only'
        assert pcf['boundary_claim']['complete_product_declaration'] is False
        exports={}
        for filename in ('export.xlsx','report.html'):
            r=client.get('/api/v1'+prefix+'/product-carbon-footprint/'+filename, params={'method_package_ref':args.pcf_method_ref})
            r.raise_for_status()
            assert r.content and (r.content.startswith(b'PK') if filename.endswith('xlsx') else b'<html' in r.content.lower())
            (args.output_dir/filename).write_bytes(r.content)
            exports[filename]=hashlib.sha256(r.content).hexdigest()
        save('receipt.json',{'application_id':args.application_id,'snapshot_id':snapshot_id,'cbam_result_sha256':cbam['content_sha256'],
            'cbam_specific':cbam['specific_embedded_emissions'],'pcf_total':pcf['total_footprint'],'exports':exports,'replay_only':bool(args.snapshot)})
        print(json.dumps({'snapshot_id':snapshot_id,'cbam':cbam['specific_embedded_emissions'],'pcf':pcf['total_footprint'],'exports':exports}))


if __name__=='__main__':
    main()
