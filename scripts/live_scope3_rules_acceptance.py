"""Real EF characterization of synthetic supplier inventory, then user-rule grouping.

Only inventory amounts are synthetic. No aggregate emission factor is declared.
Run on an explicitly isolated instance; preparation never modifies an official package.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import uuid

import live_user_method_acceptance as L
import e3_packaged_runtime_verify as P


def prepare(base, engine, output):
    identities = P._discover(base, engine)
    app = identities['demo']['app_id']
    rev = identities['demo']['rev0']
    graph = L._request(base, 'GET', f'/api/v1/system-revisions/{rev}')['graph_snapshot']
    consumer = next(n for n in graph['nodes'] if n['id'] == 'ore-sintering')
    material = next(p for p in consumer['inputs'] if p['id'] == 'iron-ore-in')
    flow_refs = [dict(source_namespace='tiangong_open_data', flow_uuid=flow, version='03.00.004')
        for flow in ('08a91e70-3ddc-11dd-923d-0050c2490048', '08a91e70-3ddc-11dd-9610-0050c2490048')]
    resolved = L._request(engine, 'POST', '/api/provider/v1/catalog/resolve', {'flows': flow_refs})
    assert all(item['status'] == 'resolved' for item in resolved['items']), resolved
    node = deepcopy(consumer)
    tag = uuid.uuid4().hex[:10]
    node.update(id='supplier', process_uuid=str(uuid.uuid4()), name='Synthetic material supplier '+tag,
                dataMode='normalized', inputs=[])
    product = deepcopy(material)
    product.update(id='product', direction='output', isProduct=True, amount=1.0)
    emissions, refs = [], []
    for gas, item, amount in zip(('co2','ch4'), resolved['items'], (10.0,0.1)):
        flow = item['value']
        emissions.append(dict(id=gas, flowUuid=flow['flow_uuid'], flowSourceNamespace=flow['source_namespace'],
            flowVersion=flow['version'], flowPropertyUuid=flow['flow_property_uuid'], flowPropertyVersion=flow['flow_property_version'],
            unitGroupUuid=flow['unit_group_uuid'], unitGroupVersion=flow['unit_group_version'], unit=flow['unit'],
            unitGroup=flow['unit_group'], name=flow['name_en'], amount=amount, type='biosphere', direction='output', isProduct=False))
        refs.append(dict(exchange_id='supplier::'+gas, **{k:flow[k] for k in
            ('source_namespace','flow_uuid','version','flow_property_uuid','flow_property_version','unit_group_uuid',
             'unit_group_version','unit','direction','compartment')}))
    node['outputs'] = [product,*emissions]
    delivery=deepcopy(node)
    delivery.update(id='delivery',process_uuid=str(uuid.uuid4()),name='Lossless synthetic material delivery')
    delivery['outputs']=[deepcopy(product)]
    input_port=deepcopy(product);input_port.update(id='material-in',direction='input',isProduct=False)
    delivery['inputs']=[input_port]
    edge=dict(id='supplier-delivery',fromNode='supplier',toNode='delivery',sourcePortId='product',targetPortId='material-in',
        sourceHandle='out:product',targetHandle='in:material-in',flowUuid=product['flowUuid'],flowName=product['name'],
        amount=1.0,unit=product['unit'],quantityMode='single',type='technosphere')
    source = dict(nodes=[node,delivery],exchanges=[edge],metadata={'elementary_flow_refs':refs},functionalUnit='1 kg synthetic material')
    project = L._request(engine,'POST','/api/projects',dict(name='Synthetic Scope3 supplier '+tag,
        reference_product=product['name'], functional_unit=source['functionalUnit']))['project_id']
    version = L._request(engine,'POST',f'/api/projects/{project}/versions',{'graph':source})['version']
    prefix = f'/api/v1/applications/{app}'
    material_path = 'ore-sintering::iron-ore-in'
    pins = []
    for path,pid,v in ((material_path,project,version),('ore-sintering::grid-electricity-in',identities['supply']['supply_project'],identities['supply']['supply_version'])):
        pins.append(L._request(base,'POST',f'{prefix}/workspace/{rev}/background/user-project-resolve',
            dict(consumer_exchange_id=path,project_id=pid,version=v))['pin'])
    ws = L._request(base,'GET',f'{prefix}/workspace/{rev}')
    saved = L._request(base,'POST',prefix+'/workspace/inputs',dict(revision_id=rev,expected_content_sha256=ws['content_sha256'],
        amounts=[7],demand_mode='reference_output',values={f['key']:f['value'] for f in ws['fields']},
        source='Synthetic supplier inventory acceptance '+tag,project_background_pins=pins))
    revision=saved['revision_id']
    baseline=L._request(base,'POST',f'{prefix}/system-revisions/{revision}/solve',dict(demand=saved['demand'],
        analysis_task='organization',calculation_purpose='lca',climate_default=True,project_background_pins=pins))
    indicator,terms=L._climate_terms(baseline)
    rules=[L._rule(t['exchange_id'],boundary_status='selected') for t in terms if t['attribution_basis']=='foreground_direct']
    rules += [L._rule('ore-sintering::grid-electricity-in',boundary_status='selected',scope='scope_2',location_role='purchased_energy',direction='input'),
        L._rule(material_path,boundary_status='selected',scope='scope_3',location_role='upstream_supply',direction='input')]
    for rule in rules:
        rule['categories']={'supplier_group':'line_a'};rule['schema_version']=2
        if rule['direction']=='input': rule['contribution_target']='upstream'
    dimensions=[dict(id='supplier_group',name='供应链分组',categories=[dict(id='line_a',name='材料组 A',is_leaf=True),dict(id='line_b',name='材料组 B',is_leaf=True)])]
    created=L._request(base,'POST',prefix+'/calculation-methods',dict(name='Scope3 real rules '+tag,purpose='organization',
        model_revision_id=revision,rules=rules,reporting_dimensions=dimensions))
    expected={scope:sum(t['value'] for t in terms if (t['attribution_basis']=='foreground_direct' if scope=='scope_1' else t.get('consumer_exchange_id')==path))
        for scope,path in (('scope_1',None),('scope_2','ore-sintering::grid-electricity-in'),('scope_3',material_path))}
    cf=next(r for r in baseline['lcia_results']['indicator_contribution_receipts'] if r['canonical_indicator_key']==indicator)
    supplier_ids={r['source_process_uuid'] for r in baseline['provider_receipt']['project_background_process_receipts']
                  if r['pin']['consumer_exchange_id']==material_path}
    supplier_terms=[t for t in cf['terms'] if t['process_uuid'] in supplier_ids]
    assert len(supplier_terms)==2 and all(t['cf_presence']=='explicit_nonzero' and t['cf_hash']
        and t['cf_runtime_assets_hash'] and t['cf_method']=='EF v3.1' for t in supplier_terms)
    assert len(supplier_ids)==2, 'both closed-network nodes must be traced to the same consumption pin'
    import math
    consumer_amount=next(r['amount'] for r in baseline['scaled_technosphere_exchanges'] if r['exchange_id']==material_path)
    amounts={flow_refs[0]['flow_uuid']:10.0,flow_refs[1]['flow_uuid']:0.1}
    independent=sum(consumer_amount*amounts[t['flow_uuid']]*t['cf_value'] for t in supplier_terms)
    assert math.isclose(expected['scope_3'],independent,rel_tol=1e-9,abs_tol=1e-9)
    result=dict(base=base,engine=engine,application_id=app,model_id=identities['demo']['model_id'],revision_id=revision,method_id=created['method']['id'],
        method_name=created['method']['name'],material_path=material_path,demand=saved['demand'],expected=expected,
        supplier=dict(project_id=project,version=version,inventory={'co2':10.0,'ch4':0.1,'product':1.0}),
        pins=pins,baseline_snapshot=baseline['id'],factor_terms=supplier_terms,independent_scope3=independent)
    output.mkdir(parents=True,exist_ok=True)
    (output/'scope3-fixture.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('application_id','revision_id','method_id','expected')},ensure_ascii=False))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--one',required=True);parser.add_argument('--lca',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();prepare(args.one,args.lca,args.output)
