"""Group Nebula LCA's weighted contributions by a user calculation method.

P3-B3 vertical slice (organization Scope). The numbers stay with Nebula LCA: this
module only re-buckets the per-exchange weighted contributions the engine already
returned, using the rules' selection, location role and Scope. Excluding a path
takes its value out of the Scope bucket and into an excluded total; a path with no
rule is left unattributed; a Scope whose only members are paths the engine does not
yet return weighted values for stays ``None`` (nothing grouped), never a fake zero.

Scope 1, 2 and 3 here are the user's declared grouping. This is not a GHG Protocol
or regulatory statement, and no value is computed from an emission factor.
"""

from __future__ import annotations

import math
from typing import Any

from .method_contribution_binding import resolve_method_identities

_SCOPES = ("scope_1", "scope_2", "scope_3")


def _num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _same(total: float, expected: float) -> bool:
    return math.isclose(total, expected, rel_tol=1e-9, abs_tol=1e-9)


def group_organization_scopes(
    *,
    rules: list[dict[str, Any]],
    scaled_exchanges: list[dict[str, Any]],
    terms: list[dict[str, Any]],
    indicator_unit: str,
) -> dict[str, Any]:
    """Re-bucket weighted elementary contribution ``terms`` by the user rules.

    ``terms`` must already be the validated contribution terms for one indicator
    (each carries ``exchange_id`` and a numeric ``contribution_value``). Every term
    is counted at most once, so ``scopes`` + ``excluded`` + ``unattributed``
    reconciles to ``contribution_total``; ``coverage_gaps`` lists selected paths the
    engine gave no weighted value for, which are reported rather than zeroed.
    """
    weighted: dict[str, float | None] = {}
    for term in terms:
        if not isinstance(term, dict):
            continue
        weighted[str(term.get("exchange_id") or "")] = _num(term.get("contribution_value"))
    weighted_ids = set(weighted)

    resolved = resolve_method_identities(
        rules=rules,
        scaled_exchanges=scaled_exchanges,
        weighted_exchange_ids=weighted_ids,
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

    bucket_values = {scope: 0.0 for scope in _SCOPES}
    bucket_counts = {scope: 0 for scope in _SCOPES}
    excluded_total = 0.0
    excluded_count = 0
    unattributed: list[str] = []
    unattributed_total = 0.0

    for exchange_id, value in weighted.items():
        amount = value or 0.0
        cls = classification.get(exchange_id)
        if cls is None or cls["boundary_status"] == "excluded":
            if cls is None:
                unattributed.append(exchange_id)
                unattributed_total += amount
            else:
                excluded_total += amount
                excluded_count += 1
            continue
        scope = cls["scope"]
        if cls["boundary_status"] == "selected" and scope in bucket_values:
            bucket_values[scope] += amount
            bucket_counts[scope] += 1
        else:
            # selected but carries no valid Scope: keep it out of the buckets, don't invent one
            unattributed.append(exchange_id)
            unattributed_total += amount

    contribution_total = sum(value or 0.0 for value in weighted.values())
    bucketed = sum(bucket_values.values()) + excluded_total + unattributed_total
    reconciled = _same(bucketed, contribution_total) and not conflicts

    problems = list(resolved["problems"]) + conflicts
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
        "scopes": scopes,
        "excluded": {"value": excluded_total, "unit": indicator_unit, "term_count": excluded_count},
        "unattributed": {"value": unattributed_total, "unit": indicator_unit, "exchange_ids": sorted(unattributed)},
        "coverage_gaps": resolved["coverage_gaps"],
        "contribution_total": contribution_total,
        "reconciled": reconciled,
        "problems": problems,
        # A user grouping is never a compliance or factor claim.
        "scope_1_2_3_statement": False,
    }
