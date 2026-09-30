"""Validate a public Process projection and import its exact Flow dependencies."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..errors import DomainError
from ..hashing import canonical_json_sha256


def validate_open_process_supply(document: dict, path: Path) -> tuple[dict, dict]:
    pin=document['source_process']
    asset=path.parent/pin['asset']
    if asset.parent!=path.parent or hashlib.sha256(asset.read_bytes()).hexdigest()!=pin['asset_sha256']:
        raise ValueError('public Process source asset hash drifted')
    snapshot=json.loads(asset.read_text(encoding='utf-8'))
    if snapshot['source_namespace']!='tiangong_open_data' or snapshot['state_scope']!='open' or len(snapshot['records'])!=1:
        raise ValueError('supply source must be one public TianGong Process')
    record=snapshot['records'][0]
    if (record['source_object_id'],record['source_version'],record['content_hash'])!=(pin['process_uuid'],pin['version'],pin['content_hash']) or canonical_json_sha256(record['payload'])!=pin['content_hash']:
        raise ValueError('public Process exact identity or content drifted')
    source=record['payload']['processDataSet']
    ownership=source['administrativeInformation']['publicationAndOwnership']
    if ownership.get('common:copyright')!='false' or ownership.get('common:licenseType')!='Free of charge for all users and uses':
        raise ValueError('public Process seed lacks the reviewed redistribution statement')
    node=document['graph']['nodes'][0]
    if node['process_uuid']!=pin['process_uuid'] or node.get('inputs'):
        raise ValueError('public supply must preserve its closed source Process')
    exchanges=source['exchanges']['exchange']
    outputs=node['outputs']
    if len(outputs)!=len(exchanges):
        raise ValueError('public supply omitted source exchanges')
    qref=source['processInformation']['quantitativeReference']['referenceToReferenceFlow']
    for exchange in exchanges:
        port=next(p for p in outputs if p['id']==exchange['@dataSetInternalID'])
        ref=exchange['referenceToFlowDataSet']
        if (exchange['exchangeDirection']!='Output' or port['direction']!='output'
            or port['flowSourceNamespace']!='tiangong_open_data'
            or (port['flowUuid'],port['flowVersion'])!=(ref['@refObjectId'],ref['@version'])
            or port['amount']!=float(exchange['resultingAmount'])
            or port['isProduct']!=(exchange['@dataSetInternalID']==qref)):
            raise ValueError('public supply graph differs from its source inventory')
    if sum(p['isProduct'] for p in outputs)!=1:
        raise ValueError('public supply requires one source reference product')
    flows_asset=path.parent/pin['flows_asset']
    if flows_asset.parent!=path.parent or hashlib.sha256(flows_asset.read_bytes()).hexdigest()!=pin['flows_asset_sha256']:
        raise ValueError('public Process Flow source hash drifted')
    return record,json.loads(flows_asset.read_text(encoding='utf-8'))


def ensure_open_process_supply_flows(client, document: dict, path: Path) -> dict:
    _,snapshot=validate_open_process_supply(document,path)
    imported=[]
    for port in document['graph']['nodes'][0]['outputs']:
        record=next(r for r in snapshot['records'] if (r['source_object_id'],r['source_version'])==(port['flowUuid'],port['flowVersion']))
        try:
            client.get_flow_version('tiangong_open_data',port['flowUuid'],port['flowVersion'])
        except DomainError as error:
            if error.details.get('upstream_status')!=404:
                raise
            payload={**record['payload'],'source':'tiangong_open_data','version':port['flowVersion'],
                'default_unit':port['unit'],'unit_group':port['unitGroup'],
                'unit_group_uuid':port['unitGroupUuid'],'unit_group_version':port['unitGroupVersion']}
            for dry_run in (True,False):
                report=client.import_tidas_flows(filename='open-process-flow.json',payload=json.dumps(payload,ensure_ascii=False).encode('utf-8'),dry_run=dry_run).payload
                if report['failed'] or report['errors']:
                    raise ValueError('exact public Process Flow import failed')
            imported.append(port['flowUuid'])
        resolved=client.resolve_provider_catalog({'flows':[dict(source_namespace='tiangong_open_data',flow_uuid=port['flowUuid'],version=port['flowVersion'])]}).payload['items'][0]
        if resolved['status']!='resolved' or resolved['value']['content_hash']!=record['content_hash']:
            raise ValueError('public Process Flow differs from its exact source')
        for key,field in [('flow_property_uuid','flowPropertyUuid'),('flow_property_version','flowPropertyVersion'),('unit_group_uuid','unitGroupUuid'),('unit_group_version','unitGroupVersion')]:
            if resolved['value'][key]!=port[field]:
                raise ValueError('public Process Flow property or UnitGroup reference drifted')
    return {'imported_flow_uuids':imported}
