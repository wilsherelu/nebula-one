"""Apply a reviewed identity-only template revision without reminting model identities."""
import re
from copy import deepcopy

from ..errors import DomainError
from ..hashing import canonical_json_sha256


IDENTITY_FIELDS = {'flowUuid', 'flowSourceNamespace', 'flowVersion', 'flowPropertyUuid',
                   'flowPropertyVersion', 'unitGroupUuid', 'unitGroupVersion', 'unit', 'unitGroup'}
DISPLAY_PROJECTION_SCHEMA = 'nebula.tiangong-flow-display-metadata.v1'
SHA256_HEX = re.compile(r'[0-9a-f]{64}')


def apply_template_revision(graph, upgrade):
    if not upgrade:
        return deepcopy(graph)

    def reject():
        raise DomainError(code='PROJECT_TEMPLATE_REVISION_INVALID',
                          message='The reviewed template revision does not match the installed model.', status_code=409)

    content = upgrade.get('content', {})
    if (upgrade.get('content_sha256') != canonical_json_sha256(content)
        or content.get('schema_version') != 'nebula_one.template-identity-revision.v1'):
        reject()
    replacements = content.get('replacements')
    if not isinstance(replacements, list) or not replacements:
        reject()
    result, seen = deepcopy(graph), set()
    linked = {f"{e['toNode']}::{e['targetPortId']}" for e in graph.get('exchanges', [])}
    for replacement in replacements:
        key = replacement.get('exchange_id')
        if not isinstance(key, str) or key in seen or key in linked:
            reject()
        seen.add(key)
        matches = [p for n in result.get('nodes', []) for p in n.get('inputs', [])
                   if f"{n['id']}::{p['id']}" == key]
        before, after = replacement.get('before', {}), replacement.get('after', {})
        if (len(matches) != 1 or set(before) != IDENTITY_FIELDS or set(after) != IDENTITY_FIELDS
            or any(not isinstance(v, str) or not v for v in after.values())
            or before['unit'] != after['unit'] or before['unitGroup'] != after['unitGroup']):
            reject()
        port = matches[0]
        if (port.get('type') != 'technosphere' or any(port.get(k) != v for k, v in before.items())
            or port.get('amount') != replacement.get('amount_preserved')):
            reject()
        port.update(after)
    for metadata in content.get('display_metadata', []):
        matches = [r for r in replacements if r['exchange_id'] == metadata.get('exchange_id')]
        if (len(matches) != 1 or not isinstance(metadata.get('name_en'), str) or not metadata['name_en'].strip()
            or any(metadata.get(k) != matches[0]['after'][v] for k, v in {
                'source_namespace': 'flowSourceNamespace', 'flow_uuid': 'flowUuid', 'version': 'flowVersion'}.items())):
            reject()
        # A display label is a pinned projection of that exact upstream flow payload, never a local translation.
        projection = metadata.get('display_projection')
        if (not isinstance(metadata.get('name_zh'), str) or not metadata['name_zh'].strip()
            or not isinstance(projection, dict) or projection.get('schema_version') != DISPLAY_PROJECTION_SCHEMA
            or not isinstance(projection.get('raw_name_field_path'), str) or not projection['raw_name_field_path'].strip()
            or not SHA256_HEX.fullmatch(str(projection.get('artifact_sha256') or ''))
            or not SHA256_HEX.fullmatch(str(metadata.get('content_hash') or ''))
            or projection.get('flow_payload_content_hash') != metadata.get('content_hash')):
            reject()
    return result
