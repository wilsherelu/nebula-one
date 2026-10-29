"""Compile user method rules into resolved, non-ambiguous accounting decisions.

This is the frozen core's compiler. The three layers stay independent: the
accounting boundary (include / exclude / pending / inherit) and the contribution
attribution (which category per reporting dimension) are resolved on their own, so
"follow the process default" is the absence of an override, not a fourth state.

Resolution priority for one consumption target is: explicit exchange rule > process
default > method default > pending. It is never decided by array order or last edit;
two rules at the same priority that disagree produce a conflict instead of a silent
winner. A process is a default container, not an extra contribution, so process
exclusion that a single exchange overrides reports the process as ``partial`` and
lists the exception rather than double-counting the process total. Mandatory method
limits (a dimension that requires a category whenever a contribution is included) are
checked independently and cannot be escaped by an override.
"""

from __future__ import annotations

from typing import Any

from ..hashing import canonical_json_sha256

_BOUNDARY_STATES = ("include", "exclude", "pending")


def _decided(value: Any) -> bool:
    return isinstance(value, str) and value in _BOUNDARY_STATES


def _key_of(rule: dict[str, Any]) -> tuple[str, str]:
    return (str(rule.get("exchange_id") or ""), str(rule.get("contribution_target") or "direct"))


def _process_key(rule: dict[str, Any]) -> tuple[str, str]:
    return (str(rule.get("process_instance_id") or ""), str(rule.get("contribution_target") or "direct"))


def compile_method_rules(
    *,
    dimensions: list[dict[str, Any]],
    exchange_targets: list[dict[str, Any]],
    exchange_rules: list[dict[str, Any]] | None = None,
    process_defaults: list[dict[str, Any]] | None = None,
    method_default: dict[str, Any] | None = None,
    required_category_dimensions: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve every consumption target's boundary and per-dimension category.

    ``exchange_targets`` are the concrete paths (``exchange_id``,
    ``process_instance_id``, ``contribution_target``) the grouping will sum. Each
    resolved target reports its effective boundary, its categories per dimension, and
    which rule each layer came from, so the result page can explain "沿用过程" vs
    "本行设置" and list the exceptions that make a process "partial".
    """
    dimensions = list(dimensions)
    dimension_ids = [str(d.get("id")) for d in dimensions]
    required_dims = set(required_category_dimensions or [])
    method_default = method_default or {}

    problems: list[dict[str, Any]] = []

    # Index exchange rules per (exchange_id, contribution_target); same-priority clashes conflict.
    ex_rules: dict[tuple[str, str], dict[str, Any]] = {}
    for rule in exchange_rules or []:
        key = _key_of(rule)
        prior = ex_rules.get(key)
        if prior is not None:
            conflicts = _overlapping_disagreements(prior, rule, dimension_ids)
            for field, first, second in conflicts:
                problems.append({
                    "code": "METHOD_COMPILE_CONFLICT",
                    "message": f"two exchange rules disagree on {field} for the same target",
                    "field": field,
                    "exchange_id": key[0],
                    "contribution_target": key[1],
                    "first": first,
                    "second": second,
                })
        ex_rules[key] = rule

    # Index process defaults; a process cannot carry two opposite defaults.
    pr_defaults: dict[tuple[str, str], dict[str, Any]] = {}
    for rule in process_defaults or []:
        key = _process_key(rule)
        prior = pr_defaults.get(key)
        if prior is not None:
            conflicts = _overlapping_disagreements(prior, rule, dimension_ids)
            for field, first, second in conflicts:
                problems.append({
                    "code": "METHOD_COMPILE_CONFLICT",
                    "message": f"two process defaults disagree on {field}",
                    "field": field,
                    "process_instance_id": key[0],
                    "contribution_target": key[1],
                    "first": first,
                    "second": second,
                })
        pr_defaults[key] = rule

    resolved: list[dict[str, Any]] = []
    for target in exchange_targets:
        key = _key_of(target)
        process_key = _process_key(target)
        ex = ex_rules.get(key)
        pr = pr_defaults.get(process_key)

        # --- boundary layer: exchange > process > method > pending, inherited on its own
        boundary_source = "pending"
        boundary = "pending"
        if ex is not None and _decided(ex.get("boundary")):
            boundary, boundary_source = ex["boundary"], "exchange"
        elif pr is not None and _decided(pr.get("boundary")):
            boundary, boundary_source = pr["boundary"], "process"
        elif _decided(method_default.get("boundary")):
            boundary, boundary_source = method_default["boundary"], "method"

        # --- attribution layer: same priority, resolved per dimension independently
        categories: dict[str, dict[str, Any]] = {}
        for dim_id in dimension_ids:
            value = None
            source = "none"
            if ex is not None and (ex.get("categories") or {}).get(dim_id) is not None:
                value, source = ex["categories"][dim_id], "exchange"
            elif pr is not None and (pr.get("categories") or {}).get(dim_id) is not None:
                value, source = pr["categories"][dim_id], "process"
            elif (method_default.get("categories") or {}).get(dim_id) is not None:
                value, source = method_default["categories"][dim_id], "method"
            categories[dim_id] = {"category": value, "source": source}

        override_notes: list[str] = []
        if ex is not None and _decided(ex.get("boundary")) and pr is not None and _decided(pr.get("boundary")) and ex["boundary"] != pr["boundary"]:
            override_notes.append("exchange boundary overrides the process default")

        # Required category only applies when the contribution is actually included.
        if boundary == "include":
            for dim_id in required_dims:
                if categories.get(dim_id, {}).get("category") is None:
                    problems.append({
                        "code": "METHOD_COMPILE_REQUIRED_CATEGORY",
                        "message": "an included contribution must carry a category for this dimension",
                        "exchange_id": key[0],
                        "contribution_target": key[1],
                        "dimension_id": dim_id,
                    })

        resolved.append({
            "exchange_id": key[0],
            "process_instance_id": str(target.get("process_instance_id") or ""),
            "contribution_target": key[1],
            "boundary": boundary,
            "boundary_source": boundary_source,
            "categories": categories,
            "override_notes": override_notes,
        })

    resolved.sort(key=lambda item: (item["exchange_id"], item["contribution_target"]))

    # A process is "partial" when its default boundary is overridden by some exchanges.
    process_status = _derive_process_status(process_defaults or [], resolved)

    plan_hash = canonical_json_sha256({
        "dimensions": dimension_ids,
        "required_category_dimensions": sorted(required_dims),
        "resolved": resolved,
        "process_status": process_status,
    })
    return {
        "resolved_targets": resolved,
        "process_status": process_status,
        "problems": problems,
        "valid": not problems,
        "execution_plan_sha256": plan_hash,
    }


def _overlapping_disagreements(a: dict[str, Any], b: dict[str, Any], dimension_ids: list[str]) -> list[tuple]:
    conflicts: list[tuple] = []
    if _decided(a.get("boundary")) and _decided(b.get("boundary")) and a["boundary"] != b["boundary"]:
        conflicts.append(("boundary", a["boundary"], b["boundary"]))
    for dim_id in dimension_ids:
        ca = (a.get("categories") or {}).get(dim_id)
        cb = (b.get("categories") or {}).get(dim_id)
        if ca is not None and cb is not None and ca != cb:
            conflicts.append((f"category:{dim_id}", ca, cb))
    return conflicts


def _derive_process_status(process_defaults: list[dict[str, Any]], resolved: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    status: dict[str, dict[str, Any]] = {}
    for default in process_defaults:
        pid = str(default.get("process_instance_id") or "")
        if not pid:
            continue
        status.setdefault(pid, {"default_boundary": default.get("boundary", "pending"), "exceptions": [], "state": default.get("boundary", "pending")})
    for item in resolved:
        pid = item["process_instance_id"]
        entry = status.get(pid)
        if entry is None:
            continue
        if item["boundary"] != entry["default_boundary"]:
            entry["exceptions"].append({"exchange_id": item["exchange_id"], "contribution_target": item["contribution_target"], "boundary": item["boundary"]})
    for entry in status.values():
        if entry["exceptions"]:
            entry["state"] = "partial"
    return status
