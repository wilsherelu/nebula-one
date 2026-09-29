from __future__ import annotations

from decimal import Decimal

from ..analysis.energy_flow import build_energy_flow
from ..analysis.energy_flow_visual import render_energy_flow_svg
from ..database import Database
from ..errors import DomainError
from ..models import SystemRevision
from ..runtime_models import EnergyCarrierResult, SolvedSystemSnapshot
from ..runtime_schemas import (
    EnergyCarrierResultOut,
    EnergyFlowCreate,
    SolvedSystemSnapshotOut,
)


class EnergyFlowService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def analyze(self, solved_snapshot_id: str, payload: EnergyFlowCreate) -> dict:
        with self.database.session() as db:
            solved = db.get(SolvedSystemSnapshot, solved_snapshot_id)
            if solved is None:
                raise DomainError(
                    code="SOLVED_SNAPSHOT_NOT_FOUND",
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
            if energy.solved_snapshot_id != solved_snapshot_id:
                raise DomainError(
                    code="ENERGY_FLOW_SNAPSHOT_MISMATCH",
                    message="energy result belongs to a different solved snapshot",
                    status_code=409,
                )
            revision = db.get(SystemRevision, solved.system_revision_id)
            if revision is None:
                raise DomainError(
                    code="SYSTEM_REVISION_NOT_FOUND",
                    message=f"system revision not found: {solved.system_revision_id}",
                    status_code=404,
                )
            solved_payload = SolvedSystemSnapshotOut.model_validate(solved).model_dump(
                mode="json"
            )
            energy_payload = EnergyCarrierResultOut.model_validate(energy).model_dump(
                mode="json"
            )
            graph = revision.graph_snapshot
        return build_energy_flow(
            solved_snapshot=solved_payload,
            graph=graph,
            energy_record=energy_payload,
            conversions=[item.model_dump(mode="json") for item in payload.conversions],
            tolerance=Decimal(str(payload.tolerance)),
        )

    def sankey_svg(self, solved_snapshot_id: str, payload: EnergyFlowCreate) -> str:
        result = self.analyze(solved_snapshot_id, payload)
        return render_energy_flow_svg(result, series_id=payload.series_id)
