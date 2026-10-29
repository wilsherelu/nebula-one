"""Group LCA's path-weighted contributions by a user calculation method.

R3 consumption of the new provider contract: Nebula LCA now publishes
`lcia.path_weighted_contribution_receipts[].terms[]` where each row is one characterized
contribution partitioned to a specific consumption path (or labelled as unattributed by the
engine). This module applies a user method's rules to those rows and re-buckets the per-path
values into the method's declared Scope grouping.

Scope 1/2/3 stays a user classification and never crosses back into LCA's generic contribution
interface. Values stay with the engine: nothing here recomputes an emission factor or a scale.
"""

from __future__ import annotations

import math
from typing import Any

from .method_contribution_binding import node_prefix, resolve_method_identities

_SCOPES = ("scope_1", "scope_2", "scope_3")
_ATTRIBUTION_TOLERANCE = 1e-9


def _num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _same(total: float, expected: float) -> bool:
    return math.isclose(total, expected, rel_tol=1e-9, abs_tol=1e-9)


def select_path_weighted_receipt(
    lcia_results: dict[str, Any] | None,
    *,
    canonical_indicator_key: str,
) -> dict[str, Any] | None:
    """Return the path-weighted receipt for the requested indicator, or None if absent.

    None means the solve did not emit the R3 view (older provider, missing lcia_methods, or
    foreground-only) — callers must fall back to the flat characterized terms, not fabricate.
    """
    receipts = (lcia_results or {}).get("path_weighted_contribution_receipts") or []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        if str(receipt.get("canonical_indicator_key") or "") == canonical_indicator_key:
            return receipt
    return None


def _exchange_aggregate(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    """Sum each path row's partitioned contribution under its elementary exchange id.

    The existing rule schema binds a rule to one exact exchange id (an elementary emission).
    When a background process's emission is split across N consumer paths, all N rows share the
    same elementary exchange id; summing their partitioned values recovers the whole emission
    so the rule decision applies consistently to every path.
    """
    weighted: dict[str, float | None] = {}
    for row in rows:
        exchange_id = str(row.get("exchange_id") or "")
        if not exchange_id:
            continue
        amount = _num(row.get("path_contribution_value"))
        current = weighted.get(exchange_id)
        if current is None:
            weighted[exchange_id] = amount
        elif amount is not None:
            weighted[exchange_id] = current + amount
    return weighted


def group_path_weighted_scopes(
    *,
    rules: list[dict[str, Any]],
    scaled_exchanges: list[dict[str, Any]],
    path_receipt: dict[str, Any] | None,
    indicator_unit: str,
) -> dict[str, Any]:
    """Apply the user method's rules to a path-weighted receipt and re-bucket by Scope.

    ``path_receipt`` must be one item from
    ``lcia.path_weighted_contribution_receipts`` selected by ``select_path_weighted_receipt``.
    If it is None, no rule is applied and the result reports ``coverage_gaps`` so callers must
    fall back to the flat characterized terms rather than invent a grouping.

    The reconciliation invariant stays identical to ``group_organization_scopes``: the Scope
    buckets + excluded + unattributed + engine_gap total exactly equals the sum of every path
    row's ``path_contribution_value``, which the engine already reconciles to the parent
    characterized term total. Nothing is zeroed; unattributed and engine-gap values are
    reported by exchange id so the user can see the gap rather than silently drop it.
    """
    if path_receipt is None:
        return {
            "indicator_unit": indicator_unit,
            "available": False,
            "reason": "path_weighted_receipt_not_emitted",
            "scopes": {scope: {"value": None, "unit": None, "term_count": 0} for scope in _SCOPES},
            "excluded": {"value": 0.0, "unit": indicator_unit, "term_count": 0},
            "unattributed": {"value": 0.0, "unit": indicator_unit, "exchange_ids": []},
            "engine_gap": {"value": 0.0, "unit": indicator_unit, "exchange_ids": []},
            "paths": [],
            "coverage_gaps": [],
            "contribution_total": 0.0,
            "reconciled": False,
            "problems": [{
                "code": "PATH_WEIGHTED_RECEIPT_MISSING",
                "message": "the solve did not emit a path-weighted receipt for this indicator; use the flat characterized terms",
            }],
            "scope_1_2_3_statement": False,
        }

    rows = [item for item in (path_receipt.get("terms") or []) if isinstance(item, dict)]
    weighted = _exchange_aggregate(rows)
    weighted_ids = set(weighted)

    # A user-pinned closed-leaf background is characterized by the engine under an expanded
    # process node that is not part of One's inventory boundary, so a Scope 2/3 rule cannot bind to
    # that node. The path-weighted receipt instead keys each such contribution by the exact
    # consumer input it was pinned onto; a rule bound to that selectable input governs those rows.
    consumer_ids = sorted({
        str(row.get("consumer_exchange_id") or "")
        for row in rows
        if row.get("attribution_basis") == "background_consumer_path" and row.get("consumer_exchange_id")
    })
    consumer_path_exchanges = [
        {
            "exchange_id": consumer_id,
            "direction": "input",
            "exchange_type": "technosphere",
            "process_id": node_prefix(consumer_id),
        }
        for consumer_id in consumer_ids
    ]

    resolved = resolve_method_identities(
        rules=rules,
        scaled_exchanges=scaled_exchanges,
        weighted_exchange_ids=weighted_ids | set(consumer_ids),
        consumer_path_exchanges=consumer_path_exchanges,
    )

    classification: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for binding in resolved["bindings"]:
        entry = {"boundary_status": binding["boundary_status"], "scope": binding["scope"]}
        existing = classification.get(binding["exchange_id"])
        if existing is not None and existing != entry:
            conflicts.append({
                "code": "METHOD_SCOPE_CONFLICT",
                "message": "two rules classify the same contribution path differently",
                "exchange_id": binding["exchange_id"],
                "first": existing,
                "second": entry,
            })
        classification[binding["exchange_id"]] = entry

    # Engine-side unattributed rows are labelled; they never enter a user-scope bucket.
    engine_gap_by_exchange: dict[str, float] = {}
    for row in rows:
        if row.get("attribution_basis") == "background_unattributed":
            exchange_id = str(row.get("exchange_id") or "")
            engine_gap_by_exchange[exchange_id] = (
                engine_gap_by_exchange.get(exchange_id, 0.0)
                + (_num(row.get("path_contribution_value")) or 0.0)
            )

    bucket_values = {scope: 0.0 for scope in _SCOPES}
    bucket_counts = {scope: 0 for scope in _SCOPES}
    excluded_total = 0.0
    excluded_count = 0
    unattributed: list[str] = []
    unattributed_total = 0.0
    path_details: list[dict[str, Any]] = []

    # Walk every path row once so per-path detail survives; the rule decision is applied to
    # the whole elementary exchange id and therefore holds identically for all its paths.
    for row in rows:
        exchange_id = str(row.get("exchange_id") or "")
        amount = _num(row.get("path_contribution_value")) or 0.0
        basis = str(row.get("attribution_basis") or "")
        cls = classification.get(exchange_id)
        if cls is None and basis == "background_consumer_path":
            # A user-pinned closed-leaf background is characterized under an expanded engine node
            # that is not in One's inventory boundary, so its rule binds to the selectable consumer
            # input instead. Fall back to the consumer path only when no elementary rule claimed it.
            consumer_id = str(row.get("consumer_exchange_id") or "")
            cls = classification.get(consumer_id)
            if cls is not None:
                exchange_id = consumer_id
        if basis == "background_unattributed":
            decision = "engine_gap"
        elif cls is None:
            decision = "unattributed"
            unattributed.append(exchange_id)
            unattributed_total += amount
        elif cls["boundary_status"] == "excluded":
            decision = "excluded"
            excluded_total += amount
            excluded_count += 1
        elif cls["boundary_status"] == "selected" and cls["scope"] in bucket_values:
            decision = cls["scope"]
            bucket_values[cls["scope"]] += amount
            bucket_counts[cls["scope"]] += 1
        else:
            decision = "unattributed"
            unattributed.append(exchange_id)
            unattributed_total += amount
        path_details.append({
            "exchange_id": exchange_id,
            "source_exchange_id": row.get("exchange_id"),
            "consumer_exchange_id": row.get("consumer_exchange_id"),
            "consumer_process_uuid": row.get("consumer_process_uuid"),
            "provider_instance_id": row.get("provider_instance_id"),
            "background_process_uuid": row.get("process_uuid"),
            "attribution_basis": basis,
            "path_share": _num(row.get("path_share")),
            "path_contribution_value": amount,
            "decision": decision,
        })

    contribution_total = sum(_num(item.get("path_contribution_value")) or 0.0 for item in rows)
    engine_gap_total = sum(engine_gap_by_exchange.values())
    bucketed = sum(bucket_values.values()) + excluded_total + unattributed_total + engine_gap_total
    reconciled = _same(bucketed, contribution_total) and not conflicts

    scopes = {
        scope: {
            "value": bucket_values[scope] if bucket_counts[scope] else None,
            "unit": indicator_unit if bucket_counts[scope] else None,
            "term_count": bucket_counts[scope],
        }
        for scope in _SCOPES
    }
    return {
        "indicator_unit": indicator_unit,
        "available": True,
        "attribution_coverage": path_receipt.get("attribution_coverage"),
        "scopes": scopes,
        "excluded": {"value": excluded_total, "unit": indicator_unit, "term_count": excluded_count},
        "unattributed": {
            "value": unattributed_total,
            "unit": indicator_unit,
            "exchange_ids": sorted(set(unattributed)),
        },
        "engine_gap": {
            "value": engine_gap_total,
            "unit": indicator_unit,
            "exchange_ids": sorted(engine_gap_by_exchange),
        },
        "paths": path_details,
        "coverage_gaps": resolved["coverage_gaps"],
        "contribution_total": contribution_total,
        "reconciled": reconciled,
        "problems": list(resolved["problems"]) + conflicts,
        # A user grouping is never a compliance or factor claim.
        "scope_1_2_3_statement": False,
    }
