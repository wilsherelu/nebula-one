from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..runtime_models import (
    BoundaryDefinition,
    Entity,
    EntityModelBinding,
    MethodPackage,
    Period,
)
from ..runtime_schemas import (
    BoundaryDefinitionCreate,
    EntityCreate,
    EntityModelBindingCreate,
    MethodPackageCreate,
    PeriodCreate,
)
from .runtime_support import (
    method_ref,
    require_application,
    require_entity,
    require_method_package,
    require_period,
    require_process_ids,
    require_revision,
)


class RegistryService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_entity(self, application_id: str, payload: EntityCreate) -> Entity:
        with self.database.session() as db:
            require_application(db, application_id)
            if payload.parent_id:
                require_entity(db, payload.parent_id, application_id)
            record = Entity(
                application_id=application_id,
                parent_id=payload.parent_id,
                entity_type=payload.entity_type,
                name=payload.name,
                external_id=payload.external_id,
                attributes=payload.attributes,
            )
            db.add(record)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise DomainError(
                    code="ENTITY_EXTERNAL_ID_CONFLICT",
                    message="entity external_id already exists in this application",
                    status_code=409,
                ) from exc
            db.refresh(record)
            return record

    def list_entities(self, application_id: str) -> list[Entity]:
        with self.database.session() as db:
            require_application(db, application_id)
            return list(
                db.scalars(
                    select(Entity)
                    .where(Entity.application_id == application_id)
                    .order_by(Entity.created_at)
                )
            )

    def create_period(self, application_id: str, payload: PeriodCreate) -> Period:
        with self.database.session() as db:
            require_application(db, application_id)
            record = Period(application_id=application_id, **payload.model_dump())
            db.add(record)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise DomainError(
                    code="PERIOD_KEY_CONFLICT",
                    message="period key already exists in this application",
                    status_code=409,
                ) from exc
            db.refresh(record)
            return record

    def list_periods(self, application_id: str) -> list[Period]:
        with self.database.session() as db:
            require_application(db, application_id)
            return list(
                db.scalars(
                    select(Period)
                    .where(Period.application_id == application_id)
                    .order_by(Period.start_date, Period.key)
                )
            )

    def find_period(self, application_id: str, key: str) -> Period | None:
        with self.database.session() as db:
            return db.scalar(
                select(Period).where(
                    Period.application_id == application_id, Period.key == key
                )
            )

    def register_method_package(self, payload: MethodPackageCreate) -> MethodPackage:
        content = payload.model_dump(mode="json")
        record = MethodPackage(
            package_id=payload.package_id,
            version=payload.version,
            package_kind=payload.package_kind,
            jurisdiction=payload.jurisdiction,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            manifest=payload.manifest,
            content_sha256=canonical_json_sha256(content),
            status="registered",
        )
        with self.database.session() as db:
            db.add(record)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                existing = db.scalar(
                    select(MethodPackage).where(
                        MethodPackage.package_id == payload.package_id,
                        MethodPackage.version == payload.version,
                    )
                )
                raise DomainError(
                    code="METHOD_PACKAGE_VERSION_CONFLICT",
                    message="method package version already exists",
                    status_code=409,
                    details={
                        "reference": method_ref(payload.package_id, payload.version),
                        "existing_content_sha256": existing.content_sha256 if existing else None,
                    },
                ) from exc
            db.refresh(record)
            return record

    def list_method_packages(self) -> list[MethodPackage]:
        with self.database.session() as db:
            return list(
                db.scalars(
                    select(MethodPackage).order_by(
                        MethodPackage.package_id, MethodPackage.version
                    )
                )
            )

    def find_method_package(self, package_id: str, version: str) -> MethodPackage | None:
        with self.database.session() as db:
            return db.scalar(
                select(MethodPackage).where(
                    MethodPackage.package_id == package_id,
                    MethodPackage.version == version,
                )
            )

    def create_boundary(
        self, application_id: str, payload: BoundaryDefinitionCreate
    ) -> BoundaryDefinition:
        with self.database.session() as db:
            require_application(db, application_id)
            for entity_id in payload.included_entity_ids:
                require_entity(db, entity_id, application_id)
            if payload.period_id:
                require_period(db, payload.period_id, application_id)
            if payload.method_package_ref:
                require_method_package(db, payload.method_package_ref)
            record = BoundaryDefinition(
                application_id=application_id,
                **payload.model_dump(),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    def list_boundaries(self, application_id: str) -> list[BoundaryDefinition]:
        with self.database.session() as db:
            require_application(db, application_id)
            return list(
                db.scalars(
                    select(BoundaryDefinition)
                    .where(BoundaryDefinition.application_id == application_id)
                    .order_by(BoundaryDefinition.created_at)
                )
            )

    def freeze_boundary(self, boundary_id: str) -> BoundaryDefinition:
        with self.database.session() as db:
            boundary = db.get(BoundaryDefinition, boundary_id)
            if boundary is None:
                raise DomainError(
                    code="BOUNDARY_NOT_FOUND",
                    message=f"boundary not found: {boundary_id}",
                    status_code=404,
                )
            if boundary.status == "frozen":
                return boundary
            if not any(
                (
                    boundary.included_entity_ids,
                    boundary.included_process_ids,
                    boundary.included_flow_rules,
                    boundary.geographic_scope,
                )
            ):
                raise DomainError(
                    code="BOUNDARY_SCOPE_EMPTY",
                    message="boundary must include an entity, process, flow rule or geographic scope",
                    status_code=422,
                )
            content = {
                "name": boundary.name,
                "boundary_type": boundary.boundary_type,
                "included_entity_ids": boundary.included_entity_ids,
                "included_process_ids": boundary.included_process_ids,
                "included_flow_rules": boundary.included_flow_rules,
                "excluded_items": boundary.excluded_items,
                "consolidation_policy": boundary.consolidation_policy,
                "period_id": boundary.period_id,
                "geographic_scope": boundary.geographic_scope,
                "method_package_ref": boundary.method_package_ref,
            }
            boundary.content_sha256 = canonical_json_sha256(content)
            boundary.status = "frozen"
            boundary.frozen_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(boundary)
            return boundary

    def create_binding(
        self, application_id: str, payload: EntityModelBindingCreate
    ) -> EntityModelBinding:
        with self.database.session() as db:
            require_application(db, application_id)
            require_entity(db, payload.entity_id, application_id)
            revision, _ = require_revision(db, payload.system_revision_id, application_id)
            if payload.period_id:
                require_period(db, payload.period_id, application_id)
            if payload.allocation_rule_ref:
                require_method_package(db, payload.allocation_rule_ref)
            require_process_ids(revision, payload.process_ids)
            if not payload.process_ids and not payload.flow_selectors:
                raise DomainError(
                    code="ENTITY_MODEL_BINDING_EMPTY",
                    message="binding requires process_ids or flow_selectors",
                    status_code=422,
                )
            content = payload.model_dump(mode="json")
            record = EntityModelBinding(
                **payload.model_dump(),
                content_sha256=canonical_json_sha256(content),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    def list_bindings(self, application_id: str) -> list[EntityModelBinding]:
        with self.database.session() as db:
            require_application(db, application_id)
            entity_ids = select(Entity.id).where(Entity.application_id == application_id)
            return list(
                db.scalars(
                    select(EntityModelBinding)
                    .where(EntityModelBinding.entity_id.in_(entity_ids))
                    .order_by(EntityModelBinding.created_at)
                )
            )
