"""Compile a user method variant into a CBAM reviewed emission selection.

A CBAM method the user copies and narrows may only take emissions *out* of the counted set.
The reviewed elementary-flow decisions the derivation reads stay verbatim except where this
compiler acts: an exchange the variant explicitly excludes flips ``include`` -> ``exclude``
and carries a clause that names the exact source version and content hash it was copied from,
so the frozen answer and the report can trace the exclusion back to that immutable version.

It is deliberately one-directional. A variant is a narrowing of a reviewed boundary, not a
licence to widen the regulated universe or to invent a clause: naming an emission the reviewed
base never declares, or trying to *include* one the base already excluded, produces a problem
that fails the whole calculation closed rather than a silent guess. The narrowed decisions are
consumed by the existing formal derivation, so ``build_cbam_trial_v2`` validates against a
regenerated boundary ledger with its counted-set equality guard left exactly as written.
"""

from __future__ import annotations

from typing import Any

from .method_rule_adapter import resolve_rule

_SOURCE_REF_KEYS = ("method_id", "version", "content_sha256")


def _problem(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def variant_narrows(user_rules: list[dict[str, Any]] | None) -> bool:
    """Whether a variant would actually take any emission out of the counted set.

    Used to fail closed rather than silently ignore: a reviewed package that does not classify
    emissions per exchange (a pre-limited or template whole-set basis) cannot express a user
    exclusion, so a variant that excludes nothing may still run as the reviewed package, but one
    that excludes an emission must refuse instead of answering without the operator's boundary.
    Only decided ``exclude`` boundaries count; a ``pending``/``inherit`` defers and narrows nothing.
    """
    for rule in user_rules or []:
        if not isinstance(rule, dict):
            continue
        shape, _ = resolve_rule(rule, enforce_cbam_relevance=True)
        if shape["boundary"] == "exclude":
            return True
    return False


def _source_clause(source: dict[str, Any]) -> str:
    """A non-empty justification naming the exact immutable version that excluded this flow.

    CBAM law supplies the clause for a *reviewed* inclusion; a user variant carries no
    compliance claim of its own, so its exclusion cites its own identity instead - the method
    id, the version, and that version's content hash - rather than restating a regulation the
    variant has not been reviewed against.
    """
    return (
        "user-variant-exclusion@"
        f"{source['method_id']}@{source['version']}#{source['content_sha256']}"
    )


def _decisions_by_exchange(
    base_decisions: list[dict[str, Any]], problems: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    by_exchange: dict[str, dict[str, Any]] = {}
    for item in base_decisions:
        if not isinstance(item, dict):
            problems.append(
                _problem(
                    "CBAM_USER_BASE_DECISION_INVALID",
                    "a reviewed elementary-flow decision is not an object",
                )
            )
            continue
        exchange_id = str(item.get("exchange_id") or "")
        if not exchange_id:
            problems.append(
                _problem(
                    "CBAM_USER_BASE_DECISION_INVALID",
                    "a reviewed elementary-flow decision names no exchange",
                )
            )
            continue
        if exchange_id in by_exchange:
            problems.append(
                _problem(
                    "CBAM_USER_BASE_DECISION_DUPLICATED",
                    "the reviewed base declares one emission exchange twice",
                    exchange_id=exchange_id,
                )
            )
            continue
        by_exchange[exchange_id] = item
    return by_exchange


def _resolved_targets(
    rules: list[dict[str, Any]],
    by_exchange: dict[str, dict[str, Any]],
    problems: list[dict[str, Any]],
) -> dict[str, str]:
    """Resolve every decided user rule to ``{exchange_id: boundary}``, exchange over process.

    Only include / exclude act; ``pending`` and ``inherit`` defer to the reviewed base. A process
    default that carries no ``exchange_id`` fans out across that process instance's reviewed
    emissions by the ``{node}::`` prefix, and an exchange-level rule then overrides any process
    default that reached the same port - so an emission is never counted under one switch and cut
    under the other. Exchange-level rules are checked directly against the base; a process default
    can only ever match a base exchange, so it can never invent or widen the regulated universe.
    """
    process_defaults: dict[str, str] = {}
    exchange_overrides: dict[str, str] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        shape, rule_problems = resolve_rule(rule, enforce_cbam_relevance=True)
        problems.extend(rule_problems)
        boundary = shape["boundary"]
        if boundary not in ("include", "exclude"):
            continue
        exchange_id = shape.get("exchange_id")
        if exchange_id:
            key = str(exchange_id)
            current = exchange_overrides.get(key)
            if current is not None and current != boundary:
                problems.append(
                    _problem(
                        "CBAM_USER_EXCHANGE_CLASSIFIED_TWICE",
                        "the variant decides one emission exchange twice at exchange level",
                        exchange_id=key,
                        first=current,
                        second=boundary,
                    )
                )
                continue
            exchange_overrides[key] = boundary
        else:
            process_instance_id = shape.get("process_instance_id")
            if process_instance_id:
                key = str(process_instance_id)
                current = process_defaults.get(key)
                if current is not None and current != boundary:
                    problems.append(
                        _problem(
                            "CBAM_USER_PROCESS_CLASSIFIED_TWICE",
                            "the variant gives one process instance two different default boundaries",
                            process_instance_id=key,
                            first=current,
                            second=boundary,
                        )
                    )
                    continue
                process_defaults[key] = boundary

    resolved: dict[str, str] = {}
    for process_instance_id, boundary in process_defaults.items():
        prefix = f"{process_instance_id}::"
        for exchange_id in by_exchange:
            if exchange_id.startswith(prefix):
                resolved[exchange_id] = boundary
    resolved.update(exchange_overrides)
    return resolved


def narrow_elementary_flow_decisions(
    base_decisions: list[dict[str, Any]],
    *,
    user_rules: list[dict[str, Any]] | None,
    source: dict[str, Any],
) -> dict[str, Any]:
    """Narrow the reviewed CBAM emission selection by a user variant's effective exclusions.

    Returns ``{valid, decisions, excluded_exchange_ids, problems}``. ``decisions`` is the
    reviewed list with each user-excluded base-included exchange flipped to ``exclude`` (a
    clause naming ``source``) and everything else carried through verbatim; the derivation
    then cuts those ports exactly as it would for any reviewed exclusion. ``source`` must name
    ``method_id``, ``version`` and ``content_sha256`` of the immutable version being narrowed.
    """
    problems: list[dict[str, Any]] = []

    if not isinstance(source, dict) or not all(
        str(source.get(key) or "").strip() for key in _SOURCE_REF_KEYS
    ):
        problems.append(
            _problem(
                "CBAM_USER_SOURCE_REF_INCOMPLETE",
                "a CBAM method variant must cite the exact source version and content hash it"
                " was copied from before its exclusions can be traced",
                required=list(_SOURCE_REF_KEYS),
                source=source,
            )
        )

    by_exchange = _decisions_by_exchange(list(base_decisions or []), problems)
    resolved = _resolved_targets(list(user_rules or []), by_exchange, problems)

    clause = _source_clause(source) if not problems else ""
    excluded: set[str] = set()
    for exchange_id, boundary in resolved.items():
        base = by_exchange.get(exchange_id)
        if base is None:
            problems.append(
                _problem(
                    "CBAM_USER_TARGET_EXCHANGE_UNKNOWN",
                    "the variant targets an emission the reviewed CBAM boundary never declared,"
                    " so it neither removes a counted emission nor adds one the base excluded",
                    exchange_id=exchange_id,
                )
            )
            continue
        base_excluded = str(base.get("disposition")) == "exclude"
        if boundary == "exclude":
            # Already out of the base counted set: the exclusion is redundant, not a widening.
            if not base_excluded:
                excluded.add(exchange_id)
        elif base_excluded:
            # An include on a base-excluded emission would widen the regulated universe.
            problems.append(
                _problem(
                    "CBAM_USER_SCOPE_WIDENING",
                    "a method variant may only take emissions out of a reviewed CBAM boundary,"
                    " never add one the base already excluded",
                    exchange_id=exchange_id,
                )
            )

    decisions: list[dict[str, Any]] = []
    for exchange_id in sorted(by_exchange):
        item = dict(by_exchange[exchange_id])
        if exchange_id in excluded:
            item["disposition"] = "exclude"
            item["clause"] = clause
        decisions.append(item)

    return {
        "valid": not problems,
        "decisions": decisions,
        "excluded_exchange_ids": sorted(excluded),
        "problems": problems,
    }
