"""Resolve user calculation-method rules to exact engine contribution paths.

This is the P3-B identity seam: a saved rule must bind to one specific model
consumption path, and that path must be one the engine actually returns a
per-exchange weighted contribution for. Rules are never emission factors and
never a regulatory conclusion; they only select and classify contributions that
Nebula LCA already produced.

The join key is ``exchange_id``, which the solved graph builds as
``"{model_node_id}::{port_id}"`` (see ``provider_solve._graph_technosphere_exchanges``).
Two model nodes that consume the same provider process therefore keep distinct
exchange ids, so attribution is per consumption path and can never be merged by
provider ``process_id``. Identity is resolved only by exact ids; nothing here
guesses by display name, array position or ratio.
"""

from __future__ import annotations

from typing import Any


def node_prefix(exchange_id: str) -> str:
    """Return the model node id encoded in a ``node::port`` exchange id."""
    return str(exchange_id or "").split("::", 1)[0]


def _present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _expand_declared_process_defaults(
    rules: list[dict[str, Any]], exchanges: list[dict[str, Any]], consumer_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Use the existing compiler for declared process defaults and exchange overrides.

    Old identity-only rules without a contribution target retain their ambiguity checks.
    A persisted process default names its target explicitly; emission means an elementary
    output, and a direct default must never absorb a purchased background path.
    """
    from .method_compile import compile_method_rules
    from .method_rule_adapter import resolve_rule

    defaults = [r for r in rules if isinstance(r, dict) and not _present(r.get("exchange_id"))
                and not _present(r.get("flow_uuid")) and "contribution_target" in r]
    if not defaults:
        return rules, []
    targets = []
    for item in exchanges:
        exchange_id = str(item.get("exchange_id") or "")
        target = "upstream" if exchange_id in consumer_ids else "direct"
        for rule in defaults:
            direction = str(rule.get("direction") or "")
            matches_direction = (not direction or direction == item.get("direction")
                                 or direction == "emission" and item.get("direction") == "output"
                                 and item.get("exchange_type") == "elementary")
            if (node_prefix(exchange_id) == rule.get("process_instance_id") and matches_direction
                    and target == rule.get("contribution_target")):
                targets.append({"exchange_id": exchange_id, "process_instance_id": node_prefix(exchange_id),
                                "contribution_target": target})
                break
    shapes = [resolve_rule(rule)[0] for rule in rules if isinstance(rule, dict) and _present(rule.get("exchange_id"))]
    # Existing exact input rules predate the upstream field. Their declared exchange remains
    # authoritative when inheriting from an upstream process default.
    target_by_id = {t["exchange_id"]: t["contribution_target"] for t in targets}
    for shape in shapes:
        if shape["exchange_id"] in target_by_id:
            shape["contribution_target"] = target_by_id[shape["exchange_id"]]
    dimensions = sorted({key for r in rules if isinstance(r, dict) for key in (r.get("categories") or {})} | {"lc_scope"})
    compiled = compile_method_rules(dimensions=[{"id": d} for d in dimensions], exchange_targets=targets,
                                    exchange_rules=shapes, process_defaults=[resolve_rule(r)[0] for r in defaults])
    if compiled["problems"]:
        return [], compiled["problems"]
    expanded_ids = {t["exchange_id"] for t in targets}
    effective = [r for r in rules if r not in defaults and r.get("exchange_id") not in expanded_ids]
    # A missing target stays a structured identity problem rather than disappearing.
    effective.extend(r for r in defaults if not any(
        t["process_instance_id"] == r["process_instance_id"]
        and t["contribution_target"] == r["contribution_target"] for t in targets))
    for target in compiled["resolved_targets"]:
        categories = {key: value["category"] for key, value in target["categories"].items()
                      if value["category"] is not None}
        effective.append({"process_instance_id": target["process_instance_id"], "exchange_id": target["exchange_id"],
                          "boundary": target["boundary"], "boundary_status": {"include": "selected", "exclude": "excluded", "pending": "pending"}[target["boundary"]],
                          "categories": categories, "scope": categories.get("lc_scope")})
    return effective, []


def resolve_method_identities(
    *,
    rules: list[dict[str, Any]],
    scaled_exchanges: list[dict[str, Any]],
    weighted_exchange_ids: set[str] | None = None,
    consumer_path_exchanges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bind each rule to exactly one scaled exchange, or report why it cannot.

    ``weighted_exchange_ids`` names the exchange ids for which the engine
    returned a per-exchange weighted contribution (foreground elementary flows).
    A selected rule whose path is outside that set is reported as a coverage gap
    instead of being silently grouped, because no weighted value exists to move.
    When it is ``None`` the coverage check is skipped (identity-only resolution).

    ``consumer_path_exchanges`` is an optional set of technosphere input exchanges
    that a user-pinned closed-leaf background was attributed onto by the engine's
    path-weighted receipt. The engine-expanded background process is not part of
    One's inventory boundary, so a Scope 2/3 rule binds to the selectable consumer
    input instead; the engine already publishes the per-path weighted value, so the
    rule governs every background term whose ``consumer_exchange_id`` matches.

    Returns ``bindings`` (rule -> exchange), ``problems`` (per rule, with
    candidates when the target is ambiguous), ``uncovered_exchange_ids`` (a
    consumption path no selected rule claims) and ``coverage_gaps`` (a selected
    rule bound to a path that has no weighted contribution). Nothing is zeroed:
    an uncovered or gap path is reported, never counted as a result.
    """
    exchanges = [dict(item) for item in scaled_exchanges if isinstance(item, dict)]
    for item in consumer_path_exchanges or []:
        if isinstance(item, dict) and str(item.get("exchange_id") or ""):
            exchanges.append(dict(item))
    exchange_ids = {str(item.get("exchange_id") or "") for item in exchanges}
    if len(exchange_ids) != len(exchanges):
        raise ValueError("scaled exchanges must carry unique exchange_id values")

    bindings: list[dict[str, Any]] = []
    rules, inherited_problems = _expand_declared_process_defaults(
        rules, exchanges, {str(item.get("exchange_id")) for item in consumer_path_exchanges or []})
    problems: list[dict[str, Any]] = list(inherited_problems)
    coverage_gaps: list[dict[str, Any]] = []
    claimed: set[str] = set()

    for index, raw_rule in enumerate(rules):
        rule = dict(raw_rule) if isinstance(raw_rule, dict) else {}
        process_instance_id = rule.get("process_instance_id")
        rule_exchange_id = rule.get("exchange_id")
        flow_uuid = rule.get("flow_uuid")
        direction = rule.get("direction")

        candidates: list[dict[str, Any]] = []
        matched_by = "exchange_id" if _present(rule_exchange_id) else "process_flow_direction"
        for item in exchanges:
            if _present(rule_exchange_id):
                if str(item.get("exchange_id") or "") == str(rule_exchange_id):
                    candidates.append(item)
            else:
                same_node = node_prefix(str(item.get("exchange_id") or "")) == str(process_instance_id or "")
                same_flow = (not _present(flow_uuid)) or str(item.get("flow_uuid") or "") == str(flow_uuid)
                same_direction = (not _present(direction)) or str(item.get("direction") or "") == str(direction)
                if same_node and same_flow and same_direction:
                    candidates.append(item)

        if not candidates:
            problems.append({
                "rule_index": index,
                "code": "METHOD_RULE_TARGET_NOT_FOUND",
                "message": "the rule does not match any consumption path in the solved graph",
                "process_instance_id": process_instance_id,
                "exchange_id": rule_exchange_id,
                "matched_by": matched_by,
            })
            continue
        if len(candidates) > 1:
            problems.append({
                "rule_index": index,
                "code": "METHOD_RULE_TARGET_AMBIGUOUS",
                "message": "the rule matches more than one consumption path; bind it to one exact exchange",
                "process_instance_id": process_instance_id,
                "exchange_id": rule_exchange_id,
                "matched_by": matched_by,
                "candidates": sorted(str(item.get("exchange_id") or "") for item in candidates),
            })
            continue

        target = candidates[0]
        target_exchange_id = str(target.get("exchange_id") or "")
        # A rule that cites both a node and an exchange must not point them apart.
        if _present(rule_exchange_id) and node_prefix(target_exchange_id) != str(process_instance_id or ""):
            problems.append({
                "rule_index": index,
                "code": "METHOD_RULE_IDENTITY_INCONSISTENT",
                "message": "the rule's process id does not match the node encoded in its exchange id",
                "process_instance_id": process_instance_id,
                "exchange_id": target_exchange_id,
                "matched_by": matched_by,
            })
            continue

        binding = {
            "rule_index": index,
            "exchange_id": target_exchange_id,
            "process_instance_id": process_instance_id,
            "process_id": target.get("process_id"),
            "direction": target.get("direction"),
            "exchange_type": target.get("exchange_type"),
            "matched_by": matched_by,
            "boundary_status": rule.get("boundary_status"),
            # The resolved accounting boundary and the per-dimension categories the rule assigns.
            # ``boundary``/``categories`` drive the generic grouping kernel; ``scope`` stays for
            # the legacy LC-Scope path. A v2 rule with no explicit ``boundary`` inherits the
            # legacy ``boundary_status`` meaning (selected counts, excluded drops).
            "boundary": rule.get("boundary"),
            "categories": dict(rule.get("categories") or {}),
            "scope": rule.get("scope"),
            "location_role": rule.get("location_role"),
            "cbam_relevant": bool(rule.get("cbam_relevant")),
        }
        claimed.add(target_exchange_id)
        if rule.get("boundary_status") == "selected" and weighted_exchange_ids is not None:
            if target_exchange_id not in weighted_exchange_ids:
                coverage_gaps.append({
                    "rule_index": index,
                    "code": "METHOD_RULE_NO_WEIGHTED_CONTRIBUTION",
                    "message": "the selected path has no per-exchange weighted contribution; its value cannot be grouped yet",
                    "exchange_id": target_exchange_id,
                })
        bindings.append(binding)

    uncovered = sorted(exchange_ids.difference(claimed))
    return {
        "bindings": bindings,
        "problems": problems,
        "coverage_gaps": coverage_gaps,
        "uncovered_exchange_ids": uncovered,
    }
