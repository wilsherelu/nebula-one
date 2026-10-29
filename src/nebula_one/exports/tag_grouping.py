"""Export the persisted tag view, never re-read or recalculate mutable method state."""
from html import escape

RESULT_CATEGORY = "result_category.v1"


def render_tag_grouping_html(result: dict) -> str:
    def cell(value):
        return escape(str(value)) if value is not None else "—"

    sections = []
    result_category_flags = []
    for item in result["schemes"]:
        scheme = item["scheme"]
        result_category = item.get("semantics") == RESULT_CATEGORY
        result_category_flags.append(result_category)
        rows = "".join(f"<tr><td>{cell(row.get('name') or row['id'])}</td><td>{cell(row['subtotal'])}</td><td>{cell(row['unit'])}</td></tr>"
                       for row in item["dimension"]["categories"])
        if not result_category and item["uncategorized"].get("term_count"):
            rows += f"<tr><td>已匹配，未分类</td><td>{cell(item['uncategorized'].get('subtotal'))}</td><td>{cell(item['uncategorized'].get('unit'))}</td></tr>"
        if result_category:
            subtotal_label = "已分类贡献小计"
            counters = (f"缺少贡献数据：{cell(item['missing']['term_count'])}；"
                        f"无（未分类）：{cell(item['unmatched']['term_count'])}")
            populated = item.get("populated")
            empty_note = "" if populated is not False else "<p>尚未给任何流选择结果分类，本口径没有可归集的贡献。</p>"
        else:
            subtotal_label = "已匹配贡献小计"
            counters = (f"缺少贡献数据：{cell(item['missing']['term_count'])}；"
                        f"未匹配：{cell(item['unmatched']['term_count'])}；待确认：{cell(item['pending']['term_count'])}")
            empty_note = ""
        sections.append(f"<section><h2>{cell(scheme['name'])} · v{cell(scheme['version'])}</h2>"
                        f"{empty_note}"
                        f"<p>{subtotal_label}：{cell(item['tag_total']['value'])} {cell(item['tag_total']['unit'])}</p>"
                        f"<p>{counters}</p>"
                        f"<table><thead><tr><th>分类</th><th>贡献</th><th>单位</th></tr></thead><tbody>{rows}</tbody></table></section>")
    selected = result.get(result["mode"])
    set_total = ""
    if selected:
        label = "并集" if result["mode"] == "union" else "交集"
        set_total = f"<p>{label}已知贡献小计：{cell(selected['value'])} {cell(selected['unit'])}；缺少贡献数据：{cell(selected.get('missing_count', 0))}</p>"
    if all(result_category_flags):
        title = "结果分类归集结果"
        intro = "结果按已分类贡献归集；选择“无”的流不参与本口径；缺少因子或背景数据不代表零排放。不同分类口径的结果可能重叠。"
    elif any(result_category_flags):
        title = "结果归集结果"
        intro = "结果按各自口径归集；缺少因子或背景数据不代表零排放。不同口径的结果可能重叠。"
    else:
        title = "标签归集结果"
        intro = "结果按已匹配贡献归集；缺少因子或背景数据不代表零排放。不同标签的结果可能重叠。"
    return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>" + title + "</title>"
            "<style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:0 24px;color:#182230}"
            "table{border-collapse:collapse;width:100%}th,td{padding:10px;border-bottom:1px solid #ddd;text-align:left}section{margin:28px 0}</style>"
            f"<h1>{title}</h1><p>保存时间：{cell(result.get('created_at'))}</p>"
            f"<p>{intro}</p>"
            + set_total + "".join(sections)
            + f"<details><summary>来源与版本</summary><p>结果：{cell(result['result_id'])}</p><p>内容摘要：{cell(result['content_sha256'])}</p><p>计算快照：{cell(result['snapshot_id'])}</p></details></html>")
