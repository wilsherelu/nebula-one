from __future__ import annotations

from ..errors import DomainError
from .solved_mfa import render_sankey_svg


def render_spatial_energy_flow_svg(
    result: dict, *, series_id: str | None = None
) -> str:
    series = result.get("series") or []
    if not series:
        raise DomainError(
            code="SPATIAL_ENERGY_FLOW_SERIES_EMPTY",
            message="spatial energy flow analysis produced no series",
            status_code=422,
        )
    if series_id is None:
        if len(series) != 1:
            raise DomainError(
                code="SPATIAL_ENERGY_FLOW_SERIES_REQUIRED",
                message="series_id is required when spatial energy flow has multiple series",
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
                code="SPATIAL_ENERGY_FLOW_SERIES_NOT_FOUND",
                message=f"spatial energy flow series not found: {series_id}",
                status_code=404,
            )
    return render_sankey_svg(
        selected,
        title=f"{result['park']['name']} · Explicit facility energy flow",
        min_width=1180,
    )
