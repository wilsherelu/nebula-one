"""Adapt persisted method rules (schema v1 and v2) into the compiler's shape.

The frozen core has three independent layers, but methods were first written against a
single flat ``scope`` value plus a separate ``cbam_relevant`` flag. This module is the
explicit, versioned bridge the plan requires: it never lets the two legacy switches act
on their own — every rule resolves to one accounting ``boundary`` and one per-dimension
category map. ``cbam_relevant`` names the flows a regulation reaches and the accounting
boundary names what this method counts, so they stay independent (a CBAM-relevant emission
this method excludes is a legal narrowing, not a contradiction); for a CBAM purpose only the
one enforceable direction yields a conflict — counting a flow the regulation does not reach.

It is a pure transformation: no engine, no database, no factors. It feeds
``analysis.method_compile.compile_method_rules`` and ``analysis.method_grouping``; it does
not itself decide numbers. ``_SCOPES`` and ``group_organization_scopes`` stay as the
LC-Scope compatibility path; new dimensions arrive through method definitions in R1.
"""

from __future__ import annotations

from typing import Any

LC_SCOPE_DIMENSION_ID = "lc_scope"
# The three GHG-Purpose-style categories the legacy ``scope`` field already used. Kept as
# leaves so a v1 method and a v2 LC-Scope dimension share one identity and renumber nothing.
LC_SCOPE_CATEGORY_IDS = ("scope_1", "scope_2", "scope_3")

# ``boundary_status`` was the only inclusion switch on a v1 rule; it maps straight onto the
# core boundary. ``pending`` stays ``pending`` (never defaulted to include or excluded).
_LEGACY_BOUNDARY = {"selected": "include", "excluded": "exclude", "pending": "pending"}
_DECIDED_BOUNDARY = ("include", "exclude", "pending")


def lc_scope_dimension(*, requires_full_coverage: bool = False) -> dict[str, Any]:
    """A versioned reporting-dimension definition equivalent to the legacy LC-Scope field."""
    return {
        "id": LC_SCOPE_DIMENSION_ID,
        "mutually_exclusive": True,
        "requires_full_coverage": requires_full_coverage,
        "categories": [
            {"id": category_id, "name": category_id, "is_leaf": True}
            for category_id in LC_SCOPE_CATEGORY_IDS
        ],
    }


def _boundary_of(rule: dict[str, Any]) -> str:
    """Resolve one rule's accounting boundary, preferring an explicit v2 ``boundary``.

    ``inherit`` (or any undecided v2 value) falls through to the legacy ``boundary_status``
    so a partially-migrated rule still resolves; the compiler treats a non-decided value as
    "defer to the process/method default", never as a fourth final state.
    """
    explicit = rule.get("boundary")
    if explicit in _DECIDED_BOUNDARY or explicit == "inherit":
        return explicit
    return _LEGACY_BOUNDARY.get(str(rule.get("boundary_status") or ""), "pending")


def _categories_of(rule: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Return ``{dimension: category}`` plus any switch-conflict problems for one rule."""
    problems: list[dict[str, Any]] = []
    categories: dict[str, str] = {}
    for dimension, category in (rule.get("categories") or {}).items():
        if category:
            categories[str(dimension)] = str(category)

    legacy_scope = rule.get("scope")
    if legacy_scope:
        current = categories.get(LC_SCOPE_DIMENSION_ID)
        if current is not None and current != legacy_scope:
            problems.append(_conflict(rule, "scope", current, legacy_scope))
        else:
            categories[LC_SCOPE_DIMENSION_ID] = str(legacy_scope)
    return categories, problems


def _conflict(rule: dict[str, Any], switch: str, first: Any, second: Any) -> dict[str, Any]:
    return {
        "code": "METHOD_RULE_SWITCH_CONFLICT",
        "message": (
            f"the {switch} switch and the resolved boundary disagree; "
            "the two legacy flags may not each take effect"
        ),
        "switch": switch,
        "process_instance_id": rule.get("process_instance_id"),
        "exchange_id": rule.get("exchange_id"),
        "first": first,
        "second": second,
    }


def resolve_rule(
    rule: dict[str, Any], *, enforce_cbam_relevance: bool = False
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Turn one stored rule into a compiler shape ``(exchange/process)`` entry.

    ``enforce_cbam_relevance`` is set by a CBAM-purpose caller so that a contribution the
    method selects but does not flag CBAM-relevant becomes a conflict rather than a silent
    inclusion; the generic adapter leaves that judgement to the caller.
    """
    problems: list[dict[str, Any]] = []
    boundary = _boundary_of(rule)
    categories, category_problems = _categories_of(rule)
    problems.extend(category_problems)

    # An explicit v2 boundary that contradicts a *declared* legacy status is the same class
    # of bug. An absent boundary_status (the common v2 case) is not a "pending" decision, so
    # it must not be reported as disagreeing with the explicit boundary.
    explicit = rule.get("boundary")
    raw_status = rule.get("boundary_status")
    legacy = _LEGACY_BOUNDARY.get(str(raw_status)) if raw_status else None
    if explicit in _DECIDED_BOUNDARY and legacy in _DECIDED_BOUNDARY and explicit != legacy:
        problems.append(_conflict(rule, "boundary_status", explicit, legacy))

    # ``cbam_relevant`` names which flows the regulation reaches; the accounting boundary says
    # which this method counts. They are the core's two independent layers, so a CBAM-relevant
    # emission the method excludes is a legal narrowing, not a contradiction, and is never a
    # conflict. Only the enforceable direction fails: a CBAM purpose may not *count* a flow the
    # regulation does not reach, because that would inflate the regulated total with an auxiliary.
    cbam = bool(rule.get("cbam_relevant"))
    if enforce_cbam_relevance and boundary == "include" and not cbam:
        problems.append(_conflict(rule, "cbam_relevant", False, boundary))

    # Explicit exclusion needs no contribution category (core rule 4).
    if boundary == "exclude":
        categories = {}

    shape = {
        "process_instance_id": rule.get("process_instance_id"),
        "exchange_id": rule.get("exchange_id"),
        "contribution_target": str(rule.get("contribution_target") or "direct"),
        "boundary": boundary,
        "categories": categories,
    }
    return shape, problems


def adapt_rules(
    rules: list[dict[str, Any]],
    *,
    enforce_cbam_relevance: bool = False,
    dimensions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Partition stored rules into compiler ``exchange_rules`` / ``process_defaults``.

    A rule with an ``exchange_id`` targets one consumption path; one without it is a process
    default. Both carry the resolved boundary and category map so the compiler inherits
    boundary and attribution independently. ``conflicts`` fail-closed the whole method.

    ``dimensions`` is the method's declared reporting-dimension tree (LC-Scope 1-3 is one such
    tree; a non-Scope ``plant_split`` is another). When omitted the adapter supplies the legacy
    LC-Scope dimension so every pre-existing v1 method compiles exactly as before. When custom
    dimensions are declared but a rule still carries a legacy ``scope`` value, the LC-Scope
    dimension is folded in so that rule keeps resolving — the two coexist without a renumber.
    """
    exchange_rules: list[dict[str, Any]] = []
    process_defaults: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        shape, problems = resolve_rule(rule, enforce_cbam_relevance=enforce_cbam_relevance)
        conflicts.extend(problems)
        if shape.get("exchange_id"):
            exchange_rules.append(shape)
        else:
            process_defaults.append(shape)

    effective = list(dimensions) if dimensions else [lc_scope_dimension()]
    if dimensions and any(rule.get("scope") for rule in rules if isinstance(rule, dict)):
        if not any(str(d.get("id")) == LC_SCOPE_DIMENSION_ID for d in effective):
            effective.append(lc_scope_dimension())

    return {
        "exchange_rules": exchange_rules,
        "process_defaults": process_defaults,
        "conflicts": conflicts,
        "dimensions": effective,
    }
