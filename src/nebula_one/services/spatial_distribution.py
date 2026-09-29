from __future__ import annotations

from sqlalchemy import select

from ..analysis.spatial_distribution import build_spatial_distribution
from ..analysis.spatial_distribution_visual import render_spatial_distribution_svg
from ..database import Database
from ..errors import DomainError
from ..models import Application
from ..runtime_models import Entity, SolvedSystemSnapshot
from ..runtime_schemas import SolvedSystemSnapshotOut, SpatialDistributionCreate
from .runtime_support import require_method_package


class SpatialDistributionService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def analyze(
        self, solved_snapshot_id: str, payload: SpatialDistributionCreate
    ) -> dict:
        with self.database.session() as db:
            snapshot = db.get(SolvedSystemSnapshot, solved_snapshot_id)
            if snapshot is None:
                raise DomainError(
                    code="SOLVED_SYSTEM_SNAPSHOT_NOT_FOUND",
                    message=f"solved system snapshot not found: {solved_snapshot_id}",
                    status_code=404,
                )
            application = db.get(Application, snapshot.application_id)
            if application is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {snapshot.application_id}",
                    status_code=404,
                )
            bound_method_refs = set(
                (application.context or {}).get("method_package_refs") or []
            )
            if payload.method_package_ref not in bound_method_refs:
                raise DomainError(
                    code="SPATIAL_DISTRIBUTION_METHOD_NOT_BOUND",
                    message="spatial distribution method is not bound to this application",
                    status_code=409,
                )
            package = require_method_package(db, payload.method_package_ref)
            destination = (package.manifest.get("classification_rules") or {}).get(
                "destination"
            )
            if not isinstance(destination, dict):
                raise DomainError(
                    code="SPATIAL_DISTRIBUTION_DESTINATION_REQUIRED",
                    message="spatial distribution method requires a destination",
                    status_code=422,
                )
            matches: list[dict] = []
            for entity in db.scalars(
                select(Entity).where(
                    Entity.application_id == snapshot.application_id,
                    Entity.entity_type == "park",
                )
            ):
                spatial = (entity.attributes or {}).get("spatial_unit")
                if not isinstance(spatial, dict):
                    continue
                spatial_ref = f"{spatial.get('spatial_unit_id')}@{spatial.get('version')}"
                if (
                    spatial_ref == destination.get("spatial_unit_ref")
                    and spatial.get("content_sha256")
                    == destination.get("spatial_unit_sha256")
                ):
                    matches.append(spatial)
            if len(matches) != 1:
                raise DomainError(
                    code="SPATIAL_DISTRIBUTION_DESTINATION_NOT_UNIQUE",
                    message="method destination must match one application park spatial unit",
                    status_code=422,
                    details={"match_count": len(matches)},
                )
            snapshot_payload = SolvedSystemSnapshotOut.model_validate(snapshot).model_dump(
                mode="json"
            )
            return build_spatial_distribution(
                solved_snapshot=snapshot_payload,
                method_package_ref=payload.method_package_ref,
                method_package_sha256=package.content_sha256,
                method_package_kind=package.package_kind,
                manifest=package.manifest,
                destination_spatial_unit=matches[0],
                tolerance=payload.tolerance,
            )

    def map_svg(
        self, solved_snapshot_id: str, payload: SpatialDistributionCreate
    ) -> str:
        if not payload.scenario_id:
            raise DomainError(
                code="SPATIAL_DISTRIBUTION_SCENARIO_REQUIRED",
                message="scenario_id is required to render a spatial distribution map",
                status_code=422,
            )
        result = self.analyze(solved_snapshot_id, payload)
        return render_spatial_distribution_svg(result, scenario_id=payload.scenario_id)
