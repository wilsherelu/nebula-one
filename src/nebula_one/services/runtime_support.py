from __future__ import annotations

from sqlalchemy.orm import Session

from ..errors import DomainError
from ..models import Application, SystemModel, SystemRevision
from ..runtime_models import Entity, MethodPackage, Period


def require_application(db: Session, application_id: str) -> Application:
    application = db.get(Application, application_id)
    if application is None:
        raise DomainError(
            code="APPLICATION_NOT_FOUND",
            message=f"application not found: {application_id}",
            status_code=404,
        )
    return application


def require_entity(db: Session, entity_id: str, application_id: str) -> Entity:
    entity = db.get(Entity, entity_id)
    if entity is None:
        raise DomainError(
            code="ENTITY_NOT_FOUND",
            message=f"entity not found: {entity_id}",
            status_code=404,
        )
    if entity.application_id != application_id:
        raise DomainError(
            code="ENTITY_APPLICATION_MISMATCH",
            message="entity does not belong to the requested application",
            status_code=409,
        )
    return entity


def require_period(db: Session, period_id: str, application_id: str) -> Period:
    period = db.get(Period, period_id)
    if period is None:
        raise DomainError(
            code="PERIOD_NOT_FOUND",
            message=f"period not found: {period_id}",
            status_code=404,
        )
    if period.application_id != application_id:
        raise DomainError(
            code="PERIOD_APPLICATION_MISMATCH",
            message="period does not belong to the requested application",
            status_code=409,
        )
    return period


def require_revision(
    db: Session, revision_id: str, application_id: str
) -> tuple[SystemRevision, SystemModel]:
    revision = db.get(SystemRevision, revision_id)
    if revision is None:
        raise DomainError(
            code="SYSTEM_REVISION_NOT_FOUND",
            message=f"system revision not found: {revision_id}",
            status_code=404,
        )
    system_model = db.get(SystemModel, revision.system_model_id)
    assert system_model is not None
    if system_model.application_id != application_id:
        raise DomainError(
            code="SYSTEM_REVISION_APPLICATION_MISMATCH",
            message="system revision does not belong to the requested application",
            status_code=409,
        )
    return revision, system_model


def method_ref(package_id: str, version: str) -> str:
    return f"{package_id}@{version}"


def require_method_package(db: Session, reference: str) -> MethodPackage:
    if "@" not in reference:
        raise DomainError(
            code="METHOD_PACKAGE_REF_INVALID",
            message=f"method package reference must be package_id@version: {reference}",
            status_code=422,
        )
    package_id, version = reference.rsplit("@", 1)
    package_id = package_id.strip()
    version = version.strip()
    if not package_id or not version:
        raise DomainError(
            code="METHOD_PACKAGE_REF_INVALID",
            message=f"method package reference must be package_id@version: {reference}",
            status_code=422,
        )
    from sqlalchemy import select

    package = db.scalar(
        select(MethodPackage).where(
            MethodPackage.package_id == package_id,
            MethodPackage.version == version,
        )
    )
    if package is None:
        raise DomainError(
            code="METHOD_PACKAGE_NOT_FOUND",
            message=f"method package not found: {reference}",
            status_code=404,
        )
    return package


def require_process_ids(revision: SystemRevision, process_ids: list[str]) -> None:
    graph_ids = {
        str(node.get("id") or "").strip()
        for node in revision.graph_snapshot.get("nodes") or []
        if isinstance(node, dict)
    }
    missing = sorted(set(process_ids).difference(graph_ids))
    if missing:
        raise DomainError(
            code="BOUND_PROCESS_NOT_FOUND",
            message="one or more process IDs are absent from the selected system revision",
            status_code=422,
            details={"missing_process_ids": missing},
        )


def is_ancestor(db: Session, ancestor_id: str, revision: SystemRevision) -> bool:
    cursor: SystemRevision | None = revision
    visited: set[str] = set()
    while cursor is not None and cursor.id not in visited:
        if cursor.id == ancestor_id:
            return True
        visited.add(cursor.id)
        cursor = (
            db.get(SystemRevision, cursor.parent_revision_id)
            if cursor.parent_revision_id
            else None
        )
    return False
