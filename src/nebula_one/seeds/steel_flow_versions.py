"""Publish immutable authored Flow snapshots from the reviewed steel seed.

The original seed and its hashes stay unchanged. This catalog-only supplement
combines its explicit port references with the authored catalog rows; it carries
no project, process, commercial inventory or characterization factors.
"""
from __future__ import annotations

from io import BytesIO
import json
from zipfile import ZIP_DEFLATED, ZipFile

from ..hashing import canonical_json_sha256
from .steel_catalog_prerequisite import load_steel_catalog_prerequisite


def steel_flow_version_bundle(steel) -> tuple[bytes, list[dict]]:
    steel.validate()
    _, _, prerequisites = load_steel_catalog_prerequisite()
    rows = {row['flow_uuid']: row for row in [*steel.owned_flows['rows'], *prerequisites]}
    versions = {}
    for node in steel.graph['nodes']:
        for port in [*node.get('inputs', []), *node.get('outputs', [])]:
            row = rows.get(port['flowUuid'])
            if row is None:
                continue
            namespace, version = row['source_namespace'], row['source_version']
            if (port.get('flowSourceNamespace'), port.get('flowVersion')) != (namespace, version):
                raise ValueError('authored Flow port differs from its catalog source identity')
            semantic = dict(flow_uuid=row['flow_uuid'], source_namespace=namespace,
                source_version=version, flow_name=row['flow_name'], flow_name_en=row.get('flow_name_en'),
                flow_type=row['flow_type'], default_unit=row['default_unit'], unit_group=row['unit_group'],
                flow_property_uuid=port.get('flowPropertyUuid'), flow_property_version=port.get('flowPropertyVersion'),
                unit_group_uuid=port.get('unitGroupUuid'), unit_group_version=port.get('unitGroupVersion'))
            if not all(semantic[key] for key in ('flow_property_uuid', 'flow_property_version', 'unit_group_uuid', 'unit_group_version')):
                raise ValueError('authored Flow lacks exact property or UnitGroup references')
            if port['unitGroup'] != row['unit_group']:
                raise ValueError('authored Flow port differs from its catalog physical quantity')
            key=(namespace, row['flow_uuid'], version)
            if key in versions and versions[key]['content_hash'] != canonical_json_sha256(semantic):
                raise ValueError('authored Flow ports disagree on their immutable semantics')
            versions[key] = {**semantic, 'version_label': row['version_label'],
                'source_updated_at': row.get('source_updated_at'), 'content_hash': canonical_json_sha256(semantic),
                'metadata_json': {'source': 'reviewed_steel_seed_catalog_supplement',
                    'graph_sha256': steel.file_digest('model/graph.json'),
                    'owned_flows_sha256': steel.file_digest('model/owned-flows.json')}}
    snapshots=list(versions.values())
    selected=sorted({v['flow_uuid'] for v in snapshots})
    entries={'catalog/flows.json': [rows[u] for u in selected], 'catalog/flow_versions.json': snapshots}
    raw={name:json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8') for name,value in entries.items()}
    from hashlib import sha256
    manifest={'schema_version':'nebula.project.bundle.v1','project_id':steel.identity['project_id'],
        'content':{name:{'sha256':sha256(data).hexdigest(),'bytes':len(data)} for name,data in raw.items()}}
    out=BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',json.dumps(manifest,sort_keys=True))
        for name,data in raw.items():
            archive.writestr(name,data)
    return out.getvalue(),snapshots


def ensure_steel_flow_versions(client, steel) -> dict:
    payload, snapshots=steel_flow_version_bundle(steel)
    request={'flows':[{'source_namespace':s['source_namespace'],'flow_uuid':s['flow_uuid'],'version':s['source_version']} for s in snapshots]}
    expected={(s['source_namespace'],s['flow_uuid'],s['source_version']):s for s in snapshots}
    def verify(response):
        missing=[]
        for item in response['items']:
            key=item['key']
            snapshot=expected[(key['source_namespace'],key['flow_uuid'],key['version'])]
            if item['status']=='not_found':
                missing.append(snapshot['flow_uuid'])
            elif item['status']!='resolved' or item['value'].get('content_hash')!=snapshot['content_hash']:
                raise ValueError('immutable authored Flow snapshot conflicts with the reviewed seed: '+snapshot['flow_uuid'])
        if len(response['items'])!=len(snapshots):
            raise ValueError('engine omitted an authored Flow resolution')
        return missing
    missing=verify(client.resolve_provider_catalog(request).payload)
    receipt=None
    if missing:
        receipt=client.restore_native_catalog_flows(filename='steel-authored-flow-versions.v1.zip',payload=payload,flow_uuids=missing).payload
        if verify(client.resolve_provider_catalog(request).payload):
            raise ValueError('engine did not persist the authored Flow snapshots')
    return {'status':'imported' if missing else 'present','flow_count':len(snapshots),'receipt':receipt}
