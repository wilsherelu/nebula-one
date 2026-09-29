from __future__ import annotations

from collections import defaultdict
from html import escape
from typing import Any

from ..errors import DomainError


def _text(value: Any) -> str:
    return str(value or "").strip()


def _format_amount(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 1_000_000 or abs(value) < 0.001:
        return f"{value:.3g}"
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def build_comparison_metrics(
    *,
    scenario_results: list[dict[str, Any]],
    baseline_scenario_id: str,
) -> list[dict[str, Any]]:
    scenario_ids = [item["scenario_id"] for item in scenario_results]
    if baseline_scenario_id not in scenario_ids:
        raise DomainError(
            code="COMPARISON_BASELINE_NOT_INCLUDED",
            message="baseline scenario must belong to the comparison run",
            status_code=409,
        )
    catalog: dict[str, dict[str, Any]] = {}
    values: dict[str, dict[str, float]] = defaultdict(dict)
    lcia_scenario_count = 0
    pcf_scenario_count = 0
    pcf_comparison_identity: dict[str, Any] | None = None

    def register(identity: dict[str, Any], scenario_id: str, value: float) -> None:
        metric_key = identity["metric_key"]
        existing = catalog.get(metric_key)
        identity_fields = (
            "metric_kind",
            "subject_id",
            "series_id",
            "unit_group",
            "unit",
            "method",
            "database_release",
            "indicator_metadata_hash",
            "pcf_method_package_ref",
            "pcf_method_package_hash",
            "pcf_functional_unit",
            "pcf_boundary_claim",
        )
        if existing is not None and any(
            existing.get(key) != identity.get(key) for key in identity_fields
        ):
            raise DomainError(
                code="COMPARISON_UNIT_IDENTITY_MISMATCH",
                message="the same comparison metric uses incompatible identities across scenarios",
                status_code=409,
                details={
                    "metric_key": metric_key,
                    "existing": existing,
                    "incoming": identity,
                },
            )
        catalog[metric_key] = identity
        values[metric_key][scenario_id] = (
            values[metric_key].get(scenario_id, 0.0) + value
        )

    for scenario in scenario_results:
        scenario_id = scenario["scenario_id"]
        for series in scenario.get("mfa_series") or []:
            series_id = _text(series.get("series_id"))
            unit_group = _text(series.get("unit_group"))
            unit_group_label = _text(series.get("unit_group_label")) or unit_group
            unit = _text(series.get("unit"))
            for link in series.get("links") or []:
                if link.get("kind") != "boundary":
                    continue
                flow_uuid = _text(link.get("flow_uuid"))
                direction = _text(link.get("direction"))
                exchange_type = _text(link.get("exchange_type"))
                metric_key = f"boundary:{direction}:{exchange_type}:{flow_uuid}"
                identity = {
                    "metric_key": metric_key,
                    "metric_kind": "boundary_flow",
                    "subject_id": flow_uuid,
                    "subject_name": _text(link.get("flow_name")) or flow_uuid,
                    "series_id": series_id,
                    "flow_uuid": flow_uuid,
                    "flow_name": _text(link.get("flow_name")) or flow_uuid,
                    "indicator_key": None,
                    "method": None,
                    "database_release": None,
                    "indicator_metadata_hash": None,
                    "direction": direction,
                    "exchange_type": exchange_type,
                    "unit_group": unit_group,
                    "unit_group_label": unit_group_label,
                    "unit": unit,
                }
                register(identity, scenario_id, float(link.get("value") or 0))

        lcia = scenario.get("lcia_results")
        indicators = lcia.get("indicator_results") if isinstance(lcia, dict) else None
        if isinstance(indicators, list) and indicators:
            lcia_scenario_count += 1
            method = _text(lcia.get("method"))
            database_release = _text(lcia.get("database_release"))
            if not method or not database_release:
                raise DomainError(
                    code="COMPARISON_LCIA_IDENTITY_INCOMPLETE",
                    message="LCIA comparison requires method and database release identity",
                    status_code=409,
                    details={"scenario_id": scenario_id},
                )
            for indicator in indicators:
                if not isinstance(indicator, dict):
                    raise DomainError(
                        code="COMPARISON_LCIA_RESULT_INVALID",
                        message="LCIA indicator results must be objects",
                        status_code=409,
                        details={"scenario_id": scenario_id},
                    )
                indicator_key = _text(indicator.get("canonical_indicator_key"))
                indicator_name = _text(indicator.get("indicator_en")) or indicator_key
                unit = _text(indicator.get("unit"))
                metadata_hash = _text(indicator.get("indicator_metadata_hash"))
                raw_value = indicator.get("value")
                if (
                    not indicator_key
                    or not indicator_name
                    or not unit
                    or not metadata_hash
                    or not isinstance(raw_value, (int, float))
                ):
                    raise DomainError(
                        code="COMPARISON_LCIA_IDENTITY_INCOMPLETE",
                        message="LCIA comparison requires exact indicator, unit and metadata identity",
                        status_code=409,
                        details={
                            "scenario_id": scenario_id,
                            "indicator_key": indicator_key,
                        },
                    )
                metric_key = (
                    f"lcia:{database_release}:{method}:{indicator_key}:{unit}"
                )
                register(
                    {
                        "metric_key": metric_key,
                        "metric_kind": "lcia_indicator",
                        "subject_id": indicator_key,
                        "subject_name": indicator_name,
                        "series_id": f"lcia::{database_release}::{method}::{unit}",
                        "flow_uuid": None,
                        "flow_name": None,
                        "indicator_key": indicator_key,
                        "method": method,
                        "database_release": database_release,
                        "indicator_metadata_hash": metadata_hash,
                        "direction": None,
                        "exchange_type": None,
                        "unit_group": method,
                        "unit_group_label": method,
                        "unit": unit,
                    },
                    scenario_id,
                    float(raw_value),
                )

        pcf = scenario.get("pcf_result")
        if isinstance(pcf, dict) and pcf:
            pcf_scenario_count += 1
            method_package = pcf.get("method_package")
            functional_unit = pcf.get("functional_unit")
            boundary_claim = pcf.get("boundary_claim")
            total = pcf.get("total_footprint")
            data_quality = pcf.get("data_quality")
            if not all(
                isinstance(item, dict)
                for item in (
                    method_package,
                    functional_unit,
                    boundary_claim,
                    total,
                    data_quality,
                )
            ):
                raise DomainError(
                    code="COMPARISON_PCF_IDENTITY_INCOMPLETE",
                    message="PCF comparison requires complete result identity",
                    status_code=409,
                    details={"scenario_id": scenario_id},
                )
            package_ref = _text(method_package.get("reference"))
            package_hash = _text(method_package.get("content_sha256"))
            method = _text(method_package.get("lcia_method"))
            indicator_key = _text(total.get("indicator_key"))
            unit = _text(total.get("unit"))
            database_release = _text(data_quality.get("database_release"))
            raw_value = total.get("value")
            result_hash = _text(scenario.get("pcf_result_hash"))
            if (
                not package_ref
                or not package_hash
                or not method
                or not indicator_key
                or not unit
                or not database_release
                or not result_hash
                or result_hash != _text(pcf.get("content_sha256"))
                or not isinstance(raw_value, (int, float))
                or isinstance(raw_value, bool)
            ):
                raise DomainError(
                    code="COMPARISON_PCF_IDENTITY_INCOMPLETE",
                    message="PCF comparison requires exact package, indicator, unit, release, and result hash identity",
                    status_code=409,
                    details={"scenario_id": scenario_id},
                )
            comparison_identity = {
                "method_package_ref": package_ref,
                "method_package_hash": package_hash,
                "functional_unit": functional_unit,
                "boundary_claim": boundary_claim,
                "indicator_key": indicator_key,
                "method": method,
                "unit": unit,
                "database_release": database_release,
            }
            if pcf_comparison_identity is None:
                pcf_comparison_identity = comparison_identity
            elif pcf_comparison_identity != comparison_identity:
                raise DomainError(
                    code="COMPARISON_PCF_IDENTITY_MISMATCH",
                    message="PCF results are not comparable across scenarios",
                    status_code=409,
                    details={
                        "scenario_id": scenario_id,
                        "baseline_identity": pcf_comparison_identity,
                        "incoming_identity": comparison_identity,
                    },
                )
            identity = {
                "metric_key": f"pcf:{indicator_key}",
                "metric_kind": "pcf_total",
                "subject_id": indicator_key,
                "subject_name": indicator_key,
                "series_id": f"pcf::{package_hash}::{database_release}::{unit}",
                "flow_uuid": None,
                "flow_name": None,
                "indicator_key": indicator_key,
                "method": method,
                "database_release": database_release,
                "indicator_metadata_hash": package_hash,
                "direction": None,
                "exchange_type": None,
                "unit_group": method,
                "unit_group_label": "Product carbon footprint",
                "unit": unit,
                "pcf_method_package_ref": package_ref,
                "pcf_method_package_hash": package_hash,
                "pcf_functional_unit": functional_unit,
                "pcf_boundary_claim": boundary_claim,
            }
            register(identity, scenario_id, float(raw_value))

    if 0 < lcia_scenario_count < len(scenario_results):
        raise DomainError(
            code="COMPARISON_LCIA_RESULT_MISSING",
            message="LCIA comparison requires results for every scenario",
            status_code=409,
            details={
                "scenario_count": len(scenario_results),
                "lcia_scenario_count": lcia_scenario_count,
            },
        )

    if 0 < pcf_scenario_count < len(scenario_results):
        raise DomainError(
            code="COMPARISON_PCF_RESULT_MISSING",
            message="PCF comparison requires results for every scenario",
            status_code=409,
            details={
                "scenario_count": len(scenario_results),
                "pcf_scenario_count": pcf_scenario_count,
            },
        )

    metrics: list[dict[str, Any]] = []
    for metric_key in sorted(catalog):
        identity = catalog[metric_key]
        scenario_values = {
            scenario_id: values[metric_key].get(scenario_id, 0.0)
            for scenario_id in scenario_ids
        }
        if identity["metric_kind"] == "lcia_indicator" and not any(
            value != 0 for value in scenario_values.values()
        ):
            continue
        baseline_value = scenario_values[baseline_scenario_id]
        deltas = {}
        for scenario_id, value in scenario_values.items():
            absolute = value - baseline_value
            deltas[scenario_id] = {
                "absolute": absolute,
                "relative": absolute / baseline_value if baseline_value != 0 else None,
            }
        metrics.append(
            {
                **identity,
                "baseline_value": baseline_value,
                "scenario_values": scenario_values,
                "deltas": deltas,
            }
        )
    return metrics


def render_comparison_svg(run: dict[str, Any]) -> str:
    metrics = list(run.get("metrics") or [])
    scenarios = list(run.get("scenario_results") or [])
    if not metrics or not scenarios:
        raise DomainError(
            code="COMPARISON_CHART_EMPTY",
            message="scenario comparison has no physical-flow metrics to chart",
            status_code=422,
        )
    scenario_names = {
        item["scenario_id"]: _text(item.get("scenario_name")) or item["scenario_id"]
        for item in scenarios
    }
    scenario_ids = [item["scenario_id"] for item in scenarios]
    chart_title = _text(run.get("chart_title")) or "Scenario comparison"
    chart_description = _text(run.get("chart_description")) or (
        f"{len(scenario_ids)} frozen scenarios · exact unit-series separation · "
        "baseline deltas audited"
    )
    palette = ("#2563eb", "#0f9f7f", "#e58a16", "#7c5ce0", "#d84f6f")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in metrics:
        grouped[metric["series_id"]].append(metric)

    width = 1440
    header_height = 122
    panel_gap = 26
    row_height = max(72, 22 * len(scenario_ids) + 26)
    panel_heights = {
        key: 66 + len(items) * row_height for key, items in grouped.items()
    }
    height = header_height + sum(panel_heights.values()) + panel_gap * len(grouped) + 52
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {width} {height}" preserveAspectRatio="xMinYMin meet" style="display:block;max-width:{width}px;height:auto" role="img" aria-labelledby="chart-title chart-desc">',
        "<style>text{font-family:Segoe UI,Arial,sans-serif;fill:#17324d}.title{font-size:26px;font-weight:700}.subtitle{font-size:13px;fill:#60778c}.panel-title{font-size:15px;font-weight:700}.metric{font-size:12px;font-weight:650}.bar-label{font-size:11px;font-weight:650}.legend{font-size:11px;fill:#526b80}.grid{stroke:#dde7ef;stroke-width:1}.bar{rx:5}</style>",
        '<rect width="100%" height="100%" fill="#f5f9fc"/>',
        f'<rect x="24" y="18" width="{width - 48}" height="86" rx="14" fill="#fff" stroke="#e0e9f0"/>',
        f'<text id="chart-title" x="48" y="53" class="title">{escape(chart_title)}</text>',
        f'<text id="chart-desc" x="48" y="78" class="subtitle">{escape(chart_description)}</text>',
    ]
    for index, scenario_id in enumerate(scenario_ids):
        color = palette[index % len(palette)]
        legend_x = 650 + (index % 3) * 220
        legend_y = 48 + (index // 3) * 24
        chunks.append(
            f'<circle cx="{legend_x}" cy="{legend_y}" r="5" fill="{color}"/>'
        )
        chunks.append(
            f'<text class="legend" x="{legend_x + 11}" y="{legend_y + 4}">{escape(scenario_names[scenario_id][:22])}</text>'
        )

    top = header_height
    label_width = 250
    plot_x = 304
    plot_width = width - plot_x - 116
    for series_id in sorted(grouped):
        series_metrics = grouped[series_id]
        all_values = [
            float(value)
            for metric in series_metrics
            for value in metric["scenario_values"].values()
        ]
        minimum = min([0.0, *all_values])
        maximum = max([0.0, *all_values])
        span = max(maximum - minimum, 1e-12)
        zero_x = plot_x + plot_width * (0.0 - minimum) / span
        panel_height = panel_heights[series_id]
        chunks.append(
            f'<rect x="24" y="{top}" width="{width - 48}" height="{panel_height}" rx="14" fill="#fff" stroke="#e0e9f0"/>'
        )
        first = series_metrics[0]
        chunks.append(
            f'<text class="panel-title" x="48" y="{top + 34}">{escape(first.get("unit_group_label") or first["unit_group"])} · {escape(first["unit"])}</text>'
        )
        chunks.append(
            f'<metadata>unit_series_identity={escape(series_id)}</metadata>'
        )
        for tick in range(5):
            x = plot_x + plot_width * tick / 4
            chunks.append(
                f'<line class="grid" x1="{x:.1f}" y1="{top + 50}" x2="{x:.1f}" y2="{top + panel_height - 18}"/>'
            )
        for metric_index, metric in enumerate(series_metrics):
            row_top = top + 60 + metric_index * row_height
            display_name = (
                metric["indicator_key"]
                if metric["metric_kind"] in {"lcia_indicator", "pcf_total"}
                else metric["subject_name"]
            )
            descriptor = (
                "LCIA indicator"
                if metric["metric_kind"] == "lcia_indicator"
                else "Product carbon footprint"
                if metric["metric_kind"] == "pcf_total"
                else (
                    "Input"
                    if metric["direction"] == "input"
                    else "Output"
                )
                + f" · {metric['exchange_type']}"
            )
            chunks.append(
                f'<text class="metric" x="{label_width}" y="{row_top + 16}" text-anchor="end">{escape(display_name[:24])}</text>'
            )
            chunks.append(
                f'<text class="legend" x="{label_width}" y="{row_top + 33}" text-anchor="end">{escape(descriptor)}</text>'
            )
            for scenario_index, scenario_id in enumerate(scenario_ids):
                value = float(metric["scenario_values"][scenario_id])
                bar_y = row_top + scenario_index * 22
                value_x = plot_x + plot_width * (value - minimum) / span
                bar_x = min(zero_x, value_x)
                bar_width = abs(value_x - zero_x)
                color = palette[scenario_index % len(palette)]
                chunks.append(
                    f'<rect class="bar" x="{bar_x:.1f}" y="{bar_y}" width="{bar_width:.1f}" height="14" fill="{color}" opacity=".84"><title>{escape(scenario_names[scenario_id])} · {escape(display_name)} · {_format_amount(value)} {escape(metric["unit"])}</title></rect>'
                )
                text_x = (
                    max(value_x - 8, plot_x + 48)
                    if value < 0
                    else min(value_x + 8, width - 72)
                )
                text_anchor = "end" if value < 0 else "start"
                chunks.append(
                    f'<text class="bar-label" x="{text_x:.1f}" y="{bar_y + 11}" text-anchor="{text_anchor}">{_format_amount(value)}</text>'
                )
        top += panel_height + panel_gap
    chunks.append(
        f'<text class="legend" x="48" y="{height - 25}">All bars are derived from frozen solved exchanges or provider LCIA results; hover for scenario and unit details.</text>'
    )
    chunks.append("</svg>")
    return "".join(chunks)
