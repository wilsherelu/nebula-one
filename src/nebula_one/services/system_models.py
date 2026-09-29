from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..adapters.nebula_lca import NebulaLCAClient, same_pinned_model
from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_content_sha256, canonical_graph_sha256
from ..models import Application, SystemModel, SystemRevision, new_id
from ..schemas import InlineSystemModelCreate, SystemModelCreate

class SystemModelService:
    def __init__(self, database: Database, client: NebulaLCAClient) -> None:
        self.database = database
        self.client = client

    def attach(
        self,
        application_id: str,
        payload: SystemModelCreate,
        *,
        expected_graph_sha256: str | None = None,
    ) -> SystemModel:
        if payload.provider != "nebula_lca":
            raise DomainError(
                code="MODEL_PROVIDER_NOT_SUPPORTED",
                message=f"model provider is not supported: {payload.provider}",
                status_code=422,
                details={"supported_providers": ["nebula_lca"]},
            )
        with self.database.session() as db:
            application = db.get(Application, application_id)
            if application is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {application_id}",
                    status_code=404,
                )
            application_context = dict(application.context)
            if application_context.get("template_locked"):
                raise DomainError(code="PROJECT_TEMPLATE_LOCKED", message="项目已固定工艺模板，不能直接替换模型。请创建新项目。", status_code=409)

        upstream = self.client.get_model_version(
            payload.upstream_project_id, payload.upstream_version
        )
        graph = upstream.payload["graph"]
        graph_hash = canonical_graph_sha256(graph)
        if expected_graph_sha256 is not None and graph_hash != expected_graph_sha256:
            raise DomainError(
                code="MODEL_SOURCE_GRAPH_HASH_MISMATCH",
                message="exact model version differs from the confirmed provider snapshot",
                status_code=409,
                details={
                    "expected_graph_sha256": expected_graph_sha256,
                    "actual_graph_sha256": graph_hash,
                },
            )
        receipt = {
            "provider": "nebula_lca",
            "endpoint": f"/api/projects/{payload.upstream_project_id}/versions/{payload.upstream_version}",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "etag": upstream.etag,
            "upstream_created_at": upstream.payload.get("created_at"),
            "source_policy": upstream.payload.get("source_policy"),
            "allowed_lcia_scope": upstream.payload.get("allowed_lcia_scope"),
            "functional_unit": graph.get("functionalUnit", graph.get("functional_unit")),
            "node_count": len(graph.get("nodes") or []),
            "exchange_count": len(graph.get("exchanges") or []),
        }
        system_model_id = new_id()
        base_revision_id = new_id()
        receipt["base_revision_id"] = base_revision_id
        record = SystemModel(
            id=system_model_id,
            application_id=application_id,
            name=payload.name,
            provider="nebula_lca",
            provider_base_url=self.client.base_url,
            upstream_project_id=payload.upstream_project_id,
            upstream_version=payload.upstream_version,
            graph_sha256=graph_hash,
            graph_snapshot=graph,
            upstream_receipt=receipt,
        )
        base_revision = SystemRevision(
            id=base_revision_id,
            system_model_id=system_model_id,
            parent_revision_id=None,
            revision_number=1,
            label=f"Imported Nebula LCA v{payload.upstream_version}",
            revision_kind="base",
            graph_sha256=graph_hash,
            content_sha256=canonical_content_sha256(graph, application_context),
            graph_snapshot=graph,
            application_context=application_context,
            status="draft",
        )
        with self.database.session() as db:
            existing = db.scalar(
                select(SystemModel).where(
                    SystemModel.application_id == application_id,
                    SystemModel.provider == "nebula_lca",
                    SystemModel.upstream_project_id == payload.upstream_project_id,
                    SystemModel.upstream_version == payload.upstream_version,
                )
            )
            if existing is not None:
                if existing.graph_sha256 != graph_hash and not same_pinned_model(
                    existing.graph_snapshot or {}, graph
                ):
                    raise DomainError(
                        code="UPSTREAM_MODEL_VERSION_MUTATED",
                        message="the same Nebula LCA project/version now returns a different graph snapshot",
                        status_code=409,
                        details={
                            "existing_graph_sha256": existing.graph_sha256,
                            "returned_graph_sha256": graph_hash,
                        },
                    )
                raise DomainError(
                    code="SYSTEM_MODEL_PIN_ALREADY_ATTACHED",
                    message="the exact Nebula LCA model pin is already attached to this application",
                    status_code=409,
                    details={
                        "application_id": application_id,
                        "upstream_project_id": payload.upstream_project_id,
                        "upstream_version": payload.upstream_version,
                        "graph_sha256": graph_hash,
                    },
                )
            db.add(record)
            db.add(base_revision)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise DomainError(
                    code="SYSTEM_MODEL_PIN_ALREADY_ATTACHED",
                    message="the exact Nebula LCA model pin is already attached to this application",
                    status_code=409,
                    details={
                        "application_id": application_id,
                        "upstream_project_id": payload.upstream_project_id,
                        "upstream_version": payload.upstream_version,
                    },
                ) from exc
            db.refresh(record)
            return record

    def attach_inline(
        self, application_id: str, payload: InlineSystemModelCreate
    ) -> SystemModel:
        if payload.provider != "nebula_lca":
            raise DomainError(
                code="MODEL_PROVIDER_NOT_SUPPORTED",
                message=f"model provider is not supported: {payload.provider}",
                status_code=422,
                details={"supported_providers": ["nebula_lca"]},
            )
        graph = payload.graph
        if not isinstance(graph.get("nodes"), list) or not isinstance(
            graph.get("exchanges"), list
        ):
            raise DomainError(
                code="INLINE_MODEL_GRAPH_INVALID",
                message="inline model graph must include nodes and exchanges lists",
                status_code=422,
            )
        graph_hash = canonical_graph_sha256(graph)
        if graph_hash != payload.expected_graph_sha256:
            raise DomainError(
                code="INLINE_MODEL_HASH_MISMATCH",
                message="inline model graph does not match expected_graph_sha256",
                status_code=409,
                details={
                    "expected_graph_sha256": payload.expected_graph_sha256,
                    "actual_graph_sha256": graph_hash,
                },
            )
        with self.database.session() as db:
            application = db.get(Application, application_id)
            if application is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {application_id}",
                    status_code=404,
                )
            application_context = dict(application.context)

        if application_context.get("template_locked"):
            raise DomainError(code="PROJECT_TEMPLATE_LOCKED", message="项目已固定工艺模板，不能直接替换模型。请创建新项目。", status_code=409)
        system_model_id = new_id()
        base_revision_id = new_id()
        receipt = {
            "provider": "nebula_lca",
            "source_kind": "inline_casepack",
            "source_id": payload.source_id,
            "source_version": payload.source_version,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "functional_unit": graph.get(
                "functionalUnit", graph.get("functional_unit")
            ),
            "node_count": len(graph["nodes"]),
            "exchange_count": len(graph["exchanges"]),
            "graph_sha256": graph_hash,
            "base_revision_id": base_revision_id,
        }
        record = SystemModel(
            id=system_model_id,
            application_id=application_id,
            name=payload.name,
            provider="nebula_lca",
            provider_base_url=self.client.base_url,
            upstream_project_id=payload.source_id,
            upstream_version=payload.source_version,
            graph_sha256=graph_hash,
            graph_snapshot=graph,
            upstream_receipt=receipt,
        )
        base_revision = SystemRevision(
            id=base_revision_id,
            system_model_id=system_model_id,
            parent_revision_id=None,
            revision_number=1,
            label=f"Imported inline CasePack v{payload.source_version}",
            revision_kind="base",
            graph_sha256=graph_hash,
            content_sha256=canonical_content_sha256(graph, application_context),
            graph_snapshot=graph,
            application_context=application_context,
            status="draft",
        )
        with self.database.session() as db:
            existing = db.scalar(
                select(SystemModel).where(
                    SystemModel.application_id == application_id,
                    SystemModel.provider == "nebula_lca",
                    SystemModel.upstream_project_id == payload.source_id,
                    SystemModel.upstream_version == payload.source_version,
                )
            )
            if existing is not None:
                if existing.graph_sha256 != graph_hash:
                    raise DomainError(
                        code="INLINE_MODEL_SOURCE_MUTATED",
                        message="the same inline source/version now has different graph content",
                        status_code=409,
                        details={
                            "existing_graph_sha256": existing.graph_sha256,
                            "returned_graph_sha256": graph_hash,
                        },
                    )
                raise DomainError(
                    code="SYSTEM_MODEL_PIN_ALREADY_ATTACHED",
                    message="the exact inline model source is already attached to this application",
                    status_code=409,
                    details={
                        "application_id": application_id,
                        "source_id": payload.source_id,
                        "source_version": payload.source_version,
                        "graph_sha256": graph_hash,
                    },
                )
            db.add(record)
            db.add(base_revision)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise DomainError(
                    code="SYSTEM_MODEL_PIN_ALREADY_ATTACHED",
                    message="the exact inline model source is already attached to this application",
                    status_code=409,
                ) from exc
            db.refresh(record)
            return record

    def get(self, system_model_id: str) -> SystemModel:
        with self.database.session() as db:
            record = db.get(SystemModel, system_model_id)
            if record is None:
                raise DomainError(
                    code="SYSTEM_MODEL_NOT_FOUND",
                    message=f"system model not found: {system_model_id}",
                    status_code=404,
                )
            return record

    def list_for_application(self, application_id: str) -> list[SystemModel]:
        with self.database.session() as db:
            if db.get(Application, application_id) is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {application_id}",
                    status_code=404,
                )
            statement = (
                select(SystemModel)
                .where(SystemModel.application_id == application_id)
                .order_by(SystemModel.created_at.desc())
            )
            return list(db.scalars(statement))
