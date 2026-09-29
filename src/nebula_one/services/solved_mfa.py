from __future__ import annotations

from ..analysis.solved_mfa import build_solved_mfa, render_sankey_svg
from ..database import Database
from ..errors import DomainError
from ..models import SystemRevision
from ..runtime_models import SolvedSystemSnapshot
from ..runtime_schemas import SolvedSystemSnapshotOut


class SolvedMFAService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def analyze(self, solved_snapshot_id: str, *, tolerance: float = 1e-9) -> dict:
        with self.database.session() as db:
            solved = db.get(SolvedSystemSnapshot, solved_snapshot_id)
            if solved is None:
                raise DomainError(
                    code="SOLVED_SNAPSHOT_NOT_FOUND",
                    message=f"solved system snapshot not found: {solved_snapshot_id}",
                    status_code=404,
                )
            revision = db.get(SystemRevision, solved.system_revision_id)
            if revision is None:
                raise DomainError(
                    code="SYSTEM_REVISION_NOT_FOUND",
                    message=f"system revision not found: {solved.system_revision_id}",
                    status_code=404,
                )
            solved_payload = SolvedSystemSnapshotOut.model_validate(solved).model_dump(
                mode="json"
            )
            graph = revision.graph_snapshot
        return build_solved_mfa(
            solved_snapshot=solved_payload,
            revision_graph=graph,
            tolerance=tolerance,
        )

    def sankey_svg(
        self,
        solved_snapshot_id: str,
        *,
        series_id: str | None = None,
        tolerance: float = 1e-9,
    ) -> str:
        result = self.analyze(solved_snapshot_id, tolerance=tolerance)
        series = result["series"]
        if not series:
            raise DomainError(
                code="SOLVED_MFA_SERIES_EMPTY",
                message="solved MFA produced no unit series",
                status_code=422,
            )
        selected = None
        if series_id is None:
            if len(series) != 1:
                raise DomainError(
                    code="SOLVED_MFA_SERIES_REQUIRED",
                    message="series_id is required when solved MFA has multiple unit series",
                    status_code=422,
                    details={"series_ids": [item["series_id"] for item in series]},
                )
            selected = series[0]
        else:
            selected = next(
                (item for item in series if item["series_id"] == series_id), None
            )
            if selected is None:
                raise DomainError(
                    code="SOLVED_MFA_SERIES_NOT_FOUND",
                    message=f"solved MFA series not found: {series_id}",
                    status_code=404,
                    details={"series_ids": [item["series_id"] for item in series]},
                )
        return render_sankey_svg(selected, title="物质流向图", chinese_labels=True)
