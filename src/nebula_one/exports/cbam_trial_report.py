"""Small, self-contained HTML report for a frozen CBAM rule trial."""
from html import escape


def _text(value):
    return escape(str(value if value is not None else ""))


def render_cbam_trial_html(result: dict) -> str:
    specific = result["specific_embedded_emissions"]
    direct = result["attributed_emissions"]["direct"]
    rows = "".join(
        f"<tr><td>{_text(item.get('exchange_id'))}</td>"
        f"<td>{_text(item.get('emission_kind'))}</td>"
        f"<td>{_text(item.get('amount'))}</td>"
        f"<td>{_text(item.get('unit'))}</td></tr>"
        for item in direct.get("exchanges", [])
    )
    open_items = "".join(
        f"<li><strong>{_text(item.get('clause'))}</strong> "
        f"{_text(item.get('item'))}：{_text(item.get('effect'))}</li>"
        for item in (result.get("coverage") or {}).get("open_items", [])
    )
    method = result["method_package"]
    snapshot = result["source_snapshot"]
    goods = result["goods"]
    activity = result["activity_level"]
    partial = specific.get("partial_result") is True
    displayed_value = specific.get("partial_value", specific.get("value")) if partial else specific.get("value")
    label = "已量化排放小计" if partial else "所选边界试算值"
    complete_note = "演示数据；结果不完整；未核查；不可正式申报。完整嵌入排放：未计算。" if partial else "未核查；不可正式申报。"
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>CBAM 规则试算报告</title>
<style>body{{font:15px/1.55 system-ui,sans-serif;max-width:940px;margin:40px auto;padding:0 24px;color:#17243b}}
h1{{font-size:25px}}h2{{font-size:18px;margin-top:30px}}.note{{padding:12px 16px;background:#fff7e8;border-left:4px solid #ed9a27}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d9e0e9;padding:8px;text-align:left}}
th{{background:#f4f7fb}}.value{{font-size:28px;font-weight:700}}.identity{{overflow-wrap:anywhere;color:#536177}}
@media print{{body{{margin:0;max-width:none}}}}</style></head><body>
<h1>CBAM 规则试算报告</h1>
<p class="note">本结果按所列模型、方法和冻结边界计算，属于规则试算，不是申报结论。未决事项见文末。</p>
<p class="note">{complete_note}</p>
<p class="value">{label}：{_text(displayed_value)} {_text(specific.get('unit'))}</p>
<table><tbody><tr><th>商品 / CN 编码</th><td>{_text(goods.get('aggregated_goods_category'))} / {_text(goods.get('cn_code'))}</td></tr>
<tr><th>活动水平</th><td>{_text(activity.get('value'))} {_text(activity.get('unit'))}</td></tr>
<tr><th>归属直接排放</th><td>{_text(direct.get('value'))} {_text(direct.get('unit'))}</td></tr>
<tr><th>结果状态</th><td>{_text(result.get('status'))}</td></tr></tbody></table>
<h2>计入的直接排放明细</h2><table><thead><tr><th>交换</th><th>类型</th><th>数量</th><th>单位</th></tr></thead><tbody>{rows}</tbody></table>
<h2>方法与冻结依据</h2><p class="identity">方法：{_text(method.get('ref'))}<br>
方法哈希：{_text(method.get('content_sha256'))}<br>
求解快照：{_text(snapshot.get('id'))}<br>
快照哈希：{_text(snapshot.get('content_sha256'))}<br>
试算结果哈希：{_text(result.get('content_sha256'))}</p>
<h2>边界未决事项</h2>{f'<ul>{open_items}</ul>' if open_items else '<p>冻结边界未列出未决事项。</p>'}
</body></html>"""
