"""Small standalone report for a persisted organization-period result."""
from __future__ import annotations

from html import escape


def render_organization_period_html(record: dict) -> str:
    result = record["result"]
    period = result["reporting_period"]
    scope = result["scopes"]
    rows = []
    for key, label in (("scope_1", "范围 1"), ("scope_2", "范围 2"), ("scope_3", "范围 3 已覆盖类别")):
        item = scope[key]
        value = "未计算" if item["value"] is None else f'{item["value"]:.9g} {item["unit"]}'
        rows.append(f"<tr><th>{label}</th><td>{escape(value)}</td><td>{escape(item['status'])}</td></tr>")
    categories = "".join(
        f"<li>{escape(item['name'])}: {escape(item['status'])}"
        + (f"，{item['value']:.9g} {escape(item['unit'])}" if item["value"] is not None else "")
        + "".join("<br><small>来源 " + escape(activity["factor_source"])
                  + " · 版本 " + escape(activity["factor_version"])
                  + " · SHA-256 " + escape(activity["evidence_sha256"]) + "</small>"
                  for activity in item.get("activities", []))
        + "</li>" for item in scope["scope_3"]["categories"]
    )
    total = "未提供完整合计" if result["combined_total"] is None else f'{result["combined_total"]:.9g} kg CO2-Eq'
    background = result.get("unclassified_background_reference")
    background_note = (f"<p>待分类电力生命周期背景参考量：{background['value']:.9g} {escape(background['unit'])}；"
                       "未计入范围 2 或组织合计。</p>") if background else ""
    return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<title>组织期间温室气体清单</title><style>body{font:16px/1.7 sans-serif;max-width:850px;margin:40px auto;color:#182b3a}"
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd6df;padding:10px;text-align:left}small{overflow-wrap:anywhere}</style>"
            f"<h1>组织期间温室气体清单</h1><p>{escape(result['organizational_boundary']['facility'])} · "
            f"{escape(period['name'])}（{escape(period['start_date'])}—{escape(period['end_date'])}）</p>"
            f"<p>期间产量 {result['activity_basis']['period_output']:.9g} {escape(result['activity_basis']['output_unit'])}；"
            f"模型基准 {result['activity_basis']['baseline_output']:.9g} {escape(result['activity_basis']['output_unit'])}</p>"
            f"<table><thead><tr><th>范围</th><th>排放量</th><th>状态</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
            f"<p>合计：{escape(total)}</p>{background_note}<h2>范围 3 类别</h2><ul>{categories}</ul>"
            "<p>本结果只覆盖当前模型、已关联电力背景及有独立证据的供应商活动；不是完整企业盘查或核证声明。</p>"
            f"<small>方法 {escape(result['method_package']['reference'])} · 方法哈希 {escape(result['method_package']['content_sha256'])}<br>"
            f"快照 {escape(result['source_snapshot']['id'])} · 快照哈希 {escape(result['source_snapshot']['content_sha256'])}<br>"
            f"结果哈希 {escape(record['content_sha256'])}</small></html>")
