"""Select publicly mapped local providers without copying licensed inventories."""
from pydantic import BaseModel, ConfigDict, Field

from ..mapped_background_schemas import ProviderMappedBackgroundProcessPin
from .project_background import background_ports, refuse


class MappedBackgroundSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    consumer_exchange_id: str = Field(min_length=1)
    process_uuid: str = Field(min_length=1)
    expected_mapping_package_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmed: bool = False


class ProjectMappedBackgroundService:
    def __init__(self, client):
        self.client = client

    def candidates(self, graph, consumer_id):
        matches = [(n, p) for n, p in background_ports(graph) if f"{n['id']}::{p['id']}" == consumer_id]
        if len(matches) != 1 or matches[0][1].get('amount', 0) <= 0:
            refuse('PROJECT_BACKGROUND_PORT_INVALID', '请选择数量大于零的外购投入。')
        node, port = matches[0]
        if port.get('flowSourceNamespace') != 'tiangong_open_data':
            refuse('PROJECT_BACKGROUND_MAPPING_REQUIRED', '当前模板的投入尚无可供跨库映射的标准流身份，请先更新模板。')
        source = {'source_flow_uuid': port.get('flowUuid'), 'source_flow_namespace': port.get('flowSourceNamespace'),
                  'source_flow_version': port.get('flowVersion'), 'source_unit': port.get('unit')}
        answer = self.client.resolve_flow_mapping({'items': [{
            'node_id': node['id'], 'port_id': port['id'], 'flow_uuid': source['source_flow_uuid'],
            'flow_source_namespace': source['source_flow_namespace'], 'flow_version': source['source_flow_version'],
            'unit': source['source_unit'], 'unit_group': port.get('unitGroup'),
            'direction': 'input', 'exchange_type': 'technosphere',
        }], 'include_unreviewed_candidates': False}).payload
        items = answer.get('items')
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            refuse('PROJECT_MAPPING_RESPONSE_INVALID', '映射目录未返回唯一的投入身份。')
        item = items[0]
        mapping = item.get('resolution')
        if item.get('status') not in ('L1', 'L2') or not isinstance(mapping, dict) or mapping.get('requires_manual_factor'):
            refuse('PROJECT_MAPPING_UNAVAILABLE', '尚无可直接使用的正式映射，或仍需核实换算依据。')
        if item.get('node_id') != node['id'] or item.get('port_id') != port['id'] or any(mapping.get(k) != v or not v for k, v in source.items()):
            refuse('PROJECT_MAPPING_IDENTITY_MISMATCH', '映射返回的源流身份与当前清单不一致。')
        if any(mapping.get(k) != answer.get(k) for k in ('package_id', 'package_version', 'package_hash')):
            refuse('PROJECT_MAPPING_IDENTITY_MISMATCH', '映射规则与映射包版本不一致。')
        if not all(mapping.get(k) for k in ('target_flow_uuid', 'target_unit', 'rule_id', 'package_id', 'package_version', 'package_hash')):
            refuse('PROJECT_MAPPING_RESPONSE_INVALID', '映射目录缺少完整的目标流或版本依据。')
        if mapping.get('mapping_level') != item['status']:
            refuse('PROJECT_MAPPING_IDENTITY_MISMATCH', '映射规则与审核等级不一致。')
        catalog = self.client.mapped_provider_candidates(mapping['target_flow_uuid']).payload
        if catalog.get('target_flow_uuid') != mapping['target_flow_uuid'] or not isinstance(catalog.get('providers'), list):
            refuse('PROJECT_MAPPING_IDENTITY_MISMATCH', '背景候选不属于映射后的产品流。')
        providers = []
        for provider in catalog['providers']:
            if not isinstance(provider, dict) or provider.get('reference_product_flow_uuid') != mapping['target_flow_uuid']:
                refuse('PROJECT_MAPPING_IDENTITY_MISMATCH', '背景候选的参考产品与映射不一致。')
            # Return catalog metadata only, never a proprietary Process inventory/vector.
            metadata = {k: provider.get(k) for k in ('process_uuid', 'process_name', 'location', 'database_release',
                'process_content_hash', 'vector_checksum', 'has_lci_vector', 'reference_product_unit')}
            metadata['executable'] = (provider.get('has_lci_vector') is True
                                      and provider.get('reference_product_unit') == mapping.get('target_unit'))
            try:
                self._pin(consumer_id, mapping, provider, confirmed=True)
            except (ValueError, TypeError, KeyError):
                metadata['executable'] = False
            providers.append(metadata)
        return {'consumer_exchange_id': consumer_id, 'mapping': mapping, 'providers': providers,
                'requires_confirmation': mapping.get('mapping_level') == 'L2', 'claim_role': 'partial_background_leaf'}

    @staticmethod
    def _pin(consumer_id, mapping, provider, confirmed):
        return ProviderMappedBackgroundProcessPin(consumer_exchange_id=consumer_id,
            **{k: mapping[k] for k in ('source_flow_namespace', 'source_flow_uuid', 'source_flow_version',
                'source_unit', 'target_flow_uuid', 'target_unit', 'amount_factor', 'mapping_level')},
            mapping_status='user_confirmed' if confirmed else 'auto', mapping_rule_id=mapping['rule_id'],
            mapping_package_id=mapping['package_id'], mapping_package_version=mapping['package_version'],
            mapping_package_hash=mapping['package_hash'], database_release=provider.get('database_release'),
            process_uuid=provider['process_uuid'], expected_process_content_hash=provider.get('process_content_hash'),
            expected_vector_checksum=provider.get('vector_checksum'))

    def resolve(self, graph, selection):
        answer = self.candidates(graph, selection.consumer_exchange_id)
        if answer['mapping']['package_hash'] != selection.expected_mapping_package_hash:
            refuse('PROJECT_MAPPING_CHANGED', '映射包已改变，请重新查询并确认。')
        if answer['requires_confirmation'] and not selection.confirmed:
            refuse('PROJECT_MAPPING_CONFIRMATION_REQUIRED', '请确认此映射的适用性后再关联。')
        matches = [p for p in answer['providers'] if p['process_uuid'] == selection.process_uuid and p['executable']]
        if len(matches) != 1:
            refuse('PROJECT_BACKGROUND_DATA_UNAVAILABLE', '当前本地数据缺少该背景过程或可执行的精确清单。')
        pin = self._pin(selection.consumer_exchange_id, answer['mapping'], matches[0], selection.confirmed)
        return {'pin': pin.model_dump(mode='json'), 'name': matches[0]['process_name']}

    def validate(self, graph, pins):
        for pin in pins:
            answer = self.resolve(graph, MappedBackgroundSelection(consumer_exchange_id=pin.consumer_exchange_id,
                process_uuid=pin.process_uuid, expected_mapping_package_hash=pin.mapping_package_hash,
                confirmed=pin.mapping_status == 'user_confirmed'))
            if answer['pin'] != pin.model_dump(mode='json'):
                refuse('PROJECT_BACKGROUND_PIN_CHANGED', '映射、背景数据库或过程内容已改变，请重新关联。')
