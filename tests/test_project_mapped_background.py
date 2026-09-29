from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.mapped_background_schemas import ProviderMappedBackgroundProcessPin
from nebula_one.services.mapped_background_receipts import validate_mapped_receipts
from nebula_one.services.project_mapped_background import MappedBackgroundSelection, ProjectMappedBackgroundService


def fixture():
    # Synthetic identities and metadata only; no licensed inventory in this fixture.
    mapping = dict(source_flow_namespace='tiangong_open_data', source_flow_uuid='synthetic-power',
                   source_flow_version='01.00.000', source_unit='MJ', target_flow_uuid='synthetic-target',
                   target_unit='kWh', amount_factor=1/3.6, mapping_level='L2', rule_id='test-rule',
                   package_id='test-mapping', package_version='1.0.0', package_hash='a'*64)
    port = dict(id='power', type='technosphere', amount=36, flowSourceNamespace='tiangong_open_data',
                flowUuid='synthetic-power', flowVersion='01.00.000', unit='MJ')
    graph = {'nodes': [{'id': 'steel', 'inputs': [port]}], 'exchanges': []}
    provider = dict(process_uuid='synthetic-provider', process_name='Synthetic power', location='test',
                    database_release='synthetic-1', process_content_hash='b'*64, vector_checksum='c'*64,
                    has_lci_vector=True, reference_product_flow_uuid='synthetic-target', reference_product_unit='kWh')
    def resolve(payload):
        assert payload['include_unreviewed_candidates'] is False
        return SimpleNamespace(payload={**{k: mapping[k] for k in ('package_id', 'package_version', 'package_hash')},
            'items': [{'node_id': 'steel', 'port_id': 'power', 'status': 'L2', 'resolution': mapping}]})
    client = SimpleNamespace(resolve_flow_mapping=resolve, mapped_provider_candidates=lambda _: SimpleNamespace(
        payload={'target_flow_uuid': 'synthetic-target', 'providers': [provider]}))
    selection = MappedBackgroundSelection(consumer_exchange_id='steel::power', process_uuid='synthetic-provider',
        expected_mapping_package_hash='a'*64, confirmed=True)
    return ProjectMappedBackgroundService(client), graph, selection, mapping, provider


def test_mapping_confirmation_exact_pins_and_content_drift():
    service, graph, selection, mapping, provider = fixture()
    with pytest.raises(DomainError) as error:
        service.resolve(graph, selection.model_copy(update={'confirmed': False}))
    assert error.value.code == 'PROJECT_MAPPING_CONFIRMATION_REQUIRED'
    pin = ProviderMappedBackgroundProcessPin.model_validate(service.resolve(graph, selection)['pin'])
    assert pin.amount_factor == 1/3.6
    service.validate(graph, [pin])
    provider['process_content_hash'] = 'd'*64
    with pytest.raises(DomainError) as error:
        service.validate(graph, [pin])
    assert error.value.code == 'PROJECT_BACKGROUND_PIN_CHANGED'
    mapping['package_hash'] = 'e'*64
    with pytest.raises(DomainError) as error:
        service.resolve(graph, selection)
    assert error.value.code == 'PROJECT_MAPPING_CHANGED'


def test_mapping_missing_target_is_a_recoverable_error():
    service, graph, selection, mapping, _ = fixture()
    mapping.pop('target_flow_uuid')
    with pytest.raises(DomainError) as error:
        service.resolve(graph, selection)
    assert error.value.code == 'PROJECT_MAPPING_RESPONSE_INVALID'


@pytest.mark.parametrize('mutation,code', [
    ('custom', 'PROJECT_BACKGROUND_MAPPING_REQUIRED'), ('source', 'PROJECT_MAPPING_IDENTITY_MISMATCH'),
    ('unit', 'PROJECT_BACKGROUND_DATA_UNAVAILABLE'), ('vector', 'PROJECT_BACKGROUND_DATA_UNAVAILABLE'),
    ('manual', 'PROJECT_MAPPING_UNAVAILABLE'),
])
def test_unusable_provider_is_never_approved(mutation, code):
    service, graph, selection, mapping, provider = fixture()
    if mutation == 'custom': graph['nodes'][0]['inputs'][0]['flowSourceNamespace'] = 'custom'
    if mutation == 'source': mapping['source_flow_version'] = '02.00.000'
    if mutation == 'unit': provider['reference_product_unit'] = 'kg'
    if mutation == 'vector': provider['has_lci_vector'] = False
    if mutation == 'manual': mapping['requires_manual_factor'] = True
    with pytest.raises(DomainError) as error:
        service.resolve(graph, selection)
    assert error.value.code == code


def receipt_fixture():
    service, graph, selection, _, _ = fixture()
    pin = ProviderMappedBackgroundProcessPin.model_validate(service.resolve(graph, selection)['pin'])
    receipt = pin.model_dump(mode='json')
    receipt.update(schema_version='provider.mapped-background-process-receipt.v1',
        process_content_hash=receipt.pop('expected_process_content_hash'), vector_checksum=receipt.pop('expected_vector_checksum'),
        claim_limit='partial_background_leaf_only_not_complete_cradle_to_gate', vector_nnz=1,
        quantitative_reference_amount=1, activity_amount=10, process_scale=10)
    result = dict(mapped_background_process_receipts=[receipt], activity_vector=[dict(process_uuid=pin.process_uuid, activity_amount=10)],
        provenance={'mapped_background_process_pins_hash': canonical_json_sha256([pin.model_dump(mode='json')])})
    return graph, pin, result


@pytest.mark.parametrize('mutation', [None, 'sum', 'conversion', 'instance', 'legacy', 'consumer', 'scale', 'nan'])
def test_shared_provider_receipts_reconcile_consumers(mutation):
    graph, pin, result = receipt_fixture()
    graph['nodes'][0]['process_uuid'] = 'steel-process'
    port = graph['nodes'][0]['inputs'][0]
    port['amount'] = 12
    graph['nodes'].append(dict(id='casting', process_uuid='casting-process', inputs=[dict(port, amount=24)]))
    other = pin.model_copy(update={'consumer_exchange_id': 'casting::power'})
    first = result['mapped_background_process_receipts'][0]
    first.update(shared_activity_schema_version='provider.mapped-background-shared-activity.v1',
        provider_instance_id='shared-provider', consumer_process_uuid='steel-process',
        consumer_converted_amount=10/3, consumer_attributed_activity_amount=10/3,
        shared_process_total_activity_amount=10, attributed_process_scale=10/3)
    second = dict(first, consumer_exchange_id='casting::power', consumer_process_uuid='casting-process',
                  consumer_converted_amount=20/3, consumer_attributed_activity_amount=20/3, attributed_process_scale=20/3)
    result['mapped_background_process_receipts'].append(second)
    result['provenance']['mapped_background_process_pins_hash'] = canonical_json_sha256(
        [p.model_dump(mode='json') for p in sorted([pin, other], key=lambda p: p.consumer_exchange_id)])
    if mutation == 'sum':
        second.update(consumer_attributed_activity_amount=7, attributed_process_scale=7)
    if mutation == 'conversion': second['consumer_converted_amount'] = 8
    if mutation == 'instance': second['provider_instance_id'] = 'different-instance'
    if mutation == 'legacy': second.pop('shared_activity_schema_version')
    if mutation == 'consumer': second['consumer_process_uuid'] = 'steel-process'
    if mutation == 'scale': second['attributed_process_scale'] = 8
    if mutation == 'nan': second['consumer_attributed_activity_amount'] = float('nan')
    if mutation:
        with pytest.raises(DomainError, match='.') as error:
            validate_mapped_receipts(result, [pin, other], graph)
        assert error.value.code == 'PROVIDER_MAPPED_BACKGROUND_RECEIPT_INVALID'
    else:
        receipts = validate_mapped_receipts(result, [pin, other], graph)
        assert sum(r['consumer_attributed_activity_amount'] for r in receipts) == 10


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'hash', 'scale', 'activity', 'provenance', 'source'])
def test_mapped_receipt_cannot_freeze_inconsistent_evidence(mutation):
    graph, pin, result = receipt_fixture()
    assert validate_mapped_receipts(result, [pin], graph) == result['mapped_background_process_receipts']
    if mutation == 'missing': result['mapped_background_process_receipts'] = []
    if mutation == 'duplicate': result['mapped_background_process_receipts'] *= 2
    if mutation == 'hash': result['mapped_background_process_receipts'][0]['vector_checksum'] = 'd'*64
    if mutation == 'scale': result['mapped_background_process_receipts'][0]['process_scale'] = 9
    if mutation == 'activity': result['activity_vector'][0]['activity_amount'] = 9
    if mutation == 'provenance': result['provenance'] = {}
    if mutation == 'source': graph['nodes'][0]['inputs'][0]['flowVersion'] = '02.00.000'
    with pytest.raises(DomainError) as error:
        validate_mapped_receipts(result, [pin], graph)
    assert error.value.code == 'PROVIDER_MAPPED_BACKGROUND_RECEIPT_INVALID'


def test_unrequested_receipt_and_unconfirmed_pin_rejected():
    graph, pin, result = receipt_fixture()
    with pytest.raises(DomainError):
        validate_mapped_receipts(result, [], graph)
    with pytest.raises(ValidationError):
        ProviderMappedBackgroundProcessPin.model_validate({**pin.model_dump(), 'mapping_status': 'auto'})


def test_solve_forwards_mapping_and_freezes_receipts_for_readback(client, model_graph, monkeypatch, upstream_requests):
    from test_api_flow import _attach_model, _create_application
    from nebula_one.services.provider_solve import _graph_technosphere_exchanges
    _, pin, result = receipt_fixture()
    pin = pin.model_copy(update={'consumer_exchange_id': 'preparation::ore-in', 'source_flow_uuid': 'flow-ore', 'source_unit': 'kg'})
    port = model_graph['nodes'][0]['inputs'][0]
    port.update(flowSourceNamespace='tiangong_open_data', flowVersion=pin.source_flow_version)
    app = _create_application(client)
    model = _attach_model(client, app['id'])
    engine = client.app.state.container.client
    original = engine.solve_provider
    def solve(payload):
        assert payload['mapped_background_process_pins'] == [pin.model_dump(mode='json')]
        response = original(payload)
        body = response.payload
        receipt = result['mapped_background_process_receipts'][0].copy()
        receipt.update(consumer_exchange_id=pin.consumer_exchange_id, source_flow_uuid=pin.source_flow_uuid, source_unit='kg')
        body['mapped_background_process_receipts'] = [receipt]
        body['provenance']['mapped_background_process_pins_hash'] = canonical_json_sha256([pin.model_dump(mode='json')])
        body['technosphere_flow_receipts'] = [{'exchange_id': exchange_id, **identity, 'resolution': 'tidas_exact_snapshot' if identity['source_namespace'] == 'tiangong_open_data' else 'inline_custom',
            **{k: 'f'*64 for k in ('content_hash', 'snapshot_hash', 'flow_property_content_hash', 'unit_group_content_hash', 'unit_content_hash')}}
            for exchange_id, identity in _graph_technosphere_exchanges(model_graph).items()]
        return response
    monkeypatch.setattr(engine, 'solve_provider', solve)
    rid = model['upstream_receipt']['base_revision_id']
    response = client.post(f"/api/v1/applications/{app['id']}/system-revisions/{rid}/solve", json={
        'demand': [{'reference_flow_uuid': 'flow-product', 'amount': 1, 'unit': 'kg'}],
        'mapped_background_process_pins': [pin.model_dump(mode='json')]})
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved['provider_receipt']['calculation_basis']['mapped_background_process_pins'] == [pin.model_dump(mode='json')]
    before = len(upstream_requests)
    reread = client.get(f"/api/v1/applications/{app['id']}/solved-system-snapshots").json()
    assert next(s for s in reread if s['id'] == saved['id'])['content_sha256'] == saved['content_sha256']
    assert len(upstream_requests) == before
