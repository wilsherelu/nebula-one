from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ..analysis.dependency_gap import dependency_gap
from ..analysis.energy_carrier import EnergyCarrierSolved
from ..analysis.energy_scenarios import energy_series_metric_key
from ..analysis.period_energy_trend import build_period_energy_trend
from ..analysis.period_energy_trend_visual import render_period_energy_trend_svg
from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..models import Application, SystemModel, SystemRevision
from ..runtime_models import EnergyCarrierResult, Period, SolvedSystemSnapshot
from ..runtime_schemas import PeriodEnergyTrendCreate


def _application_periods(session, application_id: str) -> list[Period]:
    return list(
        session.scalars(select(Period).where(Period.application_id == application_id))
    )


def _application_energy_results(session, application_id: str) -> list[EnergyCarrierResult]:
    return list(
        session.scalars(
            select(EnergyCarrierResult).where(
                EnergyCarrierResult.application_id == application_id
            )
        )
    )


class PeriodEnergyTrendService:
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
                    label = str(
                        port.get("name")
                        or port.get("flowName")
                        or port.get("flowUuid")
                        or ""
                    ).strip()
                    if node_id and port_id and label:
                        labels[f"{node_id}::{port_id}"] = label
        return labels

    @staticmethod
    def _metric_labels(
        result: EnergyCarrierSolved,
        graph: dict[str, Any],
    ) -> dict[str, str]:
        exchange_labels = PeriodEnergyTrendService._exchange_labels(graph)
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
            labels[
                energy_series_metric_key(series.unit_identity_sha256, series.basis)
            ] = " + ".join(sorted(names))
        return labels

    def analyze(
        self,
        application_id: str,
        payload: PeriodEnergyTrendCreate,
    ) -> dict[str, Any]:
        with self.database.session() as db:
            application = db.get(Application, application_id)
            if application is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {application_id}",
                    status_code=404,
                )
            period_ids = [item.period_id for item in payload.observations]
            energy_result_ids = [item.energy_result_id for item in payload.observations]
            periods = {
                item.id: item
                for item in db.scalars(select(Period).where(Period.id.in_(period_ids)))
            }
            energies = {
                item.id: item
                for item in db.scalars(
                    select(EnergyCarrierResult).where(
                        EnergyCarrierResult.id.in_(energy_result_ids)
                    )
                )
            }
            if set(periods) != set(period_ids):
                raise DomainError(
                    code="PERIOD_ENERGY_PERIOD_SET_MISMATCH",
                    message="period observations cannot be resolved exactly",
                    status_code=409,
                    details={
                        "dependency_gap": dependency_gap(
                            code="PERIOD_ENERGY_PERIOD_SET_MISMATCH",
                            kind="reporting_period",
                            step="period_energy_trend",
                            what_missing={
                                "requested_ids": sorted(period_ids),
                                "unresolved_ids": sorted(set(period_ids) - set(periods)),
                                "observed_identity": {
                                    "reporting_period_ids_of_this_application": sorted(
                                        item.id for item in _application_periods(db, application_id)
                                    )
                                },
                            },
                            affects={"downstream_steps": ["organization_ghg_inventory"]},
                            how_to_resolve=[
                                {
                                    "action": "先为该应用建立缺失的报告期，再把每期观测指向已建立且属于该应用的报告期",
                                    "owner": "应用配置 / seed 自动加载",
                                    "precondition": "报告期属于本应用，且其起止日期落在清单报告区间内",
                                }
                            ],
                            evidence={"application_id": application_id},
                        )
                    },
                )
            if set(energies) != set(energy_result_ids):
                raise DomainError(
                    code="PERIOD_ENERGY_RESULT_SET_MISMATCH",
                    message="period energy results cannot be resolved exactly",
                    status_code=409,
                    details={
                        "dependency_gap": dependency_gap(
                            code="PERIOD_ENERGY_RESULT_SET_MISMATCH",
                            kind="frozen_energy_result",
                            step="period_energy_trend",
                            what_missing={
                                "requested_ids": sorted(energy_result_ids),
                                "unresolved_ids": sorted(set(energy_result_ids) - set(energies)),
                                "observed_identity": {
                                    "frozen_energy_result_ids_of_this_application": sorted(
                                        item.id
                                        for item in _application_energy_results(db, application_id)
                                    )
                                },
                            },
                            affects={"downstream_steps": ["organization_ghg_inventory"]},
                            how_to_resolve=[
                                {
                                    "action": "为该报告期求解并冻结能源结果，再把观测指向该冻结结果",
                                    "owner": "建模与引擎求解",
                                    "precondition": "该应用已有可求解的活动系统与报告期",
                                }
                            ],
                            evidence={"application_id": application_id},
                        )
                    },
                )
            if any(item.application_id != application_id for item in periods.values()):
                raise DomainError(
                    code="PERIOD_ENERGY_APPLICATION_MISMATCH",
                    message="one or more periods belong to another application",
                    status_code=409,
                )
            if any(item.application_id != application_id for item in energies.values()):
                raise DomainError(
                    code="PERIOD_ENERGY_APPLICATION_MISMATCH",
                    message="one or more energy results belong to another application",
                    status_code=409,
                )

            snapshot_ids = [item.solved_snapshot_id for item in energies.values()]
            if len(snapshot_ids) != len(set(snapshot_ids)):
                raise DomainError(
                    code="PERIOD_ENERGY_SNAPSHOT_DUPLICATE",
                    message="each reporting period must use a distinct solved snapshot",
                    status_code=409,
                )
            snapshots = {
                item.id: item
                for item in db.scalars(
                    select(SolvedSystemSnapshot).where(
                        SolvedSystemSnapshot.id.in_(snapshot_ids)
                    )
                )
            }
            if len(snapshots) != len(energies):
                raise DomainError(
                    code="PERIOD_ENERGY_SNAPSHOT_SET_MISMATCH",
                    message="energy result snapshots cannot be resolved exactly",
                    status_code=409,
                )
            revisions = {
                item.id: item
                for item in db.scalars(
                    select(SystemRevision).where(
                        SystemRevision.id.in_(
                            [item.system_revision_id for item in snapshots.values()]
                        )
                    )
                )
            }
            if len(revisions) != len(snapshots):
                raise DomainError(
                    code="PERIOD_ENERGY_REVISION_SET_MISMATCH",
                    message="energy result revisions cannot be resolved exactly",
                    status_code=409,
                )
            system_model_ids = {item.system_model_id for item in revisions.values()}
            if len(system_model_ids) != 1:
                raise DomainError(
                    code="PERIOD_ENERGY_SYSTEM_MODEL_MISMATCH",
                    message="period observations must use one system model",
                    status_code=409,
                )
            system_model_id = next(iter(system_model_ids))
            system_model = db.get(SystemModel, system_model_id)
            if system_model is None or system_model.application_id != application_id:
                raise DomainError(
                    code="PERIOD_ENERGY_SYSTEM_MODEL_MISMATCH",
                    message="period observation model belongs to another application",
                    status_code=409,
                )

            functional_units = {
                canonical_json_sha256(item.functional_unit): item.functional_unit
                for item in snapshots.values()
            }
            if len(functional_units) != 1:
                raise DomainError(
                    code="PERIOD_ENERGY_FUNCTIONAL_UNIT_MISMATCH",
                    message="period observations must use one exact functional unit",
                    status_code=422,
                )
            functional_unit_sha256, functional_unit = next(
                iter(functional_units.items())
            )
            observation_payloads: list[dict[str, Any]] = []
            parsed_energy: dict[str, EnergyCarrierSolved] = {}
            revision_by_period: dict[str, SystemRevision] = {}
            for binding in payload.observations:
                period = periods[binding.period_id]
                energy = energies[binding.energy_result_id]
                snapshot = snapshots[energy.solved_snapshot_id]
                revision = revisions[snapshot.system_revision_id]
                if snapshot.application_id != application_id:
                    raise DomainError(
                        code="PERIOD_ENERGY_APPLICATION_MISMATCH",
                        message="one or more solved snapshots belong to another application",
                        status_code=409,
                    )
                parsed = EnergyCarrierSolved.model_validate(energy.result_json)
                expected_record_hash = canonical_json_sha256(
                    {
                        "capability_key": "energy.carrier.solved.v1",
                        "solved_snapshot_content_sha256": snapshot.content_sha256,
                        "request_sha256": energy.request_sha256,
                        "result_content_sha256": parsed.content_sha256,
                    }
                )
                if energy.content_sha256 != expected_record_hash:
                    raise DomainError(
                        code="PERIOD_ENERGY_RESULT_HASH_MISMATCH",
                        message="persisted energy result record hash does not match",
                        status_code=409,
                        details={"energy_result_id": energy.id},
                    )
                period_basis = {
                    "id": period.id,
                    "key": period.key,
                    "name": period.name,
                    "start_date": period.start_date.isoformat(),
                    "end_date": period.end_date.isoformat(),
                    "resolution": period.resolution,
                }
                source = {
                    "energy_result_id": energy.id,
                    "energy_result_record_sha256": energy.content_sha256,
                    "solved_snapshot_id": snapshot.id,
                    "solved_snapshot_content_sha256": snapshot.content_sha256,
                    "solve_hash": snapshot.solve_hash,
                    "system_revision_id": revision.id,
                    "system_revision_sha256": revision.content_sha256,
                    "system_model_id": revision.system_model_id,
                }
                parsed_energy[period.id] = parsed
                revision_by_period[period.id] = revision
                observation_payloads.append(
                    {
                        "period": {
                            **period_basis,
                            "content_sha256": canonical_json_sha256(period_basis),
                        },
                        "source": source,
                        "energy_result": parsed.model_dump(mode="json"),
                    }
                )

            earliest_period_id = min(
                period_ids,
                key=lambda period_id: (
                    periods[period_id].start_date,
                    periods[period_id].end_date,
                    period_id,
                ),
            )
            baseline_period_id = payload.baseline_period_id or earliest_period_id
            labels = self._metric_labels(
                parsed_energy[baseline_period_id],
                revision_by_period[baseline_period_id].graph_snapshot,
            )
            return build_period_energy_trend(
                application_id=application_id,
                system_model_id=system_model_id,
                functional_unit=functional_unit,
                functional_unit_sha256=functional_unit_sha256,
                observations=tuple(observation_payloads),
                baseline_period_id=baseline_period_id,
                metric_labels=labels,
            )

    def chart_svg(
        self,
        application_id: str,
        payload: PeriodEnergyTrendCreate,
    ) -> str:
        return render_period_energy_trend_svg(self.analyze(application_id, payload))
