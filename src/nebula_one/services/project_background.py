"""Exact background-leaf selections over the public provider catalogue contract."""
from pydantic import BaseModel, ConfigDict, Field

from ..errors import DomainError
from ..runtime_schemas import ProviderBackgroundProcessPin


class BackgroundSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    consumer_exchange_id: str = Field(min_length=1, max_length=255)
    process_uuid: str = Field(pattern=r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')
    version: str = Field(pattern=r'^[0-9]{2}\.[0-9]{2}\.[0-9]{3}$')


def refuse(code, message, **details):
    raise DomainError(code=code, message=message, status_code=422, details=details)


def background_ports(graph):
    connected = {(e['toNode'], e['targetPortId']) for e in graph.get('exchanges', [])}
    return [(n, p) for n in graph.get('nodes', []) for p in n.get('inputs', [])
            if p.get('type') == 'technosphere' and (n['id'], p['id']) not in connected]


def list_background_ports(graph):
    return [{'exchange_id': f"{n['id']}::{p['id']}", 'process': n.get('name', n['id']),
             'label': p.get('name', p['id']), 'unit': p.get('unit'),
             'flow_uuid': p.get('flowUuid'), 'version': p.get('flowVersion'),
             'source_namespace': p.get('flowSourceNamespace'),
             'exact_binding_supported': p.get('flowSourceNamespace') == 'tiangong_open_data'}
            for n, p in background_ports(graph)]


class ProjectBackgroundService:
    def __init__(self, client):
        self.client = client

    def _resolve(self, kind, refs):
        answer = self.client.resolve_provider_catalog({'processes' if kind == 'process' else 'flows': refs}).payload
        items = [i for i in answer['items'] if i['kind'] == kind]
        if len(items) != len(refs) or any(i['status'] != 'resolved' for i in items):
            refuse('PROJECT_BACKGROUND_DATA_UNAVAILABLE', '当前算法服务缺少所选背景数据的精确快照。', resolutions=items)
        values = []
        for ref in refs:
            matches = [i for i in items if all(i['key'].get(k) == v for k, v in ref.items())]
            if len(matches) != 1 or not isinstance(matches[0].get('value'), dict) or any(matches[0]['value'].get(k) != v for k, v in ref.items()):
                refuse('PROJECT_BACKGROUND_IDENTITY_MISMATCH', '背景目录返回的身份与请求不一致。')
            values.append(matches[0]['value'])
        return values

    def resolve(self, graph, selection):
        ports = {f"{n['id']}::{p['id']}": p for n, p in background_ports(graph)}
        port = ports.get(selection.consumer_exchange_id)
        if port is None or port.get('amount', 0) <= 0:
            refuse('PROJECT_BACKGROUND_PORT_INVALID', '请选择数量大于零、没有内部连接的投入清单。')
        if port.get('flowSourceNamespace') != 'tiangong_open_data':
            refuse('PROJECT_BACKGROUND_MAPPING_REQUIRED', '此模板使用自建流，尚未绑定上游产品流的精确身份。需要在 Nebula LCA 中完成正式映射并发布新模板，不能按名称代替关联。')
        process = self._resolve('process', [{'source_namespace': 'tiangong_open_data',
            'process_uuid': selection.process_uuid, 'version': selection.version}])[0]
        qref = process['quantitative_reference']
        refs = list({(e['flow']['source_namespace'], e['flow']['flow_uuid'], e['flow']['version']): e['flow']
                     for e in process['exchanges']}.values())
        refs = [{k: r[k] for k in ('source_namespace', 'flow_uuid', 'version')} for r in refs]
        flows = self._resolve('flow', refs)
        by_ref = {(f['source_namespace'], f['flow_uuid'], f['version']): f for f in flows}
        q = qref['flow']
        flow = by_ref[(q['source_namespace'], q['flow_uuid'], q['version'])]
        identity_fields = {'flowSourceNamespace': 'source_namespace', 'flowUuid': 'flow_uuid', 'flowVersion': 'version',
            'flowPropertyUuid': 'flow_property_uuid', 'flowPropertyVersion': 'flow_property_version',
            'unitGroupUuid': 'unit_group_uuid', 'unitGroupVersion': 'unit_group_version', 'unit': 'unit'}
        mismatches = {k: {'consumer': port.get(k), 'provider': flow.get(v)} for k, v in identity_fields.items() if port.get(k) != flow.get(v)}
        if mismatches or flow.get('flow_type') not in ('Product flow', 'Waste flow'):
            refuse('PROJECT_BACKGROUND_FLOW_MISMATCH', '背景过程的参考产品、流版本或单位与此投入不一致。', mismatches=mismatches)
        for e in process['exchanges']:
            ref = e['flow']
            f = by_ref[(ref['source_namespace'], ref['flow_uuid'], ref['version'])]
            if e['exchange_internal_id'] != qref['exchange_internal_id'] and f.get('flow_type') != 'Elementary flow':
                refuse('PROJECT_BACKGROUND_DEPENDENCIES_OPEN', '该背景过程仍有未展开的供应链，当前接口不能把它作为完整背景清单计算。')
        pin = ProviderBackgroundProcessPin(consumer_exchange_id=selection.consumer_exchange_id,
            process_uuid=selection.process_uuid, version=selection.version,
            expected_process_content_hash=process['content_hash'], expected_process_snapshot_hash=process['snapshot_hash'],
            quantitative_reference_exchange_internal_id=qref['exchange_internal_id'])
        return {'pin': pin.model_dump(mode='json'), 'name': process.get('name') or selection.process_uuid,
                'claim_role': 'partial_background_leaf'}

    def validate(self, graph, pins):
        if len({p.consumer_exchange_id for p in pins}) != len(pins):
            refuse('PROJECT_BACKGROUND_DUPLICATE', '一个投入清单只能选择一个背景过程。')
        for pin in pins:
            resolved = self.resolve(graph, BackgroundSelection(consumer_exchange_id=pin.consumer_exchange_id,
                                    process_uuid=pin.process_uuid, version=pin.version))
            if resolved['pin'] != pin.model_dump(mode='json'):
                refuse('PROJECT_BACKGROUND_PIN_CHANGED', '背景数据版本的内容或快照已改变，请重新关联。')
