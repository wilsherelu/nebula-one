from __future__ import annotations

from ..analysis.carbon_management import build_carbon_management
from ..database import Database
from ..errors import DomainError
from ..models import Application
from ..runtime_models import EnergyCarrierResult, SolvedSystemSnapshot
from ..runtime_schemas import CarbonManagementCreate
from ..analysis.energy_carrier import EnergyCarrierSolved
from .runtime_support import require_method_package


class CarbonManagementService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def analyze(self, solved_snapshot_id: str, payload: CarbonManagementCreate) -> dict:
        with self.database.session() as db:
            snapshot = db.get(SolvedSystemSnapshot, solved_snapshot_id)
            if snapshot is None:
                raise DomainError(
                    code="SOLVED_SYSTEM_SNAPSHOT_NOT_FOUND",
                    message=f"solved system snapshot not found: {solved_snapshot_id}",
                    status_code=404,
                )
            energy = db.get(EnergyCarrierResult, payload.energy_carrier_result_id)
            if energy is None:
                raise DomainError(
                    code="ENERGY_CARRIER_RESULT_NOT_FOUND",
                    message=f"energy carrier result not found: {payload.energy_carrier_result_id}",
                    status_code=404,
                )
            if energy.solved_snapshot_id != snapshot.id:
                raise DomainError(
                    code="CARBON_ENERGY_SNAPSHOT_MISMATCH",
                    message="energy and carbon inputs bind different solved snapshots",
                    status_code=409,
                )
            application = db.get(Application, snapshot.application_id)
            if application is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {snapshot.application_id}",
                    status_code=404,
                )
            context = application.context or {}
            reporting_period = {
                "id": context.get("reporting_period_id"),
                "version": context.get("reporting_period_version"),
                "content_sha256": context.get("reporting_period_sha256"),
            }
            package = require_method_package(db, payload.method_package_ref)
            return build_carbon_management(
                solved_snapshot_id=snapshot.id,
                solved_snapshot_sha256=snapshot.content_sha256,
                scaled_elementary_exchanges=snapshot.scaled_elementary_exchanges,
                lcia_results=snapshot.lcia_results,
                provider_receipt=snapshot.provider_receipt,
                reporting_period=reporting_period,
                energy_result_id=energy.id,
                energy_result_sha256=energy.content_sha256,
                energy_result=EnergyCarrierSolved.model_validate(energy.result_json),
                method_package_ref=payload.method_package_ref,
                method_package_sha256=package.content_sha256,
                method_package_kind=package.package_kind,
                manifest=package.manifest,
            )
