from __future__ import annotations

from ..analysis.cbam_complex_trial import build_cbam_complex_trial
from ..analysis.cbam_complex_trial_visual import render_cbam_complex_trial_svg
from ..database import Database
from ..errors import DomainError
from ..models import Application
from ..runtime_models import Period, SolvedSystemSnapshot
from ..runtime_schemas import CbamComplexTrialCreate, CbamTrialCreate
from .cbam_trial import CbamTrialService
from .runtime_support import require_method_package


class CbamComplexTrialService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.simple_trials = CbamTrialService(database)

    def analyze(
        self, solved_snapshot_id: str, payload: CbamComplexTrialCreate
    ) -> dict:
        precursor_results = [
            self.simple_trials.analyze(
                item.solved_snapshot_id,
                CbamTrialCreate(
                    method_package_ref=item.method_package_ref,
                    reporting_period_id=payload.reporting_period_id,
                ),
            )
            for item in payload.precursors
        ]
        with self.database.session() as db:
            snapshot = db.get(SolvedSystemSnapshot, solved_snapshot_id)
            if snapshot is None:
                raise DomainError(
                    code="SOLVED_SYSTEM_SNAPSHOT_NOT_FOUND",
                    message=f"solved system snapshot not found: {solved_snapshot_id}",
                    status_code=404,
                )
            period = db.get(Period, payload.reporting_period_id)
            if period is None:
                raise DomainError(
                    code="REPORTING_PERIOD_NOT_FOUND",
                    message=f"reporting period not found: {payload.reporting_period_id}",
                    status_code=404,
                )
            if period.application_id != snapshot.application_id:
                raise DomainError(
                    code="CBAM_COMPLEX_PERIOD_APPLICATION_MISMATCH",
                    message="reporting period and solved snapshot belong to different applications",
                    status_code=409,
                )
            if any(
                (result.get("source_snapshot") or {}).get("application_id")
                != snapshot.application_id
                for result in precursor_results
            ):
                raise DomainError(
                    code="CBAM_COMPLEX_PRECURSOR_APPLICATION_MISMATCH",
                    message="all precursor results must belong to the complex-good application",
                    status_code=409,
                )
            application = db.get(Application, snapshot.application_id)
            if application is None:
                raise DomainError(
                    code="APPLICATION_NOT_FOUND",
                    message=f"application not found: {snapshot.application_id}",
                    status_code=404,
                )
            bound_refs = set((application.context or {}).get("method_package_refs") or [])
            if payload.method_package_ref not in bound_refs:
                raise DomainError(
                    code="CBAM_COMPLEX_METHOD_NOT_BOUND",
                    message="CBAM complex-goods method is not bound to this application",
                    status_code=409,
                )
            package = require_method_package(db, payload.method_package_ref)
            reporting_period = {
                "id": period.id,
                "key": period.key,
                "name": period.name,
                "start_date": period.start_date.isoformat(),
                "end_date": period.end_date.isoformat(),
                "resolution": period.resolution,
            }
            return build_cbam_complex_trial(
                solved_snapshot_id=snapshot.id,
                solved_snapshot_sha256=snapshot.content_sha256,
                application_id=snapshot.application_id,
                activity_vector=snapshot.activity_vector,
                scaled_technosphere_exchanges=snapshot.scaled_technosphere_exchanges,
                scaled_elementary_exchanges=snapshot.scaled_elementary_exchanges,
                provider_receipt=snapshot.provider_receipt,
                reporting_period=reporting_period,
                method_package_ref=payload.method_package_ref,
                method_package_sha256=package.content_sha256,
                method_package_kind=package.package_kind,
                method_package_jurisdiction=package.jurisdiction,
                method_package_valid_from=package.valid_from,
                method_package_valid_to=package.valid_to,
                manifest=package.manifest,
                precursor_results=precursor_results,
            )

    def chart_svg(
        self, solved_snapshot_id: str, payload: CbamComplexTrialCreate
    ) -> str:
        return render_cbam_complex_trial_svg(
            self.analyze(solved_snapshot_id, payload)
        )
