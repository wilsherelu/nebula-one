from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..models import Application, SystemModel, SystemRevision
from ..runtime_models import (
    BoundaryDefinition,
    Period,
    SolvedSystemSnapshot,
    SystemBinding,
)
from ..schemas import SystemBindingCreate, SystemBindingUpdate


class SystemBindingService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self, application_id: str, payload: SystemBindingCreate
    ) -> SystemBinding:
        with self.database.session() as db:
            self._require_application(db, application_id)
            self._validate_references(
                db,
                application_id=application_id,
                binding_id=payload.binding_id,
                system_model_id=payload.system_model_id,
                system_revision_id=payload.system_revision_id,
                solved_snapshot_id=payload.solved_snapshot_id,
                reporting_period_id=payload.reporting_period_id,
                organizational_boundary_id=payload.organizational_boundary_id,
                dependencies=payload.dependencies,
            )
            record = SystemBinding(
                application_id=application_id,
                **payload.model_dump(),
                content_sha256=self._content_sha256(
                    application_id, payload.binding_id, payload.model_dump(mode="json")
                ),
            )
            db.add(record)
            self._commit(db)
            db.refresh(record)
            return record

    def list_for_application(self, application_id: str) -> list[SystemBinding]:
        with self.database.session() as db:
            self._require_application(db, application_id)
            return list(
                db.scalars(
                    select(SystemBinding)
                    .where(SystemBinding.application_id == application_id)
                    .order_by(SystemBinding.role, SystemBinding.binding_id)
                )
            )

    def get(self, application_id: str, binding_id: str) -> SystemBinding:
        with self.database.session() as db:
            self._require_application(db, application_id)
            return self._require_binding(db, application_id, binding_id)

    def update(
        self,
        application_id: str,
        binding_id: str,
        payload: SystemBindingUpdate,
    ) -> SystemBinding:
        with self.database.session() as db:
            self._require_application(db, application_id)
            record = self._require_binding(db, application_id, binding_id)
            self._validate_references(
                db,
                application_id=application_id,
                binding_id=binding_id,
                system_model_id=payload.system_model_id,
                system_revision_id=payload.system_revision_id,
                solved_snapshot_id=payload.solved_snapshot_id,
                reporting_period_id=payload.reporting_period_id,
                organizational_boundary_id=payload.organizational_boundary_id,
                dependencies=payload.dependencies,
            )
            values = payload.model_dump()
            for field, value in values.items():
                setattr(record, field, value)
            record.content_sha256 = self._content_sha256(
                application_id, binding_id, payload.model_dump(mode="json")
            )
            self._commit(db)
            db.refresh(record)
            return record

    def delete(self, application_id: str, binding_id: str) -> None:
        with self.database.session() as db:
            self._require_application(db, application_id)
            record = self._require_binding(db, application_id, binding_id)
            dependents = [
                item.binding_id
                for item in db.scalars(
                    select(SystemBinding).where(
                        SystemBinding.application_id == application_id
                    )
                )
                if binding_id in item.dependencies
            ]
            if dependents:
                raise DomainError(
                    code="SYSTEM_BINDING_IN_USE",
                    message="system binding is referenced by another binding",
                    status_code=409,
                    details={"dependent_binding_ids": sorted(dependents)},
                )
            db.delete(record)
            db.commit()

    @staticmethod
    def _content_sha256(
        application_id: str, binding_id: str, values: dict
    ) -> str:
        return canonical_json_sha256(
            {
                "application_id": application_id,
                "binding_id": binding_id,
                **values,
            }
        )

    @staticmethod
    def _require_application(db, application_id: str) -> None:
        if db.get(Application, application_id) is None:
            raise DomainError(
                code="APPLICATION_NOT_FOUND",
                message=f"application not found: {application_id}",
                status_code=404,
            )

    @staticmethod
    def _require_binding(db, application_id: str, binding_id: str) -> SystemBinding:
        record = db.scalar(
            select(SystemBinding).where(
                SystemBinding.application_id == application_id,
                SystemBinding.binding_id == binding_id,
            )
        )
        if record is None:
            raise DomainError(
                code="SYSTEM_BINDING_NOT_FOUND",
                message=f"system binding not found: {binding_id}",
                status_code=404,
            )
        return record

    @staticmethod
    def _validate_references(
        db,
        *,
        application_id: str,
        binding_id: str,
        system_model_id: str,
        system_revision_id: str,
        solved_snapshot_id: str,
        reporting_period_id: str,
        organizational_boundary_id: str,
        dependencies: list[str],
    ) -> None:
        references = (
            (SystemModel, system_model_id, "SYSTEM_MODEL"),
            (Period, reporting_period_id, "REPORTING_PERIOD"),
            (
                BoundaryDefinition,
                organizational_boundary_id,
                "ORGANIZATIONAL_BOUNDARY",
            ),
        )
        for model, reference_id, code_prefix in references:
            record = db.get(model, reference_id)
            if record is None:
                raise DomainError(
                    code=f"{code_prefix}_NOT_FOUND",
                    message=f"referenced object not found: {reference_id}",
                    status_code=422,
                )
            if record.application_id != application_id:
                raise DomainError(
                    code=f"{code_prefix}_APPLICATION_MISMATCH",
                    message="referenced object belongs to another application",
                    status_code=422,
                    details={"reference_id": reference_id},
                )
        revision = db.get(SystemRevision, system_revision_id)
        if revision is None:
            raise DomainError(
                code="SYSTEM_REVISION_NOT_FOUND",
                message=f"referenced object not found: {system_revision_id}",
                status_code=422,
            )
        if revision.system_model_id != system_model_id:
            raise DomainError(
                code="SYSTEM_BINDING_REVISION_MODEL_MISMATCH",
                message="system revision does not belong to the bound system model",
                status_code=422,
            )
        snapshot = db.get(SolvedSystemSnapshot, solved_snapshot_id)
        if snapshot is None:
            raise DomainError(
                code="SOLVED_SYSTEM_SNAPSHOT_NOT_FOUND",
                message=f"referenced object not found: {solved_snapshot_id}",
                status_code=422,
            )
        if snapshot.application_id != application_id:
            raise DomainError(
                code="SOLVED_SYSTEM_SNAPSHOT_APPLICATION_MISMATCH",
                message="solved snapshot belongs to another application",
                status_code=422,
            )
        if snapshot.system_revision_id != system_revision_id:
            raise DomainError(
                code="SYSTEM_BINDING_SNAPSHOT_REVISION_MISMATCH",
                message="solved snapshot does not belong to the bound system revision",
                status_code=422,
            )
        if binding_id in dependencies:
            raise DomainError(
                code="SYSTEM_BINDING_SELF_DEPENDENCY",
                message="system binding cannot depend on itself",
                status_code=422,
            )
        if dependencies:
            existing = set(
                db.scalars(
                    select(SystemBinding.binding_id).where(
                        SystemBinding.application_id == application_id,
                        SystemBinding.binding_id.in_(dependencies),
                    )
                )
            )
            missing = sorted(set(dependencies).difference(existing))
            if missing:
                raise DomainError(
                    code="SYSTEM_BINDING_DEPENDENCY_NOT_FOUND",
                    message="system binding dependency does not exist in this application",
                    status_code=422,
                    details={"missing_binding_ids": missing},
                )

    @staticmethod
    def _commit(db) -> None:
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise DomainError(
                code="SYSTEM_BINDING_CONFLICT",
                message="binding_id and role must be unique within an application",
                status_code=409,
            ) from exc
