from __future__ import annotations

from decimal import Decimal

from ..analysis.spatial_energy_flow import build_spatial_energy_flow
from ..analysis.spatial_energy_flow_visual import render_spatial_energy_flow_svg
from ..database import Database
from ..errors import DomainError
from ..runtime_models import SolvedSystemSnapshot
from ..runtime_schemas import (
    EnergyFlowCreate,
    SolvedSystemSnapshotOut,
    SpatialAggregateCreate,
    SpatialEnergyFlowCreate,
)
from .energy_flow import EnergyFlowService
from .spatial_aggregate import SpatialAggregateService


class SpatialEnergyFlowService:
    def __init__(
        self,
        database: Database,
        energy_flows: EnergyFlowService,
        spatial_aggregate: SpatialAggregateService,
    ) -> None:
        self.database = database
        self.energy_flows = energy_flows
        self.spatial_aggregate = spatial_aggregate

    def analyze(self, solved_snapshot_id: str, payload: SpatialEnergyFlowCreate) -> dict:
        with self.database.session() as db:
            solved = db.get(SolvedSystemSnapshot, solved_snapshot_id)
            if solved is None:
                raise DomainError(
                    code="SOLVED_SNAPSHOT_NOT_FOUND",
                    message=f"solved system snapshot not found: {solved_snapshot_id}",
                    status_code=404,
                )
            solved_payload = SolvedSystemSnapshotOut.model_validate(solved).model_dump(
                mode="json"
            )
        energy_flow = self.energy_flows.analyze(
            solved_snapshot_id,
            EnergyFlowCreate(
                energy_carrier_result_id=payload.energy_carrier_result_id,
                conversions=payload.conversions,
                tolerance=payload.tolerance,
            ),
        )
        spatial = self.spatial_aggregate.analyze(
            solved_snapshot_id,
            SpatialAggregateCreate(
                boundary_id=payload.boundary_id,
                tolerance=payload.tolerance,
            ),
        )
        return build_spatial_energy_flow(
            solved_snapshot=solved_payload,
            energy_flow=energy_flow,
            spatial_aggregate=spatial,
            tolerance=Decimal(str(payload.tolerance)),
        )

    def sankey_svg(self, solved_snapshot_id: str, payload: SpatialEnergyFlowCreate) -> str:
        result = self.analyze(solved_snapshot_id, payload)
        return render_spatial_energy_flow_svg(result, series_id=payload.series_id)
