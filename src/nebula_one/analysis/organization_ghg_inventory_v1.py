from __future__ import annotations

from math import fsum
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256


SCHEMA_VERSION = "nebula_one.organization-ghg-inventory.v1"
CAPABILITY_KEY = "organization.ghg-inventory.v1"
PACKAGE_KIND = "organization_ghg_inventory"
SCOPES = ("scope_1", "scope_2", "scope_3")


def _user_method_grouping(pcf: dict[str, Any]) -> dict[str, Any] | None:
    """Return a source PCF's user-rule grouping when it ran and reconciled, else None.

    The organization inventory must count what the user's method actually selected, not the raw
    engine total: a method that excludes a non-zero path lowers the org counted quantity, while one
    that only relabels a path moves value between Scope buckets without changing the total. When a
    source carries no executed, reconciled user grouping we fall back to the engine total so the
    pre-existing (no-method) behavior is untouched. Unattributed and missing paths are never folded
    into a Scope bucket here.
    """
    grouping = (
        (pcf.get("contribution_analysis") or {}).get("user_method_grouping") or {}
    ).get("grouping")
    if not isinstance(grouping, dict):
        return None
    scopes = grouping.get("scopes")
    if not isinstance(scopes, dict) or not grouping.get("reconciled"):
        return None
    return grouping


def _grouped_scope_values(grouping: dict[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    for scope in SCOPES:
        bucket = grouping.get("scopes", {}).get(scope)
        if isinstance(bucket, dict):
            value = bucket.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values[scope] = float(value)
    return values


def _grouping_coverage(grouping: dict[str, Any]) -> dict[str, Any]:
    """Separate known-but-unattributed paths from engine-missing ones; never fold into a Scope.

    ``unattributed`` is a contribution the engine returned that the user's rules did not select;
    ``engine_gap`` is a background path the engine could not attribute at all; ``coverage_gaps`` is
    a selected identity the engine gave no weighted value for. They are reported apart so a gap is
    visibly a gap and never becomes a silent zero or a duplicate.
    """
    unattributed = grouping.get("unattributed") or {}
    engine_gap = grouping.get("engine_gap") or {}
    return {
        "counted_scopes": _grouped_scope_values(grouping),
        "excluded": grouping.get("excluded") or {},
        "unattributed": {
            "value": unattributed.get("value"),
            "exchange_ids": unattributed.get("exchange_ids") or [],
        },
        "engine_gap": {
            "value": engine_gap.get("value"),
            "exchange_ids": engine_gap.get("exchange_ids") or [],
        },
        "coverage_gaps": grouping.get("coverage_gaps") or [],
        "contribution_total": grouping.get("contribution_total"),
        "attribution_coverage": grouping.get("attribution_coverage"),
    }


def build_organization_ghg_inventory_v1(
    *,
    application_id: str,
    sources: list[dict[str, Any]],
    method_package_ref: str,
    method_package_sha256: str,
    method_package_kind: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if method_package_kind != PACKAGE_KIND:
        raise DomainError(
            code="ORGANIZATION_GHG_METHOD_KIND_INVALID",
            message="organization inventory requires an organization_ghg_inventory method package",
            status_code=422,
        )
    output_schema = manifest.get("output_schema")
    if not isinstance(output_schema, dict) or output_schema.get(
        "schema_version"
    ) != SCHEMA_VERSION:
        raise DomainError(
            code="ORGANIZATION_GHG_METHOD_SCHEMA_INVALID",
            message="organization inventory method package declares another output schema",
            status_code=422,
        )
    rules = manifest.get("classification_rules")
    mappings = rules.get("role_mappings") if isinstance(rules, dict) else None
    required_scopes = rules.get("required_scopes") if isinstance(rules, dict) else None
    if not isinstance(mappings, list) or not mappings:
        raise DomainError(
            code="ORGANIZATION_GHG_ROLE_RULES_REQUIRED",
            message="method package must define role_mappings",
            status_code=422,
        )
    if (
        not isinstance(required_scopes, list)
        or not required_scopes
        or len(required_scopes) != len(set(required_scopes))
        or not set(required_scopes) <= set(SCOPES)
    ):
        raise DomainError(
            code="ORGANIZATION_GHG_SCOPE_RULES_INVALID",
            message="method package must declare a non-empty unique subset of Scope 1, Scope 2 and Scope 3",
            status_code=422,
        )
    if not sources:
        raise DomainError(
            code="ORGANIZATION_GHG_BINDINGS_REQUIRED",
            message="organization inventory requires system bindings",
            status_code=422,
        )
    snapshot_ids = [source["binding"]["solved_snapshot_id"] for source in sources]
    if len(snapshot_ids) != len(set(snapshot_ids)):
        raise DomainError(
            code="ORGANIZATION_GHG_SNAPSHOT_DUPLICATE",
            message="each organization inventory binding must use a distinct solved snapshot",
            status_code=422,
        )

    reporting_period_ids = {source["binding"]["reporting_period_id"] for source in sources}
    boundary_ids = {
        source["binding"]["organizational_boundary_id"] for source in sources
    }
    methods = {source["pcf"]["method_package"]["lcia_method"] for source in sources}
    units = {source["pcf"]["total_footprint"]["unit"] for source in sources}
    releases = {source["pcf"]["data_quality"]["database_release"] for source in sources}
    if any(len(values) != 1 for values in (reporting_period_ids, boundary_ids, methods, units, releases)):
        raise DomainError(
            code="ORGANIZATION_GHG_SOURCES_NOT_COMPARABLE",
            message="bindings must use one period, boundary, LCIA method, unit and database release",
            status_code=422,
        )

    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {
        scope: {} for scope in SCOPES
    }
    source_coverage: list[dict[str, Any]] = []
    for source in sources:
        binding = source["binding"]
        pcf = source["pcf"]
        source_snapshot = pcf.get("source_snapshot")
        if (
            pcf.get("capability_key") != "pcf.product.v1"
            or not isinstance(source_snapshot, dict)
            or source_snapshot.get("id") != binding["solved_snapshot_id"]
            or source_snapshot.get("system_revision_id")
            != binding["system_revision_id"]
        ):
            raise DomainError(
                code="ORGANIZATION_GHG_PCF_SOURCE_MISMATCH",
                message="PCF result does not bind the selected revision and snapshot",
                status_code=422,
            )
        classification = _classify_role(binding["role"], mappings)
        role_scope = classification["scope"]
        category = classification["category"]
        if role_scope not in grouped:
            raise DomainError(
                code="ORGANIZATION_GHG_SCOPE_INVALID",
                message=f"method package maps a role to an unsupported scope: {role_scope}",
                status_code=422,
            )
        footprint = pcf["total_footprint"]
        unit = footprint["unit"]
        entry_base = {
            "binding_id": binding["binding_id"],
            "role": binding["role"],
            "system_model_id": binding["system_model_id"],
            "system_revision_id": binding["system_revision_id"],
            "solved_snapshot_id": binding["solved_snapshot_id"],
            "binding_content_sha256": binding["content_sha256"],
            "pcf_content_sha256": pcf["content_sha256"],
            "unit": unit,
        }
        grouping = _user_method_grouping(pcf)
        if grouping is not None:
            coverage = _grouping_coverage(grouping)
            counted = coverage["counted_scopes"]
            if not counted:
                raise DomainError(
                    code="ORGANIZATION_GHG_USER_METHOD_EMPTY",
                    message="the user method grouped no contribution into any Scope",
                    status_code=422,
                    details={"binding_id": binding["binding_id"]},
                )
            # The user's method decides the Scope, so a single source can feed more than one.
            for scope, value in sorted(counted.items()):
                grouped[scope].setdefault(category, []).append(
                    {**entry_base, "value": float(value), "counted_from": "user_method_grouping"}
                )
            source_coverage.append(
                {
                    "binding_id": binding["binding_id"],
                    "method_identity": (
                        (pcf.get("contribution_analysis") or {})
                        .get("user_method_grouping", {})
                        .get("method")
                    ),
                    **coverage,
                }
            )
            continue

        value = footprint.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise DomainError(
                code="ORGANIZATION_GHG_PCF_VALUE_INVALID",
                message="PCF total must contain a numeric value",
                status_code=422,
            )
        grouped[role_scope].setdefault(category, []).append(
            {**entry_base, "value": float(value), "counted_from": "engine_total_footprint"}
        )

    missing_scopes = [scope for scope in required_scopes if not grouped[scope]]
    if missing_scopes:
        raise DomainError(
            code="ORGANIZATION_GHG_SCOPE_INCOMPLETE",
            message="required organizational inventory scopes are missing",
            status_code=422,
            details={"missing_scopes": missing_scopes},
        )
    unit = next(iter(units))
    scope_results = []
    for scope in SCOPES:
        categories = []
        for category, category_sources in sorted(grouped[scope].items()):
            ordered_sources = sorted(
                category_sources, key=lambda item: item["binding_id"]
            )
            categories.append(
                {
                    "category": category,
                    "total": {
                        "value": fsum(item["value"] for item in ordered_sources),
                        "unit": unit,
                    },
                    "sources": ordered_sources,
                }
            )
        scope_results.append(
            {
                "scope": scope,
                "total": {
                    "value": fsum(
                        category["total"]["value"] for category in categories
                    ),
                    "unit": unit,
                },
                "categories": categories,
            }
        )
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "capability_key": CAPABILITY_KEY,
        "application_id": application_id,
        "reporting_period_id": next(iter(reporting_period_ids)),
        "organizational_boundary_id": next(iter(boundary_ids)),
        "method_package": {
            "reference": method_package_ref,
            "content_sha256": method_package_sha256,
        },
        "comparability": {
            "lcia_method": next(iter(methods)),
            "unit": unit,
            "database_release": next(iter(releases)),
        },
        "scopes": scope_results,
        "attribution": {
            "counted_total": {
                "value": fsum(
                    item["total"]["value"] for item in scope_results
                ),
                "unit": unit,
            },
            "sources": source_coverage,
            "note": (
                "counted_total sums the user-selected Scope buckets; excluded, unattributed and "
                "engine_gap are reported per source in attribution.sources and are never folded "
                "into the counted Scopes, a zero, or a duplicate."
            ),
        },
        "total": {
            "value": fsum(item["total"]["value"] for item in scope_results),
            "unit": unit,
        },
        "audit": {
            "status": "passed",
            "source_binding_count": len(sources),
            "user_method_grouped_sources": len(source_coverage),
            "checks": {
                "bindings_exactly_pinned": True,
                "pcf_results_content_pinned": True,
                "reporting_period_exact": True,
                "organizational_boundary_exact": True,
                "lcia_method_exact": True,
                "unit_exact": True,
                "database_release_exact": True,
                "required_scopes_present": True,
                "unattributed_separate_from_counted": True,
            },
        },
    }
    result["content_sha256"] = canonical_json_sha256(result)
    return result


def _classify_role(role: str, mappings: list[Any]) -> dict[str, str]:
    matches = []
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        pattern = str(mapping.get("role_pattern") or "").strip()
        scope = str(mapping.get("scope") or "").strip()
        category = str(mapping.get("category") or "").strip()
        if pattern and scope and category and _role_matches(role, pattern):
            matches.append({"scope": scope, "category": category})
    if len(matches) != 1:
        raise DomainError(
            code="ORGANIZATION_GHG_ROLE_CLASSIFICATION_INVALID",
            message="each binding role must match exactly one method-package rule",
            status_code=422,
            details={"role": role, "match_count": len(matches)},
        )
    return matches[0]


def _role_matches(role: str, pattern: str) -> bool:
    if pattern.endswith("*"):
        return role.startswith(pattern[:-1])
    return role == pattern
