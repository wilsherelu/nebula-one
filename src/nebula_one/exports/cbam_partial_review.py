"""Human-readable audit note for a steel CBAM partial calculation."""
from __future__ import annotations


def render_cbam_partial_review_markdown(result: dict) -> str:
    direct = result["components"]["direct"]
    indirect = result["components"]["sinter_precursor_indirect"]
    electricity = indirect["electricity_activity"]
    factor_note = ("适用的 CBAM 电力排放因子尚未绑定，因此该间接排放分项没有数值。"
                   if indirect["value"] is None else
                   f"按登记因子包 `{indirect['eligible_factor']['package_reference']}` "
                   f"（内容哈希 `{indirect['eligible_factor']['package_content_sha256']}`）计算的间接分项为 "
                   f"**{indirect['value']} {indirect['unit']}**。")
    total = result["specific_embedded_emissions"]
    total_note = ("归属条件或因子尚未齐备，完整嵌入排放未给出数值。" if total["value"] is None else
                  f"依据已提交的条件声明，选定边界合计为 **{total['value']} {total['unit']}**；"
                  "仍需独立核验，不能直接作为正式申报。")
    declarations = (result["coverage"].get("condition_declarations") or {})
    declaration_note = "".join(f"- {key}：{value['status']}，证据 SHA-256 `{value['evidence_sha256']}`\n"
                               for key, value in sorted(declarations.items()))
    coverage_note = ''.join(f"- {row['item']}：{row['state']}。{row.get('effect', '')}\n"
                            for row in result['coverage'].get('source_streams', []))
    return (
        "# 钢铁 CBAM 计量复核\n\n演示数据；结果不完整；未核查；不可正式申报。\n\n"
        f"本次复核对应冻结快照 `{result['source_snapshot']['id']}`、数据修订 "
        f"`{result['source_snapshot']['system_revision_id']}` 和方法 "
        f"`{result['method_package']['reference']}`。已核算的直接排放分项为 "
        f"**{direct['value']} {direct['unit']}**。这只是此前边界算出的分项，不能当作完整嵌入排放。\n\n"
        f"烧结过程的购电投入为 {electricity['source_value']} {electricity['source_unit']}，"
        f"按本次产品产量归一化后为 **{electricity['value']} {electricity['unit']}**。"
        f"{factor_note}{total_note}不能以 LCA 生命周期电力 GWP 代替该因子。\n\n"
        f"条件声明：\n{declaration_note or '尚无完整条件声明。'}\n"
        f"案例源流覆盖：\n{coverage_note or '以所列冻结边界及缺项为准。'}\n"
        "同设施联合生产的前体归属、煤气跨过程或外供、烟气净化排放仍需逐项证明。"
        "旧版直接排放试算的通过状态不代表这些事项已被验证，也不构成所谓保守上界。"
        "当前公开方法不附带商业或法律因子数值。\n\n"
        "核对依据：[欧委会 CBAM 法规与指南入口](https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism/cbam-legislation-and-guidance_en)、"
        "[欧委会计量指南 No. 3](https://taxation-customs.ec.europa.eu/document/download/29b9eec7-1a4b-4eb6-ab85-96a0c9e35fd0_en)。\n\n"
        f"快照哈希：`{result['source_snapshot']['content_sha256']}`。"
        f"直接分项结果哈希：`{result['source_direct_result_sha256']}`。"
        f"复核结果哈希：`{result['content_sha256']}`。\n"
    )
