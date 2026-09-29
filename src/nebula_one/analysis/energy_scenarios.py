from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from ..casepacks.contracts import SHA256_PATTERN, StrictContract
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from .energy_carrier import EnergyBasis, EnergyCarrierSolved, EnergySolvedSnapshotRef


class EnergyScenarioError(DomainError):
    pass


def _fail(code: str, message: str, **details: Any) -> None:
    raise EnergyScenarioError(code=code, message=message, status_code=422, details=details)


class EnergyScenarioDescriptor(StrictContract):
    scenario_id: str = Field(min_length=1, max_length=128)
    scenario_name: str = Field(min_length=1, max_length=255)
    base_revision_id: str = Field(min_length=1, max_length=128)
    system_revision_id: str = Field(min_length=1, max_length=128)
    revision_content_sha256: str = Field(pattern=SHA256_PATTERN)
    solved_snapshot_ref: EnergySolvedSnapshotRef
    energy_result_content_sha256: str = Field(pattern=SHA256_PATTERN)


class EnergyScenarioDelta(StrictContract):
    absolute: Decimal
    relative: Decimal | None


class EnergyScenarioMetric(StrictContract):
    metric_key: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=255)
    unit_symbol: Literal["MJ"]
    unit_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    basis: EnergyBasis
    values: dict[str, Decimal] = Field(min_length=2)
    deltas: dict[str, EnergyScenarioDelta] = Field(min_length=2)
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_values_and_hash(self):
        if set(self.values) != set(self.deltas):
            raise ValueError("energy scenario metric values and deltas must share scenario ids")
        basis = self.model_dump(mode="json", exclude={"content_sha256"})
        if canonical_json_sha256(basis) != self.content_sha256:
            raise ValueError("energy scenario metric content_sha256 mismatch")
        return self


class EnergyScenarioIssue(StrictContract):
    code: str = Field(min_length=1, max_length=128)
    severity: Literal["warning"]
    message: str = Field(min_length=1, max_length=1024)
    scenario_ids: tuple[str, ...] = Field(min_length=1)


class EnergyScenarioComparison(StrictContract):
    schema_version: Literal["nebula.energy-scenario-comparison.v1"]
    baseline_scenario_id: str = Field(min_length=1, max_length=128)
    base_revision_id: str = Field(min_length=1, max_length=128)
    scenarios: tuple[EnergyScenarioDescriptor, ...] = Field(min_length=2, max_length=5)
    metrics: tuple[EnergyScenarioMetric, ...] = Field(min_length=1)
    issues: tuple[EnergyScenarioIssue, ...]
    status: Literal["passed", "passed_with_warnings"]
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_scenarios_status_and_hash(self):
        scenario_ids = [item.scenario_id for item in self.scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("energy scenario ids must be unique")
        if self.baseline_scenario_id not in scenario_ids:
            raise ValueError("energy scenario baseline must be included")
        if any(set(metric.values) != set(scenario_ids) for metric in self.metrics):
            raise ValueError("every energy metric must contain every scenario")
        expected_status = "passed_with_warnings" if self.issues else "passed"
        if self.status != expected_status:
            raise ValueError("energy scenario status does not match issues")
        basis = self.model_dump(mode="json", exclude={"content_sha256"})
        if canonical_json_sha256(basis) != self.content_sha256:
            raise ValueError("energy scenario comparison content_sha256 mismatch")
        return self


def energy_series_metric_key(unit_identity_sha256: str, basis: EnergyBasis) -> str:
    basis_hash = canonical_json_sha256(basis.model_dump(mode="json"))
    return f"energy::{unit_identity_sha256}::{basis_hash}"


def build_energy_scenario_comparison(
    *,
    scenario_results: tuple[dict[str, Any], ...],
    baseline_scenario_id: str,
    metric_labels: dict[str, str],
) -> EnergyScenarioComparison:
    if not 2 <= len(scenario_results) <= 5:
        _fail(
            "ENERGY_SCENARIO_COUNT_UNSUPPORTED",
            "energy scenario comparison requires two to five scenarios",
            scenario_count=len(scenario_results),
        )
    scenario_ids = [str(item.get("scenario_id") or "") for item in scenario_results]
    if any(not item for item in scenario_ids) or len(scenario_ids) != len(set(scenario_ids)):
        _fail("ENERGY_SCENARIO_ID_INVALID", "energy scenario ids must be present and unique")
    if baseline_scenario_id not in scenario_ids:
        _fail("ENERGY_SCENARIO_BASELINE_MISSING", "baseline scenario is not included")
    if any(item.get("scenario_status") != "frozen" for item in scenario_results):
        _fail("ENERGY_SCENARIO_NOT_FROZEN", "every energy scenario must be frozen")
    base_revision_ids = {str(item.get("base_revision_id") or "") for item in scenario_results}
    if len(base_revision_ids) != 1 or "" in base_revision_ids:
        _fail("ENERGY_SCENARIO_PARENT_MISMATCH", "energy scenarios must share one base revision")
    revision_ids = [str(item.get("system_revision_id") or "") for item in scenario_results]
    if any(not item for item in revision_ids) or len(revision_ids) != len(set(revision_ids)):
        _fail("ENERGY_SCENARIO_REVISION_INVALID", "energy scenarios require unique revisions")

    parsed_results: dict[str, EnergyCarrierSolved] = {}
    descriptors: list[EnergyScenarioDescriptor] = []
    warnings_by_code: dict[str, set[str]] = {}
    for item in scenario_results:
        scenario_id = str(item["scenario_id"])
        try:
            energy_result = EnergyCarrierSolved.model_validate(item.get("energy_result"))
        except Exception as exc:
            raise EnergyScenarioError(
                code="ENERGY_SCENARIO_RESULT_INVALID",
                message="scenario energy result failed strict validation",
                status_code=422,
                details={"scenario_id": scenario_id},
            ) from exc
        parsed_results[scenario_id] = energy_result
        for issue in energy_result.issues:
            warnings_by_code.setdefault(issue.code, set()).add(scenario_id)
        revision_hash = str(item.get("revision_content_sha256") or "")
        if len(revision_hash) != 64:
            _fail(
                "ENERGY_SCENARIO_REVISION_HASH_MISSING",
                "scenario revision content hash is missing",
                scenario_id=scenario_id,
            )
        descriptors.append(
            EnergyScenarioDescriptor(
                scenario_id=scenario_id,
                scenario_name=str(item.get("scenario_name") or "").strip(),
                base_revision_id=str(item["base_revision_id"]),
                system_revision_id=str(item["system_revision_id"]),
                revision_content_sha256=revision_hash,
                solved_snapshot_ref=energy_result.solved_snapshot_ref,
                energy_result_content_sha256=energy_result.content_sha256,
            )
        )

    series_by_scenario: dict[str, dict[str, Any]] = {}
    for scenario_id, result in parsed_results.items():
        series_map = {
            energy_series_metric_key(series.unit_identity_sha256, series.basis): series
            for series in result.series
        }
        if len(series_map) != len(result.series):
            _fail(
                "ENERGY_SCENARIO_SERIES_DUPLICATE",
                "scenario contains duplicate energy series identities",
                scenario_id=scenario_id,
            )
        series_by_scenario[scenario_id] = series_map
    baseline_keys = set(series_by_scenario[baseline_scenario_id])
    for scenario_id, series_map in series_by_scenario.items():
        if set(series_map) != baseline_keys:
            _fail(
                "ENERGY_SCENARIO_SERIES_NOT_COMPARABLE",
                "energy scenarios do not contain the same exact unit and basis series",
                scenario_id=scenario_id,
                baseline_keys=sorted(baseline_keys),
                scenario_keys=sorted(series_map),
            )
    if set(metric_labels) != baseline_keys or any(not value.strip() for value in metric_labels.values()):
        _fail(
            "ENERGY_SCENARIO_LABELS_INCOMPLETE",
            "metric labels must exactly cover comparable energy series",
        )

    metrics: list[EnergyScenarioMetric] = []
    for metric_key in sorted(baseline_keys):
        baseline_series = series_by_scenario[baseline_scenario_id][metric_key]
        values = {
            scenario_id: series_by_scenario[scenario_id][metric_key].total_amount
            for scenario_id in scenario_ids
        }
        baseline_value = values[baseline_scenario_id]
        deltas = {
            scenario_id: {
                "absolute": str(value - baseline_value),
                "relative": (
                    None
                    if baseline_value == 0
                    else str((value - baseline_value) / baseline_value)
                ),
            }
            for scenario_id, value in values.items()
        }
        metric_basis = {
            "metric_key": metric_key,
            "label": metric_labels[metric_key].strip(),
            "unit_symbol": "MJ",
            "unit_identity_sha256": baseline_series.unit_identity_sha256,
            "basis": baseline_series.basis.model_dump(mode="json"),
            "values": {key: str(value) for key, value in values.items()},
            "deltas": deltas,
        }
        metrics.append(
            EnergyScenarioMetric(
                **metric_basis,
                content_sha256=canonical_json_sha256(metric_basis),
            )
        )

    issues = tuple(
        EnergyScenarioIssue(
            code=code,
            severity="warning",
            message="one or more scenario energy results retain this source warning",
            scenario_ids=tuple(sorted(ids)),
        )
        for code, ids in sorted(warnings_by_code.items())
    )
    ordered_descriptors = tuple(
        next(item for item in descriptors if item.scenario_id == scenario_id)
        for scenario_id in scenario_ids
    )
    result_basis = {
        "schema_version": "nebula.energy-scenario-comparison.v1",
        "baseline_scenario_id": baseline_scenario_id,
        "base_revision_id": next(iter(base_revision_ids)),
        "scenarios": [item.model_dump(mode="json") for item in ordered_descriptors],
        "metrics": [item.model_dump(mode="json") for item in metrics],
        "issues": [item.model_dump(mode="json") for item in issues],
        "status": "passed_with_warnings" if issues else "passed",
    }
    return EnergyScenarioComparison(
        **result_basis,
        content_sha256=canonical_json_sha256(result_basis),
    )
