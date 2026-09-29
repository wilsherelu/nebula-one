"""One shape for "this refusal is missing data", shared by the period chain.

The field values come from the inputs the refusing step actually holds, so a
reader can tell which port, receipt or binding has to change before the step
runs again. Contract: docs/STANDARD_SEED_ENTERPRISE_PERIOD_AND_AUTOLOAD_V1.md §6.1.
"""

from __future__ import annotations

from typing import Any

DEPENDENCY_GAP_SCHEMA_VERSION = "nebula_one.dependency-gap.v1"


def dependency_gap(
    *,
    code: str,
    kind: str,
    step: str,
    what_missing: dict[str, Any],
    affects: dict[str, Any],
    how_to_resolve: list[dict[str, str]],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": DEPENDENCY_GAP_SCHEMA_VERSION,
        "code": code,
        "what_missing": {"kind": kind, **what_missing},
        "affects": {
            "step": step,
            "downstream_steps": list(affects.get("downstream_steps") or []),
            "scopes_affected": list(affects.get("scopes_affected") or []),
            "results_produced": False,
        },
        "how_to_resolve": how_to_resolve,
        "evidence": evidence,
    }
