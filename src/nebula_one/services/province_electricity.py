from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ..analysis.energy_carrier import EnergyCarrierSolved
from ..analysis.energy_scenarios import energy_series_metric_key
from ..analysis.province_electricity import build_province_electricity_scenario
from ..analysis.province_electricity_visual import render_province_electricity_svg
from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..models import Application
from ..runtime_models import EnergyCarrierResult
from ..runtime_schemas import ProvinceElectricityCreate
from .period_energy_total import PeriodEnergyTotalService
from .runtime_support import require_method_package


class ProvinceElectricityService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.period_totals = PeriodEnergyTotalService(database)

    def _source_binding(
        self,
        *,
        payload: ProvinceElectricityCreate,
        selector: dict[str, Any],
    ) -> dict[str, Any]:
        energy_ids = [item.energy_result_id for item in payload.period_energy_total.observations]
        period_by_energy = {
            item.energy_result_id: item.period_id
            for item in payload.period_energy_total.observations
        }
        with self.database.session() as db:
            records = {
                item.id: item
                for item in db.scalars(
                    select(EnergyCarrierResult).where(EnergyCarrierResult.id.in_(energy_ids))
                )
            }
        if set(records) != set(energy_ids):
            raise DomainError(
                code="PROVINCE_ELECTRICITY_ENERGY_RESULT_SET_MISMATCH",
                message="province electricity source results cannot be resolved exactly",
                status_code=409,
            )
        metric_keys: set[str] = set()
        unit_groups: set[tuple[str, str, str]] = set()
        sources: list[dict[str, Any]] = []
        for energy_id in energy_ids:
            record = records[energy_id]
            energy = EnergyCarrierSolved.model_validate(record.result_json)
            matching_series = []
            for series in energy.series:
                matches = [
                    entry
                    for entry in series.entries
                    if entry.carrier_flow.source_namespace == selector.get("source_namespace")
                    and str(entry.carrier_flow.flow_uuid) == selector.get("flow_uuid")
                    and entry.carrier_flow.version == selector.get("version")
                    and entry.carrier_flow.flow_content_sha256
                    == selector.get("flow_content_sha256")
                    and entry.carrier_flow.flow_snapshot_sha256
                    == selector.get("flow_snapshot_sha256")
                ]
                if matches:
                    matching_series.append((series, matches))
            if len(matching_series) != 1:
                raise DomainError(
                    code="PROVINCE_ELECTRICITY_FLOW_NOT_UNIQUE",
                    message="exact TIDAS electricity Flow must resolve to one energy series",
                    status_code=422,
                    details={"energy_result_id": energy_id, "match_count": len(matching_series)},
                )
            series, matches = matching_series[0]
            unit_identity = matches[0].unit_identity
            if unit_identity.kind != "provider_exact" or any(
                entry.unit_identity != unit_identity for entry in matches
            ):
                raise DomainError(
                    code="PROVINCE_ELECTRICITY_UNIT_IDENTITY_MISMATCH",
                    message="electricity entries require one exact provider unit identity",
                    status_code=422,
                )
            metric_key = energy_series_metric_key(series.unit_identity_sha256, series.basis)
            metric_keys.add(metric_key)
            unit_groups.add(
                (
                    str(unit_identity.unit_group.uuid),
                    unit_identity.unit_group.version,
                    unit_identity.unit_group.content_sha256,
                )
            )
            sources.append(
                {
                    "period_id": period_by_energy[energy_id],
                    "energy_result_id": energy_id,
                    "energy_result_record_sha256": record.content_sha256,
                    "energy_result_content_sha256": energy.content_sha256,
                    "solved_snapshot_ref": energy.solved_snapshot_ref.model_dump(mode="json"),
                    "matching_entry_ids": sorted(entry.entry_id for entry in matches),
                }
            )
        if len(metric_keys) != 1 or len(unit_groups) != 1:
            raise DomainError(
                code="PROVINCE_ELECTRICITY_SOURCE_NOT_COMPARABLE",
                message="electricity source series or UnitGroup differs across periods",
                status_code=422,
            )
        unit_group_uuid, unit_group_version, unit_group_hash = next(iter(unit_groups))
        basis = {
            "metric_key": next(iter(metric_keys)),
            "source_namespace": selector["source_namespace"],
            "flow_uuid": selector["flow_uuid"],
            "version": selector["version"],
            "flow_content_sha256": selector["flow_content_sha256"],
            "flow_snapshot_sha256": selector["flow_snapshot_sha256"],
            "unit_group_uuid": unit_group_uuid,
            "unit_group_version": unit_group_version,
            "unit_group_content_sha256": unit_group_hash,
            "period_ids": sorted(period_by_energy.values()),
            "sources": sorted(sources, key=lambda item: item["period_id"]),
        }
        return {**basis, "content_sha256": canonical_json_sha256(basis)}

    def analyze(self, application_id: str, payload: ProvinceElectricityCreate) -> dict:
        period_total = self.period_totals.analyze(
            application_id,
            payload.period_energy_total,
        )
        with self.database.session() as db:
            application = db.get(Application, application_id)
            if application is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {application_id}",
                    status_code=404,
                )
            bound_refs = set((application.context or {}).get("method_package_refs") or [])
            if payload.method_package_ref not in bound_refs:
                raise DomainError(
                    code="PROVINCE_ELECTRICITY_METHOD_NOT_BOUND",
                    message="province electricity method is not bound to this application",
                    status_code=409,
                )
            package = require_method_package(db, payload.method_package_ref)
            selector = (package.manifest.get("formula_graph") or {}).get(
                "electricity_flow_selector"
            )
            if not isinstance(selector, dict):
                raise DomainError(
                    code="PROVINCE_ELECTRICITY_SELECTOR_INVALID",
                    message="province electricity method lacks an exact Flow selector",
                    status_code=422,
                )
        return build_province_electricity_scenario(
            period_energy_total=period_total,
            source_binding=self._source_binding(payload=payload, selector=selector),
            method_package_ref=payload.method_package_ref,
            method_package_sha256=package.content_sha256,
            method_package_kind=package.package_kind,
            manifest=package.manifest,
        )

    def chart_svg(self, application_id: str, payload: ProvinceElectricityCreate) -> str:
        return render_province_electricity_svg(self.analyze(application_id, payload))
