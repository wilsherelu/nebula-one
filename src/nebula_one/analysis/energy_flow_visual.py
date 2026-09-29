from __future__ import annotations

from ..errors import DomainError
from .solved_mfa import render_sankey_svg


def render_energy_flow_svg(result: dict, *, series_id: str | None = None) -> str:
    series = result.get("series") or []
    if not series:
        raise DomainError(
            code="ENERGY_FLOW_SERIES_EMPTY",
            message="energy flow analysis produced no series",
            status_code=422,
        )
    if series_id is None:
        if len(series) != 1:
            raise DomainError(
                code="ENERGY_FLOW_SERIES_REQUIRED",
                message="series_id is required when energy flow has multiple series",
                status_code=422,
                details={"series_ids": [item["series_id"] for item in series]},
            )
        selected = series[0]
    else:
        selected = next((item for item in series if item["series_id"] == series_id), None)
        if selected is None:
            raise DomainError(
                code="ENERGY_FLOW_SERIES_NOT_FOUND",
                message=f"energy flow series not found: {series_id}",
                status_code=404,
            )
    chart_series = {
        **selected,
        "unit_group": selected.get("input_unit_identity_sha256"),
        "unit_group_label": "Explicit energy conversion balance",
        "diagram_mode": "energy_flow",
    }
    return render_sankey_svg(
        chart_series,
        title=f"{selected['process_name']} · Solved energy flow",
        min_width=960,
    )
