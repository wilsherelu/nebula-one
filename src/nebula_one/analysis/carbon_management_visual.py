from __future__ import annotations

from html import escape
from typing import Any


def render_carbon_management_svg(result: dict[str, Any]) -> str:
    series = result["energy_result"]["series"]
    direct = result["direct_emission_inventory"]
    climate = result.get("climate_change_total")
    attribution = result.get("carbon_attribution") or {}
    hotspots = list(attribution.get("hotspots") or [])[:6]
    direct_category = next(
        (item for item in attribution.get("categories") or [] if item.get("category") == "direct"),
        None,
    )
    lanes: list[tuple[str, str, float]] = []
    for index, item in enumerate(series):
        for category in item["categories"]:
            lanes.append((
                f"{category['category']} · {item['basis']['energy_convention']}",
                item["unit"],
                float(category["amount"]),
            ))
    max_value = max((value for _, _, value in lanes), default=1.0)
    hotspot_height = 0 if not hotspots else 72 + 46 * len(hotspots)
    energy_start = 302 + hotspot_height
    height = max(520, energy_start + 58 * len(lanes) + 120)
    has_contributions = attribution.get("indicator_receipt") is not None
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 1200 {height}" role="img" aria-labelledby="carbon-title carbon-desc">',
        '<title id="carbon-title">Period energy and carbon management</title>',
        '<desc id="carbon-desc">Auditable period energy lanes and direct elementary emissions. Different energy identities remain separate.</desc>',
        '<rect width="1200" height="100%" fill="#f7fafc"/>',
        '<text x="48" y="52" font-family="Inter,Segoe UI,sans-serif" font-size="24" font-weight="700" fill="#15324b">Period energy and carbon management</text>',
        '<text x="48" y="82" font-family="Inter,Segoe UI,sans-serif" font-size="14" fill="#55708a">Exact provider contributions when available · no inferred Scope 1/2/3 attribution</text>',
        '<rect x="48" y="112" width="720" height="140" rx="14" fill="#ffffff" stroke="#d8e2eb"/>',
        '<text x="72" y="144" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#55708a">CLIMATE CHANGE TOTAL</text>',
    ]
    if climate:
        parts.append(f'<text x="72" y="192" font-family="Inter,Segoe UI,sans-serif" font-size="32" font-weight="700" fill="#15324b">{climate["value"]:.6g} <tspan font-size="16">{escape(str(climate["unit"]))}</tspan></text>')
    else:
        parts.append('<text x="72" y="192" font-family="Inter,Segoe UI,sans-serif" font-size="22" font-weight="700" fill="#9a6a15">Unavailable in frozen solve</text>')
    total_note = (
        f'Exact provider receipt · {len(hotspots)} visible hotspot(s)'
        if has_contributions else
        'Provider total only; source attribution is not available.'
    )
    parts.extend([
        f'<text x="72" y="226" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#55708a">{escape(total_note)}</text>',
        '<rect x="792" y="112" width="360" height="140" rx="14" fill="#ffffff" stroke="#d8e2eb"/>',
        f'<text x="816" y="144" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#55708a">{"EXACT DIRECT CONTRIBUTION" if direct_category and direct_category.get("value") is not None else "DIRECT EMISSION INVENTORY"}</text>',
    ])
    direct_total = sum(float(item["amount"]) for item in direct)
    direct_unit = str(direct[0].get("unit") or "") if direct else ""
    if direct_category and direct_category.get("value") is not None:
        parts.append(f'<text x="816" y="192" font-family="Inter,Segoe UI,sans-serif" font-size="32" font-weight="700" fill="#15324b">{float(direct_category["value"]):.6g} <tspan font-size="16">{escape(str(direct_category["unit"]))}</tspan></text>')
        parts.append('<text x="816" y="226" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#55708a">Classified from exact provider terms; no EF factor recalculation.</text>')
    else:
        parts.append(f'<text x="816" y="192" font-family="Inter,Segoe UI,sans-serif" font-size="32" font-weight="700" fill="#15324b">{direct_total:.6g} <tspan font-size="16">{escape(direct_unit)}</tspan></text>')
        parts.append('<text x="816" y="226" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#55708a">Physical elementary-flow total, not a recalculated CO₂e value.</text>')

    if hotspots:
        parts.append('<text x="48" y="282" font-family="Inter,Segoe UI,sans-serif" font-size="16" font-weight="700" fill="#15324b">Climate contribution hotspots</text>')
        hotspot_max = max((abs(float(item["contribution_value"])) for item in hotspots), default=1.0)
        y = 302
        for item in hotspots:
            value = float(item["contribution_value"])
            width = 520 * (abs(value) / hotspot_max) if hotspot_max else 0
            label = f'{item["process_id"]} · {item["classification"]}'
            parts.extend([
                f'<text x="48" y="{y + 17}" font-family="Inter,Segoe UI,sans-serif" font-size="12" fill="#294963">{escape(label)}</text>',
                f'<rect x="390" y="{y}" width="{max(width, 4):.2f}" height="24" rx="7" fill="#16a085" opacity="0.82"/>',
                f'<text x="970" y="{y + 17}" font-family="Inter,Segoe UI,sans-serif" font-size="12" text-anchor="end" fill="#15324b">{value:.6g} {escape(str(item["contribution_unit"]))}</text>',
            ])
            y += 46

    y = energy_start
    parts.append(f'<text x="48" y="{energy_start - 20}" font-family="Inter,Segoe UI,sans-serif" font-size="16" font-weight="700" fill="#15324b">Energy carrier lanes</text>')
    for label, unit, value in lanes:
        width = 560 * (value / max_value) if max_value else 0
        parts.extend([
            f'<text x="48" y="{y + 18}" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#294963">{escape(label)}</text>',
            f'<rect x="390" y="{y}" width="{max(width, 4):.2f}" height="28" rx="8" fill="#2f80ed" opacity="0.82"/>',
            f'<text x="970" y="{y + 19}" font-family="Inter,Segoe UI,sans-serif" font-size="13" text-anchor="end" fill="#15324b">{value:.6g} {escape(unit)}</text>',
        ])
        y += 58
    parts.extend([
        f'<rect x="48" y="{height - 88}" width="1104" height="48" rx="12" fill="#fff7e6" stroke="#f0cf8d"/>',
        f'<text x="72" y="{height - 58}" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#744d0b">Audit status: {escape(str(result.get("audit", {}).get("status") or "unknown").replace("_", " "))} · exact identities and hashes are available in the result JSON.</text>',
        '</svg>',
    ])
    return "".join(parts)
