from __future__ import annotations

import re
from typing import Any

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .energy_scenarios import build_energy_scenario_comparison


def _fail(code: str, message: str, **details: Any) -> None:
    raise DomainError(code=code, message=message, status_code=422, details=details)


def build_period_energy_comparison(
    *,
    reporting_period: dict[str, Any],
    source_run: dict[str, Any],
    scenario_results: tuple[dict[str, Any], ...],
    baseline_scenario_id: str,
    metric_labels: dict[str, str],
) -> dict[str, Any]:
    period_fields = ("id", "version", "content_sha256")
    if any(not str(reporting_period.get(key) or "").strip() for key in period_fields):
        _fail(
            "PERIOD_ENERGY_REPORTING_PERIOD_REQUIRED",
            "energy scenario comparison requires one exact frozen reporting period",
        )
    if re.fullmatch(r"[0-9a-f]{64}", str(reporting_period["content_sha256"])) is None:
        _fail(
            "PERIOD_ENERGY_REPORTING_PERIOD_REQUIRED",
            "reporting period content_sha256 is not an exact SHA-256 identity",
        )
    if not str(source_run.get("id") or "").strip() or re.fullmatch(
        r"[0-9a-f]{64}", str(source_run.get("content_sha256") or "")
    ) is None:
        _fail(
            "PERIOD_ENERGY_SOURCE_RUN_REQUIRED",
            "period energy comparison requires an immutable scenario comparison run",
        )

    comparison = build_energy_scenario_comparison(
        scenario_results=scenario_results,
        baseline_scenario_id=baseline_scenario_id,
        metric_labels=metric_labels,
    )
    content = {
        "schema_version": "nebula_one.period-energy-scenario-comparison.v1",
        "capability_key": "energy.scenario-comparison.v1",
        "reporting_period": reporting_period,
        "source_comparison_run": source_run,
        "comparison": comparison.model_dump(mode="json"),
        "audit": {
            "status": comparison.status,
            "checks": {
                "reporting_period_pinned": True,
                "source_run_immutable": True,
                "scenario_count_supported": True,
                "scenarios_share_base_revision": True,
                "scenario_revisions_unique": True,
                "energy_results_match_solved_snapshots": True,
                "unit_and_basis_series_comparable": True,
                "zero_baseline_relative_delta_nullable": True,
            },
            "counts": {
                "scenario_count": len(comparison.scenarios),
                "metric_count": len(comparison.metrics),
            },
            "issues": [item.model_dump(mode="json") for item in comparison.issues],
            "limitations": [
                "v1 compares frozen scenarios inside one reporting period",
                "unlike unit or energy-basis series are never aggregated",
                "results do not claim a complete energy balance",
            ],
        },
    }
    return {**content, "content_sha256": canonical_json_sha256(content)}
