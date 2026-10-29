"""Compose exact public Flow snapshots for the standalone runtime, never factors."""
import hashlib
import json
import csv
import io
from pathlib import Path

BODY_FIELDS = ('schema_version', 'source_namespace', 'dataset_kind', 'state_scope',
               'filters', 'declared_total', 'records')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def compose_flow_snapshots(paths):
    records = {}
    sources = []
    for path in paths:
        document = json.loads(Path(path).read_text(encoding='utf-8'))
        if (document.get('schema_version') != 'tiangong-open-dataset-snapshot.v1'
                or document.get('source_namespace') != 'tiangong_open_data'
                or document.get('dataset_kind') != 'flow' or document.get('state_scope') != 'open'
                or digest({key: document.get(key) for key in BODY_FIELDS}) != document.get('snapshot_hash')):
            raise ValueError(f'Invalid exact open Flow snapshot: {Path(path).name}')
        sources.append({'asset': Path(path).name, 'snapshot_hash': document['snapshot_hash']})
        for record in document['records']:
            identity = (record['source_object_id'], record['source_version'])
            if identity in records and records[identity] != record:
                raise ValueError(f'Conflicting immutable Flow identity: {identity}')
            records[identity] = record
    if not records:
        raise ValueError('Open Flow snapshot cannot be empty')
    result = {'schema_version': 'tiangong-open-dataset-snapshot.v1', 'source_namespace': 'tiangong_open_data',
        'dataset_kind': 'flow', 'state_scope': 'open',
        'filters': {'exact_refs': [f'{uuid}@{version}' for uuid, version in sorted(records)]},
        'declared_total': len(records), 'records': [records[key] for key in sorted(records)]}
    result['snapshot_hash'] = digest(result)
    result['counts'] = {'flow': len(records)}
    result['source_snapshots'] = sources
    return result


def compose_elementary_catalog(base_csv, extra_csv, base_profile, extra_provenance):
    """Keep the engine's compatibility catalogue in step with exact Flow snapshots."""
    base = Path(base_csv).read_bytes()
    extra = Path(extra_csv).read_bytes()
    profile = json.loads(Path(base_profile).read_text(encoding='utf-8'))
    provenance = json.loads(Path(extra_provenance).read_text(encoding='utf-8'))
    if hashlib.sha256(base).hexdigest() != profile['selected_sha256'] or hashlib.sha256(extra).hexdigest() != provenance['selected_sha256']:
        raise ValueError('Elementary catalogue source hash mismatch')
    rows = {}
    header = None
    for data in (base, extra):
        reader = csv.reader(io.StringIO(data.decode('utf-8-sig')))
        current_header = next(reader)
        if header is not None and header != current_header:
            raise ValueError('Elementary catalogue header mismatch')
        header = current_header
        for row in reader:
            if row[0] in rows and rows[row[0]] != row:
                raise ValueError('Elementary catalogue identity conflict')
            rows[row[0]] = row
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(rows[key] for key in sorted(rows))
    data = output.getvalue().encode('utf-8')
    profile.update(selected_asset='desktop_elementary_catalog.v1.csv',
        selected_sha256=hashlib.sha256(data).hexdigest(), flow_uuids=sorted(rows),
        selection='Exact selected public Flow metadata for the standalone steel and gas-boundary examples',
        supplemental_source=provenance)
    return data, profile
