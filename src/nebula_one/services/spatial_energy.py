from __future__ import annotations

from ..analysis.spatial_energy import build_spatial_energy
from ..analysis.spatial_energy_visual import render_spatial_energy_svg
from ..database import Database
from ..errors import DomainError
from ..runtime_models import EnergyCarrierResult, SolvedSystemSnapshot
from ..runtime_schemas import EnergyCarrierResultOut, SolvedSystemSnapshotOut, SpatialAggregateCreate, SpatialEnergyCreate
from .spatial_aggregate import SpatialAggregateService


class SpatialEnergyService:
    def __init__(
        self, database: Database, spatial_aggregate: SpatialAggregateService
    ) -> None:
        self.database = database
        self.spatial_aggregate = spatial_aggregate

    def analyze(self, solved_snapshot_id: str, payload: SpatialEnergyCreate) -> dict:
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
                    message=(
                        "energy carrier result not found: "
                        f"{payload.energy_carrier_result_id}"
                    ),
                    status_code=404,
                )
            if energy.solved_snapshot_id != solved_snapshot_id:
                raise DomainError(
                    code="SPATIAL_ENERGY_SNAPSHOT_MISMATCH",
                    message="energy result belongs to a different solved snapshot",
                    status_code=409,
                )
            solved_payload = SolvedSystemSnapshotOut.model_validate(solved).model_dump(
                mode="json"
            )
            energy_payload = EnergyCarrierResultOut.model_validate(energy).model_dump(
                mode="json"
            )
        spatial = self.spatial_aggregate.analyze(
            solved_snapshot_id,
            SpatialAggregateCreate(
                boundary_id=payload.boundary_id,
                tolerance=payload.tolerance,
            ),
        )
        return build_spatial_energy(
            solved_snapshot=solved_payload,
            energy_record=energy_payload,
            spatial_aggregate=spatial,
        )

    def sankey_svg(self, solved_snapshot_id: str, payload: SpatialEnergyCreate) -> str:
        result = self.analyze(solved_snapshot_id, payload)
        return render_spatial_energy_svg(result, series_id=payload.series_id)
