from __future__ import annotations

from decimal import Decimal
from html import escape

from .energy_carrier import EnergyCarrierSolved


def _basis_label(convention: str) -> str:
    return {
        "declared_energy": "Declared energy",
        "lower_heating_value": "Lower heating value",
        "higher_heating_value": "Higher heating value",
    }[convention]


def _display_amount(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.001"))
    return format(rounded, "f").rstrip("0").rstrip(".")


def render_energy_carrier_series_svg(result: EnergyCarrierSolved) -> str:
    width = 1200
    row_height = 150
    height = 132 + row_height * len(result.series) + 62
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {width} {height}" preserveAspectRatio="xMinYMin meet" role="img" aria-labelledby="energy-title energy-desc">',
        '<title id="energy-title">Solved energy-carrier series</title>',
        '<desc id="energy-desc">Energy entries are separated by exact unit identity and basis and are not aggregated across series.</desc>',
        f'<rect width="{width}" height="{height}" fill="#f7fafc"/>',
        '<text x="48" y="46" font-family="Inter,Segoe UI,sans-serif" font-size="24" font-weight="700" fill="#15324b">Solved energy-carrier series</text>',
        '<text x="48" y="76" font-family="Inter,Segoe UI,sans-serif" font-size="14" fill="#58738c">Independent evidence series · widths are not comparable across rows</text>',
    ]
    colors = [("#e8f3ff", "#2878d0"), ("#edf8f3", "#2f9b72"), ("#fff5e8", "#cf7a24")]
    for index, series in enumerate(result.series):
        y = 112 + index * row_height
        fill, accent = colors[index % len(colors)]
        basis_label = _basis_label(series.basis.energy_convention)
        source_label = (
            "Direct solved exchange"
            if series.entries[0].source.kind == "direct_solved_exchange"
            else "Quantity conversion receipt"
        )
        exact_amount = f"{series.total_amount} {series.unit_symbol}"
        display_amount = f"{_display_amount(series.total_amount)} {series.unit_symbol}"
        lines.extend(
            [
                f'<rect x="48" y="{y}" width="1104" height="116" rx="14" fill="{fill}" stroke="{accent}" stroke-width="2"/>',
                f'<text x="72" y="{y + 32}" font-family="Inter,Segoe UI,sans-serif" font-size="13" font-weight="600" fill="#58738c">{escape(basis_label)}</text>',
                f'<g><title>Exact amount: {escape(exact_amount)}</title><text x="72" y="{y + 75}" font-family="Inter,Segoe UI,sans-serif" font-size="24" font-weight="700" fill="#15324b">{escape(display_amount)}</text></g>',
                f'<line x1="430" y1="{y + 58}" x2="790" y2="{y + 58}" stroke="{accent}" stroke-width="12" stroke-linecap="round" opacity="0.62"/>',
                f'<path d="M 778 {y + 47} L 796 {y + 58} L 778 {y + 69}" fill="none" stroke="{accent}" stroke-width="4"/>',
                f'<text x="442" y="{y + 34}" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#58738c">{escape(source_label)}</text>',
                f'<text x="836" y="{y + 52}" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#58738c">Unit identity</text>',
                f'<text x="836" y="{y + 78}" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="12" fill="#15324b">{escape(series.unit_identity_sha256[:20])}…</text>',
            ]
        )
    footer_y = height - 32
    lines.extend(
        [
            f'<text x="48" y="{footer_y}" font-family="Inter,Segoe UI,sans-serif" font-size="12" fill="#71879a">Status: {escape(result.status)} · JSON result and receipts are the source of truth.</text>',
            '</svg>',
        ]
    )
    return "".join(lines)
