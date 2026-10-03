"""Read names through the public exact catalogue, without changing model identity."""
from ..errors import UpstreamError


def exact_flow_labels(client, graph, language):
    refs = {}
    exchanges = {}
    for node in graph.get('nodes', []):
        for group in ('inputs', 'outputs', 'emissions'):
            for port in node.get(group, []):
                identity = (port.get('flowSourceNamespace'), port.get('flowUuid'), port.get('flowVersion'))
                if not all(identity):
                    continue
                refs[identity] = dict(zip(('source_namespace', 'flow_uuid', 'version'), identity))
                exchanges[f"{node['id']}::{port['id']}"] = identity
    if not refs:
        return {}, []
    try:
        answer = client.resolve_provider_catalog({'flows': list(refs.values())}).payload
    except UpstreamError as error:
        # Display lookup must not change or prevent reading the saved authored model.
        return {}, [{'status': 'unavailable', 'code': error.code}]
    names = {}
    issues = []
    for item in answer['items']:
        value = item.get('value') or {}
        identity = (value.get('source_namespace'), value.get('flow_uuid'), value.get('version'))
        if item.get('status') != 'resolved' or identity not in refs:
            issues.append({'key': item.get('key'), 'status': item.get('status')})
            continue
        multilingual = value.get('display_names') or {}
        name = multilingual.get(language) or value.get('name_' + language)
        if not name:
            name = value.get('name') if language == 'zh' else value.get('name_en') or value.get('name')
        if isinstance(name, str) and name.strip():
            names[identity] = name.strip()
        else:
            issues.append({'key': item.get('key'), 'status': 'name_unavailable'})
    return {key: names[identity] for key, identity in exchanges.items() if identity in names}, issues
