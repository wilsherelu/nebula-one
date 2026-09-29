"""Project mapped supply edges in the consumer's unit, retaining both identities."""
from math import isclose, isfinite


def mapped_supply_links(snapshot):
    receipts = (snapshot.get('provider_receipt') or {}).get('mapped_background_process_receipts') or []
    transfers = snapshot.get('internal_transfers') or []
    links, issues = [], []
    for receipt in receipts:
        consumer_id = receipt.get('consumer_exchange_id')
        targets = [t for t in transfers if t.get('exchange_id') == consumer_id]
        sources = [t for t in transfers if t.get('process_id') == receipt.get('process_uuid')
                   and t.get('flow_uuid') == receipt.get('target_flow_uuid') and t.get('direction') == 'output']
        valid = len(targets) == len(sources) == 1
        if valid:
            source, target = sources[0], targets[0]
            try:
                source_amount, target_amount, factor = float(source['amount']), float(target['amount']), float(receipt['amount_factor'])
                total_amount = source_amount
                shared = receipt.get('shared_activity_schema_version')
                if shared:
                    source_amount = float(receipt['consumer_attributed_activity_amount'])
                valid = (all(isfinite(x) and x >= 0 for x in (source_amount, target_amount, factor)) and factor > 0
                    and source.get('unit') == receipt.get('target_unit') and target.get('unit') == receipt.get('source_unit')
                    and target.get('flow_uuid') == receipt.get('source_flow_uuid') and target.get('direction') == 'input'
                    and isclose(source_amount, target_amount * factor, rel_tol=1e-9, abs_tol=1e-12)
                    and isclose(total_amount, float(receipt['activity_amount']), rel_tol=1e-9, abs_tol=1e-12)
                    and (not shared or (shared == 'provider.mapped-background-shared-activity.v1'
                         and isclose(total_amount, float(receipt['shared_process_total_activity_amount']), rel_tol=1e-9, abs_tol=1e-12))))
            except (KeyError, TypeError, ValueError):
                valid = False
        if not valid:
            issues.append({'code': 'MAPPED_BACKGROUND_TRANSFER_MISMATCH', 'severity': 'error', 'consumer_exchange_id': consumer_id})
            continue
        links.append({'source_item': source, 'target_item': target, 'receipt': receipt,
                      'source_amount': source_amount, 'target_amount': target_amount, 'factor': factor})
    groups = {}
    for link in links:
        if link['receipt'].get('shared_activity_schema_version'):
            groups.setdefault(link['source_item']['exchange_id'], []).append(link)
    invalid = set()
    for source_id, group in groups.items():
        if not isclose(sum(link['source_amount'] for link in group), float(group[0]['source_item']['amount']), rel_tol=1e-9, abs_tol=1e-12):
            invalid.add(source_id)
            issues.append({'code': 'MAPPED_BACKGROUND_TRANSFER_MISMATCH', 'severity': 'error', 'exchange_id': source_id})
    return [link for link in links if link['source_item']['exchange_id'] not in invalid], issues
