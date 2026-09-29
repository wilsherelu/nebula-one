"""Verify the upstream mapping identity before freezing application results."""
import math

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .project_background import background_ports


def validate_mapped_receipts(result, pins, graph):
    def reject(message):
        raise DomainError(code='PROVIDER_MAPPED_BACKGROUND_RECEIPT_INVALID', message=message, status_code=502)

    receipts = result.get('mapped_background_process_receipts', [])
    if not isinstance(receipts, list) or any(not isinstance(r, dict) for r in receipts):
        reject('Mapped background receipts must be a collection of identity records.')
    by_id = {r.get('consumer_exchange_id'): r for r in receipts}
    if len(by_id) != len(receipts) or set(by_id) != {p.consumer_exchange_id for p in pins}:
        reject('Mapped background receipts do not match the requested consumers.')
    if not pins:
        return []
    provenance = result.get('provenance') or {}
    expected_hash = canonical_json_sha256([p.model_dump(mode='json') for p in sorted(pins, key=lambda p: p.consumer_exchange_id)])
    if provenance.get('mapped_background_process_pins_hash') != expected_hash:
        reject('Mapped background provenance does not match the saved pins.')
    ports = {f"{n['id']}::{p['id']}": p for n, p in background_ports(graph)}
    consumers = {f"{n['id']}::{p['id']}": n.get('process_uuid') for n, p in background_ports(graph)}
    groups = {}
    for pin in pins:
        receipt = by_id[pin.consumer_exchange_id]
        expected = pin.model_dump(mode='json')
        expected['schema_version'] = 'provider.mapped-background-process-receipt.v1'
        expected['process_content_hash'] = expected.pop('expected_process_content_hash')
        expected['vector_checksum'] = expected.pop('expected_vector_checksum')
        expected['claim_limit'] = 'partial_background_leaf_only_not_complete_cradle_to_gate'
        if any(receipt.get(k) != value for k, value in expected.items()):
            reject('Mapped background receipt identity differs from the requested mapping or Process.')
        port = ports.get(pin.consumer_exchange_id)
        if not port or any(port.get(k) != value for k, value in {
            'flowSourceNamespace': pin.source_flow_namespace, 'flowUuid': pin.source_flow_uuid,
            'flowVersion': pin.source_flow_version, 'unit': pin.source_unit,
        }.items()):
            reject('Mapped background source does not belong to this model revision.')
        for field in ('quantitative_reference_amount', 'activity_amount', 'process_scale'):
            value = receipt.get(field)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                reject('Mapped background activity evidence is invalid.')
        qref = receipt['quantitative_reference_amount']
        if qref <= 0 or not math.isclose(receipt['activity_amount'] / qref, receipt['process_scale'], rel_tol=1e-9, abs_tol=1e-12):
            reject('Mapped background activity and scale evidence disagree.')
        activities = [a for a in result.get('activity_vector', []) if isinstance(a, dict) and a.get('process_uuid') == pin.process_uuid]
        if len(activities) != 1 or activities[0].get('activity_amount') != receipt['activity_amount']:
            reject('Mapped background receipt differs from the solved activity vector.')
        if not isinstance(receipt.get('vector_nnz'), int) or isinstance(receipt['vector_nnz'], bool) or receipt['vector_nnz'] <= 0:
            reject('Mapped background receipt lacks inventory coverage.')
        groups.setdefault(pin.process_uuid, []).append(receipt)
        schema = receipt.get('shared_activity_schema_version')
        if schema is not None:
            if schema != 'provider.mapped-background-shared-activity.v1' or not receipt.get('provider_instance_id'):
                reject('Unsupported shared background activity contract.')
            if receipt.get('consumer_process_uuid') != consumers[pin.consumer_exchange_id]:
                reject('Shared background consumer identity differs from the model.')
            for field in ('consumer_converted_amount', 'consumer_attributed_activity_amount',
                          'shared_process_total_activity_amount', 'attributed_process_scale'):
                value = receipt.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    reject('Shared background activity evidence is invalid.')
            if (not math.isclose(receipt['consumer_converted_amount'], port['amount'] * pin.amount_factor, rel_tol=1e-9, abs_tol=1e-12)
                or not math.isclose(receipt['consumer_attributed_activity_amount'] / qref, receipt['attributed_process_scale'], rel_tol=1e-9, abs_tol=1e-12)
                or receipt['shared_process_total_activity_amount'] != receipt['activity_amount']):
                reject('Shared background conversion or attributed scale disagrees.')
    instances = set()
    for group in groups.values():
        shared = [r for r in group if r.get('shared_activity_schema_version')]
        if not shared and len(group) == 1:
            continue  # Historical single-consumer receipts remain readable.
        if len(shared) != len(group):
            reject('Multiple consumers require shared activity evidence.')
        first = group[0]
        identity_fields = ('provider_instance_id', 'process_content_hash', 'vector_checksum',
                           'database_release', 'quantitative_reference_amount', 'activity_amount', 'vector_nnz')
        if any(any(r[k] != first[k] for k in identity_fields) for r in group):
            reject('Shared provider receipts disagree on the exact Process or activity.')
        if first['provider_instance_id'] in instances:
            reject('Different Processes claim the same provider instance.')
        instances.add(first['provider_instance_id'])
        if not math.isclose(sum(r['consumer_attributed_activity_amount'] for r in group), first['activity_amount'], rel_tol=1e-9, abs_tol=1e-12):
            reject('Consumer shares do not reconcile with total provider activity.')
    return [by_id[key] for key in sorted(by_id)]
