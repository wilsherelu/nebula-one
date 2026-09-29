from __future__ import annotations

from decimal import Decimal
from html import escape
from typing import Any


def _amount(value: Decimal) -> str:
    text = format(value.quantize(Decimal("0.001")), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def render_period_energy_trend_svg(result: dict[str, Any]) -> str:
    width = 1440
    panel_height = 300
    panel_gap = 24
    height = 126 + len(result["metrics"]) * (panel_height + panel_gap) + 40
    observations = result["observations"]
    periods = [item["period"] for item in observations]
    colors = ["#2f78c4", "#2f9b72", "#d4832f", "#7b61b3", "#4d8796"]
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {width} {height}" preserveAspectRatio="xMinYMin meet" role="img" aria-labelledby="period-energy-title period-energy-desc">',
        '<title id="period-energy-title">Period energy intensity trend</title>',
        '<desc id="period-energy-desc">Each panel compares one exact energy unit and basis series across non-overlapping reporting periods.</desc>',
        f'<rect width="{width}" height="{height}" fill="#f6f9fc"/>',
        '<text x="48" y="48" font-family="Inter,Segoe UI,sans-serif" font-size="24" font-weight="700" fill="#15324b">Period energy intensity trend</text>',
        '<text x="48" y="78" font-family="Inter,Segoe UI,sans-serif" font-size="14" fill="#58738c">Frozen energy results · same functional unit · no period-total aggregation</text>',
    ]
    for metric_index, metric in enumerate(result["metrics"]):
        panel_y = 106 + metric_index * (panel_height + panel_gap)
        values = [Decimal(metric["values"][period["id"]]) for period in periods]
        maximum = max(values)
        plot_left = Decimal("330")
        plot_width = Decimal("980")
        x_step = plot_width / Decimal(max(1, len(periods) - 1))
        points: list[tuple[Decimal, Decimal]] = []
        for index, value in enumerate(values):
            x = plot_left + Decimal(index) * x_step
            y = Decimal(panel_y + 220) - (
                Decimal("130") * value / maximum if maximum > 0 else Decimal("0")
            )
            points.append((x, y))
        polyline = " ".join(f"{float(x):.2f},{float(y):.2f}" for x, y in points)
        lines.extend(
            [
                f'<rect x="48" y="{panel_y}" width="1344" height="{panel_height}" rx="16" fill="#ffffff" stroke="#dce7ef"/>',
                f'<text x="72" y="{panel_y + 36}" font-family="Inter,Segoe UI,sans-serif" font-size="17" font-weight="700" fill="#15324b">{escape(metric["label"])}</text>',
                f'<text x="72" y="{panel_y + 60}" font-family="Inter,Segoe UI,sans-serif" font-size="12" fill="#71879a">{escape(metric["basis"]["energy_convention"])} · {escape(metric["basis"]["material_condition"])} · independent scale</text>',
                f'<line x1="330" y1="{panel_y + 220}" x2="1310" y2="{panel_y + 220}" stroke="#d9e5ed"/>',
                f'<polyline points="{polyline}" fill="none" stroke="#2f78c4" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>',
            ]
        )
        for index, ((x, y), period, value) in enumerate(zip(points, periods, values)):
            color = colors[index % len(colors)]
            lines.extend(
                [
                    f'<circle cx="{float(x):.2f}" cy="{float(y):.2f}" r="7" fill="{color}" stroke="#ffffff" stroke-width="3"><title>{escape(period["name"])}: {escape(str(value))} MJ</title></circle>',
                    f'<text x="{float(x):.2f}" y="{float(y - 16):.2f}" text-anchor="middle" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="13" font-weight="600" fill="#15324b">{escape(_amount(value))} MJ</text>',
                    f'<text x="{float(x):.2f}" y="{panel_y + 252}" text-anchor="middle" font-family="Inter,Segoe UI,sans-serif" font-size="12" font-weight="600" fill="#294960">{escape(period["key"])}</text>',
                    f'<text x="{float(x):.2f}" y="{panel_y + 272}" text-anchor="middle" font-family="Inter,Segoe UI,sans-serif" font-size="11" fill="#71879a">{escape(period["start_date"])} – {escape(period["end_date"])}</text>',
                ]
            )
    lines.extend(
        [
            f'<text x="48" y="{height - 20}" font-family="Inter,Segoe UI,sans-serif" font-size="12" fill="#71879a">Status: {escape(result["status"])} · arithmetic mean is descriptive only.</text>',
            "</svg>",
        ]
    )
    return "".join(lines)
