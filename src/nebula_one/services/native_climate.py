from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..adapters.nebula_lca import native_climate_identity_mismatches
from ..database import Database
from ..errors import DomainError
from ..exports.native_climate import build_native_climate_html, build_native_climate_xlsx
from ..mapped_background_schemas import (
    ProviderNativeBackgroundClimateRequest,
    ProviderNativeBackgroundClimateResponse,
)
from ..runtime_models import SolvedSystemSnapshot

ENVELOPE_SCHEMA_VERSION = "nebula_one.native-background-climate.v1"


class NativeClimateArtifactService:
    """Report and spreadsheet artifacts for one already frozen native climate answer.

    Nothing is re-solved and no method package is chosen here: the artifact is a projection of the
    exact answer the pinned contract returned, so a saved result can be cited after the engine has
    moved on.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def _frozen_answer(
        self, solved_snapshot_id: str
    ) -> tuple[
        SolvedSystemSnapshot,
        dict[str, Any],
        ProviderNativeBackgroundClimateResponse,
        ProviderNativeBackgroundClimateRequest,
    ]:
        with self.database.session() as db:
            snapshot = db.get(SolvedSystemSnapshot, solved_snapshot_id)
            if snapshot is None:
                raise DomainError(
                    code="SOLVED_SYSTEM_SNAPSHOT_NOT_FOUND",
                    message=f"solved system snapshot not found: {solved_snapshot_id}",
                    status_code=404,
                )
            envelope = snapshot.native_background_climate
        if (
            not isinstance(envelope, dict)
            or envelope.get("schema_version") != ENVELOPE_SCHEMA_VERSION
        ):
            raise DomainError(
                code="NATIVE_CLIMATE_ANSWER_REQUIRED",
                message=(
                    "this frozen snapshot carries no native background climate answer; "
                    "run the climate calculation before exporting it"
                ),
                status_code=422,
                details={"solved_snapshot_id": solved_snapshot_id},
            )
        try:
            request = ProviderNativeBackgroundClimateRequest.model_validate(
                envelope.get("request")
            )
            answer = ProviderNativeBackgroundClimateResponse.model_validate(
                envelope.get("response")
            )
        except ValidationError as exc:
            raise DomainError(
                code="NATIVE_CLIMATE_ANSWER_INVALID",
                message="the frozen native background climate answer does not match its contract",
                status_code=422,
                details={
                    "solved_snapshot_id": solved_snapshot_id,
                    "errors": [
                        {
                            "loc": list(error.get("loc") or []),
                            "type": error.get("type"),
                            "message": error.get("msg"),
                        }
                        for error in exc.errors(include_url=False)
                    ],
                },
            ) from exc
        mismatches = native_climate_identity_mismatches(request, answer)
        if mismatches:
            raise DomainError(
                code="NATIVE_CLIMATE_ANSWER_INVALID",
                message=(
                    "the frozen climate answer no longer states the pinned method package it was "
                    "solved against"
                ),
                status_code=422,
                details={"solved_snapshot_id": solved_snapshot_id, "mismatches": mismatches},
            )
        return snapshot, envelope, answer, request

    def _basis(self, snapshot: SolvedSystemSnapshot) -> str:
        """The quantity the answer is per: the demand the frozen solve actually answered.

        The model graph's own declared functional unit is a property of the model version, so
        quoting it beside a climate total would state a basis the answer does not have.
        """
        calculation_basis = (snapshot.provider_receipt or {}).get("calculation_basis") or {}
        demand = calculation_basis.get("demand")
        amount, unit = (
            (demand[0].get("amount"), demand[0].get("unit"))
            if isinstance(demand, list) and len(demand) == 1 and isinstance(demand[0], dict)
            else (None, None)
        )
        if amount in (None, "") or not unit:
            raise DomainError(
                code="NATIVE_CLIMATE_ANSWER_INVALID",
                message=(
                    "the frozen climate answer lacks the single product demand it was solved for"
                ),
                status_code=422,
                details={"solved_snapshot_id": snapshot.id},
            )
        return f"{amount} {unit}"

    def export_xlsx(self, solved_snapshot_id: str) -> tuple[bytes, str]:
        snapshot, envelope, answer, request = self._frozen_answer(solved_snapshot_id)
        return build_native_climate_xlsx(
            envelope,
            answer,
            request,
            snapshot_id=snapshot.id,
            snapshot_sha256=snapshot.content_sha256,
            basis=self._basis(snapshot),
        ), snapshot.content_sha256

    def report_html(self, solved_snapshot_id: str) -> tuple[str, str]:
        snapshot, envelope, answer, request = self._frozen_answer(solved_snapshot_id)
        return build_native_climate_html(
            envelope,
            answer,
            request,
            snapshot_id=snapshot.id,
            snapshot_sha256=snapshot.content_sha256,
            basis=self._basis(snapshot),
        ), snapshot.content_sha256
