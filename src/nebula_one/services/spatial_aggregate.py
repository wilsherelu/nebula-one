from __future__ import annotations

from sqlalchemy import select

from ..analysis.spatial_aggregate import build_spatial_aggregate
from ..analysis.spatial_aggregate_visual import render_spatial_aggregate_svg
from ..database import Database
from ..errors import DomainError
from ..models import SystemRevision
from ..runtime_models import BoundaryDefinition, Entity, EntityModelBinding, SolvedSystemSnapshot
from ..runtime_schemas import (
    BoundaryDefinitionOut,
    EntityModelBindingOut,
    EntityOut,
    SolvedSystemSnapshotOut,
    SpatialAggregateCreate,
)


class SpatialAggregateService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def analyze(
        self, solved_snapshot_id: str, payload: SpatialAggregateCreate
    ) -> dict:
        with self.database.session() as db:
            solved = db.get(SolvedSystemSnapshot, solved_snapshot_id)
            if solved is None:
                raise DomainError(
                    code="SOLVED_SNAPSHOT_NOT_FOUND",
                    message=f"solved system snapshot not found: {solved_snapshot_id}",
                    status_code=404,
                )
            revision = db.get(SystemRevision, solved.system_revision_id)
            if revision is None:
                raise DomainError(
                    code="SYSTEM_REVISION_NOT_FOUND",
                    message=f"system revision not found: {solved.system_revision_id}",
                    status_code=404,
                )
            boundary = db.get(BoundaryDefinition, payload.boundary_id)
            if boundary is None:
                raise DomainError(
                    code="BOUNDARY_NOT_FOUND",
                    message=f"boundary not found: {payload.boundary_id}",
                    status_code=404,
                )
            if boundary.application_id != solved.application_id:
                raise DomainError(
                    code="SPATIAL_BOUNDARY_APPLICATION_MISMATCH",
                    message="park boundary and solved snapshot belong to different applications",
                    status_code=409,
                )
            entities = list(
                db.scalars(
                    select(Entity)
                    .where(Entity.application_id == solved.application_id)
                    .order_by(Entity.id)
                )
            )
            entity_ids = [item.id for item in entities]
            bindings = (
                list(
                    db.scalars(
                        select(EntityModelBinding)
                        .where(
                            EntityModelBinding.entity_id.in_(entity_ids),
                            EntityModelBinding.system_revision_id
                            == solved.system_revision_id,
                            EntityModelBinding.period_id == boundary.period_id,
                        )
                        .order_by(EntityModelBinding.id)
                    )
                )
                if entity_ids
                else []
            )
            solved_payload = SolvedSystemSnapshotOut.model_validate(solved).model_dump(
                mode="json"
            )
            boundary_payload = BoundaryDefinitionOut.model_validate(boundary).model_dump(
                mode="json"
            )
            entity_payloads = [
                EntityOut.model_validate(item).model_dump(mode="json") for item in entities
            ]
            binding_payloads = [
                EntityModelBindingOut.model_validate(item).model_dump(mode="json")
                for item in bindings
            ]
            graph = revision.graph_snapshot
        return build_spatial_aggregate(
            solved_snapshot=solved_payload,
            revision_graph=graph,
            entities=entity_payloads,
            bindings=binding_payloads,
            boundary=boundary_payload,
            tolerance=payload.tolerance,
        )

    def sankey_svg(
        self, solved_snapshot_id: str, payload: SpatialAggregateCreate
    ) -> str:
        result = self.analyze(solved_snapshot_id, payload)
        return render_spatial_aggregate_svg(result, series_id=payload.series_id)
