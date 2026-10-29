"""Generic contribution attribution across versioned method dimensions.

This is the frozen core's grouping kernel. It is industry-neutral: reporting
categories come from a versioned method definition (LC-Scope 1-3 is just one such
definition; CBAM-style direct/indirect/precursor is another), so adding hydrogen,
fertilizer or aluminium methods needs no new code branch here.

The kernel only re-buckets weighted contributions the engine already produced — it
never computes a factor and never sums across dimensions. Reconciliation covers
known, same-caliber values only: attributed + unattributed + a real (non-missing)
total is checked, and this deliberately does NOT assert that missing paths are zero
or that the lifecycle is complete. A real zero, a missing value, an included but
unclassified contribution and an explicit exclusion are four distinct outcomes.
"""

from __future__ import annotations

import math
from typing import Any

from .method_contribution_binding import resolve_method_identities

# The legacy LC-Scope dimension id, used only to fold a v1 rule's ``scope`` into a category so a
# custom-dimension method that still carries a scope value groups that contribution too.
_LC_SCOPE_DIMENSION_ID = "lc_scope"
_LEGACY_BOUNDARY = {"selected": "include", "excluded": "exclude", "pending": "pending"}
# The compiler speaks include/exclude/pending; the aggregation kernel speaks included/excluded/pending.
_AGGREGATE_BOUNDARY = {"include": "included", "exclude": "excluded", "pending": "pending"}


def _as_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _same(total: float, expected: float) -> bool:
    return math.isclose(total, expected, rel_tol=1e-9, abs_tol=1e-9)


def normalize_dimensions(dimensions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Validate and index reporting dimensions; leaves carry values, parents roll up."""
    normalized: dict[str, dict[str, Any]] = {}
    for dimension in dimensions:
        dim_id = str(dimension.get("id") or "").strip()
        if not dim_id or dim_id in normalized:
            raise ValueError("each reporting dimension needs a unique id")
        categories: dict[str, dict[str, Any]] = {}
        for category in dimension.get("categories") or []:
            cat_id = str(category.get("id") or "").strip()
            if not cat_id or cat_id in categories:
                raise ValueError(f"dimension {dim_id} needs unique category ids")
            categories[cat_id] = {
                "id": cat_id,
                "name": category.get("name"),
                "parent_id": str(category.get("parent_id")) if category.get("parent_id") else None,
                "is_leaf": bool(category.get("is_leaf", category.get("parent_id") is None)),
            }
        for category in categories.values():
            parent = category["parent_id"]
            if parent is not None and parent not in categories:
                raise ValueError(f"category {category['id']} names an unknown parent {parent}")
        for category in categories.values():
            parent = category["parent_id"]
            if parent is not None and categories[parent]["is_leaf"]:
                raise ValueError(f"category {parent} is a leaf and cannot have children")
            ancestors = {category["id"]}
            while parent is not None:
                if parent in ancestors:
                    raise ValueError(f"dimension {dim_id} has a category cycle")
                ancestors.add(parent)
                parent = categories[parent]["parent_id"]
        normalized[dim_id] = {
            "id": dim_id,
            "name": dimension.get("name"),
            "mutually_exclusive": bool(dimension.get("mutually_exclusive", True)),
            "requires_full_coverage": bool(dimension.get("requires_full_coverage", False)),
            "categories": categories,
        }
    return normalized


def _leaf_descendants(categories: dict[str, dict[str, Any]], root_id: str) -> list[str]:
    """Return every leaf under ``root_id`` (including itself when it is a leaf)."""
    children: dict[str, list[str]] = {}
    for cat in categories.values():
        if cat["parent_id"] is not None:
            children.setdefault(cat["parent_id"], []).append(cat["id"])
    collected: list[str] = []

    def walk(cat_id: str) -> None:
        node = categories[cat_id]
        if node["is_leaf"]:
            collected.append(cat_id)
            return
        for child in sorted(children.get(cat_id, [])):
            walk(child)

    walk(root_id)
    return collected


def aggregate_contributions(
    *,
    dimensions: list[dict[str, Any]],
    contributions: list[dict[str, Any]],
    indicator_unit: str,
) -> dict[str, Any]:
    """Re-bucket weighted contributions into method-defined categories.

    Each contribution is ``{source_key, value, unit, boundary, categories}`` where
    ``boundary`` is ``included`` / ``excluded`` / ``pending`` and ``categories`` maps
    a dimension id to a single category id (or ``None`` when the user left it
    unclassified). ``value`` may be ``None`` (a path the engine returned no weighted
    number for) — that is missing, never zero.
    """
    dims = normalize_dimensions(dimensions)

    included_known: list[tuple[str, float]] = []  # (source_key, value) with a real number
    excluded_known_total = 0.0
    excluded_count = 0
    excluded_missing: list[str] = []
    pending_count = 0
    missing_value: list[str] = []
    seen_source_keys: set[str] = set()
    problems: list[dict[str, Any]] = []

    for item in contributions:
        if not isinstance(item, dict):
            continue
        source_key = str(item.get("source_key") or "")
        if source_key in seen_source_keys:
            problems.append({
                "code": "GROUPING_DUPLICATE_SOURCE",
                "message": "two contributions share one source path key",
                "source_key": source_key,
            })
            continue
        seen_source_keys.add(source_key)
        unit = str(item.get("unit") or "")
        value = _as_number(item.get("value"))
        if unit != indicator_unit:
            problems.append({
                "code": "GROUPING_UNIT_MISMATCH",
                "message": "a contribution is not in the indicator's unit; it is not summed",
                "source_key": source_key,
                "unit": unit,
            })
            continue
        boundary = str(item.get("boundary") or "pending")
        if boundary == "pending":
            pending_count += 1
            continue
        if boundary == "excluded":
            excluded_count += 1
            if value is None:
                excluded_missing.append(source_key)
            else:
                excluded_known_total += value
            continue
        # included
        if value is None:
            missing_value.append(source_key)
            continue
        included_known.append((source_key, value))

    known_total = sum(value for _, value in included_known)
    known_source_keys = {key for key, _ in included_known}

    dimensions_out: dict[str, Any] = {}
    overall_reconciled = not problems
    for dim_id, dim in dims.items():
        categories = dim["categories"]
        category_value = {cat_id: 0.0 for cat_id in categories}
        category_count = {cat_id: 0 for cat_id in categories}
        category_missing = {cat_id: 0 for cat_id in categories}
        unattributed_value = 0.0
        unattributed_count = 0
        unclassified_missing = 0

        for item in contributions:
            if not isinstance(item, dict) or str(item.get("source_key") or "") not in known_source_keys:
                continue
            raw_cat = (item.get("categories") or {}).get(dim_id)
            cat = str(raw_cat) if raw_cat else None
            source_key = str(item.get("source_key") or "")
            value = _as_number(item.get("value")) or 0.0
            if cat is None:
                unattributed_value += value
                unattributed_count += 1
                continue
            leaf_cat = categories.get(cat)
            if leaf_cat is None:
                problems.append({
                    "code": "GROUPING_UNKNOWN_CATEGORY",
                    "message": "a contribution names a category absent from this dimension",
                    "source_key": source_key,
                    "dimension_id": dim_id,
                    "category_id": cat,
                })
                overall_reconciled = False
                continue
            if not leaf_cat["is_leaf"]:
                problems.append({
                    "code": "GROUPING_PARENT_NOT_LEAF",
                    "message": "only leaf categories carry contributions; parents roll up",
                    "source_key": source_key,
                    "dimension_id": dim_id,
                    "category_id": cat,
                })
                overall_reconciled = False
                continue
            category_value[cat] += value
            category_count[cat] += 1

        # real-missing (included, no value) that were classified are counted for completeness only
        for item in contributions:
            if isinstance(item, dict) and str(item.get("source_key") or "") in {m for m in missing_value}:
                raw_cat = (item.get("categories") or {}).get(dim_id)
                if raw_cat:
                    category_missing[str(raw_cat)] += 1
                else:
                    unclassified_missing += 1

        category_rows = []
        for cat_id, cat in categories.items():
            if cat["is_leaf"]:
                subtotal = category_value[cat_id]
                term_count = category_count[cat_id]
            else:
                leaves = _leaf_descendants(categories, cat_id)
                subtotal = sum(category_value[leaf] for leaf in leaves)
                term_count = sum(category_count[leaf] for leaf in leaves)
            category_rows.append({
                "id": cat_id,
                "name": cat["name"],
                "parent_id": cat["parent_id"],
                "is_leaf": cat["is_leaf"],
                "subtotal": subtotal if term_count else None,
                "unit": indicator_unit if term_count else None,
                "term_count": term_count,
                "missing_count": category_missing[cat_id],
            })

        attributed = sum(category_value.values())
        dim_reconciled = _same(attributed + unattributed_value, known_total)
        completeness = "unavailable"
        if known_total == 0 and not included_known:
            completeness = "empty"
        elif missing_value or unclassified_missing or unattributed_count:
            completeness = "partial"
        else:
            completeness = "available"
        if dim["requires_full_coverage"] and (missing_value or unclassified_missing or unattributed_count):
            completeness = "partial"

        dimensions_out[dim_id] = {
            # The reader-facing dimension name; the id stays the stable key.
            "name": dim.get("name") or None,
            "categories": category_rows,
            "unattributed": {"subtotal": unattributed_value, "term_count": unattributed_count},
            "reconciled": dim_reconciled,
            "requires_full_coverage": dim["requires_full_coverage"],
            "completeness": completeness,
        }
        overall_reconciled = overall_reconciled and dim_reconciled

    return {
        "indicator_unit": indicator_unit,
        "known_total": known_total,
        "known_term_count": len(included_known),
        "excluded": {"value": excluded_known_total, "unit": indicator_unit, "term_count": excluded_count, "missing_count": len(excluded_missing)},
        "pending": {"term_count": pending_count},
        "missing_value": {"count": len(missing_value), "source_keys": sorted(missing_value)},
        "dimensions": dimensions_out,
        "reconciled": overall_reconciled,
        "problems": problems,
        # A user grouping is never a compliance or factor claim.
        "reporting_statement": False,
    }


def _effective_categories_for_binding(binding: dict[str, Any]) -> dict[str, str]:
    """Merge a rule's explicit per-dimension categories with its legacy ``scope`` value.

    A v1 rule that only names ``scope`` still lands in the LC-Scope dimension, so a custom
    method that carries both a category tree and a legacy scope groups both without a renumber.
    """
    categories = {str(k): str(v) for k, v in (binding.get("categories") or {}).items() if v}
    scope = binding.get("scope")
    if scope:
        categories.setdefault(_LC_SCOPE_DIMENSION_ID, str(scope))
    return categories


def _boundary_for_binding(binding: dict[str, Any]) -> str:
    boundary = binding.get("boundary")
    if boundary in ("include", "exclude", "pending"):
        return _AGGREGATE_BOUNDARY[boundary]
    legacy = _LEGACY_BOUNDARY.get(str(binding.get("boundary_status") or ""), "pending")
    return _AGGREGATE_BOUNDARY[legacy]


def path_rows_to_weighted_terms(path_receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep background values under their exact selectable consumption path."""
    totals: dict[str, float | None] = {}
    for row in (path_receipt or {}).get("terms") or []:
        if not isinstance(row, dict):
            continue
        exchange_id = str((row.get("consumer_exchange_id") if row.get("attribution_basis") == "background_consumer_path"
                           else row.get("exchange_id")) or "")
        if not exchange_id:
            continue
        raw = row.get("path_contribution_value")
        try:
            amount = float(raw)
        except (TypeError, ValueError):
            amount = None
        if amount is None or not math.isfinite(amount) or (exchange_id in totals and totals[exchange_id] is None):
            totals[exchange_id] = None
        else:
            totals[exchange_id] = (totals.get(exchange_id) or 0.0) + amount
    return [{"exchange_id": key, "contribution_value": value} for key, value in totals.items()]


def build_dimension_grouping(
    *,
    user_method: dict[str, Any],
    scaled_exchanges: list[dict[str, Any]],
    weighted_terms: list[dict[str, Any]],
    indicator_unit: str,
    path_receipt: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Group weighted values into a method's declared non-Scope categories, or ``None``.

    Only a method that declares its own reporting dimensions gets a ``dimension_grouping``; a
    Scope-only (legacy) method keeps the LC-Scope buckets and is left as ``None`` so the historical
    result/export shape is untouched. The effective dimension tree comes from the frozen execution
    plan, never re-derived from the rules here.
    """
    declared = user_method.get("reporting_dimensions") or []
    if not declared:
        return None
    plan_dims = (user_method.get("execution_plan") or {}).get("dimensions") or declared
    return group_weighted_by_dimensions(
        rules=user_method["rules"],
        scaled_exchanges=scaled_exchanges,
        weighted_terms=weighted_terms,
        dimensions=plan_dims,
        indicator_unit=indicator_unit or "",
        consumer_path_exchanges=[{"exchange_id": key, "direction": "input", "exchange_type": "technosphere",
                                  "process_id": key.split("::", 1)[0]}
                                 for key in sorted({row["consumer_exchange_id"] for row in (path_receipt or {}).get("terms", [])
                                                    if row.get("attribution_basis") == "background_consumer_path" and row.get("consumer_exchange_id")})],
    )


def group_weighted_by_dimensions(
    *,
    rules: list[dict[str, Any]],
    scaled_exchanges: list[dict[str, Any]],
    weighted_terms: list[dict[str, Any]],
    dimensions: list[dict[str, Any]],
    indicator_unit: str,
    consumer_path_exchanges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Group engine per-exchange weighted values into a method's declared category dimensions.

    ``weighted_terms`` are ``{exchange_id, contribution_value}`` rows the engine already produced
    (the same per-elementary-flow values the LC-Scope groupers consume). Each rule is bound to its
    consumption path through ``resolve_method_identities`` — never by display name or array order —
    and the resolved boundary plus per-dimension categories are handed to the generic
    ``aggregate_contributions`` kernel. A weighted path no rule claims is treated as
    included-unclassified, so it surfaces in the ``unattributed`` subtotal instead of vanishing.

    Nothing is computed: no factor, no cross-dimension sum, no zeroing of missing values. When
    ``dimensions`` is empty this reports the same shape the LC-Scope path would, but with no
    categories declared, so the caller can tell "custom grouping" from the legacy Scope buckets.
    """
    weighted: dict[str, float | None] = {}
    for term in weighted_terms:
        if not isinstance(term, dict):
            continue
        weighted[str(term.get("exchange_id") or "")] = _as_number(term.get("contribution_value"))
    weighted_ids = set(weighted)

    resolved = resolve_method_identities(
        rules=rules,
        scaled_exchanges=scaled_exchanges,
        weighted_exchange_ids=weighted_ids,
        consumer_path_exchanges=consumer_path_exchanges,
    )

    classification: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for binding in resolved["bindings"]:
        entry = {
            "boundary": _boundary_for_binding(binding),
            "categories": _effective_categories_for_binding(binding),
        }
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

    contributions: list[dict[str, Any]] = []
    for exchange_id, value in weighted.items():
        cls = classification.get(exchange_id)
        if cls is None:
            # An engine contribution no rule claims: included but unclassified, kept visible.
            contributions.append({
                "source_key": exchange_id,
                "value": value,
                "unit": indicator_unit,
                "boundary": "included",
                "categories": {},
            })
            continue
        contributions.append({
            "source_key": exchange_id,
            "value": value,
            "unit": indicator_unit,
            "boundary": cls["boundary"],
            "categories": cls["categories"],
        })

    aggregated = aggregate_contributions(
        dimensions=dimensions,
        contributions=contributions,
        indicator_unit=indicator_unit,
    )
    problems = list(resolved["problems"]) + conflicts + aggregated["problems"]
    return {
        "grouping": aggregated,
        "coverage_gaps": resolved["coverage_gaps"],
        "uncovered_exchange_ids": resolved["uncovered_exchange_ids"],
        "reconciled": aggregated["reconciled"] and not conflicts,
        "problems": problems,
        "scope_1_2_3_statement": False,
    }
