from __future__ import annotations

from ..errors import DomainError
from .solved_mfa import render_sankey_svg


def render_water_balance_svg(result: dict, *, series_id: str | None = None) -> str:
    series = result.get("series") or []
    if not series:
        raise DomainError(
            code="WATER_BALANCE_SERIES_EMPTY",
            message="water balance produced no series",
            status_code=422,
        )
    if series_id is None:
        if len(series) != 1:
            raise DomainError(
                code="WATER_BALANCE_SERIES_REQUIRED",
                message="series_id is required when water balance has multiple series",
                status_code=422,
                details={"series_ids": [item["series_id"] for item in series]},
            )
        selected = series[0]
    else:
        selected = next((item for item in series if item["series_id"] == series_id), None)
        if selected is None:
            raise DomainError(
                code="WATER_BALANCE_SERIES_NOT_FOUND",
                message=f"water balance series not found: {series_id}",
                status_code=404,
            )
    chart_series = {
        **selected,
        "unit_group": selected.get("unit_group_uuid"),
        "unit_group_label": "Explicit solved water balance",
        "diagram_mode": "water_balance",
    }
    return render_sankey_svg(
        chart_series,
        title="Solved water withdrawal, reuse and discharge",
        min_width=1120,
    )
