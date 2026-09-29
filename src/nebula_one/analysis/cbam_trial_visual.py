from __future__ import annotations

from decimal import Decimal
from html import escape


def _fmt(value: str, places: int = 4) -> str:
    return f"{Decimal(value):,.{places}f}".rstrip("0").rstrip(".")


def render_cbam_trial_svg(result: dict) -> str:
    activity = result["activity_level"]
    direct = result["attributed_emissions"]["direct"]
    specific = result["specific_embedded_emissions"]
    goods = result["goods"]
    return "".join(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720" viewBox="0 0 1200 720" role="img" aria-labelledby="title desc">',
            '<title id="title">CBAM hydrogen embedded-emissions trial</title>',
            '<desc id="desc">Direct-only specific embedded emissions calculated from one frozen solved snapshot.</desc>',
            '<rect width="1200" height="720" fill="#f6f9fc"/>',
            '<text x="48" y="54" font-family="Inter,Segoe UI,sans-serif" font-size="24" font-weight="700" fill="#15324b">CBAM hydrogen trial</text>',
            f'<text x="48" y="84" font-family="Inter,Segoe UI,sans-serif" font-size="14" fill="#55738e">CN {escape(str(goods["cn_code"]))} · {escape(str(goods["aggregated_goods_category"]))} · direct emissions only</text>',
            '<rect x="48" y="120" width="1104" height="414" rx="18" fill="#ffffff" stroke="#d8e2ea"/>',
            '<text x="88" y="174" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#70879a">ACTIVITY LEVEL</text>',
            f'<text x="88" y="222" font-family="Inter,Segoe UI,sans-serif" font-size="30" font-weight="700" fill="#15324b">{_fmt(activity["value"])} <tspan font-size="14">t product</tspan></text>',
            '<path d="M360 214 H470" stroke="#9eb4c5" stroke-width="3" marker-end="url(#arrow)"/>',
            '<text x="506" y="174" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#70879a">ATTRIBUTED DIRECT EMISSIONS</text>',
            f'<text x="506" y="222" font-family="Inter,Segoe UI,sans-serif" font-size="30" font-weight="700" fill="#15324b">{_fmt(direct["value"])} <tspan font-size="14">t CO₂e</tspan></text>',
            '<path d="M804 214 H894" stroke="#9eb4c5" stroke-width="3" marker-end="url(#arrow)"/>',
            '<text x="920" y="174" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#70879a">SPECIFIC EMBEDDED EMISSIONS</text>',
            f'<text x="920" y="222" font-family="Inter,Segoe UI,sans-serif" font-size="30" font-weight="700" fill="#11a37f">{_fmt(specific["value"])} <tspan font-size="14">t CO₂e/t</tspan></text>',
            '<line x1="88" y1="278" x2="1112" y2="278" stroke="#e2eaf0"/>',
            '<text x="88" y="326" font-family="Inter,Segoe UI,sans-serif" font-size="14" font-weight="700" fill="#15324b">Evidence chain</text>',
            '<text x="88" y="360" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#55738e">Frozen provider activity vector → exact TIDAS hydrogen output → exact elementary CO₂ exchange → direct-only ratio</text>',
            f'<text x="88" y="404" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#55738e">Process: {escape(str(goods["production_process_uuid"]))}</text>',
            f'<text x="88" y="434" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#55738e">Reporting period: {escape(str(result["reporting_period"]["start_date"]))} — {escape(str(result["reporting_period"]["end_date"]))}</text>',
            '<rect x="48" y="566" width="1104" height="96" rx="14" fill="#fff8e8" stroke="#efcf83"/>',
            '<text x="72" y="606" font-family="Inter,Segoe UI,sans-serif" font-size="14" font-weight="700" fill="#7a5310">TRIAL ONLY</text>',
            '<text x="72" y="636" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#7a5310">Not a CBAM declaration or verified value. Certificate liability, carbon-price deduction and free-allocation adjustment are not calculated.</text>',
            '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#9eb4c5"/></marker></defs>',
            '</svg>',
        ]
    )
