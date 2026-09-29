from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..models import OutboxEvent


OUTBOX_PENDING = "pending"
OUTBOX_PROCESSING = "processing"
OUTBOX_RETRY_WAIT = "retry_wait"
OUTBOX_COMPLETED = "completed"
OUTBOX_FAILED = "failed"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def enqueue_outbox_event(
    db: Session,
    *,
    topic: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    max_attempts: int = 3,
) -> OutboxEvent:
    if not 1 <= max_attempts <= 20:
        raise DomainError(
            code="OUTBOX_MAX_ATTEMPTS_INVALID",
            message="outbox max_attempts must be between 1 and 20",
            status_code=422,
        )
    payload_sha256 = canonical_json_sha256(payload)
    existing = db.scalar(
        select(OutboxEvent).where(
            OutboxEvent.topic == topic,
            OutboxEvent.aggregate_id == aggregate_id,
        )
    )
    if existing is not None:
        if (
            existing.aggregate_type != aggregate_type
            or existing.payload_sha256 != payload_sha256
        ):
            raise DomainError(
                code="OUTBOX_AGGREGATE_CONFLICT",
                message="outbox topic and aggregate already bind a different payload",
                status_code=409,
                details={
                    "event_id": existing.id,
                    "topic": topic,
                    "aggregate_id": aggregate_id,
                },
            )
        return existing
    event = OutboxEvent(
        topic=topic,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
        payload_sha256=payload_sha256,
        status=OUTBOX_PENDING,
        attempt_count=0,
        max_attempts=max_attempts,
        available_at=utcnow(),
        last_error={},
        result_ref={},
    )
    db.add(event)
    return event


class OutboxService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, event_id: str) -> OutboxEvent:
        with self.database.session() as db:
            event = db.get(OutboxEvent, event_id)
            if event is None:
                raise DomainError(
                    code="OUTBOX_EVENT_NOT_FOUND",
                    message=f"outbox event not found: {event_id}",
                    status_code=404,
                )
            return event

    def get_for_aggregate(self, topic: str, aggregate_id: str) -> OutboxEvent:
        with self.database.session() as db:
            event = db.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.topic == topic,
                    OutboxEvent.aggregate_id == aggregate_id,
                )
            )
            if event is None:
                raise DomainError(
                    code="OUTBOX_EVENT_NOT_FOUND",
                    message="outbox event not found for aggregate",
                    status_code=404,
                    details={"topic": topic, "aggregate_id": aggregate_id},
                )
            return event

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        topics: tuple[str, ...] | None = None,
        now: datetime | None = None,
    ) -> OutboxEvent | None:
        if not worker_id.strip() or len(worker_id) > 128:
            raise DomainError(
                code="OUTBOX_WORKER_ID_INVALID",
                message="worker_id must contain 1 to 128 characters",
                status_code=422,
            )
        if not 1 <= lease_seconds <= 3600:
            raise DomainError(
                code="OUTBOX_LEASE_INVALID",
                message="lease_seconds must be between 1 and 3600",
                status_code=422,
            )
        claim_time = now or utcnow()
        self._fail_exhausted_leases(claim_time, topics)
        eligible = or_(
            and_(
                OutboxEvent.status.in_((OUTBOX_PENDING, OUTBOX_RETRY_WAIT)),
                OutboxEvent.available_at <= claim_time,
            ),
            and_(
                OutboxEvent.status == OUTBOX_PROCESSING,
                OutboxEvent.lease_expires_at.is_not(None),
                OutboxEvent.lease_expires_at <= claim_time,
            ),
        )
        with self.database.session() as db:
            statement = (
                select(OutboxEvent)
                .where(eligible)
                .order_by(OutboxEvent.available_at, OutboxEvent.created_at)
                .limit(1)
            )
            if topics:
                statement = statement.where(OutboxEvent.topic.in_(topics))
            if self.database.engine.dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
            event = db.scalar(statement)
            if event is None:
                return None
            event.status = OUTBOX_PROCESSING
            event.attempt_count += 1
            event.lease_owner = worker_id.strip()
            event.lease_expires_at = claim_time + timedelta(seconds=lease_seconds)
            event.updated_at = claim_time
            db.commit()
            db.refresh(event)
            return event

    def _fail_exhausted_leases(
        self,
        now: datetime,
        topics: tuple[str, ...] | None,
    ) -> None:
        while True:
            with self.database.session() as db:
                statement = (
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.status == OUTBOX_PROCESSING,
                        OutboxEvent.lease_expires_at.is_not(None),
                        OutboxEvent.lease_expires_at <= now,
                        OutboxEvent.attempt_count >= OutboxEvent.max_attempts,
                    )
                    .order_by(OutboxEvent.lease_expires_at)
                    .limit(1)
                )
                if topics:
                    statement = statement.where(OutboxEvent.topic.in_(topics))
                if self.database.engine.dialect.name == "postgresql":
                    statement = statement.with_for_update(skip_locked=True)
                event = db.scalar(statement)
                if event is None:
                    return
                event.status = OUTBOX_FAILED
                event.lease_owner = None
                event.lease_expires_at = None
                event.completed_at = now
                event.updated_at = now
                event.last_error = {
                    "code": "OUTBOX_LEASE_ATTEMPTS_EXHAUSTED",
                    "message": "worker lease expired after the final allowed attempt",
                    "status_code": 500,
                    "details": {"attempt_count": event.attempt_count},
                }
                db.commit()

    def claim_event(
        self,
        event_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> OutboxEvent:
        if not worker_id.strip() or len(worker_id) > 128:
            raise DomainError(
                code="OUTBOX_WORKER_ID_INVALID",
                message="worker_id must contain 1 to 128 characters",
                status_code=422,
            )
        if not 1 <= lease_seconds <= 3600:
            raise DomainError(
                code="OUTBOX_LEASE_INVALID",
                message="lease_seconds must be between 1 and 3600",
                status_code=422,
            )
        claim_time = now or utcnow()
        with self.database.session() as db:
            statement = select(OutboxEvent).where(OutboxEvent.id == event_id)
            if self.database.engine.dialect.name == "postgresql":
                statement = statement.with_for_update()
            event = db.scalar(statement)
            if event is None:
                raise DomainError(
                    code="OUTBOX_EVENT_NOT_FOUND",
                    message=f"outbox event not found: {event_id}",
                    status_code=404,
                )
            if (
                event.status == OUTBOX_PROCESSING
                and event.lease_expires_at is not None
                and _as_utc(event.lease_expires_at) <= claim_time
                and event.attempt_count >= event.max_attempts
            ):
                event.status = OUTBOX_FAILED
                event.lease_owner = None
                event.lease_expires_at = None
                event.completed_at = claim_time
                event.updated_at = claim_time
                event.last_error = {
                    "code": "OUTBOX_LEASE_ATTEMPTS_EXHAUSTED",
                    "message": "worker lease expired after the final allowed attempt",
                    "status_code": 500,
                    "details": {"attempt_count": event.attempt_count},
                }
                db.commit()
                raise DomainError(
                    code="OUTBOX_ATTEMPTS_EXHAUSTED",
                    message="outbox event exhausted its worker lease attempts",
                    status_code=409,
                    details={"event_id": event.id},
                )
            eligible = (
                event.status in {OUTBOX_PENDING, OUTBOX_RETRY_WAIT}
                and _as_utc(event.available_at) <= claim_time
            ) or (
                event.status == OUTBOX_PROCESSING
                and event.lease_expires_at is not None
                and _as_utc(event.lease_expires_at) <= claim_time
            )
            if not eligible:
                raise DomainError(
                    code="OUTBOX_EVENT_NOT_CLAIMABLE",
                    message="outbox event is not currently claimable",
                    status_code=409,
                    details={
                        "event_id": event.id,
                        "status": event.status,
                        "available_at": event.available_at.isoformat(),
                        "lease_expires_at": (
                            event.lease_expires_at.isoformat()
                            if event.lease_expires_at is not None
                            else None
                        ),
                    },
                )
            event.status = OUTBOX_PROCESSING
            event.attempt_count += 1
            event.lease_owner = worker_id.strip()
            event.lease_expires_at = claim_time + timedelta(seconds=lease_seconds)
            event.updated_at = claim_time
            db.commit()
            db.refresh(event)
            return event

    def complete(
        self,
        event_id: str,
        *,
        worker_id: str,
        result_ref: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> OutboxEvent:
        completion_time = now or utcnow()
        with self.database.session() as db:
            event = self._owned_processing_event(db, event_id, worker_id)
            event.status = OUTBOX_COMPLETED
            event.lease_owner = None
            event.lease_expires_at = None
            event.completed_at = completion_time
            event.updated_at = completion_time
            event.result_ref = result_ref or {}
            db.commit()
            db.refresh(event)
            return event

    def fail(
        self,
        event_id: str,
        *,
        worker_id: str,
        error: dict[str, Any],
        retryable: bool,
        now: datetime | None = None,
    ) -> OutboxEvent:
        failure_time = now or utcnow()
        with self.database.session() as db:
            event = self._owned_processing_event(db, event_id, worker_id)
            event.last_error = error
            event.lease_owner = None
            event.lease_expires_at = None
            event.updated_at = failure_time
            if retryable and event.attempt_count < event.max_attempts:
                delay_seconds = min(60, 2 ** max(0, event.attempt_count - 1))
                event.status = OUTBOX_RETRY_WAIT
                event.available_at = failure_time + timedelta(seconds=delay_seconds)
            else:
                event.status = OUTBOX_FAILED
                event.completed_at = failure_time
            db.commit()
            db.refresh(event)
            return event

    @staticmethod
    def _owned_processing_event(
        db: Session, event_id: str, worker_id: str
    ) -> OutboxEvent:
        event = db.get(OutboxEvent, event_id)
        if event is None:
            raise DomainError(
                code="OUTBOX_EVENT_NOT_FOUND",
                message=f"outbox event not found: {event_id}",
                status_code=404,
            )
        if event.status != OUTBOX_PROCESSING or event.lease_owner != worker_id:
            raise DomainError(
                code="OUTBOX_LEASE_OWNERSHIP_MISMATCH",
                message="outbox event is not leased by this worker",
                status_code=409,
                details={
                    "event_id": event.id,
                    "status": event.status,
                    "lease_owner": event.lease_owner,
                },
            )
        return event


class OutboxWorker:
    def __init__(
        self,
        outbox: OutboxService,
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]],
    ) -> None:
        self.outbox = outbox
        self.handlers = handlers

    def process_one(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 30,
        now: datetime | None = None,
    ) -> OutboxEvent | None:
        event = self.outbox.claim_next(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            topics=tuple(sorted(self.handlers)),
            now=now,
        )
        if event is None:
            return None
        handler = self.handlers.get(event.topic)
        assert handler is not None
        try:
            result_ref = handler(dict(event.payload))
        except DomainError as exc:
            return self.outbox.fail(
                event.id,
                worker_id=worker_id,
                retryable=exc.status_code >= 500,
                now=now,
                error={
                    "code": exc.code,
                    "message": exc.message,
                    "status_code": exc.status_code,
                    "details": exc.details,
                },
            )
        except Exception as exc:
            return self.outbox.fail(
                event.id,
                worker_id=worker_id,
                retryable=True,
                now=now,
                error={
                    "code": "OUTBOX_HANDLER_FAILED",
                    "message": "outbox handler failed unexpectedly",
                    "status_code": 500,
                    "details": {"exception_type": type(exc).__name__},
                },
            )
        return self.outbox.complete(
            event.id,
            worker_id=worker_id,
            result_ref=result_ref,
            now=now,
        )
