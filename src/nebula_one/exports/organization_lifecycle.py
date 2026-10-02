"""Standalone report for Nebula authored organization lifecycle carbon results."""
from __future__ import annotations

from html import escape


def _uncharacterized_html(result: dict, *, english: bool = False) -> str:
    terms = (result.get("climate_source") or {}).get("uncharacterized_terms") or []
    unassigned = (result.get("climate_source") or {}).get("unassigned_suppliers") or []
    supply_html = ""
    if unassigned:
        message = ("These supplies are not grouped by this method and are excluded from the results and total."
                   if english else "以下背景贡献尚不支持归组，未计入三组结果或合计。")
        supply_html = f"<p>{message}</p><ul>" + "".join(
            f"<li>{escape(row['consumer_exchange_id'])}: {escape(str(row['contribution_value']))} kg CO2-Eq</li>"
            for row in unassigned) + "</ul>"
    if not terms:
        return supply_html
    message = (f"{len(terms)} inventory flows are not characterized by this climate method; no numeric contribution is assigned."
               if english else f"有 {len(terms)} 项清单流未被本气候方法表征，未计入气候贡献。")
    title = "Flow identities" if english else "流身份详情"
    rows = "".join(f"<li>{escape(str(term['flow_uuid']))}@{escape(str(term.get('flow_version') or ''))} · "
                   f"{escape(str(term['exchange_id']))} · {escape(str(term.get('amount')))} "
                   f"{escape(str(term.get('amount_unit') or ''))}</li>" for term in terms)
    return supply_html + f"<p>{message}</p><details><summary>{title}</summary><ul>{rows}</ul></details>"


def _category_supply_html(item: dict) -> str:
    return "".join(
        f"<br><small>{escape(row['consumer_exchange_id'])} · "
        f"{escape(str(row['contribution_value']))} kg CO2-Eq · {escape(row['status'])} · "
        f"{escape(row['project_id'])}@{row['version']} · SHA-256 {escape(row['source_graph_hash'])}</small>"
        for row in item.get("supply_receipts", [])) + "".join(
        f"<br><small>{escape(exchange_id)}: —</small>" for exchange_id in item.get("missing_exchange_ids", []))


def render_organization_lifecycle_html(record: dict, *, english_labels: dict | None = None) -> str:
    if english_labels is not None:
        return _render_english(record, english_labels)
    result = record["result"]
    groups = result["groups"]
    labels = (("on_site_direct", "范围 1：厂内直接排放"),
              ("purchased_energy_lifecycle", "范围 2：外购能源相关排放"),
              ("other_value_chain", "范围 3：其他上下游排放"))
    def amount(value: float | None, missing: str) -> str:
        return missing if value is None else f"{value:.9g} kg CO2-Eq"

    rows = "".join(
        f"<tr><th>{label}</th><td>{amount(groups[key]['value'], '未计算')}</td>"
        f"<td>{escape(groups[key]['status'])}</td></tr>" for key, label in labels
    )
    categories = "".join(
        f"<li>{escape(item['name'])}：{('本次边界外' if item.get('boundary_status') == 'not_in_boundary' else amount(item['value'], '缺活动数据'))}"
        + "".join(f"<br><small>因子来源 {escape(activity['factor_source'])}，版本 {escape(activity['factor_version'])}，"
                  f"SHA-256 {escape(activity['evidence_sha256'])}</small>" for activity in item["activities"])
        + _category_supply_html(item)
        + (f"<br><small>公开示例代理参考量 {amount(item.get('proxy_reference_value'), '无')}；不计入已核算值或合计。</small>"
           if item.get("proxy_reference_value") is not None else "")
        + "</li>" for item in groups["other_value_chain"]["categories"]
    )
    total = amount(result["combined_total"], "所选边界有缺项或示例代理因子，未给出合计")
    excluded = [item["name"] for item in groups["other_value_chain"]["categories"]
                if item.get("boundary_status") == "not_in_boundary"]
    basis = result["activity_basis"]
    period_name = "基于当前生产模型" if basis["mode"] == "current_model_total" else result['reporting_period']['name']
    basis_label = "当前模型总量" if basis["mode"] == "current_model_total" else basis['mode']
    return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>LCA 一致型组织碳核算</title>"
            "<style>body{font:16px/1.7 sans-serif;max-width:850px;margin:40px auto;color:#182b3a}"
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd6df;padding:10px;text-align:left}"
            "small{overflow-wrap:anywhere}</style>"
            f"<h1>LCA 一致型组织碳核算</h1><p>{escape(result['facility'])} · "
            f"{escape(period_name)}</p>"
            f"<p>输入基准：{escape(basis_label)}；模型产量 {basis['baseline_output']:.9g} kg，"
            f"期间产量 {basis['period_output']:.9g} kg，缩放系数 {basis['scale_factor']:.9g}。</p>"
            f"<table><thead><tr><th>归组</th><th>排放量</th><th>状态</th></tr></thead><tbody>{rows}</tbody></table>"
            f"<p>所选边界合计：{escape(total)}；本次边界外：{escape('、'.join(excluded) or '无')}。"
            f"该合计不代表完整生命周期排放。</p><h2>其他上下游活动</h2><ul>{categories}</ul>"
            "<p>这是 Nebula 自定义的 LCA 一致型组织归组方法，不是 GHG Protocol 范围 1–3，"
            "也不代表 ILCD 认可本分类。覆盖由当前模型、供应路径及已提供因子决定。</p>"
            + _uncharacterized_html(result)
            + f"<small>方法 {escape(result['method_package']['reference'])} · 方法哈希 "
            f"{escape(result['method_package']['content_sha256'])}<br>快照 "
            f"{escape(result['source_snapshot']['id'])} · 快照哈希 "
            f"{escape(result['source_snapshot']['content_sha256'])}<br>结果哈希 "
            f"{escape(record['content_sha256'])}</small></html>")


def _render_english(record: dict, labels: dict) -> str:
    result = record["result"]
    groups = result["groups"]
    def amount(value: float | None, missing: str) -> str:
        return missing if value is None else f"{value:.9g} kg CO2-Eq"
    group_names = (("on_site_direct", "Scope 1: on site direct emissions"),
                   ("purchased_energy_lifecycle", "Scope 2: purchased energy related emissions"),
                   ("other_value_chain", "Scope 3: other upstream and downstream emissions"))
    rows = "".join(
        f"<tr><th>{escape(name)}</th><td>{amount(groups[key]['value'], 'Not calculated')}</td>"
        f"<td>{escape(labels['group_status'].get(groups[key]['status'], groups[key]['status']))}</td></tr>"
        for key, name in group_names
    )
    category_rows = groups["other_value_chain"]["categories"]
    categories = "".join(
        f"<li>{escape(labels['categories'][item['category']])}: "
        f"{('Outside the selected boundary' if item.get('boundary_status') == 'not_in_boundary' else amount(item['value'], 'Activity data missing'))}"
        + "".join(f"<br><small>Factor source {escape(activity['factor_source'])}, version "
                  f"{escape(activity['factor_version'])}, SHA-256 {escape(activity['evidence_sha256'])}</small>"
                  for activity in item["activities"])
        + _category_supply_html(item)
        + (f"<br><small>Public example proxy reference {amount(item.get('proxy_reference_value'), 'None')}; "
           "excluded from the calculated amount and total.</small>"
           if item.get("proxy_reference_value") is not None else "")
        + "</li>" for item in category_rows
    )
    excluded = [labels["categories"][item["category"]] for item in category_rows
                if item.get("boundary_status") == "not_in_boundary"]
    basis = result["activity_basis"]
    total = amount(result["combined_total"], "No total: the selected boundary has missing activities or example proxy factors")
    period = result["reporting_period"]
    period_name = (f"{period['start_date']}—{period['end_date']}"
                   if period.get("start_date") and period.get("end_date") else period["name"])
    if basis["mode"] == "current_model_total":
        period_name = "Based on the current production model"
    basis_label = "Current model total" if basis["mode"] == "current_model_total" else labels['input_basis'][basis['mode']]
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><title>Organizational lifecycle carbon accounting</title>"
            "<style>body{font:16px/1.7 sans-serif;max-width:850px;margin:40px auto;color:#182b3a}"
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd6df;padding:10px;text-align:left}"
            "small{overflow-wrap:anywhere}</style>"
            f"<h1>Organizational lifecycle carbon accounting</h1><p>{escape(result['facility'])} · "
            f"{escape(period_name)}</p>"
            f"<p>Input basis: {escape(basis_label)}; model output "
            f"{basis['baseline_output']:.9g} kg; period output {basis['period_output']:.9g} kg; "
            f"scale factor {basis['scale_factor']:.9g}.</p>"
            f"<table><thead><tr><th>Group</th><th>Emissions</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>"
            f"<p>Selected boundary total: {escape(total)}; outside this boundary: "
            f"{escape(', '.join(excluded) or 'None')}. This is not a complete lifecycle inventory.</p>"
            f"<h2>Other upstream and downstream activities</h2><ul>{categories}</ul>"
            "<p>These Nebula authored lifecycle groups are not GHG Protocol scopes 1–3 or an ILCD endorsed "
            "classification. Coverage depends on the current model, supplier paths, and provided factors.</p>"
            + _uncharacterized_html(result, english=True)
            + f"<small>Method {escape(result['method_package']['reference'])} · method hash "
            f"{escape(result['method_package']['content_sha256'])}<br>Snapshot "
            f"{escape(result['source_snapshot']['id'])} · snapshot hash "
            f"{escape(result['source_snapshot']['content_sha256'])}<br>Result hash "
            f"{escape(record['content_sha256'])}</small></html>")
