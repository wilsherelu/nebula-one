# `pcf.product.v1` 前景边界产品碳足迹

`pcf.product.v1` 是 Nebula One 的产品碳足迹应用。它不新增求解器，也不在应用层维护排放因子，而是读取 Nebula LCA 已冻结的 `SolvedSystemSnapshot`，按版本化 `MethodPackage` 选择 EF 3.1 气候变化结果，并生成带内容哈希、功能单位、边界声明、贡献热点和 provider 凭据的确定性结果。

## 当前适用边界

第一版只支持 `foreground_boundary`。结果可以用于模型验证、热点识别和方案比较，但不能称为完整生命周期产品声明、认证 PCF 或法规结论。只有背景 Process 已精确固定并由 provider 回传相应 receipts 时，结果才会标记为 `foreground_with_pinned_background`；即便如此，本合同仍保持 `complete_product_declaration=false`。

功能单位来自生成该快照的 `solve.nebula.v1` 运行参数，必须是唯一且结构化的 demand，包含产品 Flow UUID、数量、单位及单位组版本。
demand 选择器因此不是自由选择的：`ProviderDemandItem` 允许 `process_uuid` / `reference_exchange_id` / `reference_flow_uuid` 三选一，
但功能单位必须落在产品 Flow 身份上，所以按前两种选择器求解的快照只能产出 MFA/CBAM，`POST …/product-carbon-footprint` 会以
422 `PCF_FUNCTIONAL_UNIT_INVALID`（`missing: ["reference_flow_uuid"]`）拒绝，PCF 求解必须以 `reference_flow_uuid` 发起。
（实测出处：`runtime/seed-install-2026-09-18/evidence/segment9-slice5b-1.3.0-01/pcf.json`，该次 seed 求解用
`reference_exchange_id` 选择 demand。）LCIA 总值直接采用 provider 返回的唯一 `climate change` 指标，不在 Nebula One 中重算或拼接因子。

当 provider 返回带哈希的 `indicator_contribution_receipts` 时，PCF 会逐项核对贡献 term 与冻结的 scaled elementary exchange、基本流版本、CF 哈希、solve hash 和 runtime assets，然后按贡献绝对值生成 Process/Exchange/基本流热点。缺少这组 receipts 不影响已验证的总值，但热点状态为 `unavailable`；无论哪种情况都不会按清单数量自行推断贡献。

## 最小调用链

1. 注册 `examples/pcf-product-gold-standard/method-package.json`；
2. 对冻结 System revision 调用 solve-and-freeze，并请求 `EF v3.1`；
3. 调用 `POST /api/v1/solved-system-snapshots/{snapshot_id}/product-carbon-footprint`，请求体仅包含精确 `method_package_ref`；
4. 保存返回结果及 `content_sha256`，图表和报告只消费该结果。

只读导出接口：

- `GET /api/v1/solved-system-snapshots/{snapshot_id}/product-carbon-footprint/export.xlsx?method_package_ref=...`
- `GET /api/v1/solved-system-snapshots/{snapshot_id}/product-carbon-footprint/report.html?method_package_ref=...`

Excel 包含核算摘要、LCIA 结果、贡献热点和审计追溯。HTML 是自包含技术核算报告，浏览器中的“打印 / 另存 PDF”使用同一结果源。两个响应都通过 `X-Nebula-Result-SHA256` 和 `ETag` 绑定对应 PCF 结果，不把导出文件作为新的计算来源。

缺少结构化功能单位、方法不匹配、总指标不唯一、单位不是方法包声明单位或缺少基本流 receipts 时，接口均 fail closed。金标准规定：`1 kg` 产品系统排放 `2 kg` EF 3.1 化石 CO₂ 时，总足迹为 `2 kg CO2-Eq`，化石分量同为 `2 kg CO2-Eq`，生物源和土地利用分量为零。
