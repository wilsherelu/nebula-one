from __future__ import annotations

from ..errors import DomainError
from .solved_mfa import render_sankey_svg


def render_spatial_aggregate_svg(
    result: dict, *, series_id: str | None = None
) -> str:
    series = result.get("series") or []
    if not series:
        raise DomainError(
            code="SPATIAL_SERIES_EMPTY",
            message="park aggregation produced no unit series",
            status_code=422,
        )
    if series_id is None:
        if len(series) != 1:
            raise DomainError(
                code="SPATIAL_SERIES_REQUIRED",
                message="series_id is required when park aggregation has multiple unit series",
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
                code="SPATIAL_SERIES_NOT_FOUND",
                message=f"park aggregation series not found: {series_id}",
                status_code=404,
                details={"series_ids": [item["series_id"] for item in series]},
            )
    return render_sankey_svg(
        selected,
        title=f"{result['park']['name']} · Consolidated MFA",
    )
