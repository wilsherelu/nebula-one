"""Group a frozen contribution pool by user-defined flow-tag schemes.

A tag scheme is one analysis caliber: a versioned name, one category tree, and one confirmed
match per model exchange. It never computes a factor and never rescales the model; it only
selects contributions the engine already characterized and re-buckets them. The semantics differ
from a boundary method in one decisive way: a flow with no match is not "excluded", it is simply
outside this scheme's range, and it is reported as such instead of vanishing into a zero.

Every outcome stays distinct: a known value, a real zero, a tagged path the engine returned no
weighted value for, an untagged path, and a pending (unconfirmed) suggestion are never collapsed
into one another. Multi-scheme viewing keeps each scheme's panel separate, and union/intersection
deduplicate by the frozen contribution source key, never by flow name or global UUID.
"""

from __future__ import annotations

import math
from typing import Any

from .method_contribution_binding import resolve_method_identities
from .method_grouping import aggregate_contributions

# The persisted marker that distinguishes a tag scheme from a legacy boundary/Scope method.
TAG_SEMANTICS = "flow_tag.v1"
# Result-category calibers: a flow belongs to the caliber only through an assigned leaf category.
# `flow_tag.v1` keeps its original presence/pending reading so historical replays do not change.
RESULT_CATEGORY_SEMANTICS = "result_category.v1"
CALIBER_SEMANTICS = (TAG_SEMANTICS, RESULT_CATEGORY_SEMANTICS)

_TAG_BOUNDARY = {"selected": "selected", "pending": "pending", "include": "selected", "exclude": "excluded"}


def _num(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _same(total: float, expected: float) -> bool:
    return math.isclose(total, expected, rel_tol=1e-9, abs_tol=1e-9)


def tag_dimension(user_method: dict[str, Any] | None) -> dict[str, Any] | None:
    """The single category tree a tag scheme declares, or ``None`` for a malformed version."""
    dimensions = (user_method or {}).get("reporting_dimensions") or []
    return dimensions[0] if len(dimensions) == 1 else None


def leaf_category_ids(dimension: dict[str, Any] | None) -> set[str]:
    """The declared categories that can carry a contribution: no children, not marked non-leaf."""
    categories = [c for c in (dimension or {}).get("categories") or [] if isinstance(c, dict)]
    parents = {str(c.get("parent_id")) for c in categories if c.get("parent_id")}
    return {
        str(c["id"])
        for c in categories
        if c.get("id") and str(c["id"]) not in parents and c.get("is_leaf") is not False
    }


def consumer_path_exchanges(path_receipt: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The selectable consumer inputs a pinned background contribution was attributed onto."""
    from .method_contribution_binding import node_prefix

    ids = sorted(
        {
            str(row.get("consumer_exchange_id") or "")
            for row in (path_receipt or {}).get("terms") or []
            if isinstance(row, dict)
            and row.get("attribution_basis") == "background_consumer_path"
            and row.get("consumer_exchange_id")
        }
    )
    return [
        {
            "exchange_id": exchange_id,
            "direction": "input",
            "exchange_type": "technosphere",
            "process_id": node_prefix(exchange_id),
        }
        for exchange_id in ids
    ]


def _category_rows(
    *,
    dimension: dict[str, Any] | None,
    matched_known: list[tuple[str, float]],
    matched_missing: list[str],
    category_of: dict[str, str | None],
    indicator_unit: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], bool]:
    """Leaf/parent subtotals for a scheme, plus the tagged-but-uncategorized subtotal."""
    dimension_id = str((dimension or {}).get("id") or "")
    declared = (dimension or {}).get("categories") or []
    if not dimension_id or not declared:
        # No sub-categories: every match belongs directly to the tag, so nothing is "unattributed".
        return [], {"subtotal": 0.0, "unit": indicator_unit, "term_count": 0}, [], True
    contributions = [
        {
            "source_key": exchange_id,
            "value": value,
            "unit": indicator_unit,
            "boundary": "included",
            "categories": {dimension_id: category_of.get(exchange_id)} if category_of.get(exchange_id) else {},
        }
        for exchange_id, value in matched_known
    ]
    # A consumer can have a known subtotal and missing characterized paths simultaneously.
    contributions.extend({"source_key": f"missing::{exchange_id}", "value": None,
                          "unit": indicator_unit, "boundary": "included",
                          "categories": {dimension_id: category_of[exchange_id]} if category_of.get(exchange_id) else {}}
                         for exchange_id in matched_missing)
    aggregated = aggregate_contributions(
        dimensions=[dimension], contributions=contributions, indicator_unit=indicator_unit
    )
    grouped = aggregated["dimensions"][dimension_id]
    return (
        grouped["categories"],
        grouped["unattributed"],
        aggregated["problems"],
        bool(grouped["reconciled"]),
    )


def group_tag_scheme(
    *,
    rules: list[dict[str, Any]],
    scaled_exchanges: list[dict[str, Any]],
    weighted_terms: list[dict[str, Any]],
    dimension: dict[str, Any] | None,
    indicator_unit: str,
    consumer_paths: list[dict[str, Any]] | None = None,
    missing_exchange_ids: set[str] | None = None,
    semantics: str = TAG_SEMANTICS,
) -> dict[str, Any]:
    """Re-bucket one frozen contribution pool for a single tag scheme.

    ``weighted_terms`` are ``{exchange_id, contribution_value}`` rows the engine already produced;
    a ``None`` value is missing, never zero. Each rule binds through the same exact identity
    resolver every other grouping uses, so the same flow in two processes and the same provider on
    two consumer ports stay two independent matches.

    ``result_category.v1`` counts a bound path only when its rule names a declared leaf category;
    a rule without one is a problem, never an implicit match. ``flow_tag.v1`` keeps its historical
    presence/pending reading so old snapshots replay byte-identically.
    """
    if semantics not in CALIBER_SEMANTICS:
        raise ValueError(f"unknown caliber semantics {semantics!r}")
    result_category = semantics == RESULT_CATEGORY_SEMANTICS
    weighted: dict[str, float | None] = {}
    duplicate_terms: list[dict[str, Any]] = []
    for term in weighted_terms:
        if not isinstance(term, dict):
            continue
        exchange_id = str(term.get("exchange_id") or "")
        if exchange_id:
            if exchange_id in weighted:
                duplicate_terms.append({"code": "TAG_CONTRIBUTION_DUPLICATE", "exchange_id": exchange_id,
                                        "message": "the contribution pool contains a duplicate source"})
            weighted[exchange_id] = _num(term.get("contribution_value"))
    missing_pool = set(missing_exchange_ids or [])
    for exchange_id in missing_pool:
        weighted.setdefault(exchange_id, None)

    resolved = resolve_method_identities(
        rules=rules,
        scaled_exchanges=scaled_exchanges,
        weighted_exchange_ids=set(weighted),
        consumer_path_exchanges=consumer_paths,
    )
    dimension_id = str((dimension or {}).get("id") or "")
    leaves = leaf_category_ids(dimension) if result_category else set()

    classification: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = list(duplicate_terms)
    for binding in resolved["bindings"]:
        category = (binding.get("categories") or {}).get(dimension_id) if dimension_id else None
        if result_category:
            if dimension_id and category and str(category) in leaves:
                entry = {"status": "selected", "category": str(category)}
            else:
                # A stored caliber that lost its category is a defect, not an implicit "no".
                conflicts.append(
                    {
                        "code": "TAG_SCHEME_CATEGORY_INVALID",
                        "message": "a result-category rule must name a declared leaf category",
                        "exchange_id": binding["exchange_id"],
                        "category": category,
                    }
                )
                continue
        else:
            raw_status = binding.get("boundary_status")
            entry = {
                "status": _TAG_BOUNDARY.get(str(raw_status), "pending"),
                "category": category,
            }
        existing = classification.get(binding["exchange_id"])
        if existing is not None and existing != entry:
            conflicts.append(
                {
                    "code": "TAG_MATCH_CONFLICT",
                    "message": "two matches classify the same contribution path differently",
                    "exchange_id": binding["exchange_id"],
                    "first": existing,
                    "second": entry,
                }
            )
        classification[binding["exchange_id"]] = entry

    matched_known: list[tuple[str, float]] = []
    matched_missing: list[str] = []
    pending_ids: list[str] = []
    unmatched_ids: list[str] = []
    unmatched_known = 0.0
    unmatched_known_count = 0
    unmatched_missing: list[str] = []
    category_of: dict[str, str | None] = {}

    for exchange_id, value in weighted.items():
        cls = classification.get(exchange_id)
        if cls is None:
            unmatched_ids.append(exchange_id)
            if value is None or exchange_id in missing_pool:
                unmatched_missing.append(exchange_id)
            if value is not None:
                unmatched_known += value
                unmatched_known_count += 1
            continue
        if cls["status"] == "pending":
            pending_ids.append(exchange_id)
            continue
        if cls["status"] == "excluded":
            conflicts.append(
                {
                    "code": "TAG_MATCH_EXCLUDED",
                    "message": "a tag scheme reports a match or nothing; an excluded rule is ambiguous",
                    "exchange_id": exchange_id,
                }
            )
            continue
        category_of[exchange_id] = cls.get("category")
        if value is None or exchange_id in missing_pool:
            matched_missing.append(exchange_id)
        if value is not None:
            matched_known.append((exchange_id, value))

    # A match whose path the engine returned no weighted contribution for is a real gap, kept
    # apart from a missing factor on an existing contribution only by its reason code.
    gap_ids = sorted({str(gap.get("exchange_id") or "") for gap in resolved["coverage_gaps"]})
    missing_ids = sorted(set(matched_missing).union(gap_ids))
    for exchange_id in gap_ids:
        category_of[exchange_id] = classification.get(exchange_id, {}).get("category")

    known_total = sum(value for _, value in matched_known)
    categories, uncategorized, category_problems, categories_reconciled = _category_rows(
        dimension=dimension,
        matched_known=matched_known,
        matched_missing=missing_ids,
        category_of=category_of,
        indicator_unit=indicator_unit,
    )
    tag_known = known_total
    categorized_total = sum(row["subtotal"] or 0.0 for row in categories if row["is_leaf"])
    if categories:
        reconciled = (
            _same(categorized_total + (uncategorized["subtotal"] or 0.0), tag_known)
            and categories_reconciled
        )
    else:
        # Without sub-categories every matched value belongs directly to the tag itself.
        reconciled = True

    real_zero_ids = sorted(exchange_id for exchange_id, value in matched_known
                           if value == 0.0 and exchange_id not in missing_ids)
    total_terms = len(weighted)
    matched_terms = len({key for key, _ in matched_known} | set(missing_ids))
    problems = list(resolved["problems"]) + conflicts + category_problems

    return {
        "semantics": semantics,
        "dimension": {
            "id": dimension_id or None,
            "name": (dimension or {}).get("name"),
            "requires_full_coverage": bool((dimension or {}).get("requires_full_coverage")),
            "categories": categories,
        },
        "tag_total": {
            "value": tag_known if matched_known else None,
            "unit": indicator_unit if matched_known else None,
            "term_count": len(matched_known),
        },
        "uncategorized": uncategorized,
        "matched": {"term_count": matched_terms, "known_term_count": len(matched_known)},
        "unmatched": {
            "term_count": len(unmatched_ids),
            "known_term_count": unmatched_known_count,
            "known_value": unmatched_known if unmatched_known_count else None,
            "unit": indicator_unit if unmatched_known_count else None,
            "missing_count": len(unmatched_missing),
            "exchange_ids": sorted(unmatched_ids),
        },
        "pending": {"term_count": len(pending_ids), "exchange_ids": sorted(pending_ids)},
        "missing": {
            "term_count": len(missing_ids),
            "exchange_ids": missing_ids,
            "no_weighted_value_ids": gap_ids,
        },
        "real_zero": {"term_count": len(real_zero_ids), "exchange_ids": real_zero_ids},
        "coverage": {
            "weighted_term_count": total_terms,
            "matched_term_count": matched_terms,
            "unmatched_term_count": len(unmatched_ids),
            "pending_term_count": len(pending_ids),
            "matched_share": (matched_terms / total_terms) if total_terms else None,
            "complete": bool(weighted) and not unmatched_ids and not pending_ids and not missing_ids,
        },
        # Set-operation input: only contributions with a real value can enter a union/intersection.
        "matched_exchange_ids": sorted(exchange_id for exchange_id, _ in matched_known),
        # False means no flow carries a relation in this caliber yet; the reader sees that instead
        # of a zero total that could be mistaken for a complete, empty footprint.
        "populated": bool(matched_terms),
        "reconciled": reconciled and not problems,
        "problems": problems,
        "reporting_statement": False,
    }


def group_tag_schemes(
    *,
    schemes: list[dict[str, Any]],
    scaled_exchanges: list[dict[str, Any]],
    weighted_terms: list[dict[str, Any]],
    indicator_unit: str,
    mode: str = "separate",
    consumer_paths: list[dict[str, Any]] | None = None,
    missing_exchange_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Group one frozen pool for several tag schemes, with explicit set semantics.

    ``schemes`` items are ``{scheme, rules, dimension}``; ``scheme`` is the exact identity the
    caller cited. Each scheme is always computed on its own first. Union counts a contribution
    once even when several schemes match it, and intersection only keeps contributions every
    scheme matched - so 100 matched by A and B plus 30 matched only by A gives A=130, B=100,
    union=130 and intersection=100, never a 230 total.
    """
    if mode not in ("separate", "intersection", "union"):
        raise ValueError(f"unknown tag grouping mode {mode!r}")

    results: list[dict[str, Any]] = []
    memberships: dict[str, set[str]] = {}
    missing_memberships: dict[str, set[str]] = {}
    known_by_id: dict[str, float] = {}
    for term in weighted_terms:
        if not isinstance(term, dict):
            continue
        exchange_id = str(term.get("exchange_id") or "")
        value = _num(term.get("contribution_value"))
        if exchange_id and value is not None:
            known_by_id[exchange_id] = value

    for item in schemes:
        scheme = item.get("scheme") or {}
        scheme_key = str(scheme.get("method_id") or "")
        grouped = group_tag_scheme(
            rules=item.get("rules") or [],
            scaled_exchanges=scaled_exchanges,
            weighted_terms=weighted_terms,
            dimension=item.get("dimension"),
            indicator_unit=indicator_unit,
            consumer_paths=consumer_paths,
            missing_exchange_ids=missing_exchange_ids,
            semantics=str(item.get("semantics") or TAG_SEMANTICS),
        )
        grouped["scheme"] = scheme
        results.append(grouped)
        for exchange_id in grouped["matched_exchange_ids"]:
            memberships.setdefault(exchange_id, set()).add(scheme_key)
        for exchange_id in grouped["missing"]["exchange_ids"]:
            missing_memberships.setdefault(exchange_id, set()).add(scheme_key)

    all_memberships = {key: set(owners) for key, owners in memberships.items()}
    for key, owners in missing_memberships.items():
        all_memberships.setdefault(key, set()).update(owners)

    union_ids = sorted(all_memberships)
    intersection_ids = sorted(
        exchange_id for exchange_id, owners in all_memberships.items() if len(owners) == len(schemes)
    )

    def total(ids: list[str]) -> dict[str, Any]:
        value = sum(known_by_id[exchange_id] for exchange_id in ids if exchange_id in known_by_id)
        return {
            "value": value if any(key in known_by_id for key in ids) else None,
            "unit": indicator_unit if ids else None,
            "term_count": len(ids),
            "exchange_ids": ids,
            "missing_count": sum(key in missing_memberships for key in ids),
            "missing_exchange_ids": [key for key in ids if key in missing_memberships],
        }

    overlap = {
        "multi_scheme_term_count": sum(1 for owners in memberships.values() if len(owners) > 1),
        "term_count_by_scheme": {
            str((item.get("scheme") or {}).get("method_id") or ""): len(result["matched_exchange_ids"])
            for item, result in zip(schemes, results)
        },
    }
    union = total(union_ids)
    intersection = total(intersection_ids) if schemes else total([])
    union_reconciled = _same(
        union["value"] or 0.0,
        sum(known_by_id[exchange_id] for exchange_id in union_ids if exchange_id in known_by_id),
    )
    return {
        "mode": mode,
        "indicator_unit": indicator_unit,
        "schemes": results,
        "union": union if mode == "union" else None,
        "intersection": intersection if mode == "intersection" else None,
        "overlap": overlap,
        "reconciled": union_reconciled and all(result["reconciled"] for result in results),
        "problems": [problem for result in results for problem in result["problems"]],
        "reporting_statement": False,
    }
