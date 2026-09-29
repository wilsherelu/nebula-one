"""Project an exact user-supplied process edge in the consumer's unit."""
from math import isclose, isfinite


def project_supply_links(snapshot):
    provider_receipt = snapshot.get("provider_receipt") or {}
    receipts = provider_receipt.get("project_background_process_receipts") or []
    pins = (provider_receipt.get("calculation_basis") or {}).get("project_background_pins") or []
    transfers = snapshot.get("internal_transfers") or []
    links, issues = [], []
    for receipt in receipts:
        pin = receipt.get("pin") or {}
        consumer_id = pin.get("consumer_exchange_id")
        provider_id = f"{receipt.get('expanded_node_id')}::{pin.get('reference_port_id')}"
        sources = [item for item in transfers if item.get("exchange_id") == provider_id]
        targets = [item for item in transfers if item.get("exchange_id") == consumer_id]
        valid = (len(sources) == len(targets) == 1 and pins.count(pin) == 1
                 and receipt.get("source_graph_hash") == pin.get("expected_graph_hash")
                 and pin.get("schema_version") == "provider.project-background-pin.v1")
        if valid:
            source, target = sources[0], targets[0]
            try:
                source_amount = float(source["amount"])
                target_amount = float(target["amount"])
                factor = float(receipt["unit_conversion_factor"])
                activity_amount = float(receipt["activity_amount"])
                valid = (all(isfinite(value) and value >= 0 for value in
                             (source_amount, target_amount, activity_amount, factor)) and factor > 0
                         and source.get("process_id") == receipt.get("source_process_uuid")
                         and source.get("direction") == "output" and target.get("direction") == "input"
                         and source.get("flow_uuid") == target.get("flow_uuid") == receipt.get("reference_flow_uuid")
                         and source.get("unit_group") == target.get("unit_group")
                         and source.get("unit") == receipt.get("reference_unit")
                         and target.get("unit") == receipt.get("consumer_unit")
                         and isclose(factor, float(pin["provider_amount_per_consumer_unit"]), rel_tol=1e-12)
                         and isclose(source_amount, activity_amount, rel_tol=1e-9, abs_tol=1e-12)
                         and isclose(source_amount, target_amount * factor, rel_tol=1e-9, abs_tol=1e-12))
            except (KeyError, TypeError, ValueError):
                valid = False
        if not valid:
            issues.append({"code": "PROJECT_BACKGROUND_TRANSFER_MISMATCH", "severity": "error",
                           "consumer_exchange_id": consumer_id})
            continue
        links.append({"source_item": source, "target_item": target, "receipt": receipt,
                      "source_amount": source_amount, "target_amount": target_amount, "factor": factor})
    return links, issues
