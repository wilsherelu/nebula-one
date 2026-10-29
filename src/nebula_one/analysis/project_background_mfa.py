"""Project an exact user-supplied process edge in the consumer's unit."""
from math import isclose, isfinite


NETWORK_CLAIM_ROLE = "user_declared_partial_background_network"
NETWORK_CLAIM_LIMIT = "user_declared_partial_background_closed_network"
PIN_SCHEMA_VERSION = "provider.project-background-pin.v1"


def is_network_claim(pin):
    return isinstance(pin, dict) and pin.get("claim_role") == NETWORK_CLAIM_ROLE


def _group_rows_by_pin(pins, receipts):
    """Return [(pin, rows)] in pin order, or None if rows do not form exact, exclusive pin groups.

    Every row must carry a pin identical to a declared pin, and every declared pin must have at
    least one row. A row whose pin matches no declaration, or a declaration with no row, is an
    inexact or non-exclusive supply and yields None; cardinality is allowed to exceed one per pin
    because a closed network contributes several node rows to one consumer path.
    """
    by_consumer: dict[str, list] = {}
    for row in receipts:
        pin = row.get("pin") or {}
        by_consumer.setdefault(str(pin.get("consumer_exchange_id") or ""), []).append(row)
    groups = []
    consumed = 0
    for pin in pins:
        rows = by_consumer.get(str(pin.get("consumer_exchange_id") or ""), [])
        if not rows or any(row.get("pin") != pin for row in rows):
            return None
        consumed += len(rows)
        groups.append((pin, rows))
    if consumed != len(receipts):
        return None
    return groups


def _network_boundary_row(pin, rows):
    """Return the single entry-node row of a closed network, or None if the node mapping is absent.

    Mirrors the solve-time contract: distinct expanded nodes covering one shared network set, a
    distinct source process per node so no contribution is double counted, exactly one row is the
    declared entry node feeding the consumer, and every node pinned to the expected graph hash.
    """
    nodes = [row.get("expanded_node_id") for row in rows]
    node_set = set(nodes)
    boundaries = [row for row in rows if row.get("source_node_id") == pin.get("source_node_id")]
    if (None in nodes or len(node_set) != len(rows) or len(boundaries) != 1
            or any(set(row.get("expanded_network_node_ids") or []) != node_set for row in rows)
            or len({row.get("source_process_uuid") for row in rows}) != len(rows)
            or any(row.get("claim_limit") != NETWORK_CLAIM_LIMIT for row in rows)
            or any(row.get("source_graph_hash") != pin.get("expected_graph_hash") for row in rows)):
        return None
    return boundaries[0]


def project_supply_links(snapshot):
    provider_receipt = snapshot.get("provider_receipt") or {}
    receipts = provider_receipt.get("project_background_process_receipts") or []
    pins = (provider_receipt.get("calculation_basis") or {}).get("project_background_pins") or []
    transfers = snapshot.get("internal_transfers") or []
    links, issues = [], []
    groups = _group_rows_by_pin(pins, receipts)
    if groups is None:
        return [], [{"code": "PROJECT_BACKGROUND_TRANSFER_MISMATCH", "severity": "error",
                     "consumer_exchange_id": None}]
    for pin, rows in groups:
        consumer_id = pin.get("consumer_exchange_id")
        network = is_network_claim(pin)
        if network:
            boundary = _network_boundary_row(pin, rows)
        elif len(rows) == 1:
            boundary = rows[0]
        else:
            boundary = None
        if (boundary is None or pin.get("schema_version") != PIN_SCHEMA_VERSION
                or boundary.get("source_graph_hash") != pin.get("expected_graph_hash")):
            issues.append({"code": "PROJECT_BACKGROUND_TRANSFER_MISMATCH", "severity": "error",
                           "consumer_exchange_id": consumer_id})
            continue
        provider_id = f"{boundary.get('expanded_node_id')}::{pin.get('reference_port_id')}"
        sources = [item for item in transfers if item.get("exchange_id") == provider_id]
        targets = [item for item in transfers if item.get("exchange_id") == consumer_id]
        valid = len(sources) == len(targets) == 1
        if valid:
            source, target = sources[0], targets[0]
            try:
                source_amount = float(source["amount"])
                target_amount = float(target["amount"])
                factor = float(boundary["unit_conversion_factor"])
                activity_amount = float(boundary["activity_amount"])
                valid = (all(isfinite(value) and value >= 0 for value in
                             (source_amount, target_amount, activity_amount, factor)) and factor > 0
                         and source.get("process_id") == boundary.get("source_process_uuid")
                         and source.get("direction") == "output" and target.get("direction") == "input"
                         and source.get("flow_uuid") == target.get("flow_uuid") == boundary.get("reference_flow_uuid")
                         and source.get("unit_group") == target.get("unit_group")
                         and source.get("unit") == boundary.get("reference_unit")
                         and target.get("unit") == boundary.get("consumer_unit")
                         and isclose(factor, float(pin["provider_amount_per_consumer_unit"]), rel_tol=1e-12)
                         and isclose(source_amount, activity_amount, rel_tol=1e-9, abs_tol=1e-12)
                         and isclose(source_amount, target_amount * factor, rel_tol=1e-9, abs_tol=1e-12))
            except (KeyError, TypeError, ValueError):
                valid = False
        if not valid:
            issues.append({"code": "PROJECT_BACKGROUND_TRANSFER_MISMATCH", "severity": "error",
                           "consumer_exchange_id": consumer_id})
            continue
        links.append({"source_item": source, "target_item": target, "receipt": boundary,
                      "source_amount": source_amount, "target_amount": target_amount, "factor": factor,
                      "pin": pin, "network": network, "rows": rows})
    return links, issues
