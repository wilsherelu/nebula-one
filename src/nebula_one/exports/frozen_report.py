"""Full-row exports of the same frozen report projection shown in One."""
from html import escape
from io import BytesIO
import re

from openpyxl import Workbook


STATUS_LABELS = {
    "counted": "已计入", "not_counted": "未计入", "applicable_pending_factor": "适用因子待补",
    "excluded_with_basis": "按边界未计入", "not_applicable_with_basis": "有依据不适用",
    "internal_transfer_netted_inside_the_boundary": "内部转移，不重复计入",
    "reference_product_output_is_the_denominator": "核算产品基准",
    "method_has_no_cf": "本气候方法未表征，未计入；适用范围未判定",
    "explicit_zero_cf": "方法明确提供零因子，已表征",
    "calculated_from_controlled_foreground": "已按厂内模型计算", "calculated": "已计算",
    "calculated_from_exclusive_energy_background_paths": "已按所关联能源路径计算", "configured_categories": "已按所选边界计算",
    "open_coverage_limitation": "覆盖条件待补",
    "partial_characterization": "部分流已表征", "partial_activity": "部分已计算", "partial": "尚有缺项",
    "missing_activity": "尚缺活动数据或背景关联", "required_missing": "所需数据待补",
    "missing_energy_path": "能源背景路径待补", "not_in_boundary": "本次边界外",
    "missing_data": "数据待补", "applicability_unknown": "适用条件待确认",
    "case_not_modelled": "本例尚未建模", "demonstration_assumption": "演示假设，需实测依据",
    "proxy_reference_only": "仅供代理参考，未计入合计", "unassigned": "归组待确认",
}
GROUP_LABELS = {"user_excluded": "用户排除", "engine_gap": "引擎归属待补", "direct": "直接排放", "indirect": "间接排放", "on_site_direct": "厂内直接排放",
                "purchased_energy_lifecycle": "外购能源相关排放", "other_value_chain": "其他上下游排放", "unassigned": "归组待确认"}


def presentation(report):
    status = STATUS_LABELS
    groups = GROUP_LABELS
    if report.get("language") == "en":
        status = {"counted": "Included", "not_counted": "Not included", "explicit_zero_cf": "Characterized with an explicit zero factor",
                  "method_has_no_cf": "Not characterized by this method; applicability undetermined",
                  "missing_activity": "Activity data or supply link missing", "not_in_boundary": "Outside this boundary",
                  "required_missing": "Required data missing", "partial": "Partially calculated"}
        groups = {"user_excluded": "User excluded", "engine_gap": "Engine attribution gap", "direct": "Included direct emissions", "indirect": "Indirect emissions",
                  "on_site_direct": "On site direct emissions", "purchased_energy_lifecycle": "Purchased energy lifecycle emissions",
                  "other_value_chain": "Other value chain emissions", "unassigned": "Grouping pending"}
    return {**report, "status_labels": {**status, **report.get("status_labels", {})}, "group_labels": groups}


def report_tables(report):
    group = lambda value: GROUP_LABELS.get(value, value)
    status = lambda value: STATUS_LABELS.get(value, value)
    def source_rows(value, path=""):
        if isinstance(value, dict):
            return [row for key, item in value.items() for row in source_rows(item, f"{path}.{key}" if path else key)]
        if isinstance(value, list):
            return [row for index, item in enumerate(value) for row in source_rows(item, f"{path}[{index}]" )] or [[path, "[]"]]
        return [[path, value]]
    details = [[group(r["group"]), r.get("process_name") or "未提供过程名称", r.get("flow_name") or "未提供流名称",
                r["quantity"], r["quantity_unit"], r["contribution_value"], r["contribution_unit"], status(r["status"]), r.get("basis")]
               for r in report["details"]]
    return [
        *[(dim['name'], ['分组','排放量','单位'], [[cat['name'],cat['subtotal'],cat['unit']]
           for cat in dim['categories'] if cat['is_leaf']]) for dim in report.get('custom_dimensions',[])],
        ("摘要", ["归组", "排放量", "单位", "状态"], [[group(r["group"]), r["value"], r["unit"], status(r["status"])] for r in report["summary"]]),
        ("冻结输入", ["过程", "流", "方向", "数量", "单位", "交换身份"],
         [[r["process"], r["label"], {"input":"投入", "output":"产出", "emission":"排放", "emissions":"排放"}.get(r["group"], r["group"]), r["value"], r["unit"], r["key"]] for r in report["inputs"]]),
        ("过程贡献", ["归组", "过程", "计入排放量", "单位"],
         [[group(r["group"]), r.get("process_name") or "未提供过程名称", r["contribution_value"], r["contribution_unit"]] for r in report["process_contributions"]]),
        ("核算明细", ["归组", "过程", "流", "原始数量", "原始单位", "计入排放量", "排放单位", "状态", "依据"], details),
        ("缺项", ["事项", "状态", "说明"], [[r.get("name") or "未提供事项名称", status(r["status"]), r.get("basis")] for r in report["gaps"]]),
        ("边界外", ["事项", "状态"], [[r["name"], status(r["status"])] for r in report["outside_boundary"]]),
        ("未表征流", ["过程", "流", "数量", "单位", "状态"], [[r.get("process_name") or "未提供过程名称", r.get("flow_name") or "未提供流名称", r["quantity"], r["quantity_unit"], status(r["status"])] for r in report["uncharacterized"]]),
        ("方法及来源", ["字段", "内容"], source_rows({"snapshot_id": report["snapshot_id"], "revision_id": report["revision_id"], "record_id": report.get("record_id"), "method_name": report.get("method_name"), "method_version": report["method_version"], "basis": report["basis"], "demand": report["demand"], "complete_total": report["complete_total"], **report["sources"]})),
    ]


def export_frozen_report_xlsx(report):
    book = Workbook()
    book.remove(book.active)
    for name, headings, rows in report_tables(report):
        sheet = book.create_sheet(re.sub(r'[\\/*?:\[\]]', '_', name)[:31] or 'Sheet')
        sheet.append(headings)
        for row in rows:
            # Null is intentionally blank, not zero. Keep Decimal strings losslessly in the file.
            sheet.append([value if not isinstance(value, str) or not value.startswith("=") else "'" + value for value in row])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def render_frozen_report_html(report):
    def cell(value):
        return escape(str(value)) if value is not None else "未计算"
    sections = []
    for name, headings, rows in report_tables(report):
        if name == "冻结输入":
            headings, rows = headings[:-1], [row[:-1] for row in rows]
        table = '<table><thead><tr>' + ''.join(f'<th>{cell(h)}</th>' for h in headings) + '</tr></thead><tbody>'
        table += ''.join('<tr>' + ''.join(f'<td>{cell(v)}</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table>'
        sections.append(f'<section><h2>{name}</h2>{table}</section>' if name != "方法及来源" else f'<details><summary>方法及来源附录</summary>{table}</details>')
    note = "完整合计未计算；已计算部分见下表。" if report["complete_total"] is None else "合计仅反映该记录已声明的数据边界。"
    basis = report["basis"]
    quantity = basis.get("period_output", basis.get("source_value"))
    unit = basis.get("unit") if "period_output" in basis else basis.get("source_unit")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{cell(report["title"])}</title>
<style>body{{font:15px/1.6 system-ui,sans-serif;max-width:1200px;margin:24px auto;padding:0 24px;color:#17243b}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d9e0e9;padding:8px;text-align:left;overflow-wrap:anywhere}}th{{background:#f4f7fb}}section{{margin:24px 0}}@media print{{button{{display:none}}details>table{{display:table}}body{{margin:0;max-width:none}}}}</style></head><body>
<button onclick="window.print()">打印 / 另存 PDF</button><h1>{cell(report["title"])}</h1>
<p>{note} 按当前生产模型及所列方法评价，未覆盖部分另列；本报告不是完整监管申报或完整组织盘查声明。</p>
<p>核算生产量：{cell(quantity)} {cell(unit)}；方法版本：{cell(report["method_version"])}</p>{''.join(sections)}</body></html>'''
