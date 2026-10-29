"""Derive previewable classification suggestions from versioned, traceable evidence.

This is an authoring aid, never an authority: it reads only structural facts that already exist
(the exact model graph's ports, the rules a method version persists, and the purchased-energy
exchanges a bound method package declares) and turns them into a located suggestion with its basis
and confidence. It invents no emission factor, reads no flow name as a classification, and keeps a
port pending whenever the evidence is insufficient to choose a Scope. Formal classification still
runs through backend validation; nothing here writes a rule.

The frontend renders `rationale` and `basis` codes through its own i18n, so this module emits stable
code strings and never a translation, a business UUID, or a hardcoded classification table.
"""
from __future__ import annotations

from typing import Any

SUGGESTION_STRATEGY_VERSION = "nebula_one.classification-suggestion.v1"

# The GHG location role each Scope is declared against, mirrored from the validation service so a
# suggestion never proposes a Scope/location pair validation would refuse.
_SCOPE_LOCATION = {
    "scope_1": "onsite",
    "scope_2": "purchased_energy",
    "scope_3": "upstream_supply",
}

_CONFIDENCE_ORDER = ("high", "medium", "insufficient", "none")


def _existing_rule(exchange_id: str, rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    for rule in rules:
        if rule.get("exchange_id") == exchange_id:
            return rule
    return None


def _decided(rule: dict[str, Any] | None) -> bool:
    """A rule the reader already made up their mind about: a boundary other than pending, or a Scope.

    Suggestions default to not overriding these; the reader has spoken for this exact exchange.
    """
    if rule is None:
        return False
    return rule.get("boundary_status") in ("selected", "excluded") or rule.get("scope") is not None


def _current(rule: dict[str, Any] | None) -> dict[str, Any] | None:
    if rule is None:
        return None
    return {
        "boundary_status": rule.get("boundary_status") or "pending",
        "location_role": rule.get("location_role") or "other",
        "scope": rule.get("scope"),
    }


def _suggestion(boundary_status: str, scope: str | None) -> dict[str, Any]:
    return {
        "boundary_status": boundary_status,
        "location_role": _SCOPE_LOCATION[scope] if scope else "other",
        "scope": scope,
    }


def suggest_classifications(
    *,
    ports: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    energy_exchange_ids: set[str],
    energy_packages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One suggestion per model port, from structural evidence only.

    ``energy_packages`` records which bound package declared which purchased-energy exchanges, so a
    Scope 2/3 choice cites a versioned source. When no package is bound the energy property of a
    purchased input is unresolved and that port stays pending rather than being guessed.
    """
    energy_declared = bool(energy_packages)
    suggestions: list[dict[str, Any]] = []
    for port in ports:
        exchange_id = str(port.get("exchange_id") or "")
        if not exchange_id:
            continue
        direction = str(port.get("direction") or "")
        internal = bool(port.get("internal"))
        rule = _existing_rule(exchange_id, rules)
        row: dict[str, Any] = {
            "exchange_id": exchange_id,
            "process_id": port.get("process_id"),
            "process_name": port.get("process_name"),
            "flow_name": port.get("name"),
            "unit": port.get("unit") or "",
            "direction": direction,
            "current": _current(rule),
        }

        if _decided(rule):
            row.update(status="already_classified", rationale="manual_rule_present",
                       confidence="none", basis=["rule.manual"], suggested=None)
            suggestions.append(row)
            continue

        if direction in ("emission", "resource"):
            # An elementary exchange at the process boundary is a direct onsite exchange with the
            # environment; the direction is structural evidence, not a name match.
            row.update(status="suggested", rationale="onsite_direct_emission", confidence="high",
                       basis=["flow_type.elementary", f"direction.{direction}",
                              "contribution_domain.direct"],
                       suggested=_suggestion("selected", "scope_1"))
        elif direction == "input" and internal:
            # Fed by another modelled process: a foreground transfer whose emissions are already
            # counted at the provider. Giving it a Scope here would double-count the same path.
            row.update(status="not_applicable", rationale="foreground_internal_transfer",
                       confidence="high",
                       basis=["direction.input", "contribution_domain.direct",
                              "consumer_path.internal"],
                       suggested=None)
        elif direction == "input":
            # A purchased input from outside the model. Scope 2 vs Scope 3 turns on the energy
            # property, which only a bound package's declared energy exchanges can evidence.
            if exchange_id in energy_exchange_ids:
                row.update(status="suggested", rationale="purchased_energy_path", confidence="high",
                           basis=["direction.input", "contribution_domain.upstream",
                                  "consumer_path.purchased", "energy_property.declared_energy"],
                           suggested=_suggestion("selected", "scope_2"))
            elif energy_declared:
                # A package is bound and does not declare this purchase as energy: absence from an
                # authoritative declared set is medium evidence of a non-energy supply path.
                row.update(status="suggested", rationale="non_energy_supply_path", confidence="medium",
                           basis=["direction.input", "contribution_domain.upstream",
                                  "consumer_path.purchased", "energy_property.not_declared_energy"],
                           suggested=_suggestion("selected", "scope_3"))
            else:
                row.update(status="pending_evidence", rationale="purchased_input_energy_unresolved",
                           confidence="insufficient",
                           basis=["direction.input", "contribution_domain.upstream",
                                  "consumer_path.purchased", "energy_property.unresolved"],
                           suggested=_suggestion("pending", None))
        else:
            # A technosphere output is a product or co-product, not an emission to characterize.
            row.update(status="not_applicable", rationale="not_an_emission", confidence="high",
                       basis=[f"direction.{direction or 'unknown'}", "flow_type.technosphere"],
                       suggested=None)
        suggestions.append(row)
    return suggestions


def collect_energy_evidence(
    manifests: list[tuple[dict[str, Any], str, str, str]],
) -> tuple[set[str], list[dict[str, Any]]]:
    """Union the purchased-energy exchanges a set of bound method packages declares.

    ``manifests`` is a list of ``(manifest, package_id, version, content_sha256)``. Each package's
    ``classification_rules`` may name ``energy_purchase_exchange_ids`` and/or
    ``scope2_purchase_exchange_ids``; both are recorded so a Scope 2 suggestion cites the exact
    versioned source that declared the path.
    """
    energy_ids: set[str] = set()
    packages: list[dict[str, Any]] = []
    for manifest, package_id, version, content_sha256 in manifests:
        rules = (manifest or {}).get("classification_rules") or {}
        declared = sorted(
            {str(item) for item in (rules.get("energy_purchase_exchange_ids") or [])}
            | {str(item) for item in (rules.get("scope2_purchase_exchange_ids") or [])}
        )
        if not declared:
            continue
        energy_ids.update(declared)
        packages.append({
            "package_id": package_id,
            "version": version,
            "content_sha256": content_sha256,
            "declared_energy_exchange_ids": declared,
        })
    return energy_ids, packages
