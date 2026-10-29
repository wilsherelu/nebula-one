# Flow 标签与结果归集：Qoder 后续开发方案

2026-10-28 · revision 2 · 状态：用户否定上一版产品逻辑，待 Qoder 按下述修订实施。本文是本轮唯一实施入口。

## 0. 最新修订：以结果分类为主线（优先于下文历史内容）

### 2026-10-29 交互补充（优先于旧批量栏和分类弹窗要求）

用户要求分类在主界面直接新增、改名、删除，移除“顶级分类/添加子分类”操作；已有层级数据保留，不重写历史。删除仍先确认影响数量及重归类或设“无”。批量栏改为清单底部常驻，未选时说明勾选用途并禁用应用，不再选中后突然出现。编辑器固定在视口内，过程和流清单内部滚动，全局不滚动。

“放弃草稿”改称“撤销本次未保存修改”，仅撤销并留在当前页；返回保留原离开确认流程。CO₂同名项保留精确交换身份，并展示模型自带 `display_description`：示例中分别为焦粉燃烧和烧结熔剂中碳酸盐分解，不合并、不按端口名硬编码来源。

本轮由主代理独立实施，无子代理。方法页47项、typecheck/build、真实浏览器模板链10项通过；新增 `scripts/ui_inline_categories_acceptance.mjs` 验证四视口无全局横纵滚动、批量栏始终可见、选择启用及两条CO₂来源。证据 `.local-evidence/inline-category-20261029/`。用户体验待用户确认。

### Codex 接回结论（2026-10-28，基于 `2e507a4`）

**R4 暂不通过交付门禁，先完成 R5。** 新结果分类路径及截图已有改进，但旧用户入口和转换契约仍有两项阻断。编写本记录前工作树干净；Codex 独立执行 `tests/test_result_category.py`，12 passed、exit 0，说明现有测试未覆盖正确的兼容目标。未生成新安装包；本地编译产物不等于已交付包。

| 阻断 | 已核实行为 | R5 必须修改与验收 |
| --- | --- | --- |
| P1：截图对应的旧普通方法仍能编辑计入 | `MethodEditor.tsx` 仅把 `flow_tag.v1` 判为旧方案；`semantics=null` 仍进入可编辑 `ScopePanel`。后端保存/复制拦截也只覆盖旧标签；`_conversion_source` 对 null 返回422。用户原有普通方法会继续看到“是否计入”，没有升级路径 | 同时覆盖旧普通方法和旧标签。旧配置在结果分类管理中只读并有转换入口，后端写入和能力声明一致；正式CBAM/组织/PCF执行与历史回放不改变。多维或仅scope旧配置须明确选择/映射目标分类并预览，不能猜测或丢弃。新增 null 语义方法的项目/模板真实浏览器用例和 API 反例，不能只测 flow_tag |
| P1：无效分类可被丢弃后转换 | `_conversion_plan` 对未知分类/父级分类记录 `invalid_category`，但 `can_convert` 只阻部分冲突，仍允许转成“无”；`test_conversion_preview_maps_every_legacy_outcome` 还把这一行为断言为True | 对无效分类阻止应用转换；提供在转换草稿中修复映射的操作，不要求编辑已只读的来源。预览和应用使用同一映射，服务端拒绝未解决冲突；用户可明确重映射到合法叶子或主动选择“无”，再显示影响并确认。修正固化错误语义的测试，旧版本/结果字节不变 |

R5 完成后回交实际提交、两项反例修复证据及受影响回归；再接续包内验收。不扩大到专用核算策略，也不覆盖上一安装文件。

### 0.1 用户要完成什么

先定义结果分类，再把具体过程中的流分到相应分类。CBAM、范围1–3、碳市场、CCER、地区碳排放双控等都是用户可定义的分类口径，不能把 CBAM 做成与分类工作流并列的特殊“计入方法”。选了分类，才进入该分类的计算归集；选“无”，就不参与该口径的归集。默认 LCA、产品碳足迹始终按完整物理模型正常计算，不受这些分类选择影响。

本节替代旧文中的“标签匹配本身即可进入归集”“已匹配，未分类仍参与计算”“新建标签方案与新建用户方法并列”等要求。后文 F0–F4 和历史验收只证明当时实现，不代表满足本次修订；不得用旧测试数量宣布本轮产品通过。

### 0.2 当前事实与改动边界

基线：`D:/VibeCoding/project/nebula-one`，`main @ 526c1c8`，编写本节前工作树干净。上一包 One 为 `163040f`，位于 `D:/VibeCoding/releases/nebula-one/20261028-0.1.1-flow-tags/`。用户截图确实展示旧式计入编辑器，但截图不能单独确定正在运行的安装版本。

已核实：`MethodList.tsx` 仍提供标签与普通用户方法两个新建入口，`MethodEditor.tsx` 根据版本 `semantics` 分派 `TagSchemeEditor` 或 `ScopePanel`，因此新包内也保留了进入旧交互的路径。Qoder 必须核验模板、项目、已有方法、复制方法四类入口，不能只修一个截图或声称用户用错版本。

只修改 One 内相关前后端、迁移、测试与本文回交记录；LCA 引擎只读。保留旧方案、冻结结果、原始库、旧包和用户实例。最小 UTF-8 patch，不整文件重写；Qoder 不使用 PowerShell，可用 Git Bash/cmd 与固定 Python `C:/Users/31534/PycharmProjects/ILCD/.venv/Scripts/python.exe`。允许本地提交，禁止 push、PR、Release、GitHub 连接和云部署。此交接不自动启动外部 Qoder。

### 0.3 页面和操作顺序

统一入口为“结果分类”。默认 LCA/产品碳足迹仍在原有计算入口；不要再要求用户新建或复制这两类默认计算方法。自定义结果配置不再提供普通方法/标签两条新建分支。

1. 用户先创建分类口径，例如“CBAM”或“范围1–3”，并定义其分类。简单口径可直接建立同名分类；需要分组时可定义叶子分类，例如 CBAM 下的直接、间接，或范围1–3下的范围1、范围2、范围3。分类名称来自保存的定义，不硬编码到前端。
2. 分类定义完成后进入流分配。没有分类时显示“先添加结果分类”及唯一主按钮，不展示一大张无法使用的流表。分类定义可随时通过“管理分类”修改。
3. 当前口径内，每条可分配的流只有“结果分类”一个下拉，选项为“无”和用户定义的叶子分类；默认“无”。选择叶子分类立即形成该口径的归集关系，选择“无”解除关系。删除“是否计入”、待确认、已匹配未分类、单独匹配开关及重复的解除匹配选项。
4. 同一流可在不同口径分别分类，例如同时进入 CBAM 和范围1；同一口径内单条流只能属于一个叶子分类。父分类由叶子汇总，不能与叶子重复累加。不同口径的结果不直接相加，沿用显式交并集去重能力。
5. 分类删除前显示影响数量，允许迁移到另一个叶子分类或改为“无”。只改名称保留关系；改变分类后保存新版本。保存、检查、模板冻结、建项目、输入版本继承、结果导出沿用已有完整链路。

编辑器采用以下结构，沿用 Arco 和现有 tokens：

```text
‹ 返回结果分类    当前口径名称 · 版本状态             检查  更多  保存
分类： [现场排放 12] [外购能源 3]                 管理分类
────────────────────────────────────────────────────────────
过程列表（桌面） │ 当前过程     搜索流    分类筛选    批量设置
                │ 流名称 / 单位 / 类型    结果分类       详情
                │ 二氧化碳               现场排放
                │ 铁矿石                 无
```

黄色区域的具体处理：返回改为紧凑左箭头加文字，视觉次于标题，不做大块链接区；过程搜索与列表同宽，移除独立的“收起过程列表”蓝色链接；过滤控件同一紧凑工具栏，长搜索框不独占一整行；移除冗长“选择要计入的流，再设置结果分类”说明。分类定义要显眼、可先操作，不放表格底部，也不只留一个被忽略的管理按钮。批量操作仅选中流后出现。390px 与窄窗口以过程选择器代替整列过程列表，弹窗须可关闭且不超宽。

首屏预算继续使用 1440×900、1280×800：流区域至少占视口65%，可见至少6条数据行；150%缩放与390px均能看见并实际操作流。达标只是最低布局条件，还必须查看截图确认返回、搜索、分类定义和表格的视觉层级。主界面不显示哈希、内部ID、错误枚举和开发说明。

### 0.4 前后端契约与历史兼容

以下为待实施契约，不能描述成当前已有行为：服务端以合法叶子分类归属决定归集资格，不能继续用 `selected` 或“标签存在”单独决定。`无`表示无分类关系，不是数值零，也不从物理模型删除流。前端隐藏计入列不算修复，直接 API 请求也必须遵循同一规则。

复用既有版本、分类树、精确过程/交换定位、冻结快照及归集结果，不新建平行计算引擎。内部如保留旧 boundary 字段用于兼容，只能由领域适配器推导，不能让用户重复填写。新语义必须显式版本化（具体键由 Qoder 在实施前写入本节回交契约），禁止改变 `flow_tag.v1` 原有哈希和回放含义。同步请求/响应 schema、能力契约和前端类型，禁止只在客户端过滤。

旧方案只读回放并提供“转换为结果分类”动作：先预览旧分类、计入/排除/未分类关系及转换影响，确认后创建独立新版本或副本。旧“选中但未分类”在新语义中变为“无”，必须在预览明确数量；原本排除但带分类的记录不能自动恢复计入。分类冲突和无效分类需修复后再保存，不按名称猜匹配，也不为凑数自动建分类。转换前后旧快照、历史导出和旧内容摘要保持原值。

默认 LCA/PCF 使用完整求解结果；自定义分类从同一冻结贡献池归集。分类了但缺因子或背景数据时，保留分类并显示缺项/已知小计，不伪造零。“无”造成的主动不归集与已分类缺项分开展示。内部传递不重复计量，背景贡献按真实消费路径归属。名称为 CBAM 或 CCER 不自动获得专用算法；已有正式 CBAM 计算能力不因本次统一分类界面被删除，分类归集与正式专用计算的能力范围必须准确声明。

#### 0.4.1 回交契约（R0 填写，实施以此为准）

- 语义键：新增 `result_category.v1`，写入既有 `calculation_method_versions.semantics`（列宽 32 足够，本轮无库结构迁移）。`flow_tag.v1` 的规则、哈希、回放与旧快照一律不变。
- 归集资格：仅 `categories[<唯一维度 id>]` 指向该维度已声明叶子分类的规则计入；`boundary_status`、`boundary`、`scope`、`cbam_relevant` 不参与资格判断。没有规则或分类为“无”，不是数值零，也不从物理模型删除。保存/检查拒绝未分类规则、非叶子、未知分类、同一流重复分类与跨维度分类；直接 API 同规则。
- 兼容字段由服务端推导：`result_category.v1` 的规则保存时归一为 `boundary_status=selected`、`classification_basis=user`、`boundary=null`、`cbam_relevant=false`，不作为用户可编辑项，也不改变上述资格规则。
- 旧方案：`flow_tag.v1` 版本只读，保存/克隆返回 409 `CALCULATION_METHOD_LEGACY_READ_ONLY`；检查、历史、归集回放、归档仍可用。转换接口：
  - `GET /calculation-methods/{id}/versions/{version}/conversion-preview` 返回维度、逐规则旧分类→新分类、“无”的原因与计数（`selected_without_category`、`pending`、`excluded`、`invalid_category`）、`can_convert`/`reason`。
  - `POST /calculation-methods/{id}/versions/{version}/convert`（`{name}`）创建独立新方法（新 id、v1、draft、`result_category.v1`），只迁移“已选 + 合法叶子分类”的规则；其余按预览转为“无”，旧方法及其所有版本字节不变。名称冲突沿用 409 `CALCULATION_METHOD_NAME_CONFLICT`。
- 能力契约新增 `result_category`、`legacy_tag_scheme`、`conversion_available`；两类分类口径的 `processing_package_selection` 均为 false，原因码分别为 `CALCULATION_METHOD_RESULT_CATEGORY_NO_PROCESSING_PACKAGE` 与既有 `CALCULATION_METHOD_TAG_NO_PROCESSING_PACKAGE`。
- 归集响应维持既有形状；方案项新增 `semantics` 与 `populated`（空口径为 false）。新语义下 `unmatched` 即“无（未分类）”，与 `missing`（已分类缺项）、`real_zero` 分开。空口径返回 available 但不显示零排放。
- 错误码新增：`CALCULATION_METHOD_RESULT_CATEGORY_{REQUIRED,DIMENSION_COUNT,UNKNOWN,NOT_LEAF,CATEGORY_DIMENSION,SCOPE_NOT_ALLOWED,BOUNDARY_NOT_ALLOWED,PURPOSE_INVALID,BOUNDARY_REF_NOT_ALLOWED,PROCESSING_REF_NOT_ALLOWED,RULE_NEEDS_EXCHANGE}`、`CALCULATION_METHOD_RESULT_MATCH_DUPLICATE`、`CALCULATION_METHOD_LEGACY_READ_ONLY`、`TAG_SCHEME_CONVERSION_NOT_LEGACY`、`TAG_SCHEME_CONVERSION_NO_DIMENSION`、`TAG_SCHEME_CONVERSION_SOURCE_CORRUPT`。
- 入口核对（R0）：模板配置 `TemplateConfigPage.tsx` → `MethodTaskPanel`“新建方案”与项目页 `MethodList` 两个按钮都能新建；编辑器 `?method=` 按语义分派 `ScopePanel`/`TagSchemeEditor`；`MethodEditor` 另存与 `MethodMigration` 复制按版本语义继承。R2 后新建只剩“结果分类”一个入口，旧标签行只读并提供转换。

### 0.5 Qoder 分阶段实施及验收

| 阶段 | 工作与涉及模块 | 可观察结果 |
| --- | --- | --- |
| R0 | 更新本节中的接口/语义版本及转换映射；核对所有入口，记录源码和实际运行包身份 | 不再遗漏项目旧方法入口；契约明确“有分类才归集” |
| R1 | `runtime_schemas.py`、`services/calculation_methods.py`、`analysis/tag_grouping.py`、`services/tag_grouping.py` 及必要迁移 | 分类创建、分配、无、冲突校验、归集、历史转换由服务端一致执行 |
| R2 | `MethodList.tsx`、`TemplateConfigPage.tsx`、`CalculationMethodsPage.tsx`、`MethodEditor.tsx`、`TagSchemeEditor.tsx`、样式/i18n | 先分类后分流的唯一新建路径；黄色区域重做；旧配置可读和转换 |
| R3 | 模板服务、输入版本继承、`TagResultPanel.tsx`、导出 | 保存模板→建项目→修改用量→检查→计算→按分类结果汇总→刷新/重启/导出完整可用 |
| R4 | 定向测试、真实引擎及浏览器、回交记录 | 按下述业务断言验收，最终由 Codex 接回复核后准备新单机包 |

必须覆盖的业务断言：

- 从模板和项目入口新建，均先定义结果分类；所有新建路径都不出现“是否计入”和“已匹配未分类”。
- 同一真实快照中，已知贡献100的流分到分类A、已知贡献30的流选“无”：分类A为100，默认LCA/PCF仍为130；把第二条也分到A后A为130；改回“无”后A恢复100。这个小例可用单测，但还需公开钢铁数据的真实引擎独立对账。
- CBAM口径与范围1–3口径可同时给同一流分类，交并集不重复计算。类别、分类树和名称刷新后均读回；删除分类迁移/无两种操作与影响数量一致。
- 无分类关系的口径返回空结果或明确“尚未分类”，不显示零排放；已分类缺项与真实零、主动“无”分别可辨。
- 旧方案转换前后历史结果逐项一致；不得仅以隐藏旧入口替代兼容，也不能继续把旧编辑器作为新建入口。
- 真实浏览器完成四视口截图、手机分配/保存/检查/关闭、模板建项目、输入变更后继承、结果导出和重启读回。遇到真实缺陷修复后再跑，不能把错误产品语义固化到测试。

运行时使用自有隔离端口和数据目录，沿用 `scripts/tag_acceptance_runtime.cjs`、`scripts/live_tag_template_acceptance.py`、两份 `ui_tag_*_acceptance.mjs` 与 `desktop/test/tag-runtime.cjs`，按新语义修改断言；不要复用用户数据库做写入验收。前端在 `web/` 执行 `npx.cmd vitest run`、`npm.cmd run typecheck`、`npm.cmd run build`；后端用固定 Python 跑受影响的标签、方法、迁移、模板、PCF与组织回归，不以全库重跑代替定向分析。

回交追加在本文末尾：基线/最终本地提交、改动文件、实际契约与迁移、转换规则、每条入口行为、测试命令与exit、真实数据来源、四视口截图、实际包身份、遗留项。未运行写 `not_run`，不要把工程通过等同用户已认可UI。保留上一安装文件原字节；新包放新目录，不覆盖上一包，不自行推送或部署。

## 1. 本轮要交付什么

用户先定义标签，例如 CBAM、范围1–3、碳市场、CCER、地区碳排放双控考核，再给模型中的具体 flow 匹配标签。计算后，按标签筛选贡献、按该标签下的分类汇总。底层先支持这条完整链路，再改编辑器，不能只换控件或给前端加一套临时标签。

一套标签定义一个分析口径；同一条流可以同时属于多套标签。范围1–3不是每个方法强制携带的字段。“是否计入”和“结果归集”不再作为两套需要用户重复填写的操作：某条流关联当前标签，就进入该标签的分析范围；没有关联，只是不进入这套结果，不从物理模型或默认 LCIA 中删除。

本轮先实现通用标签、分类、匹配、版本保存、结果筛选与归集。五个业务名称都应能通过同一数据契约创建，不能只支持写死的 CBAM/Scope 枚举。名称本身不触发公式、改变评价因子或赋予法规合规含义。专用核算规则以明确、版本化的能力接入；尚未接入时仍可进行有来源的标签归集，但不得冒充完整业务核算。

### 取代哪些旧要求

- 取代编辑器常驻“是否计入 + Scope + 多个自定义维度”的设计，新工作流以标签匹配为核心。
- 取代“版本与复制”整块展开区，以及“检查与试算”“来源与版本”两个常驻编辑页签。
- 取代把分类定义放在流表底部的设计，先定义标签和分类，再匹配流。
- 保留 PCF 默认 LCIA、精确版本、逐过程逐交换身份、贡献去重、缺项披露、历史快照冻结等约束。
- 2026-10-18 的工程和截图记录是历史证据；用户已否定当前体验，不能据此宣布本轮产品通过。

## 2. 已核对的项目事实与边界

One 主目录 `D:/VibeCoding/project/nebula-one`，本方案编写前 `main @ dbc1775c5a7052c6a043b0e934ebad26789a202f`，工作树干净。LCA 只读参考目录 `D:/VibeCoding/nebula-lca`，`main @ f255d3ecad9f79d6ef298fac642e62188bada099`，工作树干净。开工重新核对，不能重置到上述提交覆盖后续工作。

当前安装包是 `D:/VibeCoding/releases/nebula-one/20261018-0.1.1-ui-revision/Nebula-One-0.1.1-windows-x64.exe`，包内 One 为 `cb0a2dc`；不能把源码文档提交当作包内代码版本。

用户两张截图确认：顶部上下文和版本展开占用过多高度；分类定义位置过低；历史表“流/贡献”含义不清；来源页出现 `MODEL_PROCESSING_TEMPLATE_UNBOUND (409)`。本轮已核对源码链路，未启动用户实例复现网络请求，也未更改其数据库；报错的具体请求与运行实例仍须 Qoder 实测绑定。

### 可以直接复用的实现

| 范围 | 文件与现状 | 本轮处理 |
| --- | --- | --- |
| 模板入口 | `web/src/pages/TemplateConfigPage.tsx`、`templateConfig/MethodTaskPanel.tsx` | 复用模板精确版本和独立副本关系；编辑时移除重复外层大标题 |
| 模板清单 | `src/nebula_one/services/template_accounting_methods.py` | 已提供模板来源版本展示图；标签匹配继续使用，不回退项目填报接口 |
| 方法版本 | `services/calculation_methods.py`、`runtime_models.py`、`runtime_schemas.py` | 复用版本、哈希、并发控制；新增标签语义必须显式版本化 |
| 分类结构 | `MethodDimensionSpec`、`reporting_dimensions`、规则 `categories` | 已能表示分类树及维度到类别映射；优先适配为标签定义及分类，不另建全局重复字典 |
| 执行链 | `analysis/method_rule_adapter.py`、`method_compile.py`、`method_contribution_binding.py`、`services/method_execution_contract.py` | 复用身份匹配与冻结执行计划；新增标签模式单独解释，旧规则不变义 |
| 归集 | `analysis/method_grouping.py`、`method_path_grouping.py` | 已有贡献归组、缺项和去重基础；增加多标签查询与交并集语义 |
| 前端 | `calculationMethods/MethodEditor.tsx`、`ScopePanel.tsx`、`MethodPanels.tsx`、`useMethodDraft.ts` | 按职责改造，保留草稿、版本冲突、保存读回等能力 |
| 视觉 | Arco Design、`web/src/styles/tokens.css`、`pages.css` | 沿用现有组件与样式变量，不另建 UI 系统 |

目录表中的服务/分析相对路径均在 `src/nebula_one/` 下。Qoder 先确认实际契约，不把本文 proposed 字段当成现有 API。

## 3. 底层概念与数据责任

### 3.1 标签定义、分类与流匹配

一个用户可见的“标签方案”是一套独立、版本化的归集定义，可以沿用现有方法资源承载，不要求新增平行方法系统。示例：

| 标签方案 | 可选分类示例 | 解释 |
| --- | --- | --- |
| CBAM | 直接排放、间接排放、前体 | 用户选择哪些分类适合自己的分析；不是默认宣称全部受现有核算器支持 |
| 范围1–3 | 范围1、范围2、范围3 | 可编辑副本，可删除、改名或替换分类；生命周期口径与 GHG 专用口径仍须区分 |
| 碳市场 | 用户定义的履约分析分类 | 不自动提供地区或行业公式 |
| CCER | 用户定义的项目分析分类 | 标签归集可用；项目减排量算法需要独立方法学能力 |
| 地区碳排放双控考核 | 用户定义的地区、行业或责任分类 | 地区、期间、指标边界依定义保存，不按名称猜测 |

这些是需求示例，不得在前端用五个名称构造业务分支。内置示例若交付，作为后端版本化预设；用户同样可以创建第六种标签。

标签方案可以不设子分类，匹配后直接汇总到标签本身；设有子分类时，同一贡献在该方案中最多进入一个叶子分类。父分类只汇总子分类，不作为第二份贡献再次相加。若需要同一流有多个独立视角，使用不同标签方案，不在一个方案里叠加彼此独立的维度。

每条匹配绑定精确模型 revision、过程实例、exchange/消费端口、flow 身份及贡献目标。不能只向全局 flow UUID 写一个属性，否则同一流在两个过程、同一供应方在两个消费端口会串改。标签属于模型版本之上的分析声明，不写回背景数据库或篡改模型清单。

同一流允许同时关联 CBAM 和范围1–3等多个方案，各自保存版本和分类。删除其中一个关联，不影响其他标签。UI 一次编辑一套方案；底层支持从一条流查到它的所有关联，也支持一次查询多套结果。

### 3.2 proposed 契约要求

实施阶段先冻结具体 schema 与端点，再编码。以下名称表示语义，不要求按字面另建全部表：

- 标签定义：稳定 ID、版本、名称、说明、所属模板或项目、精确模型版本、分类树、分类覆盖策略、可选执行策略引用、内容哈希。
- 标签匹配：标签定义的精确引用、过程实例、交换身份、贡献目标、可选分类 ID、来源（手工/批量/规则建议）、确认状态。没有子分类时，关联标签本身即可。
- 定义必须显式标记新标签语义版本；不能仅用 `purpose=custom` 或“字段为空”猜测新模式。复用旧方法资源时一个新模式版本只有一套分类定义，旧多维度版本仍按原语义读取。
- 标签方案及其所有匹配作为同一不可变版本保存、计算内容哈希；分类删除与引用清理原子提交，不允许出现悬空匹配。
- 批量保存复用 `expected_content_sha256`，冲突保持用户草稿；重复请求不能重复新增版本。服务端重新校验身份、范围与引用，按钮禁用不能代替并发控制。
- 新模式的执行计划由服务端从匹配关系生成；如果适配现有编译器需要 inclusion 字段，只能由适配器唯一派生，前端不得再维护另一套可冲突的开关。
- 编辑查询返回实际能力与原因，例如可编辑标签、可做结果归集、是否有可用专用计算策略；显示名来自版本化定义，前端仅翻译通用操作文案。
- 计算/归集请求引用精确模型、解算快照、标签定义版本及匹配哈希；禁止 latest、按名称匹配或服务端默默选最新包。
- 结果查询支持单标签、多标签分别汇总、交集、并集；请求明确模式。默认多选为分别展示，不自动合计。
- 前端缓存、草稿和结果键包含账户/项目或模板、模型版本、方案、版本；切换后废弃过期请求，不能串回上一对象。

现有 create/read/save/clone/validate API 优先扩展；需要新增标签能力查询或多标签归集端点时，在本文回填实际请求、响应、错误码和权限范围。schema、前端类型、客户端与服务端同步变更。

### 3.3 匹配流程

第一版支持逐流选择及批量匹配；用户先选方案，再选流，最后选择可选分类。搜索、方向、流类型、过程等筛选只控制当前列表，不隐式改变标签或计算范围。“批量应用”明确显示目标数量；筛选结果和整个过程必须是两个有明确范围的操作，不能用隐藏行偷换。

匹配建议只生成待确认项。可以复用已有建议能力，但接受前必须落到确切交换身份并展示依据；同名流、模糊文本或 LLM 输出不能直接变成正式规则。不得新增外部模型调用或失败 fallback。

无匹配的流不进入当前标签汇总。未完成的建议、无效分类和版本失配仍是待处理/错误，不能静默解释成“用户有意不计入”。标签保存可以是草稿；正式汇总需要对本版本的匹配范围确认。若方案要求全覆盖，存在未匹配项则校验失败；若明确允许部分覆盖，结果显示已匹配范围及未匹配数量，不暗示全模型覆盖。

## 4. 结果筛选和计算的边界

### 4.1 首先实现冻结贡献上的标签归集

默认 LCIA 继续求解模型，产生有来源、单位和覆盖状态的冻结贡献池。标签对这份贡献池进行筛选与归组。标签变动可生成新的归集结果，不应无故重新求解物理模型；只有需求、模型、背景、指标或专用策略变化才按现有契约重新计算。

按某标签查看：取匹配流所对应的贡献路径，再按该标签的分类分组。直接排放读取真实特征化贡献，外购输入读取与该消费端口绑定的上游贡献；不能把 kg 物料或 kWh 数量直接当 kg CO₂-eq。内部传递可记录标签，但不产生第二份独立排放贡献。无法映射的目标必须返回原因和未解析项，不能忽略后显示完整成功。

多标签分别展示时，同一贡献可以出现在各自结果里，但各面板总量不能直接相加。交集/并集按冻结贡献来源键计算，不能按流名或全局 UUID 去重。一个消费端口的总贡献与其展开路径属于同一份来源，不能父子同时计数。

同一归集只汇总相同指标、单位、计算需求和核算期间的数值；不同快照/模型的结果本轮分别展示，禁止跨快照盲目并集。总量与单位产品换算继续由后端按冻结参考产出统一执行，不重复除以产量。

结果至少保留：已匹配已知贡献小计、标签内缺因子/缺背景项、未匹配范围、待确认项、真实零及不可归集原因。部分标签覆盖和因子覆盖是两回事；未匹配不是缺因子，带标签的缺因子项也不能消失。分类小计与标签小计对账；并集与独立来源清单对账。

### 4.2 业务专用算法是明确的后续接入点

底层预留版本化执行策略与能力校验接口，至少区分“冻结贡献归集”和“需要专用输入与算法”。标签定义可以引用受支持的执行策略，但普通业务名称不能决定执行器。

CBAM 现有正式试算继续通过其经核对的处理包和真实数据执行；用标签筛选出的直接贡献只是标签分析结果，不能直接替代原试算契约。生命周期范围1–3仍按用户选定的生命周期贡献归集，不强制套用另一套发电排放口径。

碳市场、CCER、地区碳排放双控考核，本轮支持标签定义、匹配和已有贡献汇总；专用输入（如期间、地域、基准情景、项目情景、活动数据、核算边界与规则引用）可由后续执行策略声明。未实现策略应明确返回“不支持该核算方式”及缺项，不返回零或退回另一算法。用户未提供的公式、系数、适用条件不自行编造。

这样后续可增加方法学而不重写标签底座；本轮不建设任意公式编辑器、完整 CCER 申报或地区考核平台。

## 5. 删除、兼容和历史

- 范围1–3仅是可选预设。新自定义方案不自动增加 Scope 列；用户可清除流上的范围标签，也可删除用户副本中的分类。
- 删除被引用的分类时，弹窗展示受影响匹配数，选择重新归到另一分类或解除这些匹配；取消无变化。后端原子验证，禁止只删定义留下旧类别 ID。
- 删除标签方案：未引用草稿可以删除；被计算结果、模板或项目引用的版本只归档/停用，历史可读。移除当前项目中的使用不删除来源或其他项目副本。
- 内置预设只读；调整时复用现有用户副本流程。不能为了“可删除”改写内置方法包原字节。
- 旧 `scope`、`boundary_status`、`categories` 多维度记录保持原解释。旧版的“计入但未分类”“排除但有分类”“pending”不能自动折叠成一个新标签关联。
- 迁移是显式复制成新版本/新方案，提供映射预览和冲突清单。旧多维度方案可拆成多个标签方案，但不得默认丢弃任一维度；无法无损转换的记录保持旧版只读，说明原因。
- 数据库迁移必须可重复核对，不重置库。历史回放继续使用原 schema、编译器版本和哈希；模板与项目继承独立副本，来源更新不能修改历史结果。

## 6. 图 2 报错专项

源码调用链已确认：`MethodEditor.tsx` 在 `tab === 'source'` 时调用 `api.selectableProcessingPackages(methodId)`；后端 `CalculationMethodService.list_selectable_processing_packages` 无条件调用 `template_identity(revision, application)`；该函数在模型无受审模板来源时抛出截图中的 409。`ProcessingPackagesPanel` 直接用 `ErrorState` 显示错误。

这条链路解释了为什么“看来源/改名称”也可能触发计算专属守卫；但需从实际请求与精确模型上下文确认截图实例，不能仅凭源码宣布完成复现。

Qoder 处理要求：

1. 用自有隔离数据构造“模板可提供展示图、源模型没有项目填报/受审模板绑定”的反例，记录打开编辑器、改名称和查看详情时的请求。
2. 标签编辑与普通来源查看不依赖处理包选择。用服务端能力契约区分无此需求、缺少绑定、确有可选包和请求失败；不能 catch 409 后伪装空列表。
3. 只有用户进入有能力支持的专用计算设置才加载对应包。无绑定的标签方案仍能定义、匹配、保存；已有合法冻结贡献时可以执行通用归集。
4. 必须依赖模板绑定的正式计算仍保留拒绝守卫。需要从模板生成项目时走正式继承流程，不能把前端传来的 template ID 当作可信来源写进旧模型。
5. 错误主文案说明阻碍和实际可执行的下一步；HTTP 码、英文异常和内部 ID 放“诊断详情”。数据损坏、权限错误和网络故障仍如实报错，不一概当作“不适用”。

## 7. UI 修改方案

### 7.1 页面任务与导航

面向桌面建模/核算人员，入口沿用模板或项目中的核算规则区域，不增加第二套入口。列表改为标签方案列表，显示名称、分类摘要、适用范围及编辑入口。预设可以快速创建副本，自定义也走相同编辑器。默认 LCIA 留在模型与数据。

用户依次完成“定义标签与分类—匹配流—查看归集结果”，但不强制三步向导。新建时用短弹窗填写名称与初始分类；进入聚焦工作区后，定义始终在上方可见、可编辑。

```text
← 返回方案列表  高炉—转炉钢铁 / CBAM   已保存     [检查] [更多 ▾] [保存]
分类：直接排放  间接排放  前体             [管理分类]
────────────────────────────────────────────────────────────
过程搜索          当前过程：铁矿石烧结    搜索流…  [筛选 ▾]
铁矿石烧结        流名称 / 单位 / 类型    当前标签分类      操作
高炉炼铁          二氧化碳               直接排放          详情
转炉炼钢          甲烷                   未匹配            详情
……                外购电力               间接排放          详情
                  勾选后出现：匹配标签 / 更改分类 / 解除匹配
```

无子分类的方案使用“匹配/解除”行操作；有分类时选一个分类即关联，清除即解除。上述示例名称来自实际数据或版本化定义，不在组件中硬编码业务选项。结果页选择标签后显示分类小计与贡献明细，提供多标签分别/交集/并集查看。

### 7.2 首屏预算与控件

- 将模板上下文、方法名、保存状态与动作合为一个紧凑页头，移除上方另占一整行的模板大标题。使用现有字体、颜色和间距；桌面外侧 padding 约16–24px，主操作约32–36px高，不靠缩小字号解决密度。
- 在1440×900及1280×800、100%缩放的工作区内容视口，页头、分类摘要、表格工具条合计目标不超过约200px，首屏至少可操作6条正常长度流；过程与流区域至少占可用高度约65%。这些是布局验收目标，不使用固定空白高度强凑。
- 桌面左侧过程导航约200–220px；右侧占满剩余宽度。移除表格写死420px造成的空间浪费，按剩余视口分配滚动区域；过程列表和流表各自滚动，避免外页与表格双重滚动争抢。
- 搜索与常用筛选在一行；低频筛选由按钮弹出。批量工具只在选中记录后出现，明确选择范围。
- “更多”下拉项：编辑名称与说明、另存方案、历史版本、来源与诊断、归档。每项进入局部弹窗，不再用整页 `<details>` 展开容器。
- “管理分类”弹窗支持新增、改名、删除和调整层级。分类 ID 稳定且不让用户直接编辑；改名不生成新身份。删除影响需显示数量与处理方式。
- 行“详情”用明确按钮打开局部弹窗，显示过程/流、位置与来源等信息；不在每行横铺长折叠标题。关键缺背景状态保留可见，不能全部藏进弹窗。

### 7.3 检查、历史与内容哈希

“检查”是按钮，打开当前版本的问题清单，问题能跳回具体过程/流。只对已保存版本检查；草稿未保存时明确先保存，不能用旧版校验结果覆盖新草稿。试算进入真实结果任务，编辑页不再嵌套历史表与试算表单。

历史版本放“更多→历史版本”弹窗；列为版本、保存时间、变更摘要、查看。原表的“流/贡献”实际是 `row.rules.length`，不能称为贡献数；若保留数量，改为准确的“匹配记录数”，必要时由后端计算，且不冒充清单流数或数值贡献数。默认首屏不显示历史列表。

内容哈希、内部包版本（例如独立出现的1.1.9）、JSON 和 API 错误码移到诊断详情，按需复制；底层校验继续保留。来源详情优先显示可读的来源对象、版本和时间。

### 7.4 状态与设备

桌面优先，验证1440×900、1280×800及150%缩放；390px使用过程选择按钮和逐流卡片，支持编辑一个标签、保存和返回。高缩放允许重排和合理滚动，不强求单行。

新建空分类提供“添加分类”或不设分类继续匹配；没有流与搜索无匹配分别显示。加载不抢占已编辑内容；失败保留草稿并重试；历史版本只读。返回列表恢复对象和位置，刷新定位同一方案/版本，未保存切换保留原有确认。弹窗支持键盘、Esc与焦点归还；主按钮和错误不能被固定头遮挡。帮助说明支持鼠标、键盘和点击，不只依赖原生 title。

## 8. Qoder 实施顺序：底层先行

用户把本文交给 Qoder 后，按以下阶段连续实施，不逐阶段重复询问是否继续。真正影响业务含义且本文无法确定的冲突，只暂停相关部分并记录；不自行猜算法。

| 阶段 | 入口与工作 | 可观察结果与准入下一阶段条件 |
| --- | --- | --- |
| F0 契约收口 | 核对 Git/实例；复现来源页请求；把第3节映射到现有资源，确定新语义版本、端点和迁移 | 回填实际字段、旧版转换表、能力声明；不再把 proposed 当 existing |
| F1 标签底座 | 在现有方法版本体系支持单方案分类、逐交换多标签关联、增删改、并发和显式迁移 | 真实 HTTP 新建五种名称及第六种自定义方案；同一flow关联多方案，保存/重启读回不串改；无受审模板绑定也可编辑标签 |
| F2 归集底座 | 标签编译接入现有贡献绑定与归集；多标签分别/交并集、覆盖状态、结果冻结、策略能力边界 | 从真实引擎回执到标签结果闭环；独立数值对账通过；专用未支持策略明确拒绝；旧快照回放不变 |
| F3 UI 接入 | 先用一套自定义分类打通列表→定义→匹配→保存→结果，再接全部同类方案；修复来源查看误请求 | 首屏以流操作为主，分类可见且可删除，版本等进入菜单弹窗；不再依靠两个独立开关定义同一条规则 |
| F4 验收回交 | 受影响后端/前端测试、真实浏览器、导出与重启读回；文档和本地提交收口 | 提供源码/实例身份、实际命令、截图、结果与未过项；用户体验验收独立记录 |

F1/F2未通过不能先交一个只在浏览器中工作的标签编辑器。已有服务可复用就适配，不复制求解器、不新建标签微服务、不进行全库重构。

### 允许改动的模块

One 内：上表列出的服务、schema/models、分析编译/绑定/归集、对应现有 API 路由与客户端/types，必要的增量数据库迁移；相关模板继承、结果展示与导出；编辑器、标签列表及局部弹窗组件、i18n和局部样式；相应测试及本轮设计/回交文档。

React 按职责拆分：工作区容器只负责上下文与动作；标签定义/分类弹窗、流匹配表、筛选/批量工具、版本/诊断弹窗、归集结果各有模块。优先复用已有组件，不把所有逻辑塞回 `MethodEditor.tsx` 或另造一套平行页面。共享样式只修实际问题，避免全站选择器改动。

LCA 本轮只读，使用既有真实引擎契约；如确需增加引擎回执能力，先记录所缺数据和最小契约变更，再由用户决定跨仓范围。不能在 One 伪造贡献来绕过缺口。

## 9. 必须有的验收证据

1. **身份隔离**：同名/同UUID流在两个过程、同一背景供应方在两个消费端口分别打标签；改一个不改另一个；跨模型版本引用被拒绝。
2. **任意标签**：CBAM、范围1–3、碳市场、CCER、地区碳排放双控考核和第六种用户名称走同一路径；改名不影响匹配、不触发另一算法。
3. **多标签去重**：同一贡献100同时匹配A/B，另一贡献30只匹配A，则A=130、B=100、并集=130、交集=100；不能给出230作为并集合计。此例是合成单元判据，另需真实冻结回执对账。
4. **分类结构**：叶子汇总等于标签小计，父类不重复计入；循环层级、重复ID、悬空分类、同方案重复归类被拒绝。无子分类标签也可独立汇总。
5. **删除恢复**：删除Scope分类或解除一个标签关联后，另一个标签和默认LCIA不变；引用历史仍可读；取消删除无变化。空方案不显示成“排放为0且完整”。
6. **缺项分离**：未匹配、待确认、带标签但缺因子、缺背景、真实零分别验证；只对已知同单位贡献对账，不把缺项置零。
7. **旧版兼容**：旧Scope、多维度、计入但未分类等记录不能被隐式改义；迁移预览和冲突保留；旧方法/计算内容哈希和原历史文件不变。
8. **来源错误**：无模板绑定模型可定义和保存标签，打开名称/历史/来源不触发无关处理包请求；依赖绑定的正式计算依旧拒绝，诊断可查看真实错误。
9. **并发与快照**：重复保存不增生版本，409保留草稿；分类定义和匹配原子提交；重启后读回；页面与XLSX/HTML等实际支持的导出使用同一冻结归集结果。
10. **真实用户路径**：从模板新建标签，定义/删改分类，切换过程，批量匹配，保存，刷新，查看分类结果，再返回继续编辑；真实组件不得mock掉。核对首屏空间预算、菜单/弹窗和四视口截图，不以“无横溢”替代可用性验收。
11. **策略边界**：不支持的CCER等专用核算策略明确拒绝；已有通用标签归集仍可用；不静默执行默认算法。现有CBAM正式试算与默认PCF定向回归。

建议先运行受影响测试；新增测试文件以实施后的真实名称补入，不机械重跑用户已拒绝的全量后端。以下使用 cmd.exe 或直接进程调用，Qoder 禁用 PowerShell：

```bat
cd /d D:\VibeCoding\project\nebula-one
C:\Users\31534\PycharmProjects\ILCD\.venv\Scripts\python.exe -m pytest tests/test_calculation_methods.py tests/test_template_accounting_methods.py tests/test_method_rule_adapter.py tests/test_method_compile.py tests/test_method_grouping.py tests/test_custom_dimension_grouping.py tests/test_method_contribution_binding.py tests/test_user_method_replay_identity.py -q
cd /d D:\VibeCoding\project\nebula-one\web
npx.cmd vitest run src/pages/TemplateConfigPage.test.tsx src/pages/CalculationMethodsPage.test.tsx src/pages/TemplateRuleEditing.test.tsx src/pages/calculationMethods/ScopePanel.test.tsx
npm.cmd run build
```

真实API/浏览器需另记隔离实例的确切启动命令、端口、数据目录、进程身份与清理方式；先检查端口，不占用户6616实例。已有 `desktop/test/template-browser.cjs` 可参考，但驱动应按新用户路径改造，保留业务断言，不调用隐藏控件。源码浏览器验收与安装包验收分开；本轮任务书不追加自动打包或发布授权，旧包不能冒充本轮已验收。

## 10. 执行限制与回交

只做最小UTF-8 patch，不整文件重写；Qoder 不使用PowerShell。普通Python固定使用 `C:/Users/31534/PycharmProjects/ILCD/.venv/Scripts/python.exe`。保留用户库、账户、旧包、背景资产、原始证据、未提交材料和其他进程。不要重新播种用户库，不删卷，不迁移真实用户数据来试验。

只允许本地commit，禁止自行连接GitHub、push、PR、Release、云部署；版本暂保持0.1.1。公开候选和原历史中商业资产的边界继续按交接文档执行。禁止硬编码业务分类翻译/身份映射、按名称猜流、放宽精确哈希检查、静默fallback或伪造缺失贡献。不更新Codex记忆。

实施时在本节后追加回交记录，不再生成相互矛盾的计划。每阶段记录起止commit、改动文件、实际行为、契约/迁移、命令及退出码、源码和实例身份、隔离数据/报告/截图位置。检查标为pass/fail/not_run，合成测试与真实引擎数值证据分开；未解决项给出复现和影响。最终说明当前能演示哪条完整用户路径、是否已有新包、哪些专用算法仍未实现。

本方案编写仅做源码和文档核对；未修改产品、运行测试或声称问题已修复。方法依据为 qoder-development 与 product-ui-design 技能，执行要求已内嵌在本文，Qoder 无需访问本机技能目录。

### 回交记录（2026-10-28）

**基线与提交**：起始提交 `8825762`（仅方案文档）。本轮回交源码 HEAD `8be609e`，分支 `main`，版本仍为 0.1.1；仅本地提交，未 push/PR/Release/云部署。

| 阶段 | 提交 | 范围 |
| --- | --- | --- |
| F0/F1/F2（契约、标签底座、归集底座） | `db7366c`，15 个文件 | `runtime_models.py`、`database.py`、`runtime_schemas.py`、`runtime_api.py`、`container.py`、`services/calculation_methods.py`、`services/tag_grouping.py`、`analysis/tag_grouping.py`、`analysis/pcf.py`、`analysis/carbon_management.py`、`services/method_execution_contract.py`、迁移 `20261028_17_add_version_semantics.py`、三个测试文件 |
| F3（UI 接入与来源误请求修复） | `8be609e`，13 个文件 | `MethodEditor.tsx`、`TagSchemeEditor.tsx`、`MethodList.tsx`、`MethodPanels.tsx`、`TagResultPanel.tsx`、`ProductCarbonFootprintPanel.tsx`、`AnalysisResultsPage.tsx`、`api/types.ts`、`api/client.ts`、`i18n/messages.ts`、`styles/pages.css` 及两个测试文件 |
| F4（验收与回交） | 本文档提交 | 仅追加本节 |

**契约与迁移**：`calculation_method_versions` 新增可空 `semantics VARCHAR(32)`（迁移 `20261028_17`，down_revision `20261008_16`，启动时对既有 SQLite 补列）。空值保持旧边界/Scope 语义；`flow_tag.v1` 表示标签方案。该字段仅当非空才并入内容哈希，历史版本哈希与回放不变。新增 `GET /calculation-methods/{id}/capabilities`、`POST /calculation-methods/{id}/archive`、`POST /applications/{id}/tag-grouping`；错误码含 `TAG_SCHEME_ARCHIVED`、`TAG_SCHEME_NOT_VALIDATED`、`TAG_SCHEME_HASH_MISMATCH`、`TAG_SCHEME_REVISION_MISMATCH`、`TAG_SCHEME_APPLICATION_MISMATCH`、`TAG_SCHEME_SEMANTICS_MISMATCH`、`TAG_SCHEME_DIMENSION_INVALID`、`TAG_GROUPING_DUPLICATE_SCHEME`、`TAG_GROUPING_SNAPSHOT_NOT_FOUND`、`CALCULATION_METHOD_TAG_NO_PROCESSING_PACKAGE`。归档把方法与其 ready 头版本改为 `retired`，不删任何版本；归档方案用新快照归集返回 409。

**实际行为**：
- 列表按记录自身事实显示类型、分类摘要、状态；`新建标签方案`（写入 `semantics` 与初始分类）与`新建用户方法`分开，标签方案不给 Purpose 选择。
- 编辑器为单行工具栏：返回、名称+标签徽章、版本/用途/状态、保存状态、`检查`、`更多 ▾`、`保存为新版本`；`编辑名称与说明`/`另存方案`/`历史版本`/`来源与诊断`/`分类建议`（仅非标签且可编辑）/`归档方案` 全部是局部弹窗，不再有常驻“检查与试算”“来源与版本”页签；历史表列为版本/状态/匹配记录数/保存时间/查看；检查只校验已保存版本，草稿未存时禁用并提示先保存；试算进入既有真实任务入口。
- 标签工作区把分类区放在流表之上：可新增、改名、删除分类；删除弹窗先显示“被 N 条匹配引用”，选择重归类或解除后再删；每行只有一个匹配下拉（未匹配/叶子分类/解除匹配），`已匹配，未分类` 仅清空分类并保留匹配，解除匹配是独立选项；支持按过程批量设置分类与解除；来源与诊断对标签方案不请求处理包，普通方法只在能力契约允许时才请求。
- 结果页只在同一 revision 存在 `flow_tag.v1` 且 ready、带内容哈希的方案时渲染标签归集；请求携带精确方案版本与哈希，展示标签小计、分类小计、已匹配未分类、未匹配、待确认、带标签缺值、真实零、覆盖率与问题码，支持分别/交集/并集；无就绪方案时整块不渲染，不显示成零或完整。

**命令与结果（均在本轮 8be609e 上执行）**：

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests/test_tag_grouping.py tests/test_tag_grouping_service.py tests/test_calculation_methods.py -q` | 65 passed，exit 0 |
| `python -m pytest tests/test_template_accounting_methods.py tests/test_method_rule_adapter.py tests/test_method_compile.py tests/test_method_grouping.py tests/test_custom_dimension_grouping.py tests/test_method_contribution_binding.py tests/test_user_method_replay_identity.py tests/test_pcf_user_method_grouping.py tests/test_carbon_user_method_grouping.py tests/test_method_scope_grouping.py -q` | 96 passed，exit 0 |
| `python -m pytest tests/test_climate_method_selection.py -q` | 7 passed，exit 0 |
| `npx.cmd vitest run`（web，全量） | 52 files / 366 tests passed，exit 0 |
| `npm run typecheck` | exit 0 |
| `npm run build` | exit 0（仅既有 chunk > 500 kB 提示） |

测试进程使用固定解释器 `C:/Users/31534/PycharmProjects/ILCD/.venv/Scripts/python.exe`；未启动新的真实服务实例，未重建共享栈，未重播种用户库，未改动用户数据。

**pass / not_run**：
- pass：上述自动化；合成与 API 级判据覆盖多方案并集/交集去重、缺项与真实零分离、分类小计对账、归档后停止归集且历史可读、能力契约声明标签方案无需处理包、来源页在能力为否时不发处理包请求、标签方案保存携带 `semantics` 与分类、分类删除前提示影响条数并重归类/解除、行内“未分类≠解除匹配”。
- not_run：真实浏览器四视口（1440×900、1280×800、150%、390px）与首屏空间截图；真实引擎冻结回执的端到端数值对账（本轮数值证据来自测试内合成回执）；进程重启后读回。原因：未起隔离服务实例，应用内浏览器视口为 0×0、截图不可用，不以 DOM 断言代替像素验收。复现方式：按交接惯例以独立端口/数据目录启动后端与 `npm run dev`，先检查端口不占用户实例，再按第 7.4 节四视口核对。
- 未实现（明确边界）：CCER、碳市场、双控等专用核算策略接入点尚未实现，`capabilities.dedicated_strategy` 恒为 `null`，不静默回退成专用算法；通用标签归集路径可用。

**当前可演示的完整路径**：模板内新建标签方案 → 定义/改名/删除分类 → 选择过程 → 行内或批量匹配流 → 保存为新版本 → 校验通过 → 在结果页对同一快照查看分类归集（前提是该 revision 已有 ready 方案，快照带路径加权贡献回执）。尚无新安装包；旧包未用于本轮任何验收。

### 回交记录（2026-10-28，§0 revision 2）

**基线与提交**：起始提交 `4e05a52`（仅方案文档，工作树干净）。本轮源码提交 `225bf65`（R1–R3，29 个文件）；R4 验收脚本补强 `9d61c9d`；本文档提交仅追加本节。分支 `main`，版本仍为 0.1.1；仅本地提交，未 push、PR、Release、连接 GitHub 或云部署。

**改动文件**（相对 `4e05a52`）：
- 后端：`services/calculation_methods.py`（结果分类校验、服务端兼容字段、转换预览/转换）、`runtime_api.py`（转换预览与转换端点）、`runtime_schemas.py`、`analysis/tag_grouping.py`、`services/tag_grouping.py`、`services/method_execution_contract.py`、`services/template_calculation_methods.py`、`exports/tag_grouping.py`。
- 前端：`MethodList.tsx`（唯一“新建结果分类”入口、旧行只读并提供转换）、`TagSchemeEditor.tsx`（分类在流表之上、每流一个分类下拉、无计入开关）、`MethodEditor.tsx`、`LegacyConversionDialog.tsx`、`MethodMigration.tsx`、`TemplateConfigPage.tsx`、`TagResultPanel.tsx`、`ProductCarbonFootprintPanel.tsx`、`api/client.ts`、`api/types.ts`、`i18n/messages.ts`、`styles/pages.css`。
- 测试与脚本：`tests/test_result_category.py`、`tests/test_tag_grouping_service.py`、`tests/test_template_save_as_mine.py`、`CalculationMethodsPage.test.tsx`、`ProductCarbonFootprintPanel.test.tsx`、`TemplateConfigPage.test.tsx`、`scripts/live_tag_template_acceptance.py`、`scripts/ui_tag_template_acceptance.mjs`、`scripts/ui_tag_results_acceptance.mjs`。

**契约与迁移**：本轮无新增数据库结构；沿用既有可空列 `calculation_method_versions.semantics`（VARCHAR(32)），写入新值 `result_category.v1`。`flow_tag.v1` 的规则、内容哈希、回放与旧快照不变；该字段仅在非空时并入内容哈希。归集资格只由“合法叶子分类归属”决定：`categories[dimension.id]` 必须命名已声明的叶子；未分类即“无”，不参与本口径，不写零、不删除流。后端返回的兼容字段由服务端派生（`boundary_status="selected"`、`classification_basis="user"`、`boundary=null`、`cbam_relevant=false`），前端不重复填写，也不接受客户端伪造。新增 `GET /calculation-methods/{id}/versions/{version}/conversion-preview` 与 `POST /calculation-methods/{id}/versions/{version}/convert`（请求 `{name}`）；转换创建独立方法（新 id、v1、draft、`result_category.v1`、custom），只迁移“已选 + 合法叶子”的规则，其余在预览中计入“无”的原因。`flow_tag.v1` 保存/克隆返回 409 `CALCULATION_METHOD_LEGACY_READ_ONLY`；名称冲突沿用 409 `CALCULATION_METHOD_NAME_CONFLICT`。能力契约新增 `result_category`、`legacy_tag_scheme`、`conversion_available`；两种口径都以各自原因码声明 `processing_package_selection=false`。归集响应在顶层与每个方案上返回 `semantics` 与 `populated`；空口径返回已声明分类与 `subtotal: null`，不返回零排放。报告导出按语义选择措辞：新口径为“结果分类归集结果/已分类贡献小计/无（未分类）”，旧口径逐字保留“标签归集结果/已匹配贡献小计/未匹配/待确认”。

**每条入口的实际行为**：
- 模板配置：只保留“新建结果分类”一个创建入口；命名后可携带首个可选分类，创建即 `result_category.v1` v1、规则为空；分类管理、删除影响提示、每流一个分类下拉、保存为新版本、检查与来源诊断均走可见控件。
- 项目方法页：同样只有“新建结果分类”；旧 `flow_tag.v1` 记录仍出现在列表和历史中，打开为只读（不显示保存、管理分类、逐流下拉），保留原归属读法并显示“转换为结果分类”。
- 已有方法与复制：编辑器按版本 `semantics` 分派；结果分类进入分类工作区，旧标签方案进入只读视图；另存/复制按源版本语义继承，旧标签方案另存/克隆被 409 拒绝。
- 模板保存与建项目：只有已检查的版本可冻结进模板；保存时冻结 `semantics`、规则与内容哈希；从模板建项目继承独立方法（新 id），输入变更产生新 revision 后再次按原语义、原规则继承。
- 结果与导出：同一快照可选择两套结果分类方案分别/并集/交集；历史选择刷新后仍读同一冻结记录与哈希；HTML/JSON 导出与页面数值一致；无关系口径显示“尚未分类”，不显示零。

**转换规则**：预览逐规则给出旧分类、新分类、结果（`assigned`/`unassigned`/`invalid_category`）并计数 `total`、`assigned`、`selected_without_category`、`pending`、`excluded`、`invalid_category`；旧“已选但未分类”在新口径中为“无”，旧“排除”与“未确认”不自动恢复计入；无效分类必须在来源修复，不按名称猜测，也不为凑数自动建分类。转换只创建独立方法，旧方法及其所有版本字节、旧快照与历史导出保持原值。

**命令与结果（均在 `9d61c9d` 工作树执行）**：

| 命令 | 结果 |
| --- | --- |
| `npx.cmd vitest run`（`web/`，全量） | 52 files / 375 tests passed，exit 0 |
| `npm.cmd run typecheck`（`web/`） | exit 0 |
| `npm.cmd run build`（`web/`） | exit 0（仅既有 chunk > 500 kB 提示） |
| 固定 Python `-m pytest` 14 个定向文件（结果分类、归集、冻结池、方法、模板、PCF、用户方法） | 172 passed，exit 0 |
| 固定 Python `-m pytest` 8 个组织/CBAM/PCF 文件 | 55 passed，exit 0 |
| `python scripts/live_tag_template_acceptance.py --one http://127.0.0.1:8633 --output .local-evidence/tag-rev2-20261028/live` | 真实引擎全链路通过，exit 0 |
| 同上 `--readback`（重启后） | `restart readback passed`，exit 0 |
| `node scripts/ui_tag_template_acceptance.mjs http://127.0.0.1:8633 19476 .local-evidence/tag-rev2-20261028/browser-template-6` | 10 项检查通过，exit 0 |
| `node scripts/ui_tag_results_acceptance.mjs http://127.0.0.1:8633 .local-evidence/tag-rev2-20261028/live/summary.json 19478 .local-evidence/tag-rev2-20261028/browser-results-3` | 6 项检查通过，exit 0 |

**真实引擎与数据来源**：使用公开钢铁演示种子（`nebula.iron-steel.bf-bof-crude-steel`）在隔离实例中求解，气候指标贡献取自真实引擎回执路径加权项；两方案对账期望 `[267.9072, 193.4592] kg CO2-Eq`，并集为 267.9072、交集为 193.4592；旧方案预览计数为 `{total: 2, assigned: 1, selected_without_category: 1, pending: 0, excluded: 0, invalid_category: 0}`。未重播种用户库，未使用用户数据或旧包数据做写入验收；数值证据与合成测试分列。

**四视口截图与布局测量**（`.local-evidence/tag-rev2-20261028/browser-template-6/`）：
- `editor-1440.png`：1440×900，7 行可见，内容区占比 75.1%，`scrollWidth=1440`；sha256 `b2a4963f446b2ea594b763ac0ca1d0a857cfd3b773d9edcffda4eb863a78d8aa`。
- `editor-1280.png`：1280×800，7 行可见，内容区占比 72.0%，`scrollWidth=1265`；sha256 `177dabdc11e7389a11f47b4383ed1bb49802193d2e911c0ad94274cadfc1da8a`。
- `editor-150pct.png`：853×533（150%），3 行可见，`scrollWidth=838`；sha256 `3d5967dd90dea323b2580d3d9fa3855ee8f2e16c142136776f9c11adba1d1b7d`。
- `editor-390.png`：390×844，2 张过程卡，`scrollWidth=375`；sha256 `3947cf7f9c4bb593b02edb849c67021b010e97124bf7073ccc73ba292f122c94`。
- 其他证据：`mobile-saved.png`（390px 分配/保存/检查/返回）、`changed-input.png`（改数量后新 revision，sha256 `dcea92b64a32ecd14eb56ed4b338e5db45464a75a5337e2d113dab037ff516e6`）、`.local-evidence/tag-rev2-20261028/browser-results-3/results-first-screen-1440.png`（sha256 `58194b3ffc07fb43513d07f9c4a85718e217e833f2500a93bd461e4aedd9254c`）、`legacy-conversion-preview-1440.png`（sha256 `10e7171d748c37e14ac3ced9076bcd8cd37158c495d9e9c355279f90f66f0bfd`）、`downloads/tag-result-*.html|json`。所有浏览器运行 `httpErrors=[]`、`consoleErrors=[]`；模板验收另有 `layoutFailures=[]`。

**隔离实例身份**：One `http://127.0.0.1:8633`（PID 31696）、编辑器 `http://127.0.0.1:8632`、LCA `http://127.0.0.1:5415`；数据目录 `.local-evidence/tag-rev2-20261028/runtime`（自有 SQLite 与日志），LCA 资源来自既有安装 `D:/VibeCoding/releases/nebula-one/20261018-0.1.1-ui-revision/win-unpacked/resources/runtime`，只读使用。验收完成后写入 `stop`，运行时与三个子进程均已退出，8633/8632/5415 端口确认无响应。

**实际包身份**：版本仍为 0.1.1；本轮**未生成新安装包**，未覆盖或改写 `20261028-0.1.1-flow-tags` 与 `20261018-0.1.1-ui-revision` 的原有字节；上表资源仅作为运行时资源被读取。`desktop/test/tag-runtime.cjs` 的本轮封装验收为 **not_run**：本轮任务未授权打包，且要求不覆盖上一包；不能用旧包冒充本轮产品验收。

**pass / fail / not_run**：
- pass：结果分类创建、分配、无、冲突/非叶子/未知维度校验；服务端派生兼容字段；空口径返回“尚未分类”而非零；已分类缺项、真实零、主动“无”三者可分；两方案交并集不重复计数；分类删除前影响数量与重归类/设“无”；模板冻结与建项目继承；输入变更后的新 revision 再继承；旧方案只读、保存/克隆 409、转换预览与独立新方法、旧版本字节与冻结结果不变；结果页历史回读与导出；重启后持久化读回；四视口真实浏览器操作与截图。
- not_run：安装包内运行验收（未打包）；旧方案历史结果在浏览器中的逐项重放（后端测试已逐项对账，浏览器只验证只读与转换预览）；CCER、碳市场、双控等专用核算策略仍未实现，`capabilities.dedicated_strategy` 保持 `null`，不静默回退。
- 未声明：本轮工程通过不等于用户已认可新 UI；最终体验验收仍由用户/Codex 复核。

**当前可演示的完整用户路径**：模板中新建结果分类 → 定义/改名/删除分类 → 选择过程 → 行内或批量给流选分类或“无” → 保存为新版本 → 检查通过 → 保存为我的模板 → 用模板建项目 → 修改生产数据生成新 revision 并保留同一结果分类规则 → 真实引擎求解 → 在结果页分别/并集/交集查看分类归集 → 导出 HTML/JSON → 重启后回读；旧标签方案在同一路径中只读可见并可转换。通用 PCF/组织计算照常完整执行，本轮不改变其口径。

### 回交记录（2026-10-29，§0 R5）

**基线与提交**：起始提交 `898056e`（仅追加 R5 要求，工作树干净）。本轮源码提交 `0952e28`（后端、前端与单测，15 个文件）、`41fbcb2`（真实 HTTP 与浏览器验收脚本，2 个文件）；本文档提交仅追加本节。分支 `main`，版本仍为 0.1.1；仅本地提交，未 push、PR、Release、连接 GitHub 或云部署。

**改动文件**（相对 `898056e`）：
- 后端：`services/calculation_methods.py`（旧普通方法判定与写拒绝、转换计划/映射解析/`mapping_sha256`）、`runtime_api.py`（GET/POST 转换预览与转换）、`runtime_schemas.py`（`legacy_method` 能力、`ResultCategoryConversionOptions`/`Resolution`、输出 `rule_index`、`expected_mapping_sha256`）。
- 前端：`MethodEditor.tsx`（按 `flow_tag`/旧普通/结果分类三分派，旧普通为只读范围视图）、`LegacyConversionDialog.tsx`（目标分类树、逐条映射、影响确认、映射哈希）、`MethodList.tsx`、`MethodMigration.tsx`、`api/client.ts`、`api/types.ts`、`i18n/messages.ts`、`styles/pages.css`。
- 测试与脚本：`tests/test_result_category.py`、`tests/test_tag_grouping_service.py`、`CalculationMethodsPage.test.tsx`、`TemplateRuleEditing.test.tsx`、`scripts/live_tag_template_acceptance.py`、`scripts/ui_tag_results_acceptance.mjs`。

**契约与迁移**：无新增数据库结构，沿用可空列 `calculation_method_versions.semantics`。能力契约新增 `legacy_method`：`semantics` 为空且 `purpose=custom` 的方法为 `true`，`conversion_available=true`，`processing_package_selection=false`，原因码 `CALCULATION_METHOD_LEGACY_METHOD_NO_PROCESSING_PACKAGE`；对该方法的保存、克隆、分类写入一律 409 `CALCULATION_METHOD_LEGACY_READ_ONLY`，与能力声明逐字一致。转换预览 `GET/POST /calculation-methods/{id}/versions/{version}/conversion-preview` 与转换 `POST .../convert` 共用请求体 `{source_dimension_id?, target_dimension?, resolutions:[{rule_index, category|null}], name?, expected_mapping_sha256?}`，并共用同一份计划：预览返回的 `mapping_sha256` 必须原样回传，不一致为 409 `TAG_SCHEME_CONVERSION_MAPPING_CHANGED`；未解决冲突为 422 `TAG_SCHEME_CONVERSION_UNRESOLVED_MAPPING`，重复规则/映射不适用等分别给出 `TAG_SCHEME_CONVERSION_DUPLICATE_RULE`、`TAG_SCHEME_CONVERSION_MAPPING_REJECTED`。计数口径为 `total/assigned/selected_without_category/pending/excluded/invalid_category/unresolved_invalid/resolved_without_category`。

**转换规则（本轮收口）**：
- 无效、缺失或属于其他维度的旧分类**不会**被当成“无”：只要 `unresolved_invalid>0`，预览与转换同时被拒，弹窗内“创建结果分类口径”保持禁用。
- 用户只能在草稿的映射选择里把它显式改到已声明的叶子分类，或显式选择“无”；前者计入 `assigned`，后者计入 `resolved_without_category`，两者都在影响区文案中分列，确认后才提交。
- 旧树为空（仅范围语义的旧普通方法）：必须先命名目标分类口径并至少添加一个分类，再逐条映射；目标树由用户输入，服务端不按名称猜测、不自动拷贝旧分类。
- 旧树多于一棵：必须先选择来源分类树，其他树的归属按“不在所选树中”处理并须逐条映射。
- 旧“排除”“未确认”不恢复计入；旧方法及其全部版本字节、内容哈希、旧快照与历史导出保持原值，转换只产生独立新方法（新 id、v1、draft、`result_category.v1`）。

**每条入口的实际行为**：
- 项目方法页与模板配置：旧普通方法与旧 `flow_tag.v1` 一律只读——无“保存为新版本”、无“管理分类”、无 `[aria-label="是否计入"]` 开关、无逐流分类下拉；只读面板显示计入/不计入/待确认与“旧范围分布”，唯一动作是“转换为结果分类 / 转换为结果分类口径”。
- 转换弹窗：先显示来源、分类数、计数与问题；“仍待处理”逐条给出过程/流名与旧归属，下拉提供目标叶子和“无”；未处理时提交禁用并提示还有 N 条；处理完显示“N 条带入新口径、M 条保留为‘无’”。
- 结果页、历史与导出：本轮未改，继续按冻结回执与内容哈希读取；旧方案仍以原措辞导出。

**命令与结果（均在 `41fbcb2` 工作树执行；固定解释器 `C:/Users/31534/PycharmProjects/ILCD/.venv/Scripts/python.exe`）**：

| 命令 | 结果 |
| --- | --- |
| `-m pytest tests/test_result_category.py -o addopts="" -q` | 16 passed，exit 0 |
| `-m pytest` 12 个受影响文件（结果分类、方法、标签归集/冻结池、模板、继承、绑定、库）`-o addopts="" -q` | 167 passed，exit 0 |
| `-m pytest tests/test_project_template_profiles.py -o addopts="" -q` | 1 failed / 5 passed：`test_current_profile_binds_new_organization_method_and_preserves_old_reference` 期望 `1.0.10`，包内已是 `1.0.11`。与 R5 无关：在 `898056e` 的临时 `git worktree` 上同测同样失败，工作本本轮未改该文件 |
| `npx.cmd vitest run`（`web/`，全量） | 52 files / 378 tests passed，exit 0 |
| `npm.cmd run typecheck`（`web/`） | exit 0 |
| `npm.cmd run build`（`web/`） | exit 0（仅既有 chunk > 500 kB 提示） |
| `python scripts/live_tag_template_acceptance.py --one http://127.0.0.1:5911 --output .local-evidence/tag-r5-final/live` | 真实引擎全链路通过，exit 0 |
| 同上 `--readback`（重启后） | `restart readback passed`，exit 0 |
| `node scripts/ui_tag_results_acceptance.mjs http://127.0.0.1:5911 .local-evidence/tag-r5-final/live/summary.json 19484 .local-evidence/tag-r5-final/browser-results` | 8 项检查通过，exit 0 |
| `node scripts/ui_tag_template_acceptance.mjs http://127.0.0.1:5911 19485 .local-evidence/tag-r5-final/browser-template` | 10 项检查通过，exit 0 |

**规则回归守卫的变异验证**：`ResultCategoryConversionRuleOut` 先前漏声明 `rule_index`，导致 POST 预览把该字段裁掉、弹窗提交 `rule_index:null` 被 422。已在 `tests/test_result_category.py` 断言 POST 预览保留 `rule_index`；删掉该字段后同一测试报 `KeyError` 失败（1 failed / 15 passed），恢复后 16 passed，说明守卫能真正拦住该回归。

**真实引擎与数据来源**：公开钢铁演示种子（`nebula.iron-steel.bf-bof-crude-steel`）在隔离实例中求解，气候指标取自真实回执路径加权项；两方案对账期望 `[267.9072, 193.4592] kg CO2-Eq`，并集 267.9072、交集 193.4592。反例数据均由脚本经真实 API 创建：旧普通方法（`semantics=null`、无分类树、1 条已计入 + 1 条待确认、仅范围语义）预设计数为 `{total:2, assigned:0, pending:1, invalid_category:1, unresolved_invalid:1}`，映射 1 条后为 `{assigned:1, invalid_category:1, unresolved_invalid:0}`；无效分类方案（`flow_tag.v1`，分类 `ghost`）预设计数为 `{invalid_category:1, unresolved_invalid:1}`、显式“无”后 `{resolved_without_category:1}`、改映射后 `{assigned:1}`，转换后源版本内容哈希 `b34f60d9…896367` 与 `{tag:'ghost'}` 原样保留。未重播种用户库，未使用用户数据或旧包数据做写入验收。

**四视口截图与布局测量**（`.local-evidence/tag-r5-final/browser-template/`）：
- `editor-1440.png`：1440×900，7 行可见，内容区占比 75.1%，`scrollWidth=1440`；sha256 `437a8b3acc9e20acc63741a0952254d792260e1f712e5e10d5abcc77fb94c3fd`。
- `editor-1280.png`：1280×800，7 行可见，内容区占比 72.0%，`scrollWidth=1265`；sha256 `ec01c1c7423716fa165e47919e57747be36d5bbd3c2e3aa300ca8aedefb3759a`。
- `editor-150pct.png`：853×533（150%），3 行可见，`scrollWidth=838`；sha256 `bff820f2aea5715a4b7a62321bd29d9348af0bde4e080d253cd26d3b3f103296`。
- `editor-390.png`：390×844，2 张过程卡，`scrollWidth=375`；sha256 `c2d72447dd8fb5cad8c188b6723f6a6b2bf8635c7a5961b96d7addd645c09e49`。
- 反例截图（`.local-evidence/tag-r5-final/browser-results/`）：`legacy-ordinary-readonly-1440.png`（sha256 `ea4f7cffee9bf2a0c05c0f13be6c2f530b6d0a88644cd29e188fd03f3b2f89ff`）、`legacy-ordinary-mapped-1440.png`（`daf782cac70160f8d274f4e7aa5c63c3e27048cbfcfc6db8780ec772a592e018`）、`template-legacy-ordinary-readonly-1440.png`（`a3f2a5e135f952a92bf81da7f654cbce87a433d00a4f4f614cc0fc2582683e57`）、`legacy-invalid-category-blocked-1440.png`（`a09dd2f7a4e26ecfe6c5a4fd3f06d3b3d398e6ea04017683376bdab8b568f227`）；结果页 `results-first-screen-1440.png`（`912c78fe39488fbb2233b1893f9b6fbeb2f48ec45469c800073c213439511b9b`）、导出 `downloads/tag-result-34410d65-…html`（`e6ac6bb6f9e40b0d55fcafd223c38a4f234f6903c571ea7b82bfff5959d9fe3d`）与同 id `.json`（`aac5bd50b976ec8f5ec4e96ffe35ca5cc623721890c994e34e634c4dede19ce0`）。两次浏览器运行均 `httpErrors=[]`、`consoleErrors=[]`、`browserAnomalies=[]`；模板验收 `layoutFailures=[]`。

**隔离实例身份**：One `http://127.0.0.1:5911`（源码进程 PID 46380，重启后 37640）、编辑器 `http://127.0.0.1:5910`、LCA `http://127.0.0.1:2835`；数据目录 `.local-evidence/tag-r5-final/runtime`（自有 SQLite 与日志），LCA/编辑器二进制来自既有安装 `D:/VibeCoding/releases/nebula-one/20261018-0.1.1-ui-revision/win-unpacked/resources/runtime` 的只读使用。Web 产物由 `web/dist` 本轮构建提供。验收后写入 `stop`，源码进程与运行时子进程均已退出，5911/5910/2835 端口确认无响应；早先用过的 `.local-evidence/tag-r5-20261029` 实例（4559/4558/3947）同样已停止。

**实际包身份**：版本仍为 0.1.1；本轮**未生成新安装包**，未覆盖或改写既有安装目录与上一安装文件字节；上表 `win-unpacked/resources/runtime` 仅作为运行时资源被读取。安装包内运行验收为 **not_run**（本轮未授权打包），不能用旧包冒充本轮产品验收。

**pass / fail / not_run**：
- pass：旧普通方法与旧 `flow_tag.v1` 的只读视图（项目与模板两处，无保存/管理分类/计入开关/逐流下拉）；能力声明与 409 写拒绝一致；空树旧方法必须自建目标分类树并逐条映射；无效/异维度/缺失旧分类在预览与转换两端都阻塞，显式“无”与重映射为叶子两条出口均可走通且影响分列；预览与转换共用 `mapping_sha256`，陈旧哈希 409；源版本字节、哈希与旧分类不变；转换产物为独立 `result_category.v1` 草稿；真实引擎数值与冻结回执对账；历史选择、HTML/JSON 导出、重启读回；四视口真实浏览器操作与布局预算。
- not_run：安装包内运行验收（未打包）；旧普通方法历史快照在浏览器中的逐项重放（后端已覆盖字节与规则不变，浏览器只验证只读、范围分布与转换）。
- 已知小问题（本轮范围外，未修）：对同一来源重复转换时默认方案名与已存在方案重名，服务端按既有 `CALCULATION_METHOD_NAME_CONFLICT` 返回 409，而弹窗只显示通用“转换失败，请稍后重试。”；在弹窗“新方案名称”改名即可继续。验收脚本因此每次显式改名。
- 未实现（边界不变）：CCER、碳市场、双控等专用核算策略仍未接入，`capabilities.dedicated_strategy` 保持 `null`，不静默回退。

**当前可演示的完整用户路径**：模板/项目中新建结果分类 → 给流选分类或“无” → 保存、检查 → 结果页归集与导出；旧标签方案与旧普通方法在列表和历史中只读可见 → “转换为结果分类” →（必要时自建目标分类树并逐条映射，或修复无效分类）→ 确认影响 → 生成独立新口径并继续编辑。已验收，等待用户/Codex 复核后决定是否出包。

