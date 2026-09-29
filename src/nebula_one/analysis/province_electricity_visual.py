from __future__ import annotations

from decimal import Decimal
from html import escape


def _fmt(value: str | Decimal) -> str:
    return f"{Decimal(str(value)):,.4f}".rstrip("0").rstrip(".")


def render_province_electricity_svg(result: dict) -> str:
    scenarios = result.get("scenarios") or []
    maximum = max(
        (Decimal(item["covered_period_total"]) for item in scenarios),
        default=Decimal("1"),
    )
    if maximum <= 0:
        maximum = Decimal("1")
    chart_x, chart_y, chart_w, chart_h = 76, 178, 760, 390
    slot = chart_w / max(len(scenarios), 1)
    bar_w = min(112, slot * 0.58)
    baseline_id = result["baseline_scenario_id"]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720" viewBox="0 0 1200 720" role="img" aria-labelledby="title desc">',
        '<title id="title">Province electricity CO2 scenario comparison</title>',
        '<desc id="desc">Location-based purchased electricity carbon dioxide scenarios using one frozen electricity activity total.</desc>',
        '<rect width="1200" height="720" fill="#f6f9fc"/>',
        '<text x="48" y="52" font-family="Inter,Segoe UI,sans-serif" font-size="24" font-weight="700" fill="#15324b">Province electricity CO₂ scenarios</text>',
        f'<text x="48" y="82" font-family="Inter,Segoe UI,sans-serif" font-size="14" fill="#55738e">{escape(result["factor_source"]["title"])} · {escape(str(result["factor_source"]["data_year"]))}</text>',
        '<rect x="48" y="112" width="820" height="510" rx="16" fill="#ffffff" stroke="#d8e2ea"/>',
    ]
    for index in range(5):
        y = chart_y + chart_h * index / 4
        value = maximum * Decimal(str(1 - index / 4))
        parts.extend(
            [
                f'<line x1="{chart_x}" y1="{y:.1f}" x2="{chart_x + chart_w}" y2="{y:.1f}" stroke="#e6edf3"/>',
                f'<text x="{chart_x - 12}" y="{y + 4:.1f}" text-anchor="end" font-family="Inter,Segoe UI,sans-serif" font-size="11" fill="#70879a">{_fmt(value)}</text>',
            ]
        )
    for index, scenario in enumerate(scenarios):
        value = Decimal(scenario["covered_period_total"])
        height = float(value / maximum) * chart_h
        x = chart_x + index * slot + (slot - bar_w) / 2
        y = chart_y + chart_h - height
        color = "#11a37f" if scenario["scenario_id"] == baseline_id else "#2e82e6"
        parts.extend(
            [
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{height:.1f}" rx="8" fill="{color}"/>',
                f'<text x="{x + bar_w / 2:.1f}" y="{max(y - 12, chart_y + 16):.1f}" text-anchor="middle" font-family="Inter,Segoe UI,sans-serif" font-size="13" font-weight="700" fill="#15324b">{_fmt(value)}</text>',
                f'<text x="{x + bar_w / 2:.1f}" y="{chart_y + chart_h + 28:.1f}" text-anchor="middle" font-family="Inter,Segoe UI,sans-serif" font-size="13" font-weight="700" fill="#15324b">{escape(scenario["province_name"])}</text>',
                f'<text x="{x + bar_w / 2:.1f}" y="{chart_y + chart_h + 48:.1f}" text-anchor="middle" font-family="Inter,Segoe UI,sans-serif" font-size="11" fill="#70879a">{escape(scenario["factor"])} kg CO₂/kWh</text>',
            ]
        )
    baseline = next(item for item in scenarios if item["scenario_id"] == baseline_id)
    parts.extend(
        [
            '<rect x="900" y="112" width="252" height="510" rx="16" fill="#ffffff" stroke="#d8e2ea"/>',
            '<text x="924" y="150" font-family="Inter,Segoe UI,sans-serif" font-size="14" font-weight="700" fill="#15324b">Frozen activity</text>',
            f'<text x="924" y="188" font-family="Inter,Segoe UI,sans-serif" font-size="24" font-weight="700" fill="#2e82e6">{_fmt(result["electricity_activity"]["covered_period_total_kwh"])} <tspan font-size="12">kWh</tspan></text>',
            '<text x="924" y="228" font-family="Inter,Segoe UI,sans-serif" font-size="12" fill="#70879a">Baseline province</text>',
            f'<text x="924" y="256" font-family="Inter,Segoe UI,sans-serif" font-size="18" font-weight="700" fill="#15324b">{escape(baseline["province_name"])}</text>',
            '<line x1="924" y1="286" x2="1128" y2="286" stroke="#d8e2ea"/>',
            '<text x="924" y="322" font-family="Inter,Segoe UI,sans-serif" font-size="12" fill="#70879a">Accounting boundary</text>',
            '<text x="924" y="350" font-family="Inter,Segoe UI,sans-serif" font-size="13" font-weight="700" fill="#15324b">Location-based indirect CO₂</text>',
            '<text x="924" y="382" font-family="Inter,Segoe UI,sans-serif" font-size="11" fill="#70879a">Reference calculation only</text>',
            '<text x="924" y="402" font-family="Inter,Segoe UI,sans-serif" font-size="11" fill="#70879a">Not EF 3.1 LCIA</text>',
            '<text x="924" y="422" font-family="Inter,Segoe UI,sans-serif" font-size="11" fill="#70879a">Not a complete Scope 2 claim</text>',
            '<line x1="924" y1="454" x2="1128" y2="454" stroke="#d8e2ea"/>',
            f'<text x="924" y="488" font-family="Inter,Segoe UI,sans-serif" font-size="12" fill="#70879a">Status · {escape(result["status"])}</text>',
            '<text x="48" y="680" font-family="Inter,Segoe UI,sans-serif" font-size="11" fill="#70879a">Chart generated from a frozen period energy total, exact TIDAS electricity identity and a versioned official-factor method package.</text>',
            '</svg>',
        ]
    )
    return "".join(parts)
