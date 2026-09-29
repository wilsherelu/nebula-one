from __future__ import annotations

import html
import math

from ..errors import DomainError


def render_product_pcf_svg(result: dict) -> str:
    total = result.get("total_footprint")
    components = result.get("component_results")
    if not isinstance(total, dict) or not isinstance(components, list):
        raise DomainError(
            code="PCF_CHART_RESULT_INVALID",
            message="PCF chart requires a validated product footprint result",
            status_code=422,
        )
    unit = str(total.get("unit") or "").strip()
    total_value = total.get("value")
    if not unit or isinstance(total_value, bool) or not isinstance(
        total_value, (int, float)
    ) or not math.isfinite(float(total_value)):
        raise DomainError(
            code="PCF_CHART_RESULT_INVALID",
            message="PCF chart total is not finite or has no unit",
            status_code=422,
        )
    rows = [
        {
            "label": str(item.get("indicator_key") or "").strip(),
            "value": float(item.get("value")),
        }
        for item in components
        if isinstance(item, dict)
        and isinstance(item.get("value"), (int, float))
        and not isinstance(item.get("value"), bool)
        and math.isfinite(float(item["value"]))
        and str(item.get("unit") or "").strip() == unit
    ]
    maximum = max([abs(float(total_value)), *(abs(item["value"]) for item in rows), 1e-12])
    width = 1100
    height = 250 + max(1, len(rows)) * 72
    bar_x = 410
    bar_width = 560
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Product carbon footprint</title>',
        '<desc id="desc">Total EF 3.1 climate-change result and component indicators from a frozen solved-system snapshot.</desc>',
        '<rect width="100%" height="100%" fill="#f7fafc"/>',
        '<text x="52" y="52" font-family="Inter,Segoe UI,sans-serif" font-size="26" font-weight="700" fill="#15324b">Product carbon footprint</text>',
        f'<text x="52" y="82" font-family="Inter,Segoe UI,sans-serif" font-size="14" fill="#557086">{html.escape(result["boundary_claim"]["claim_scope"])} · {html.escape(unit)}</text>',
        '<rect x="52" y="112" width="996" height="86" rx="14" fill="#ffffff" stroke="#dbe6ee"/>',
        '<text x="78" y="144" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#557086">TOTAL CLIMATE CHANGE</text>',
        f'<text x="78" y="180" font-family="Inter,Segoe UI,sans-serif" font-size="30" font-weight="700" fill="#123f5a">{float(total_value):.6g} {html.escape(unit)}</text>',
    ]
    for index, row in enumerate(rows):
        y = 235 + index * 72
        length = max(2.0, abs(row["value"]) / maximum * bar_width)
        color = "#1976a3" if row["value"] >= 0 else "#b44949"
        parts.extend(
            [
                f'<text x="52" y="{y + 22}" font-family="Inter,Segoe UI,sans-serif" font-size="14" fill="#263f52">{html.escape(row["label"])}</text>',
                f'<rect x="{bar_x}" y="{y}" width="{bar_width}" height="30" rx="6" fill="#e7eef3"/>',
                f'<rect x="{bar_x}" y="{y}" width="{length:.2f}" height="30" rx="6" fill="{color}"/>',
                f'<text x="990" y="{y + 21}" text-anchor="start" font-family="Inter,Segoe UI,sans-serif" font-size="14" font-weight="600" fill="#15324b">{row["value"]:.6g}</text>',
            ]
        )
    parts.append("</svg>")
    return "".join(parts)
