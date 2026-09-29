from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ..analysis.period_energy_total import build_period_energy_total
from ..analysis.period_energy_total_visual import render_period_energy_total_svg
from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..models import SystemRevision
from ..runtime_models import (
    BoundaryDefinition,
    EnergyCarrierResult,
    EvidenceItem,
    InventoryDataPoint,
    InventorySnapshot,
    SolvedSystemSnapshot,
)
from ..runtime_schemas import (
    PeriodEnergyTotalCreate,
    PeriodEnergyTrendCreate,
    PeriodEnergyTrendObservationCreate,
)
from .period_energy_trend import PeriodEnergyTrendService


class PeriodEnergyTotalService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.trends = PeriodEnergyTrendService(database)

    @staticmethod
    def _inventory_hash(
        inventory: InventorySnapshot,
        boundary: BoundaryDefinition,
        points: list[InventoryDataPoint],
    ) -> str:
        content = {
            "system_revision_id": inventory.system_revision_id,
            "boundary_hash": boundary.content_sha256,
            "period_id": inventory.period_id,
            "data_points": [
                {
                    "id": point.id,
                    "entity_id": point.entity_id,
                    "process_id": point.process_id,
                    "flow_uuid": point.flow_uuid,
                    "metric_key": point.metric_key,
                    "quantity": point.quantity,
                    "unit": point.unit,
                    "source_type": point.source_type,
                    "evidence_id": point.evidence_id,
                    "mapping_target": point.mapping_target,
                    "quality_status": point.quality_status,
                    "review_status": point.review_status,
                    "uncertainty": point.uncertainty,
                }
                for point in points
            ],
        }
        return canonical_json_sha256(content)

    @staticmethod
    def _output_port(
        revision: SystemRevision,
        point: InventoryDataPoint,
    ) -> tuple[dict[str, Any], str]:
        port_id = str(point.mapping_target.get("port_id") or "").strip()
        role = str(point.mapping_target.get("role") or "").strip()
        if not point.process_id or not port_id or role != "period_product_output":
            raise DomainError(
                code="PERIOD_ENERGY_ACTIVITY_MAPPING_INVALID",
                message="period product output requires process, port and role mapping",
                status_code=422,
                details={"data_point_id": point.id},
            )
        nodes = [
            node
            for node in revision.graph_snapshot.get("nodes") or []
            if isinstance(node, dict) and str(node.get("id") or "") == point.process_id
        ]
        ports = [
            port
            for node in nodes
            for port in node.get("outputs") or []
            if isinstance(port, dict) and str(port.get("id") or "") == port_id
        ]
        if len(ports) != 1:
            raise DomainError(
                code="PERIOD_ENERGY_FUNCTIONAL_OUTPUT_NOT_FOUND",
                message="period product output mapping does not resolve exactly",
                status_code=422,
                details={"data_point_id": point.id},
            )
        port = ports[0]
        if port.get("isProduct") is not True or str(port.get("direction") or "") != "output":
            raise DomainError(
                code="PERIOD_ENERGY_FUNCTIONAL_OUTPUT_INVALID",
                message="period product output must map to a product output port",
                status_code=422,
                details={"data_point_id": point.id},
            )
        return port, f"{point.process_id}::{port_id}"

    def analyze(
        self,
        application_id: str,
        payload: PeriodEnergyTotalCreate,
    ) -> dict[str, Any]:
        trend_payload = PeriodEnergyTrendCreate(
            observations=[
                PeriodEnergyTrendObservationCreate(
                    period_id=item.period_id,
                    energy_result_id=item.energy_result_id,
                )
                for item in payload.observations
            ],
            baseline_period_id=payload.baseline_period_id,
        )
        trend = self.trends.analyze(application_id, trend_payload)

        inventory_ids = [item.inventory_snapshot_id for item in payload.observations]
        point_ids = [item.production_data_point_id for item in payload.observations]
        energy_ids = [item.energy_result_id for item in payload.observations]
        with self.database.session() as db:
            inventories = {
                item.id: item
                for item in db.scalars(
                    select(InventorySnapshot).where(
                        InventorySnapshot.id.in_(inventory_ids)
                    )
                )
            }
            points = {
                item.id: item
                for item in db.scalars(
                    select(InventoryDataPoint).where(InventoryDataPoint.id.in_(point_ids))
                )
            }
            energies = {
                item.id: item
                for item in db.scalars(
                    select(EnergyCarrierResult).where(EnergyCarrierResult.id.in_(energy_ids))
                )
            }
            if set(inventories) != set(inventory_ids) or set(points) != set(point_ids):
                raise DomainError(
                    code="PERIOD_ENERGY_ACTIVITY_SET_MISMATCH",
                    message="period inventory or product output cannot be resolved exactly",
                    status_code=409,
                )
            if set(energies) != set(energy_ids):
                raise DomainError(
                    code="PERIOD_ENERGY_RESULT_SET_MISMATCH",
                    message="period energy results cannot be resolved exactly",
                    status_code=409,
                )
            snapshots = {
                item.id: item
                for item in db.scalars(
                    select(SolvedSystemSnapshot).where(
                        SolvedSystemSnapshot.id.in_(
                            [energy.solved_snapshot_id for energy in energies.values()]
                        )
                    )
                )
            }
            revisions = {
                item.id: item
                for item in db.scalars(
                    select(SystemRevision).where(
                        SystemRevision.id.in_(
                            [snapshot.system_revision_id for snapshot in snapshots.values()]
                        )
                    )
                )
            }
            activities: list[dict[str, Any]] = []
            for binding in payload.observations:
                inventory = inventories[binding.inventory_snapshot_id]
                point = points[binding.production_data_point_id]
                energy = energies[binding.energy_result_id]
                snapshot = snapshots.get(energy.solved_snapshot_id)
                if snapshot is None:
                    raise DomainError(
                        code="PERIOD_ENERGY_SNAPSHOT_SET_MISMATCH",
                        message="period energy snapshot cannot be resolved",
                        status_code=409,
                    )
                revision = revisions.get(snapshot.system_revision_id)
                if revision is None:
                    raise DomainError(
                        code="PERIOD_ENERGY_REVISION_SET_MISMATCH",
                        message="period energy revision cannot be resolved",
                        status_code=409,
                    )
                if (
                    inventory.application_id != application_id
                    or snapshot.application_id != application_id
                    or inventory.period_id != binding.period_id
                    or inventory.system_revision_id != snapshot.system_revision_id
                ):
                    raise DomainError(
                        code="PERIOD_ENERGY_ACTIVITY_SOURCE_MISMATCH",
                        message="period inventory must match application, period and solved revision",
                        status_code=409,
                        details={"period_id": binding.period_id},
                    )
                if inventory.status != "frozen" or not inventory.content_sha256:
                    raise DomainError(
                        code="PERIOD_ENERGY_INVENTORY_NOT_FROZEN",
                        message="period energy total requires a frozen inventory snapshot",
                        status_code=409,
                        details={"inventory_snapshot_id": inventory.id},
                    )
                boundary = db.get(BoundaryDefinition, inventory.boundary_id)
                if boundary is None or boundary.status != "frozen":
                    raise DomainError(
                        code="PERIOD_ENERGY_BOUNDARY_NOT_FROZEN",
                        message="period inventory requires a frozen boundary",
                        status_code=409,
                    )
                all_points = list(
                    db.scalars(
                        select(InventoryDataPoint)
                        .where(InventoryDataPoint.inventory_snapshot_id == inventory.id)
                        .order_by(InventoryDataPoint.id)
                    )
                )
                if self._inventory_hash(inventory, boundary, all_points) != inventory.content_sha256:
                    raise DomainError(
                        code="PERIOD_ENERGY_INVENTORY_HASH_MISMATCH",
                        message="frozen inventory content hash does not match",
                        status_code=409,
                        details={"inventory_snapshot_id": inventory.id},
                    )
                if point.inventory_snapshot_id != inventory.id:
                    raise DomainError(
                        code="PERIOD_ENERGY_ACTIVITY_SOURCE_MISMATCH",
                        message="product output data point belongs to another inventory",
                        status_code=409,
                    )
                evidence = db.get(EvidenceItem, point.evidence_id)
                if evidence is None or evidence.application_id != application_id:
                    raise DomainError(
                        code="PERIOD_ENERGY_EVIDENCE_IDENTITY_INVALID",
                        message="product output evidence cannot be resolved in the application",
                        status_code=409,
                    )
                port, exchange_id = self._output_port(revision, point)
                boundary_outputs = [
                    item
                    for item in snapshot.boundary_flows
                    if isinstance(item, dict)
                    and item.get("exchange_id") == exchange_id
                    and item.get("direction") == "output"
                    and item.get("flow_uuid") == port.get("flowUuid")
                ]
                if len(boundary_outputs) != 1:
                    raise DomainError(
                        code="PERIOD_ENERGY_SOLVED_OUTPUT_NOT_FOUND",
                        message="solved snapshot lacks the exact functional output",
                        status_code=422,
                        details={"exchange_id": exchange_id},
                    )
                solved_output = boundary_outputs[0]
                if solved_output.get("unit") != point.unit or (
                    solved_output.get("unit_group") != port.get("unitGroupUuid")
                ):
                    raise DomainError(
                        code="PERIOD_ENERGY_ACTIVITY_UNIT_MISMATCH",
                        message="period output and solved output units differ",
                        status_code=422,
                        details={"period_id": binding.period_id},
                    )
                point_basis = {
                    "id": point.id,
                    "inventory_snapshot_id": point.inventory_snapshot_id,
                    "entity_id": point.entity_id,
                    "process_id": point.process_id,
                    "flow_uuid": point.flow_uuid,
                    "metric_key": point.metric_key,
                    "quantity": point.quantity,
                    "unit": point.unit,
                    "source_type": point.source_type,
                    "evidence_id": point.evidence_id,
                    "mapping_target": point.mapping_target,
                    "quality_status": point.quality_status,
                    "review_status": point.review_status,
                    "uncertainty": point.uncertainty,
                }
                activities.append(
                    {
                        "period_id": binding.period_id,
                        "inventory_snapshot": {
                            "id": inventory.id,
                            "content_sha256": inventory.content_sha256,
                            "system_revision_id": inventory.system_revision_id,
                            "boundary_id": inventory.boundary_id,
                            "period_id": inventory.period_id,
                        },
                        "data_point": {
                            **point_basis,
                            "content_sha256": canonical_json_sha256(point_basis),
                        },
                        "evidence": {
                            "id": evidence.id,
                            "content_sha256": evidence.content_sha256,
                            "evidence_type": evidence.evidence_type,
                            "source_name": evidence.source_name,
                            "source_ref": evidence.source_ref,
                        },
                        "functional_output": {
                            "exchange_id": exchange_id,
                            "solved_reference_amount": solved_output.get("amount"),
                            "flow_identity": {
                                "source_namespace": port.get("flowSourceNamespace"),
                                "flow_uuid": port.get("flowUuid"),
                                "version": port.get("flowVersion"),
                                "flow_property_uuid": port.get("flowPropertyUuid"),
                                "flow_property_version": port.get("flowPropertyVersion"),
                                "unit_group_uuid": port.get("unitGroupUuid"),
                                "unit_group_version": port.get("unitGroupVersion"),
                                "unit": port.get("unit"),
                            },
                        },
                    }
                )
        return build_period_energy_total(
            intensity_trend=trend,
            activities=tuple(activities),
        )

    def chart_svg(
        self,
        application_id: str,
        payload: PeriodEnergyTotalCreate,
    ) -> str:
        return render_period_energy_total_svg(self.analyze(application_id, payload))
