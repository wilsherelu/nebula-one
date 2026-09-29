from __future__ import annotations

from decimal import Decimal

from ..analysis.water_balance import build_water_balance
from ..analysis.water_balance_visual import render_water_balance_svg
from ..database import Database
from ..errors import DomainError
from ..models import SystemRevision
from ..runtime_models import SolvedSystemSnapshot
from ..runtime_schemas import SolvedSystemSnapshotOut, WaterBalanceCreate


class WaterBalanceService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def analyze(self, solved_snapshot_id: str, payload: WaterBalanceCreate) -> dict:
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
        return build_water_balance(
            solved_snapshot=solved_payload,
            revision_graph=graph,
            series_specs=[item.model_dump(mode="json") for item in payload.series],
            tolerance=Decimal(str(payload.tolerance)),
        )

    def sankey_svg(self, solved_snapshot_id: str, payload: WaterBalanceCreate) -> str:
        return render_water_balance_svg(
            self.analyze(solved_snapshot_id, payload), series_id=payload.series_id
        )
