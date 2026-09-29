from __future__ import annotations

from sqlalchemy.orm import Session

from ..casepacks.bindings import (
    ParentRevisionSnapshot,
    ResolvedOperationSet,
    parse_parameter_set_snapshot,
    resolve_parameter_binding,
    to_operation_batch_create,
)
from ..database import Database
from ..errors import DomainError
from ..models import ModelOperation, OperationBatch, SystemModel, SystemRevision
from ..runtime_models import ParameterSet
from ..schemas import ParameterBindingApplyCreate
from .system_revisions import SystemRevisionService


class ParameterBindingService:
    def __init__(
        self, database: Database, system_revisions: SystemRevisionService
    ) -> None:
        self.database = database
        self.system_revisions = system_revisions

    @staticmethod
    def _require_inputs(
        db: Session, system_model_id: str, payload: ParameterBindingApplyCreate
    ) -> tuple[SystemModel, SystemRevision, ParameterSet]:
        system_model = db.get(SystemModel, system_model_id)
        if system_model is None:
            raise DomainError(
                code="SYSTEM_MODEL_NOT_FOUND",
                message=f"system model not found: {system_model_id}",
                status_code=404,
            )
        parent = db.get(SystemRevision, payload.parent_revision_id)
        if parent is None:
            raise DomainError(
                code="SYSTEM_REVISION_NOT_FOUND",
                message=f"system revision not found: {payload.parent_revision_id}",
                status_code=404,
            )
        if parent.system_model_id != system_model_id:
            raise DomainError(
                code="SYSTEM_REVISION_MODEL_MISMATCH",
                message="parent revision does not belong to the requested system model",
                status_code=409,
            )
        if parent.content_sha256 != payload.expected_parent_content_sha256:
            raise DomainError(
                code="SYSTEM_REVISION_OPTIMISTIC_LOCK_FAILED",
                message="parent revision content hash differs from the expected hash",
                status_code=409,
                details={
                    "expected": payload.expected_parent_content_sha256,
                    "actual": parent.content_sha256,
                },
            )
        parameter_set = db.get(ParameterSet, payload.parameter_set_id)
        if parameter_set is None:
            raise DomainError(
                code="PARAMETER_SET_NOT_FOUND",
                message=f"parameter set not found: {payload.parameter_set_id}",
                status_code=404,
            )
        if parameter_set.application_id != system_model.application_id:
            raise DomainError(
                code="PARAMETER_SET_APPLICATION_MISMATCH",
                message="parameter set does not belong to the system model application",
                status_code=409,
            )
        if parameter_set.status != "frozen" or parameter_set.content_sha256 is None:
            raise DomainError(
                code="PARAMETER_SET_NOT_FROZEN",
                message="parameter set must be frozen before binding resolution",
                status_code=409,
            )
        return system_model, parent, parameter_set

    def resolve_and_apply(
        self, system_model_id: str, payload: ParameterBindingApplyCreate
    ) -> tuple[
        ResolvedOperationSet,
        OperationBatch,
        SystemRevision,
        list[ModelOperation],
        bool,
    ]:
        with self.database.session() as db:
            _, parent, parameter_set = self._require_inputs(
                db, system_model_id, payload
            )
            parameter_snapshot_payload = {
                "schema_version": "nebula.parameter-set.snapshot.v1",
                "parameter_set_id": parameter_set.id,
                "status": parameter_set.status,
                "content_sha256": parameter_set.content_sha256,
                "values": parameter_set.values,
                "metadata": parameter_set.metadata_json,
            }
            parent_snapshot = ParentRevisionSnapshot(
                revision_id=parent.id,
                content_sha256=parent.content_sha256,
                graph=parent.graph_snapshot,
            )
        parameter_snapshot = parse_parameter_set_snapshot(parameter_snapshot_payload)
        resolved = resolve_parameter_binding(
            payload.binding,
            parameter_snapshot,
            parent_snapshot,
        )
        batch_create = to_operation_batch_create(resolved, label=payload.label)
        batch, revision, operations, replay = self.system_revisions.apply_batch(
            system_model_id, batch_create
        )
        return resolved, batch, revision, operations, replay
