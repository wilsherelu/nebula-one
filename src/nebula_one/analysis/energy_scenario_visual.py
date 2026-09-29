from __future__ import annotations

from decimal import Decimal
from html import escape

from .energy_scenarios import EnergyScenarioComparison


def _amount(value: Decimal) -> str:
    text = format(value.quantize(Decimal("0.001")), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def render_energy_scenario_comparison_svg(
    comparison: EnergyScenarioComparison,
    *,
    title: str = "Petrochemical energy scenarios",
) -> str:
    width = 1440
    row_height = 44
    panel_header = 86
    panel_gap = 26
    panel_height = panel_header + row_height * len(comparison.scenarios)
    height = 126 + len(comparison.metrics) * (panel_height + panel_gap) + 44
    scenario_names = {
        item.scenario_id: item.scenario_name for item in comparison.scenarios
    }
    colors = ["#2f78c4", "#2f9b72", "#d4832f", "#7b61b3", "#4d8796"]
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {width} {height}" preserveAspectRatio="xMinYMin meet" role="img" aria-labelledby="energy-scenario-title energy-scenario-desc">',
        '<title id="energy-scenario-title">Petrochemical energy scenario comparison</title>',
        '<desc id="energy-scenario-desc">Each panel has its own exact unit and energy-basis identity. Values are not aggregated across panels.</desc>',
        f'<rect width="{width}" height="{height}" fill="#f6f9fc"/>',
        f'<text x="48" y="48" font-family="Inter,Segoe UI,sans-serif" font-size="24" font-weight="700" fill="#15324b">{escape(title)}</text>',
        '<text x="48" y="78" font-family="Inter,Segoe UI,sans-serif" font-size="14" fill="#58738c">Frozen revisions · exact evidence series · independent scale per panel</text>',
    ]
    for metric_index, metric in enumerate(comparison.metrics):
        panel_y = 106 + metric_index * (panel_height + panel_gap)
        max_value = max(metric.values.values())
        scale = Decimal("680") / max_value if max_value > 0 else Decimal("0")
        lines.extend(
            [
                f'<rect x="48" y="{panel_y}" width="1344" height="{panel_height}" rx="16" fill="#ffffff" stroke="#dce7ef"/>',
                f'<text x="72" y="{panel_y + 34}" font-family="Inter,Segoe UI,sans-serif" font-size="17" font-weight="700" fill="#15324b">{escape(metric.label)}</text>',
                f'<text x="72" y="{panel_y + 58}" font-family="Inter,Segoe UI,sans-serif" font-size="12" fill="#71879a">{escape(metric.basis.energy_convention)} · {escape(metric.basis.material_condition)} · unit identity {escape(metric.unit_identity_sha256[:18])}…</text>',
            ]
        )
        for scenario_index, scenario in enumerate(comparison.scenarios):
            row_y = panel_y + panel_header + scenario_index * row_height
            value = metric.values[scenario.scenario_id]
            bar_width = max(2, float(value * scale)) if value > 0 else 0
            color = colors[scenario_index % len(colors)]
            baseline_marker = (
                " · baseline"
                if scenario.scenario_id == comparison.baseline_scenario_id
                else ""
            )
            lines.extend(
                [
                    f'<text x="72" y="{row_y + 25}" font-family="Inter,Segoe UI,sans-serif" font-size="13" font-weight="600" fill="#294960">{escape(scenario_names[scenario.scenario_id] + baseline_marker)}</text>',
                    f'<rect x="342" y="{row_y + 10}" width="680" height="18" rx="9" fill="#edf2f6"/>',
                    f'<rect x="342" y="{row_y + 10}" width="{bar_width:.2f}" height="18" rx="9" fill="{color}"/>',
                    f'<text x="1050" y="{row_y + 25}" font-family="ui-monospace,SFMono-Regular,Consolas,monospace" font-size="14" font-weight="600" fill="#15324b">{escape(_amount(value))} {metric.unit_symbol}<title>Exact value: {escape(str(value))} {metric.unit_symbol}</title></text>',
                ]
            )
    lines.extend(
        [
            f'<text x="48" y="{height - 24}" font-family="Inter,Segoe UI,sans-serif" font-size="12" fill="#71879a">Status: {escape(comparison.status)} · no cross-panel total is calculated.</text>',
            "</svg>",
        ]
    )
    return "".join(lines)
