from __future__ import annotations

from decimal import Decimal
from html import escape
from typing import Any


def _amount(value: Decimal) -> str:
    if abs(value) >= Decimal("1000000"):
        return f"{value / Decimal('1000000'):.3f}M"
    if abs(value) >= Decimal("1000"):
        return f"{value / Decimal('1000'):.3f}k"
    text = format(value.quantize(Decimal("0.001")), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def render_period_energy_total_svg(result: dict[str, Any]) -> str:
    width = 1440
    panel_height = 310
    panel_gap = 24
    height = 126 + len(result["metrics"]) * (panel_height + panel_gap) + 40
    periods = [item["period"] for item in result["observations"]]
    colors = ["#2f78c4", "#2f9b72", "#d4832f", "#7b61b3", "#4d8796"]
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {width} {height}" preserveAspectRatio="xMinYMin meet" role="img" aria-labelledby="period-total-title period-total-desc">',
        '<title id="period-total-title">Period energy totals</title>',
        '<desc id="period-total-desc">Each panel shows evidence-scaled energy totals for non-overlapping reporting periods.</desc>',
        f'<rect width="{width}" height="{height}" fill="#f6f9fc"/>',
        '<text x="48" y="48" font-family="Inter,Segoe UI,sans-serif" font-size="24" font-weight="700" fill="#15324b">Period energy totals</text>',
        '<text x="48" y="78" font-family="Inter,Segoe UI,sans-serif" font-size="14" fill="#58738c">Frozen solve intensity × reviewed period product output · exact units only</text>',
    ]
    for metric_index, metric in enumerate(result["metrics"]):
        panel_y = 106 + metric_index * (panel_height + panel_gap)
        values = [Decimal(metric["period_total_values"][period["id"]]) for period in periods]
        maximum = max(values)
        plot_left = Decimal("330")
        plot_width = Decimal("980")
        bar_width = min(Decimal("130"), plot_width / Decimal(max(1, len(periods) * 2)))
        slot = plot_width / Decimal(len(periods))
        lines.extend(
            [
                f'<rect x="48" y="{panel_y}" width="1344" height="{panel_height}" rx="16" fill="#ffffff" stroke="#dce7ef"/>',
                f'<text x="72" y="{panel_y + 36}" font-family="Inter,Segoe UI,sans-serif" font-size="17" font-weight="700" fill="#15324b">{escape(metric["label"])}</text>',
                f'<text x="72" y="{panel_y + 60}" font-family="Inter,Segoe UI,sans-serif" font-size="12" fill="#71879a">{escape(metric["basis"]["energy_convention"])} · {escape(metric["basis"]["material_condition"])} · independent scale</text>',
                f'<line x1="330" y1="{panel_y + 228}" x2="1310" y2="{panel_y + 228}" stroke="#d9e5ed"/>',
            ]
        )
        for index, (period, value) in enumerate(zip(periods, values)):
            x = plot_left + Decimal(index) * slot + (slot - bar_width) / Decimal("2")
            bar_height = Decimal("142") * value / maximum if maximum > 0 else Decimal("0")
            y = Decimal(panel_y + 228) - bar_height
            color = colors[index % len(colors)]
            lines.extend(
                [
                    f'<rect x="{float(x):.2f}" y="{float(y):.2f}" width="{float(bar_width):.2f}" height="{float(bar_height):.2f}" rx="6" fill="{color}"><title>{escape(period["name"])}: {escape(str(value))} {escape(metric["unit_symbol"])}</title></rect>',
                    f'<text x="{float(x + bar_width / 2):.2f}" y="{float(y - 12):.2f}" text-anchor="middle" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="13" font-weight="600" fill="#15324b">{escape(_amount(value))} {escape(metric["unit_symbol"])}</text>',
                    f'<text x="{float(x + bar_width / 2):.2f}" y="{panel_y + 258}" text-anchor="middle" font-family="Inter,Segoe UI,sans-serif" font-size="12" font-weight="600" fill="#294960">{escape(period["key"])}</text>',
                    f'<text x="{float(x + bar_width / 2):.2f}" y="{panel_y + 280}" text-anchor="middle" font-family="Inter,Segoe UI,sans-serif" font-size="11" fill="#71879a">{escape(period["start_date"])} – {escape(period["end_date"])}</text>',
                ]
            )
    lines.extend(
        [
            f'<text x="48" y="{height - 20}" font-family="Inter,Segoe UI,sans-serif" font-size="12" fill="#71879a">Status: {escape(result["status"])} · totals cover supplied periods only.</text>',
            "</svg>",
        ]
    )
    return "".join(lines)
