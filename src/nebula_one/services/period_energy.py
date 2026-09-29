from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select

from ..analysis.energy_carrier import EnergyCarrierSolved
from ..analysis.energy_scenario_visual import render_energy_scenario_comparison_svg
from ..analysis.energy_scenarios import (
    EnergyScenarioComparison,
    energy_series_metric_key,
)
from ..analysis.period_energy import build_period_energy_comparison
from ..database import Database
from ..errors import DomainError
from ..models import Application, SystemRevision
from ..runtime_models import EnergyCarrierResult, Scenario, ScenarioComparisonRun
from ..runtime_schemas import PeriodEnergyComparisonCreate


class PeriodEnergyComparisonService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _exchange_labels(graph: dict[str, Any]) -> dict[str, str]:
        labels: dict[str, str] = {}
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "").strip()
            for collection in ("inputs", "outputs"):
                for port in node.get(collection) or []:
                    if not isinstance(port, dict):
                        continue
                    port_id = str(port.get("id") or "").strip()
                    exchange_id = f"{node_id}::{port_id}"
                    label = str(
                        port.get("name") or port.get("flowName") or port.get("flowUuid") or ""
                    ).strip()
                    if exchange_id and label:
                        labels[exchange_id] = label
        return labels

    @staticmethod
    def _series_labels(
        result: EnergyCarrierSolved,
        exchange_labels: dict[str, str],
    ) -> dict[str, str]:
        labels: dict[str, str] = {}
        for series in result.series:
            names: set[str] = set()
            for entry in series.entries:
                source = entry.source
                exchange_id = (
                    source.exchange_id
                    if source.kind == "direct_solved_exchange"
                    else source.source_exchange_id
                )
                label = exchange_labels.get(exchange_id)
                if not label:
                    raise DomainError(
                        code="PERIOD_ENERGY_LABEL_UNRESOLVED",
                        message="energy source exchange has no model label",
                        status_code=422,
                        details={"exchange_id": exchange_id},
                    )
                names.add(label)
            metric_key = energy_series_metric_key(
                series.unit_identity_sha256,
                series.basis,
            )
            labels[metric_key] = " + ".join(sorted(names))
        return labels

    def analyze(
        self,
        run_id: str,
        payload: PeriodEnergyComparisonCreate,
    ) -> dict[str, Any]:
        with self.database.session() as db:
            run = db.get(ScenarioComparisonRun, run_id)
            if run is None:
                raise DomainError(
                    code="SCENARIO_COMPARISON_RUN_NOT_FOUND",
                    message=f"scenario comparison run not found: {run_id}",
                    status_code=404,
                )
            if run.status != "succeeded" or not run.content_sha256:
                raise DomainError(
                    code="PERIOD_ENERGY_SOURCE_RUN_NOT_SUCCEEDED",
                    message="period energy comparison requires a succeeded immutable run",
                    status_code=409,
                )
            application = db.get(Application, run.application_id)
            if application is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {run.application_id}",
                    status_code=404,
                )
            context = application.context or {}
            reporting_period = {
                "id": context.get("reporting_period_id"),
                "version": context.get("reporting_period_version"),
                "content_sha256": context.get("reporting_period_sha256"),
            }

            result_rows = list(run.scenario_results or [])
            scenario_ids = [str(item.get("scenario_id") or "") for item in result_rows]
            scenarios = {
                item.id: item
                for item in db.scalars(select(Scenario).where(Scenario.id.in_(scenario_ids)))
            }
            if set(scenarios) != set(scenario_ids):
                raise DomainError(
                    code="PERIOD_ENERGY_SCENARIO_SET_MISMATCH",
                    message="source run scenarios cannot be resolved exactly",
                    status_code=409,
                )
            if any(
                scenario.application_id != run.application_id
                for scenario in scenarios.values()
            ):
                raise DomainError(
                    code="PERIOD_ENERGY_APPLICATION_MISMATCH",
                    message="source run scenarios belong to a different application",
                    status_code=409,
                )
            revision_ids = [str(item.get("system_revision_id") or "") for item in result_rows]
            revisions = {
                item.id: item
                for item in db.scalars(
                    select(SystemRevision).where(SystemRevision.id.in_(revision_ids))
                )
            }
            if set(revisions) != set(revision_ids):
                raise DomainError(
                    code="PERIOD_ENERGY_REVISION_SET_MISMATCH",
                    message="source run revisions cannot be resolved exactly",
                    status_code=409,
                )

            snapshot_ids = [str(item.get("solved_snapshot_id") or "") for item in result_rows]
            energy_query = select(EnergyCarrierResult).where(
                EnergyCarrierResult.application_id == run.application_id,
                EnergyCarrierResult.solved_snapshot_id.in_(snapshot_ids),
            )
            if payload.energy_result_ids:
                energy_query = energy_query.where(
                    EnergyCarrierResult.id.in_(payload.energy_result_ids)
                )
            energy_by_snapshot: dict[str, list[EnergyCarrierResult]] = defaultdict(list)
            for record in db.scalars(energy_query):
                energy_by_snapshot[record.solved_snapshot_id].append(record)
            if payload.energy_result_ids and sum(
                len(items) for items in energy_by_snapshot.values()
            ) != len(payload.energy_result_ids):
                raise DomainError(
                    code="PERIOD_ENERGY_RESULT_SET_MISMATCH",
                    message="explicit energy result ids do not match the source run",
                    status_code=409,
                )

            scenario_inputs: list[dict[str, Any]] = []
            parsed_energy: dict[str, EnergyCarrierSolved] = {}
            for row in result_rows:
                scenario_id = str(row["scenario_id"])
                snapshot_id = str(row["solved_snapshot_id"])
                matches = energy_by_snapshot.get(snapshot_id, [])
                if len(matches) != 1:
                    raise DomainError(
                        code="PERIOD_ENERGY_RESULT_AMBIGUOUS",
                        message="each scenario snapshot must have exactly one selected energy result",
                        status_code=422,
                        details={"scenario_id": scenario_id, "count": len(matches)},
                    )
                energy = matches[0]
                parsed = EnergyCarrierSolved.model_validate(energy.result_json)
                if str(parsed.solved_snapshot_ref.id) != snapshot_id:
                    raise DomainError(
                        code="PERIOD_ENERGY_SNAPSHOT_MISMATCH",
                        message="energy result belongs to a different solved snapshot",
                        status_code=409,
                    )
                scenario = scenarios[scenario_id]
                revision = revisions[scenario.system_revision_id]
                if (
                    scenario.status != "frozen"
                    or scenario.system_revision_id != row.get("system_revision_id")
                    or revision.content_sha256 != row.get("provider_receipt", {}).get(
                        "system_revision_hash"
                    )
                ):
                    raise DomainError(
                        code="PERIOD_ENERGY_SCENARIO_IDENTITY_MISMATCH",
                        message="scenario or revision identity differs from the source run",
                        status_code=409,
                        details={"scenario_id": scenario_id},
                    )
                parsed_energy[scenario_id] = parsed
                scenario_inputs.append(
                    {
                        "scenario_id": scenario.id,
                        "scenario_name": scenario.name,
                        "scenario_status": scenario.status,
                        "base_revision_id": scenario.base_revision_id,
                        "system_revision_id": scenario.system_revision_id,
                        "revision_content_sha256": revision.content_sha256,
                        "energy_result": parsed.model_dump(mode="json"),
                    }
                )

            baseline_scenario = scenarios.get(run.baseline_scenario_id)
            if baseline_scenario is None:
                raise DomainError(
                    code="PERIOD_ENERGY_BASELINE_MISSING",
                    message="source run baseline scenario is missing",
                    status_code=409,
                )
            baseline_revision = revisions[baseline_scenario.system_revision_id]
            labels = self._series_labels(
                parsed_energy[run.baseline_scenario_id],
                self._exchange_labels(baseline_revision.graph_snapshot),
            )
            return build_period_energy_comparison(
                reporting_period=reporting_period,
                source_run={"id": run.id, "content_sha256": run.content_sha256},
                scenario_results=tuple(scenario_inputs),
                baseline_scenario_id=run.baseline_scenario_id,
                metric_labels=labels,
            )

    def chart_svg(
        self,
        run_id: str,
        payload: PeriodEnergyComparisonCreate,
    ) -> str:
        result = self.analyze(run_id, payload)
        comparison = EnergyScenarioComparison.model_validate(result["comparison"])
        period = result["reporting_period"]
        return render_energy_scenario_comparison_svg(
            comparison,
            title=f"Energy scenarios · {period['id']}@{period['version']}",
        )
