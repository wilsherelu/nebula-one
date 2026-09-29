from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..runtime_models import (
    BoundaryDefinition,
    EvidenceItem,
    InventoryDataPoint,
    InventorySnapshot,
    ParameterSet,
)
from ..runtime_schemas import (
    EvidenceItemCreate,
    InventoryDataPointCreate,
    InventorySnapshotCreate,
    ParameterSetCreate,
)
from .runtime_support import (
    require_application,
    require_entity,
    require_period,
    require_process_ids,
    require_revision,
)


class InventoryService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_evidence(
        self, application_id: str, payload: EvidenceItemCreate
    ) -> EvidenceItem:
        with self.database.session() as db:
            require_application(db, application_id)
            record = EvidenceItem(
                application_id=application_id,
                evidence_type=payload.evidence_type,
                source_name=payload.source_name,
                source_ref=payload.source_ref,
                content_sha256=payload.content_sha256,
                metadata_json=payload.metadata,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    def list_evidence(self, application_id: str) -> list[EvidenceItem]:
        with self.database.session() as db:
            require_application(db, application_id)
            return list(
                db.scalars(
                    select(EvidenceItem)
                    .where(EvidenceItem.application_id == application_id)
                    .order_by(EvidenceItem.created_at)
                )
            )

    def create_inventory(
        self, application_id: str, payload: InventorySnapshotCreate
    ) -> InventorySnapshot:
        with self.database.session() as db:
            require_application(db, application_id)
            require_revision(db, payload.system_revision_id, application_id)
            require_period(db, payload.period_id, application_id)
            boundary = db.get(BoundaryDefinition, payload.boundary_id)
            if boundary is None:
                raise DomainError(
                    code="BOUNDARY_NOT_FOUND",
                    message=f"boundary not found: {payload.boundary_id}",
                    status_code=404,
                )
            if boundary.application_id != application_id:
                raise DomainError(
                    code="BOUNDARY_APPLICATION_MISMATCH",
                    message="boundary does not belong to the requested application",
                    status_code=409,
                )
            record = InventorySnapshot(
                application_id=application_id,
                **payload.model_dump(),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    def list_inventories(self, application_id: str) -> list[InventorySnapshot]:
        with self.database.session() as db:
            require_application(db, application_id)
            return list(
                db.scalars(
                    select(InventorySnapshot)
                    .where(InventorySnapshot.application_id == application_id)
                    .order_by(InventorySnapshot.created_at)
                )
            )

    def add_data_point(
        self, inventory_id: str, payload: InventoryDataPointCreate
    ) -> InventoryDataPoint:
        with self.database.session() as db:
            inventory = db.get(InventorySnapshot, inventory_id)
            if inventory is None:
                raise DomainError(
                    code="INVENTORY_SNAPSHOT_NOT_FOUND",
                    message=f"inventory snapshot not found: {inventory_id}",
                    status_code=404,
                )
            if inventory.status != "draft":
                raise DomainError(
                    code="INVENTORY_SNAPSHOT_FROZEN",
                    message="data points cannot be added to a frozen inventory snapshot",
                    status_code=409,
                )
            if payload.entity_id:
                require_entity(db, payload.entity_id, inventory.application_id)
            evidence = db.get(EvidenceItem, payload.evidence_id)
            if evidence is None:
                raise DomainError(
                    code="EVIDENCE_ITEM_NOT_FOUND",
                    message=f"evidence item not found: {payload.evidence_id}",
                    status_code=404,
                )
            if evidence.application_id != inventory.application_id:
                raise DomainError(
                    code="EVIDENCE_APPLICATION_MISMATCH",
                    message="evidence does not belong to the inventory application",
                    status_code=409,
                )
            revision, _ = require_revision(
                db, inventory.system_revision_id, inventory.application_id
            )
            if payload.process_id:
                require_process_ids(revision, [payload.process_id])
            self._validate_mapping_target(revision.graph_snapshot, payload)
            record = InventoryDataPoint(
                inventory_snapshot_id=inventory_id,
                **payload.model_dump(),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    @staticmethod
    def _validate_mapping_target(
        graph: dict, payload: InventoryDataPointCreate
    ) -> None:
        nodes = [node for node in graph.get("nodes") or [] if isinstance(node, dict)]
        selected_nodes = (
            [node for node in nodes if str(node.get("id") or "") == payload.process_id]
            if payload.process_id
            else nodes
        )
        ports: list[dict] = []
        for node in selected_nodes:
            for group in ("inputs", "outputs", "emissions"):
                ports.extend(
                    port
                    for port in node.get(group) or []
                    if isinstance(port, dict)
                )
        if payload.flow_uuid and not any(
            str(port.get("flowUuid", port.get("flow_uuid")) or "")
            == payload.flow_uuid
            for port in ports
        ):
            raise DomainError(
                code="INVENTORY_FLOW_MAPPING_NOT_FOUND",
                message="flow_uuid is absent from the selected system revision scope",
                status_code=422,
                details={
                    "process_id": payload.process_id,
                    "flow_uuid": payload.flow_uuid,
                },
            )
        port_id = str(payload.mapping_target.get("port_id") or "").strip()
        if port_id:
            if not payload.process_id:
                raise DomainError(
                    code="INVENTORY_PORT_MAPPING_PROCESS_REQUIRED",
                    message="mapping_target.port_id requires process_id",
                    status_code=422,
                )
            matching = [
                port for port in ports if str(port.get("id") or "") == port_id
            ]
            if not matching:
                raise DomainError(
                    code="INVENTORY_PORT_MAPPING_NOT_FOUND",
                    message="mapping target port is absent from the selected process",
                    status_code=422,
                    details={"process_id": payload.process_id, "port_id": port_id},
                )
            mapped_flow = str(
                matching[0].get("flowUuid", matching[0].get("flow_uuid")) or ""
            )
            if payload.flow_uuid and mapped_flow and mapped_flow != payload.flow_uuid:
                raise DomainError(
                    code="INVENTORY_PORT_FLOW_MISMATCH",
                    message="mapping target port belongs to a different flow",
                    status_code=422,
                    details={
                        "flow_uuid": payload.flow_uuid,
                        "mapped_flow_uuid": mapped_flow,
                    },
                )
        exchange_id = str(payload.mapping_target.get("exchange_id") or "").strip()
        if exchange_id and not any(
            str(exchange.get("id") or "") == exchange_id
            for exchange in graph.get("exchanges") or []
            if isinstance(exchange, dict)
        ):
            raise DomainError(
                code="INVENTORY_EXCHANGE_MAPPING_NOT_FOUND",
                message="mapping target exchange is absent from the selected system revision",
                status_code=422,
                details={"exchange_id": exchange_id},
            )

    def list_data_points(self, inventory_id: str) -> list[InventoryDataPoint]:
        with self.database.session() as db:
            if db.get(InventorySnapshot, inventory_id) is None:
                raise DomainError(
                    code="INVENTORY_SNAPSHOT_NOT_FOUND",
                    message=f"inventory snapshot not found: {inventory_id}",
                    status_code=404,
                )
            return list(
                db.scalars(
                    select(InventoryDataPoint)
                    .where(InventoryDataPoint.inventory_snapshot_id == inventory_id)
                    .order_by(InventoryDataPoint.created_at, InventoryDataPoint.id)
                )
            )

    def freeze_inventory(self, inventory_id: str) -> InventorySnapshot:
        with self.database.session() as db:
            inventory = db.get(InventorySnapshot, inventory_id)
            if inventory is None:
                raise DomainError(
                    code="INVENTORY_SNAPSHOT_NOT_FOUND",
                    message=f"inventory snapshot not found: {inventory_id}",
                    status_code=404,
                )
            if inventory.status == "frozen":
                return inventory
            boundary = db.get(BoundaryDefinition, inventory.boundary_id)
            assert boundary is not None
            if boundary.status != "frozen":
                raise DomainError(
                    code="BOUNDARY_NOT_FROZEN",
                    message="inventory snapshot requires a frozen boundary",
                    status_code=409,
                )
            if boundary.period_id and boundary.period_id != inventory.period_id:
                raise DomainError(
                    code="INVENTORY_BOUNDARY_PERIOD_MISMATCH",
                    message="inventory period differs from the boundary period",
                    status_code=409,
                )
            points = list(
                db.scalars(
                    select(InventoryDataPoint)
                    .where(InventoryDataPoint.inventory_snapshot_id == inventory_id)
                    .order_by(InventoryDataPoint.id)
                )
            )
            if not points:
                raise DomainError(
                    code="INVENTORY_SNAPSHOT_EMPTY",
                    message="inventory snapshot requires at least one data point",
                    status_code=422,
                )
            pending = [point.id for point in points if point.review_status != "approved"]
            invalid = [
                point.id
                for point in points
                if point.quality_status in {"invalid", "rejected"}
            ]
            if pending or invalid:
                raise DomainError(
                    code="INVENTORY_REVIEW_INCOMPLETE",
                    message="all inventory data points must be approved and quality-valid before freezing",
                    status_code=409,
                    details={"not_approved": pending, "invalid_quality": invalid},
                )
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
            inventory.content_sha256 = canonical_json_sha256(content)
            inventory.status = "frozen"
            inventory.frozen_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(inventory)
            return inventory

    def create_parameter_set(
        self, application_id: str, payload: ParameterSetCreate
    ) -> ParameterSet:
        with self.database.session() as db:
            require_application(db, application_id)
            record = ParameterSet(
                application_id=application_id,
                name=payload.name,
                values=payload.values,
                metadata_json=payload.metadata,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    def list_parameter_sets(self, application_id: str) -> list[ParameterSet]:
        with self.database.session() as db:
            require_application(db, application_id)
            return list(
                db.scalars(
                    select(ParameterSet)
                    .where(ParameterSet.application_id == application_id)
                    .order_by(ParameterSet.created_at)
                )
            )

    def freeze_parameter_set(self, parameter_set_id: str) -> ParameterSet:
        with self.database.session() as db:
            record = db.get(ParameterSet, parameter_set_id)
            if record is None:
                raise DomainError(
                    code="PARAMETER_SET_NOT_FOUND",
                    message=f"parameter set not found: {parameter_set_id}",
                    status_code=404,
                )
            if record.status == "frozen":
                return record
            record.content_sha256 = canonical_json_sha256(
                {"values": record.values, "metadata": record.metadata_json}
            )
            record.status = "frozen"
            record.frozen_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(record)
            return record
