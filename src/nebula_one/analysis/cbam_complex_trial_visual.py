from __future__ import annotations

from html import escape
from typing import Any


def _number(value: str) -> str:
    return format(float(value), ".6g")


def render_cbam_complex_trial_svg(result: dict[str, Any]) -> str:
    goods = result["goods"]
    activity = result["activity_level"]
    emissions = result["attributed_emissions"]
    specific = result["specific_embedded_emissions"]
    precursor = result["precursors"][0]
    title = escape(str(goods.get("aggregated_goods_category") or "Complex good"))
    product_value = _number(activity["value"])
    direct_value = _number(emissions["final_process_direct"]["value"])
    precursor_value = _number(emissions["precursor_embedded_direct"]["value"])
    total_value = _number(specific["value"])
    precursor_mass = _number(precursor["mass"]["value"])
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720" viewBox="0 0 1200 720" role="img" aria-label="CBAM complex-goods direct-component trial">
<style>
text{{font-family:Inter,"Segoe UI",Arial,sans-serif;fill:#17324d}} .title{{font-size:34px;font-weight:700}} .sub{{font-size:17px;fill:#5f7690}} .label{{font-size:17px;font-weight:650}} .value{{font-size:25px;font-weight:750}} .small{{font-size:14px;fill:#5f7690}} .box{{fill:#fff;stroke:#d9e3ec;stroke-width:2}} .line{{stroke:#74a7d8;stroke-width:10;fill:none;stroke-linecap:round}} .amber{{fill:#fff6df;stroke:#e9b44c;stroke-width:2}}
</style>
<rect width="1200" height="720" fill="#f6f9fc"/>
<text x="54" y="62" class="title">CBAM complex-goods trial</text>
<text x="54" y="94" class="sub">{title} · Equation 62 · direct component only</text>
<path class="line" d="M252 294 C340 294 382 360 470 360"/>
<path class="line" d="M730 360 C820 360 850 294 944 294"/>
<rect class="box" x="54" y="214" rx="14" width="198" height="160"/>
<text x="78" y="252" class="label">Solved precursor</text>
<text x="78" y="290" class="value">{precursor_mass} t</text>
<text x="78" y="321" class="small">precursor consumed</text>
<text x="78" y="348" class="small">{precursor_value} t CO₂e embedded</text>
<rect class="box" x="470" y="260" rx="14" width="260" height="200"/>
<text x="494" y="300" class="label">Final production process</text>
<text x="494" y="340" class="value">{product_value} t product</text>
<text x="494" y="374" class="small">{direct_value} t CO₂e direct</text>
<text x="494" y="402" class="small">+ {precursor_value} t CO₂e precursor</text>
<rect class="box" x="944" y="214" rx="14" width="202" height="160"/>
<text x="968" y="252" class="label">Direct component</text>
<text x="968" y="294" class="value">{total_value}</text>
<text x="968" y="325" class="small">t CO₂e/t product</text>
<text x="968" y="351" class="small">ae_g + Σ(m_i × SEE_i)</text>
<rect class="amber" x="54" y="544" rx="12" width="1092" height="112"/>
<text x="78" y="582" class="label">TRIAL ONLY</text>
<text x="78" y="612" class="small">This chart excludes indirect emissions, defaults, verification, certificates, carbon-price deductions and free-allocation adjustments.</text>
<text x="78" y="638" class="small">Every value is rendered from a frozen solved-system snapshot and hash-verified precursor result.</text>
</svg>'''
