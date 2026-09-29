from __future__ import annotations

from sqlalchemy import select

from ..database import Database
from ..errors import DomainError
from ..models import Application
from ..profiles import ApplicationProfiles
from ..release_resources import internal_application_ids
from ..schemas import ApplicationCreate


class ApplicationService:
    def __init__(self, database: Database, profiles: ApplicationProfiles) -> None:
        self.database = database
        self.profiles = profiles

    def create(
        self, payload: ApplicationCreate, *, application_id: str | None = None
    ) -> Application:
        self.profiles.require(payload.application_type)
        columns: dict[str, object] = {
            "name": payload.name,
            "application_type": payload.application_type,
            "description": payload.description,
            "context": payload.context,
        }
        # passing id=None would count as an explicit NULL and skip the generated default
        if application_id is not None:
            columns["id"] = application_id
        record = Application(**columns)
        with self.database.session() as db:
            db.add(record)
            db.commit()
            db.refresh(record)
            return record

    def list(self) -> list[Application]:
        """Projects a person works on; a seed and its modeling source are reached by id instead."""
        with self.database.session() as db:
            internal = internal_application_ids(db)
            records = db.scalars(select(Application).order_by(Application.created_at.desc()))
            return [record for record in records if record.id not in internal]

    def get(self, application_id: str) -> Application:
        with self.database.session() as db:
            record = db.get(Application, application_id)
            if record is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {application_id}",
                    status_code=404,
                )
            return record
