"""Same single-process LCA model, independently selected CO2/CH4 accounting boundaries.

Artificial acceptance quantities, NOT a measured facility inventory or regulatory CBAM claim.
Factors and weighted contributions come exclusively from the live EF runtime.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import math

from live_user_method_acceptance import _request, _create_validate_method, _pcf, _rule


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--one', default='http://127.0.0.1:18938')
    parser.add_argument('--lca', default='http://127.0.0.1:18931')
    parser.add_argument('--output', default='.local-evidence/gas-boundary')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    tag = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    refs = [dict(source_namespace='tiangong_open_data', flow_uuid=uuid, version='03.00.004')
        for uuid in ('08a91e70-3ddc-11dd-923d-0050c2490048', '08a91e70-3ddc-11dd-9610-0050c2490048')]
    resolution = _request(args.lca, 'POST', '/api/provider/v1/catalog/resolve', {'flows': refs})
    assert all(item['status'] == 'resolved' for item in resolution['items']), resolution
    identities = {item['value']['flow_uuid']: item['value'] for item in resolution['items']}
    seed = json.loads(Path('cases/standard-lca-seeds/iron-steel-bf-bof-crude-steel/model/graph.json').read_text(encoding='utf-8'))['graph']
    product = deepcopy(next(port for node in seed['nodes'] for port in node['outputs'] if port.get('isProduct')))
    product.update(id='product', amount=1.0)
    emissions, elementary_refs = [], []
    for gas, ref, amount in zip(('co2', 'ch4'), refs, (10.0, 0.1)):
        flow = identities[ref['flow_uuid']]
        emissions.append({'id': gas, 'flowUuid': flow['flow_uuid'], 'flowSourceNamespace': flow['source_namespace'],
            'flowVersion': flow['version'], 'flowPropertyUuid': flow['flow_property_uuid'],
            'flowPropertyVersion': flow['flow_property_version'], 'unitGroupUuid': flow['unit_group_uuid'],
            'unitGroupVersion': flow['unit_group_version'], 'unit': flow['unit'], 'unitGroup': flow['unit_group'],
            'name': flow['name_en'], 'amount': amount, 'type': 'biosphere', 'direction': 'output', 'isProduct': False})
        elementary_refs.append({'exchange_id': 'unit-process::' + gas, **ref,
            **{key: flow[key] for key in ('flow_property_uuid', 'flow_property_version',
                'unit_group_uuid', 'unit_group_version', 'unit', 'direction', 'compartment')}})
    node = deepcopy(seed['nodes'][-1])
    node.update(id='unit-process', name='CO2 and CH4 boundary acceptance', dataMode='normalized',
        inputs=[], outputs=[product, *emissions], position={'x': 0, 'y': 0})
    graph = {'nodes': [node], 'exchanges': [], 'metadata': {'elementary_flow_refs': elementary_refs},
        'functionalUnit': '1 kg acceptance product'}
    application = _request(args.one, 'POST', '/api/v1/applications', {
        'name': 'Gas boundary acceptance ' + tag, 'application_type': 'system_analysis',
        'description': 'Artificial single-process mechanism test; not a facility or CBAM compliance result', 'context': {}})
    app_id = application['id']
    model = _request(args.one, 'POST', f'/api/v1/applications/{app_id}/system-models/inline', {
        'name': 'Single process with CO2 and CH4', 'provider': 'nebula_lca',
        'source_id': 'acceptance:co2-ch4:' + tag, 'source_version': 1,
        'expected_graph_sha256': digest(graph), 'graph': graph})
    revision_id = model['upstream_receipt']['base_revision_id']
    demand = [{'reference_flow_uuid': product['flowUuid'], 'amount': 1.0, 'unit': product['unit'],
        'unit_group_uuid': product['unitGroupUuid'], 'unit_group_version': product['unitGroupVersion']}]
    snapshots = {}
    results = {}
    method_refs = {}
    for label, included in (('both', {'co2', 'ch4'}), ('co2_only', {'co2'}), ('ch4_only', {'ch4'})):
        rules = [_rule('unit-process::' + gas, boundary_status='selected' if gas in included else 'excluded')
            for gas in ('co2', 'ch4')]
        ref = _create_validate_method(args.one, app_id, revision_id, 'Boundary ' + label, 'pcf', rules)
        method_refs[label] = {key: ref[key] for key in ('method_id', 'version', 'content_sha256')}
        snap = _request(args.one, 'POST', f'/api/v1/applications/{app_id}/system-revisions/{revision_id}/solve', {
            'demand': demand, 'analysis_task': 'pcf', 'climate_default': True,
            'calculation_method_ref': method_refs[label], 'idempotency_key': tag + '-' + label})
        snapshots[label] = snap
        persisted = next(item for item in _request(args.one, 'GET', f'/api/v1/applications/{app_id}/solved-system-snapshots')
            if item['id'] == snap['id'])
        assert persisted['content_sha256'] == snap['content_sha256']
        assert persisted['provider_receipt']['user_calculation_method']['content_sha256'] == method_refs[label]['content_sha256']
        default = _request(args.one, 'GET', f"/api/v1/solved-system-snapshots/{snap['id']}/product-carbon-footprint/default-method")
        results[label] = _pcf(args.one, snap['id'], default['reference'])
        (out / (label + '-snapshot.json')).write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding='utf-8')
        (out / (label + '-pcf.json')).write_text(json.dumps(results[label], ensure_ascii=False, indent=2), encoding='utf-8')

    receipt = next(row for row in snapshots['both']['lcia_results']['path_weighted_contribution_receipts']
        if row['canonical_indicator_key'].startswith('climate change|'))
    terms = {term['exchange_id']: term['path_contribution_value'] for term in receipt['terms']}
    assert set(terms) == {'unit-process::co2', 'unit-process::ch4'}, terms
    co2, ch4 = terms['unit-process::co2'], terms['unit-process::ch4']
    assert co2 > 0 and ch4 > 0
    cf_receipt = next(row for row in snapshots['both']['lcia_results']['indicator_contribution_receipts']
        if row['canonical_indicator_key'] == receipt['canonical_indicator_key'])
    cf_terms = {row['exchange_id']: row for row in cf_receipt['terms']}
    assert set(cf_terms) == set(terms)
    for exchange_id, amount in (('unit-process::co2', 10.0), ('unit-process::ch4', 0.1)):
        row = cf_terms[exchange_id]
        assert row['cf_presence'] == 'explicit_nonzero' and row['cf_hash'] and row['cf_runtime_assets_hash']
        assert row['cf_method'] == 'EF v3.1'
        assert math.isclose(row['amount'], amount, rel_tol=1e-9, abs_tol=1e-9)
        assert math.isclose(amount * row['cf_value'], terms[exchange_id], rel_tol=1e-9, abs_tol=1e-9)
    summary = {}
    checks = []

    def close(actual, expected, name):
        assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9), (name, actual, expected)
        checks.append(name)

    for label, expected in (('both', co2 + ch4), ('co2_only', co2), ('ch4_only', ch4)):
        result = results[label]
        grouping = result['contribution_analysis']['user_method_grouping']
        assert grouping['grouping_mode'] == 'path_weighted'
        assert grouping['execution_status'] == 'executed_full'
        counts = grouping['grouping']
        assert counts['reconciled'] and not counts['coverage_gaps']
        assert not counts['unattributed']['exchange_ids']
        counted = sum(bucket['value'] for bucket in counts['scopes'].values() if bucket['value'] is not None)
        close(counted, expected, label + '_counted')
        close(counts['excluded']['value'], co2 + ch4 - expected, label + '_excluded')
        close(result['total_footprint']['value'], co2 + ch4, label + '_physical_lca_unchanged')
        assert snapshots[label]['system_revision_id'] == revision_id
        assert snapshots[label]['scaled_elementary_exchanges'] == snapshots['both']['scaled_elementary_exchanges']
        assert snapshots[label]['provider_receipt']['user_calculation_method']['content_sha256'] == method_refs[label]['content_sha256']
        summary[label] = {'counted': counted, 'excluded': counts['excluded']['value'],
            'physical_lca_total': result['total_footprint']['value'], 'snapshot_id': snapshots[label]['id']}
    close(summary['both']['counted'] - summary['co2_only']['counted'], ch4, 'exclude_ch4_delta')
    close(summary['both']['counted'] - summary['ch4_only']['counted'], co2, 'exclude_co2_delta')
    assert len({snap['id'] for snap in snapshots.values()}) == 3
    baseline = _request(args.one, 'POST', f'/api/v1/applications/{app_id}/system-revisions/{revision_id}/solve', {
        'demand': demand, 'analysis_task': 'pcf', 'climate_default': True,
        'idempotency_key': tag + '-no-user-method'})
    default = _request(args.one, 'GET', f"/api/v1/solved-system-snapshots/{baseline['id']}/product-carbon-footprint/default-method")
    baseline_pcf = _pcf(args.one, baseline['id'], default['reference'])
    close(baseline_pcf['total_footprint']['value'], co2 + ch4, 'no_user_method_baseline')
    assert not baseline['provider_receipt'].get('user_calculation_method')
    doubled = _request(args.one, 'POST', f'/api/v1/applications/{app_id}/system-revisions/{revision_id}/solve', {
        'demand': [{**demand[0], 'amount': 2.0}], 'analysis_task': 'pcf', 'climate_default': True,
        'calculation_method_ref': method_refs['both'], 'idempotency_key': tag + '-double'})
    doubled_receipt = next(row for row in doubled['lcia_results']['path_weighted_contribution_receipts']
        if row['canonical_indicator_key'] == receipt['canonical_indicator_key'])
    doubled_terms = {row['exchange_id']: row['path_contribution_value'] for row in doubled_receipt['terms']}
    close(doubled_terms['unit-process::co2'], co2 * 2, 'co2_demand_doubles_once')
    close(doubled_terms['unit-process::ch4'], ch4 * 2, 'ch4_demand_doubles_once')
    doubled_pcf = _pcf(args.one, doubled['id'], default['reference'])
    close(doubled_pcf['total_footprint']['value'], (co2 + ch4) * 2, 'batch_footprint_doubles_once')
    close(doubled_pcf['total_footprint']['value'] / 2, co2 + ch4, 'per_kg_footprint_unchanged')
    (out / 'doubled-snapshot.json').write_text(json.dumps(doubled, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'baseline-pcf.json').write_text(json.dumps(baseline_pcf, ensure_ascii=False, indent=2), encoding='utf-8')
    report = {'passed': True, 'application_id': app_id, 'model_revision_id': revision_id,
        'graph_sha256': digest(graph), 'quantities': {'product_kg': 1, 'co2_kg': 10, 'ch4_kg': 0.1},
        'effective_runtime_factors': {'co2': cf_terms['unit-process::co2']['cf_value'],
            'ch4': cf_terms['unit-process::ch4']['cf_value']},
        'factor_evidence': {gas: {key: cf_terms['unit-process::' + gas][key]
            for key in ('cf_hash', 'cf_runtime_assets_hash', 'cf_method', 'cf_version', 'flow_uuid', 'flow_version')}
            for gas in ('co2', 'ch4')},
        'factor_source': 'live EF 3.1 characterized contribution receipt; not user-defined factors',
        'results': summary, 'checks': checks}
    report['method_references'] = method_refs
    report['provider_commit'] = cf_receipt['provider_commit']
    report['invariants'] = ['one exact model revision', 'one process with two gas exchanges',
        'same inventory under all three rules', 'same EF runtime and factor hashes',
        'distinct persisted snapshots and method identities', 'counted plus excluded reconciles',
        'no emission quantity or factor rewritten by selection']
    (out / 'model.json').write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'flow-resolution.json').write_text(json.dumps(resolution, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'manifest.json').write_text(json.dumps({path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(out.glob('*.json')) if path.name != 'manifest.json'}, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
