from types import SimpleNamespace

import pytest

from nebula_one.errors import DomainError
from nebula_one.runtime_schemas import ProviderBackgroundProcessPin
from nebula_one.services.project_background import BackgroundSelection, ProjectBackgroundService


def fixture():
    flow = dict(source_namespace='tiangong_open_data', flow_uuid='flow-1', version='01.00.000',
                flow_property_uuid='property', flow_property_version='01.00.000',
                unit_group_uuid='group', unit_group_version='01.00.000', unit='kg', flow_type='Product flow')
    elementary = {**flow, 'flow_uuid': 'co2', 'flow_type': 'Elementary flow'}
    port = dict(id='input', type='technosphere', amount=2, flowSourceNamespace=flow['source_namespace'],
                flowUuid=flow['flow_uuid'], flowVersion=flow['version'], flowPropertyUuid='property',
                flowPropertyVersion='01.00.000', unitGroupUuid='group', unitGroupVersion='01.00.000', unit='kg')
    graph = {'nodes': [{'id': 'process', 'inputs': [port]}], 'exchanges': []}
    ref = lambda f: {k: f[k] for k in ('source_namespace', 'flow_uuid', 'version')}
    process = {'source_namespace': 'tiangong_open_data', 'process_uuid': '00000000-0000-4000-8000-000000000001', 'version': '01.00.000',
               'content_hash': 'a'*64, 'snapshot_hash': 'b'*64, 'name': 'Reviewed leaf',
               'quantitative_reference': {'exchange_internal_id': '0', 'flow': ref(flow)},
               'exchanges': [{'exchange_internal_id': '0', 'flow': ref(flow)}, {'exchange_internal_id': '1', 'flow': ref(elementary)}]}
    def resolve(payload):
        if 'processes' in payload:
            return SimpleNamespace(payload={'items': [{'kind': 'process', 'key': payload['processes'][0], 'status': 'resolved', 'value': process}]})
        assert set(payload) == {'flows'}
        return SimpleNamespace(payload={'items': [{'kind': 'flow', 'key': r, 'status': 'resolved', 'value': flow if r['flow_uuid'] == 'flow-1' else elementary} for r in payload['flows']]})
    service = ProjectBackgroundService(SimpleNamespace(resolve_provider_catalog=resolve))
    selection = BackgroundSelection(consumer_exchange_id='process::input', process_uuid='00000000-0000-4000-8000-000000000001', version='01.00.000')
    return service, graph, selection, flow, elementary, process


def test_exact_leaf_pin_is_revalidated_and_content_drift_refused():
    service, graph, selection, _, _, process = fixture()
    answer = service.resolve(graph, selection)
    pin = ProviderBackgroundProcessPin.model_validate(answer['pin'])
    service.validate(graph, [pin])
    assert pin.expected_process_content_hash == 'a'*64
    process['content_hash'] = 'c'*64
    with pytest.raises(DomainError) as error:
        service.validate(graph, [pin])
    assert error.value.code == 'PROJECT_BACKGROUND_PIN_CHANGED'


@pytest.mark.parametrize('mutation,code', [
    ('namespace', 'PROJECT_BACKGROUND_MAPPING_REQUIRED'),
    ('unit', 'PROJECT_BACKGROUND_FLOW_MISMATCH'),
    ('product', 'PROJECT_BACKGROUND_FLOW_MISMATCH'),
    ('dependency', 'PROJECT_BACKGROUND_DEPENDENCIES_OPEN'),
    ('connected', 'PROJECT_BACKGROUND_PORT_INVALID'),
])
def test_incompatible_or_unresolved_background_is_not_saved(mutation, code):
    service, graph, selection, flow, elementary, _ = fixture()
    if mutation == 'namespace': graph['nodes'][0]['inputs'][0]['flowSourceNamespace'] = 'custom'
    if mutation == 'unit': flow['unit'] = 'MJ'
    if mutation == 'product': graph['nodes'][0]['inputs'][0]['flowVersion'] = '02.00.000'
    if mutation == 'dependency': elementary['flow_type'] = 'Product flow'
    if mutation == 'connected': graph['exchanges'] = [{'toNode': 'process', 'targetPortId': 'input'}]
    with pytest.raises(DomainError) as error:
        service.resolve(graph, selection)
    assert error.value.code == code
