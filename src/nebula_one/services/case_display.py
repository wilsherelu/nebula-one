"""Versioned authored presentation overlays; never edits a saved graph or catalog."""
from copy import deepcopy
import json
from pathlib import Path

from ..hashing import canonical_json_sha256
from ..release_resources import pick_name


def display_project_graph(graph, roots, language, catalog_labels=None):
    display = deepcopy(graph)
    sources = []
    catalog_labels = catalog_labels or {}
    for root in roots:
        for path in sorted((Path(root)/'project-templates').glob('*/display.v*.json')):
            document = json.loads(path.read_text(encoding='utf-8'))
            if document.get('schema_version') != 'nebula_one.case-display.v1':
                continue
            processes = {(row['node_id'], row['process_uuid'], row['source_name']): row for row in document['processes']}
            flows = {(row['source_namespace'], row['flow_uuid'], row['version']): row for row in document['flows']}
            exchanges = {row['exchange_id']: row for row in document['exchanges']}
            applied = []
            for node in display.get('nodes', []):
                process = processes.get((node['id'], node.get('process_uuid'), node.get('name')))
                if not process:
                    continue
                node['source_display_name'] = node['name']
                node['name'] = pick_name(process['names'], language) or node['name']
                for group in ('inputs', 'outputs', 'emissions'):
                    for port in node.get(group, []):
                        key = f"{node['id']}::{port['id']}"
                        identity = (port.get('flowSourceNamespace'), port.get('flowUuid'), port.get('flowVersion'))
                        flow = flows.get(identity)
                        original = port.get('name')
                        port['source_display_name'] = original
                        if key in catalog_labels:
                            port['source_catalog_display_name'] = catalog_labels[key]
                        port['name'] = (pick_name(flow['names'], language) if flow else None) or catalog_labels.get(key) or original
                        row = exchanges.get(key)
                        if (row and row['source_name'] == original
                                and identity == tuple(row['flow'][k] for k in ('source_namespace', 'flow_uuid', 'version'))):
                            port['display_description'] = pick_name(row['description'], language)
                        applied.append(key)
            if applied:
                sources.append({'id': document['id'], 'version': document['version'],
                    'content_sha256': canonical_json_sha256(document), 'language': language,
                    'exchange_ids': applied, 'license': document['license']})
    return display, sources
