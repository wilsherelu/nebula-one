from __future__ import annotations

from html import escape
from math import sqrt

from ..errors import DomainError


def _fmt(value: float) -> str:
    return f"{value:,.6g}"


def render_spatial_distribution_svg(result: dict, *, scenario_id: str) -> str:
    scenario = next(
        (item for item in result.get("scenarios") or [] if item["scenario_id"] == scenario_id),
        None,
    )
    if scenario is None:
        raise DomainError(
            code="SPATIAL_DISTRIBUTION_SCENARIO_NOT_FOUND",
            message=f"spatial distribution scenario not found: {scenario_id}",
            status_code=404,
        )
    destination = result["destination"]
    rows = scenario["regions"]
    points = [
        (
            float(item["region"]["representative_point"]["coordinates"][0]),
            float(item["region"]["representative_point"]["coordinates"][1]),
        )
        for item in rows
    ] + [(float(destination["longitude"]), float(destination["latitude"]))]
    min_lon, max_lon = min(item[0] for item in points), max(item[0] for item in points)
    min_lat, max_lat = min(item[1] for item in points), max(item[1] for item in points)
    lon_span = max(max_lon - min_lon, 1.0)
    lat_span = max(max_lat - min_lat, 1.0)
    min_lon -= lon_span * 0.12
    max_lon += lon_span * 0.12
    min_lat -= lat_span * 0.12
    max_lat += lat_span * 0.12
    plot_x, plot_y, plot_w, plot_h = 64.0, 118.0, 820.0, 520.0

    def project(longitude: float, latitude: float) -> tuple[float, float]:
        x = plot_x + (longitude - min_lon) / (max_lon - min_lon) * plot_w
        y = plot_y + (max_lat - latitude) / (max_lat - min_lat) * plot_h
        return x, y

    destination_x, destination_y = project(
        float(destination["longitude"]), float(destination["latitude"])
    )
    maximum = max((float(item["amount"]) for item in rows), default=0.0)
    unit = escape(result["source_flow"]["unit"])
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720" viewBox="0 0 1200 720" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(scenario["name"])} spatial supply distribution</title>',
        '<desc id="desc">Demonstration province representative points and declared source shares connected to one destination park.</desc>',
        '<rect width="1200" height="720" fill="#f7fafc"/>',
        '<text x="48" y="48" font-family="Inter,Segoe UI,sans-serif" font-size="24" font-weight="700" fill="#15324b">Province supply distribution</text>',
        f'<text x="48" y="78" font-family="Inter,Segoe UI,sans-serif" font-size="14" fill="#55738e">{escape(scenario["name"])} · {_fmt(result["source_flow"]["amount"])} {unit}</text>',
        '<rect x="48" y="100" width="852" height="560" rx="16" fill="#ffffff" stroke="#d8e2ea"/>',
    ]
    for index in range(1, 5):
        x = plot_x + plot_w * index / 5
        y = plot_y + plot_h * index / 5
        parts.extend(
            [
                f'<line x1="{x:.1f}" y1="{plot_y:.1f}" x2="{x:.1f}" y2="{plot_y + plot_h:.1f}" stroke="#e8eef3" stroke-dasharray="4 6"/>',
                f'<line x1="{plot_x:.1f}" y1="{y:.1f}" x2="{plot_x + plot_w:.1f}" y2="{y:.1f}" stroke="#e8eef3" stroke-dasharray="4 6"/>',
            ]
        )
    for item in rows:
        region = item["region"]
        x, y = project(
            float(region["representative_point"]["coordinates"][0]),
            float(region["representative_point"]["coordinates"][1]),
        )
        amount = float(item["amount"])
        ratio = 0.0 if maximum <= 0 else amount / maximum
        radius = 10.0 + sqrt(ratio) * 18.0
        control_x = (x + destination_x) / 2
        control_y = min(y, destination_y) - 48.0
        stroke = 2.0 + ratio * 10.0
        parts.extend(
            [
                f'<path d="M {x:.1f} {y:.1f} Q {control_x:.1f} {control_y:.1f} {destination_x:.1f} {destination_y:.1f}" fill="none" stroke="#2e82e6" stroke-opacity="0.30" stroke-width="{stroke:.1f}"/>',
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="#eaf4ff" stroke="#2e82e6" stroke-width="2"/>',
                f'<text x="{x:.1f}" y="{y - radius - 10:.1f}" text-anchor="middle" font-family="Inter,Segoe UI,sans-serif" font-size="13" font-weight="700" fill="#15324b">{escape(region["name"])}</text>',
                f'<text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="middle" font-family="Inter,Segoe UI,sans-serif" font-size="12" fill="#1d5f9f">{item["share"]:.0%}</text>',
                f'<text x="{x:.1f}" y="{y + radius + 18:.1f}" text-anchor="middle" font-family="Inter,Segoe UI,sans-serif" font-size="11" fill="#55738e">{_fmt(amount)} {unit}</text>',
            ]
        )
    parts.extend(
        [
            f'<circle cx="{destination_x:.1f}" cy="{destination_y:.1f}" r="22" fill="#11a37f" stroke="#ffffff" stroke-width="5"/>',
            f'<text x="{destination_x:.1f}" y="{destination_y + 46:.1f}" text-anchor="middle" font-family="Inter,Segoe UI,sans-serif" font-size="13" font-weight="700" fill="#15324b">Destination park</text>',
            '<rect x="928" y="100" width="224" height="560" rx="16" fill="#ffffff" stroke="#d8e2ea"/>',
            '<text x="952" y="136" font-family="Inter,Segoe UI,sans-serif" font-size="14" font-weight="700" fill="#15324b">Declared allocation</text>',
        ]
    )
    for index, item in enumerate(sorted(rows, key=lambda row: -row["amount"])):
        y = 178 + index * 92
        delta = float(item["amount_delta_from_baseline"])
        delta_text = "baseline" if scenario_id == result["baseline_scenario_id"] else f"Δ {_fmt(delta)} {unit}"
        parts.extend(
            [
                f'<text x="952" y="{y}" font-family="Inter,Segoe UI,sans-serif" font-size="13" font-weight="700" fill="#15324b">{escape(item["region"]["name"])}</text>',
                f'<text x="952" y="{y + 24}" font-family="Inter,Segoe UI,sans-serif" font-size="20" font-weight="700" fill="#2e82e6">{_fmt(item["amount"])} <tspan font-size="12">{unit}</tspan></text>',
                f'<text x="952" y="{y + 46}" font-family="Inter,Segoe UI,sans-serif" font-size="11" fill="#70879a">{item["share"]:.1%} · {escape(delta_text)}</text>',
            ]
        )
    parts.extend(
        [
            '<line x1="952" y1="570" x2="1128" y2="570" stroke="#d8e2ea"/>',
            '<text x="952" y="600" font-family="Inter,Segoe UI,sans-serif" font-size="11" fill="#70879a">Representative points only</text>',
            '<text x="952" y="620" font-family="Inter,Segoe UI,sans-serif" font-size="11" fill="#70879a">No official boundary geometry</text>',
            '<text x="48" y="694" font-family="Inter,Segoe UI,sans-serif" font-size="11" fill="#70879a">Map generated from a frozen solved boundary Flow and a versioned demonstration allocation package.</text>',
            '</svg>',
        ]
    )
    return "".join(parts)
