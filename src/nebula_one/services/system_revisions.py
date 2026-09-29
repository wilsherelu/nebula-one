from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..adapters.nebula_lca import NebulaLCAClient
from ..database import Database
from ..domain.operations import apply_operation
from ..errors import DomainError
from ..hashing import (
    canonical_content_sha256,
    canonical_graph_sha256,
    canonical_json_sha256,
)
from ..models import (
    Application,
    ModelOperation,
    OperationBatch,
    SystemModel,
    SystemRevision,
    new_id,
)
from ..schemas import (
    ModelOperationBatchCreate,
    ModelOperationCreate,
    PublishRevisionRequest,
)


class SystemRevisionService:
    def __init__(self, database: Database, client: NebulaLCAClient) -> None:
        self.database = database
        self.client = client

    def get(self, revision_id: str) -> SystemRevision:
        with self.database.session() as db:
            revision = db.get(SystemRevision, revision_id)
            if revision is None:
                raise DomainError(
                    code="SYSTEM_REVISION_NOT_FOUND",
                    message=f"system revision not found: {revision_id}",
                    status_code=404,
                )
            return revision

    def list_for_system_model(self, system_model_id: str) -> list[SystemRevision]:
        with self.database.session() as db:
            if db.get(SystemModel, system_model_id) is None:
                raise DomainError(
                    code="SYSTEM_MODEL_NOT_FOUND",
                    message=f"system model not found: {system_model_id}",
                    status_code=404,
                )
            statement = (
                select(SystemRevision)
                .where(SystemRevision.system_model_id == system_model_id)
                .order_by(SystemRevision.revision_number)
            )
            return list(db.scalars(statement))

    def apply(
        self, system_model_id: str, payload: ModelOperationCreate
    ) -> tuple[SystemRevision, ModelOperation]:
        with self.database.session() as db:
            system_model = db.get(SystemModel, system_model_id)
            if system_model is None:
                raise DomainError(
                    code="SYSTEM_MODEL_NOT_FOUND",
                    message=f"system model not found: {system_model_id}",
                    status_code=404,
                )
            application = db.get(Application, system_model.application_id)
            if application and application.context.get("template_locked"):
                raise DomainError(code="PROJECT_TEMPLATE_LOCKED", message="项目工艺结构已固定，请通过生产数据表填写允许修改的参数。", status_code=409)
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
            graph, context, target_kind, target_id = apply_operation(
                parent.graph_snapshot,
                parent.application_context,
                payload.operation_type,
                payload.payload,
            )
            graph_sha256 = canonical_graph_sha256(graph)
            content_sha256 = canonical_content_sha256(graph, context)
            next_number = (
                db.scalar(
                    select(func.max(SystemRevision.revision_number)).where(
                        SystemRevision.system_model_id == system_model_id
                    )
                )
                or 0
            ) + 1
            revision = SystemRevision(
                id=new_id(),
                system_model_id=system_model_id,
                parent_revision_id=parent.id,
                revision_number=next_number,
                label=payload.label,
                revision_kind="operation",
                graph_sha256=graph_sha256,
                content_sha256=content_sha256,
                graph_snapshot=graph,
                application_context=context,
                status="draft",
            )
            operation = ModelOperation(
                id=new_id(),
                system_revision_id=revision.id,
                operation_batch_id=None,
                batch_sequence=0,
                operation_type=payload.operation_type,
                target_kind=target_kind,
                target_id=target_id,
                payload=payload.payload,
                before_content_sha256=parent.content_sha256,
                after_content_sha256=content_sha256,
            )
            db.add_all((revision, operation))
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise DomainError(
                    code="SYSTEM_REVISION_CONFLICT",
                    message="a concurrent operation created the same revision number; retry the operation",
                    status_code=409,
                ) from exc
            db.refresh(revision)
            db.refresh(operation)
            return revision, operation

    def apply_batch(
        self, system_model_id: str, payload: ModelOperationBatchCreate, *, template_input: bool = False
    ) -> tuple[OperationBatch, SystemRevision, list[ModelOperation], bool]:
        request_sha256 = canonical_json_sha256(
            payload.model_dump(mode="json", exclude={"idempotency_key"})
        )
        with self.database.session() as db:
            system_model = db.get(SystemModel, system_model_id)
            if system_model is None:
                raise DomainError(
                    code="SYSTEM_MODEL_NOT_FOUND",
                    message=f"system model not found: {system_model_id}",
                    status_code=404,
                )
            existing = db.scalar(
                select(OperationBatch).where(
                    OperationBatch.system_model_id == system_model_id,
                    OperationBatch.idempotency_key == payload.idempotency_key,
                )
            )
            application = db.get(Application, system_model.application_id)
            if application and application.context.get("template_locked") and not template_input:
                raise DomainError(code="PROJECT_TEMPLATE_LOCKED", message="项目工艺结构已固定，请通过生产数据表填写允许修改的参数。", status_code=409)
            if existing is not None:
                if existing.request_sha256 != request_sha256:
                    raise DomainError(
                        code="OPERATION_IDEMPOTENCY_CONFLICT",
                        message="idempotency key was already used with a different request",
                        status_code=409,
                        details={"idempotency_key": payload.idempotency_key},
                    )
                revision = db.get(SystemRevision, existing.final_revision_id)
                assert revision is not None
                operations = list(
                    db.scalars(
                        select(ModelOperation)
                        .where(ModelOperation.operation_batch_id == existing.id)
                        .order_by(ModelOperation.batch_sequence)
                    )
                )
                return existing, revision, operations, True

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

            graph = parent.graph_snapshot
            context = parent.application_context
            before_hash = parent.content_sha256
            operation_specs: list[dict] = []
            for sequence, item in enumerate(payload.operations, start=1):
                graph, context, target_kind, target_id = apply_operation(
                    graph, context, item.operation_type, item.payload
                )
                after_hash = canonical_content_sha256(graph, context)
                operation_specs.append(
                    {
                        "sequence": sequence,
                        "operation_type": item.operation_type,
                        "target_kind": target_kind,
                        "target_id": target_id,
                        "payload": item.payload,
                        "before_hash": before_hash,
                        "after_hash": after_hash,
                    }
                )
                before_hash = after_hash

            next_number = (
                db.scalar(
                    select(func.max(SystemRevision.revision_number)).where(
                        SystemRevision.system_model_id == system_model_id
                    )
                )
                or 0
            ) + 1
            batch_id = new_id()
            revision = SystemRevision(
                id=new_id(),
                system_model_id=system_model_id,
                parent_revision_id=parent.id,
                revision_number=next_number,
                label=payload.label,
                revision_kind="operation_batch",
                graph_sha256=canonical_graph_sha256(graph),
                content_sha256=before_hash,
                graph_snapshot=graph,
                application_context=context,
                status="draft",
            )
            batch = OperationBatch(
                id=batch_id,
                system_model_id=system_model_id,
                parent_revision_id=parent.id,
                final_revision_id=revision.id,
                idempotency_key=payload.idempotency_key,
                request_sha256=request_sha256,
            )
            operations = [
                ModelOperation(
                    id=new_id(),
                    system_revision_id=revision.id,
                    operation_batch_id=batch_id,
                    batch_sequence=spec["sequence"],
                    operation_type=spec["operation_type"],
                    target_kind=spec["target_kind"],
                    target_id=spec["target_id"],
                    payload=spec["payload"],
                    before_content_sha256=spec["before_hash"],
                    after_content_sha256=spec["after_hash"],
                )
                for spec in operation_specs
            ]
            try:
                db.add(revision)
                db.flush()
                db.add(batch)
                db.flush()
                db.add_all(operations)
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise DomainError(
                    code="OPERATION_BATCH_CONFLICT",
                    message="operation batch conflicted with a concurrent write; retry with the same idempotency key",
                    status_code=409,
                ) from exc
            db.refresh(revision)
            db.refresh(batch)
            for operation in operations:
                db.refresh(operation)
            return batch, revision, operations, False

    def list_operations(self, revision_id: str) -> list[ModelOperation]:
        with self.database.session() as db:
            if db.get(SystemRevision, revision_id) is None:
                raise DomainError(
                    code="SYSTEM_REVISION_NOT_FOUND",
                    message=f"system revision not found: {revision_id}",
                    status_code=404,
                )
            statement = (
                select(ModelOperation)
                .where(ModelOperation.system_revision_id == revision_id)
                .order_by(ModelOperation.batch_sequence, ModelOperation.created_at)
            )
            return list(db.scalars(statement))

    def publish(
        self, revision_id: str, payload: PublishRevisionRequest
    ) -> SystemRevision:
        if payload.confirm_upstream_write is not True:
            raise DomainError(
                code="UPSTREAM_WRITE_CONFIRMATION_REQUIRED",
                message="publishing creates a new Nebula LCA model version and requires explicit confirmation",
                status_code=409,
            )
        with self.database.session() as db:
            revision = db.get(SystemRevision, revision_id)
            if revision is None:
                raise DomainError(
                    code="SYSTEM_REVISION_NOT_FOUND",
                    message=f"system revision not found: {revision_id}",
                    status_code=404,
                )
            system_model = db.get(SystemModel, revision.system_model_id)
            assert system_model is not None
            if revision.status == "published":
                raise DomainError(
                    code="SYSTEM_REVISION_ALREADY_PUBLISHED",
                    message=f"system revision is already published: {revision_id}",
                    status_code=409,
                    details={"publish_receipt": revision.publish_receipt},
                )
            if system_model.provider_base_url.rstrip("/") != self.client.base_url:
                raise DomainError(
                    code="MODEL_PROVIDER_CONNECTION_CHANGED",
                    message="the configured Nebula LCA connection differs from the model pin source",
                    status_code=409,
                    details={
                        "pinned_base_url": system_model.provider_base_url,
                        "configured_base_url": self.client.base_url,
                    },
                )
            project_id = system_model.upstream_project_id
            graph = dict(revision.graph_snapshot)
            graph_sha256 = revision.graph_sha256

        upstream = self.client.create_model_version(
            project_id=project_id,
            graph=graph,
            compile_pts_on_save=payload.compile_pts_on_save,
        )
        returned_project_id = str(upstream.payload.get("project_id") or "").strip()
        returned_version = upstream.payload.get("version")
        if returned_project_id != project_id or not isinstance(returned_version, int) or returned_version <= 0:
            raise DomainError(
                code="UPSTREAM_VERSION_RECEIPT_INVALID",
                message="Nebula LCA returned an invalid model-version receipt",
                status_code=502,
                details={
                    "expected_project_id": project_id,
                    "returned_project_id": returned_project_id,
                    "returned_version": returned_version,
                },
            )
        receipt = {
            "provider": "nebula_lca",
            "endpoint": f"/api/projects/{project_id}/versions",
            "base_url": self.client.base_url,
            "project_id": returned_project_id,
            "version": returned_version,
            "created_new_version": upstream.payload.get("created_new_version"),
            "graph_sha256": graph_sha256,
            "upstream_graph_hash": upstream.payload.get("graph_hash"),
            "graph_repair_count": upstream.payload.get("graph_repair_count"),
            "compile_pts_on_save": payload.compile_pts_on_save,
            "etag": upstream.etag,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.database.session() as db:
            revision = db.get(SystemRevision, revision_id)
            assert revision is not None
            if revision.status == "published":
                raise DomainError(
                    code="SYSTEM_REVISION_ALREADY_PUBLISHED",
                    message=f"system revision is already published: {revision_id}",
                    status_code=409,
                    details={"publish_receipt": revision.publish_receipt},
                )
            revision.status = "published"
            revision.publish_receipt = receipt
            revision.published_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(revision)
            return revision
