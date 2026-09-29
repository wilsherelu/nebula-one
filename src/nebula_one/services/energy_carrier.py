from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..analysis.energy_carrier import EnergyCarrierSolved, build_energy_carrier_solved
from ..analysis.energy_carrier_visual import render_energy_carrier_series_svg
from ..database import Database
from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..runtime_models import EnergyCarrierResult, SolvedSystemSnapshot
from ..runtime_schemas import (
    EnergyCarrierResultCreate,
    SolvedSystemSnapshotOut,
)


CAPABILITY_KEY = "energy.carrier.solved.v1"


class EnergyCarrierResultService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _require_snapshot(db, solved_snapshot_id: str) -> SolvedSystemSnapshot:
        snapshot = db.get(SolvedSystemSnapshot, solved_snapshot_id)
        if snapshot is None:
            raise DomainError(
                code="SOLVED_SNAPSHOT_NOT_FOUND",
                message=f"solved snapshot not found: {solved_snapshot_id}",
                status_code=404,
            )
        return snapshot

    def create(
        self,
        solved_snapshot_id: str,
        payload: EnergyCarrierResultCreate,
    ) -> EnergyCarrierResult:
        with self.database.session() as db:
            snapshot = self._require_snapshot(db, solved_snapshot_id)
            snapshot_payload = SolvedSystemSnapshotOut.model_validate(snapshot).model_dump(
                mode="json"
            )
            result = build_energy_carrier_solved(
                solved_snapshot=snapshot_payload,
                direct_exchange_ids=payload.direct_exchange_ids,
                conversions=payload.conversions,
            )
            request_basis = {
                "capability_key": CAPABILITY_KEY,
                "solved_snapshot_content_sha256": snapshot.content_sha256,
                "direct_exchange_ids": list(payload.direct_exchange_ids),
                "conversions": [
                    item.model_dump(mode="json") for item in payload.conversions
                ],
            }
            request_sha256 = canonical_json_sha256(request_basis)
            content_sha256 = canonical_json_sha256(
                {
                    "capability_key": CAPABILITY_KEY,
                    "solved_snapshot_content_sha256": snapshot.content_sha256,
                    "request_sha256": request_sha256,
                    "result_content_sha256": result.content_sha256,
                }
            )
            existing = db.scalar(
                select(EnergyCarrierResult).where(
                    EnergyCarrierResult.solved_snapshot_id == solved_snapshot_id,
                    EnergyCarrierResult.request_sha256 == request_sha256,
                )
            )
            if existing is not None:
                if existing.content_sha256 != content_sha256:
                    raise DomainError(
                        code="ENERGY_CARRIER_RESULT_CONFLICT",
                        message="the same energy request produced different frozen content",
                        status_code=409,
                    )
                return existing
            record = EnergyCarrierResult(
                application_id=snapshot.application_id,
                solved_snapshot_id=solved_snapshot_id,
                request_sha256=request_sha256,
                result_json=result.model_dump(mode="json"),
                content_sha256=content_sha256,
            )
            db.add(record)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                existing = db.scalar(
                    select(EnergyCarrierResult).where(
                        EnergyCarrierResult.solved_snapshot_id == solved_snapshot_id,
                        EnergyCarrierResult.request_sha256 == request_sha256,
                    )
                )
                if existing is not None and existing.content_sha256 == content_sha256:
                    return existing
                raise DomainError(
                    code="ENERGY_CARRIER_RESULT_CONFLICT",
                    message="the energy result request conflicts with persisted content",
                    status_code=409,
                ) from exc
            db.refresh(record)
            return record

    def list_for_snapshot(self, solved_snapshot_id: str) -> list[EnergyCarrierResult]:
        with self.database.session() as db:
            self._require_snapshot(db, solved_snapshot_id)
            return list(
                db.scalars(
                    select(EnergyCarrierResult)
                    .where(EnergyCarrierResult.solved_snapshot_id == solved_snapshot_id)
                    .order_by(EnergyCarrierResult.created_at, EnergyCarrierResult.id)
                )
            )

    def get(self, result_id: str) -> EnergyCarrierResult:
        with self.database.session() as db:
            result = db.get(EnergyCarrierResult, result_id)
            if result is None:
                raise DomainError(
                    code="ENERGY_CARRIER_RESULT_NOT_FOUND",
                    message=f"energy carrier result not found: {result_id}",
                    status_code=404,
                )
            return result

    def chart_svg(self, result_id: str) -> str:
        result = self.get(result_id)
        return render_energy_carrier_series_svg(
            EnergyCarrierSolved.model_validate(result.result_json)
        )
