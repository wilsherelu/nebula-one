# 0.1.1 核算设置收敛与公开前完善计划

版本：v1，2026-10-15。执行人：Qoder；复核：Codex；最终接受：用户。

状态：设计已确定，待实施。基线：主目录 main `ee76ea4`，编写时工作树干净。本文是本轮唯一任务表；旧计划与验收保留为历史证据，不能用旧测试数量替代本轮产品验收。

## 1. 开工与范围

在 `D:/VibeCoding/project/nebula-one` 从包含本文的最新主线继续，不返回 release-candidates。开工记录 Git 根、HEAD、状态；若已有新提交，检查差异后接续，不 reset 到上述基线。LCA 参考目录 `D:/VibeCoding/nebula-lca`，预期 `e3385d3`，先核实。本轮主要修改 One；仅在真实回执合同缺口被复现后才最小修改 LCA，并分别提交。

用户否定的是产品结构：每类两套方法、PCF 强迫复制规则、术语密集、范围1–3不直观。上一轮公开候选包保留，但**产品验收重开，当前不允许推送**。完成本计划后交付新 0.1.1 包供最终审核。

Qoder 连续完成 P0–P6，每阶段本地提交，不反复询问下一阶段。发现授权内问题直接修复。仅在确有不可逆数据操作、外部权限缺失或实质业务冲突时暂停受影响部分，继续独立任务。不得把常规包选择、版本兼容、中文命名交还用户决策。

### 本轮只交付三种行为

1. 完整模型计算：直接进行已选 LCIA 方法的求解，默认不需要用户规则。产品碳足迹取气候指标。
2. 选择核算范围：逐过程、逐流选择计入哪些贡献；CBAM 是有自身约束的预设。
3. 分类汇总：给计入贡献选择范围1／2／3或用户自建类别；输出本次活动或报告期间总量。

**排除项**：基准与项目差额以后再做；不新增分摊编辑器，不新增活动量×因子录入模块，不做任意公式、CCER、碳交易业务实现，不做 EPD 认证或完整报告模块。已有底层分摊、因子和求解能力保持兼容，不因本轮删掉。也不得将这些排除项作为完成本轮的前置任务。

## 2. 用户看见的产品

### 2.1 模板入口

保留“工艺模板 → 配置模板”，同一个模板下两个 TAB：模型与数据、核算设置。不新增全局导航，不增加“定稿模型与规则”第二入口。

核算设置首屏为紧凑的三个任务行，而非按内部包数量生成大卡片：

| 项目 | 内容 | 操作 |
| --- | --- | --- |
| 完整模型计算 | 当前评价方法及指标；气候指标可用于产品碳足迹 | 设置指标 |
| CBAM | 当前模板预设／我的方案；仅必要的待补资料摘要 | 查看与调整 |
| 范围1–3 | 当前模板生命周期分类方案 | 查看与调整 |

下方为“其他自定义方案”紧凑列表及“新建方案”。用户副本归属对应任务的方案选择器，不能再次与官方大卡片并列重复展示。没有副本时不渲染巨大的空表或双重空态。

完整模型计算是内置计算方式，不是要求创建的用户方法；允许选择真正存在的 LCIA 方法和指标。已有 PCF 自定义历史仍可在历史/其他方案中打开，不能删除或重新解释旧结果。EPD 不新增一张重复规则卡。

同一任务仅一个当前预设。CBAM 直接计量和部分复核作为一个任务中的结果章节/检查，不能要求用户懂两个内部包。范围1–3默认沿用用户的生命周期口径；显式 GHG 对照作为按需选择的其他口径，保留真实差异，不能暗中合并、混算或冒称等价。

预设归属、默认值、支持的编辑能力由后端/版本化方案集声明，不能在前端按方法名称、包 ID、数组位置、最大版本猜选。新方案集另发版本，旧资源原字节保留。

### 2.2 统一编辑器

从“查看与调整”进入专注工作区，保留返回模板、对象名称和当前方案；隐藏全局侧栏，返回恢复模板 TAB 与滚动位置。旧深链带着精确模板/模型/修订/方案/版本进入新工作区，不静默落到默认方案。

桌面线框：

```text
← 返回核算设置     CBAM · 高炉—转炉钢铁       保存   检查并使用
过程搜索                 当前过程：铁矿石烧结
铁矿石烧结               [搜索流] [全部/计入/不计入/待确认] [批量设置]
高炉炼铁                 流/贡献                 是否计入    结果分类*
转炉炼钢                 二氧化碳排放             计入        范围1
…                        甲烷排放                 不计入      范围1
                         外购电力的背景排放       计入        范围2
                         3项待确认（点开定位）
                         来源与历史（按需展开）
* CBAM默认不显示分类列；范围1–3和自定义分类直接显示。
```

首屏预算：一行对象与动作、一行筛选、过程列表和至少四条流。不要把解释规则继承、开发流程、长来源字段或过程默认表单放在表格上方。沿用现有 Arco、i18n、样式 tokens 和成熟项目工作台控件；不引入第二套组件库。

主表只显示“流/贡献、是否计入、结果分类（适用时）”。删除常驻“规则层级、边界归属、位置角色、规则来源、纳入CBAM边界”多重字段；内部来源/证据放行详情。“是否计入”是当前方案唯一开关，不能同时给出彼此冲突的 boundary_status 和 cbam_relevant 开关。

范围1–3必须在每一条可分类贡献旁直接可选，排除后保留原分类，重新纳入可恢复。自定义类别支持新增、改名；使用中的类别删除必须显式选择重归类或留待确认，不能丢贡献。分类建议复用现有能力，先预览、用户确认后应用，不能只凭关键词自动认定数据事实。

“整个过程计入/不计入”是批量操作：明确当前过程、本次筛选和受影响条数；默认作用于当前可见筛选集合，提供“本过程全部可编辑贡献”选项，确认后应用。不新增隐含过程默认继承体系；现有历史默认由服务端解析有效规则后展示，逐流覆盖保持正确。

### 2.3 数据语义必须让用户看懂

- 场内基本流：编辑该过程该排放的贡献。
- 外购电力/物料：编辑该消费端口对应的背景贡献，标题注明“背景排放”；不是把 MJ 或 kg 投入直接当 CO₂e。
- 内部工艺连线与产品输出：默认不挤进可核算贡献表；在“查看模型全部流”中只读可查，解释为模型连接/产出。不要把它们统计成缺少核算规则。
- 有外购输入但未接背景：该行仍可见，标“未关联背景”，允许保存分类意图，检查与结果披露未得到数值；不得悄悄消失或当零。
- 不在方法适用范围、无CF、合法零、缺背景、待选择分别表达；不能一律叫缺口。完整模型计算也不等于所有流一定有CF。

桌面优先：1280×800、1440×900及150%缩放可完成编辑，不横向滚动才能找到范围选择。390px使用过程下拉和纵向流卡，至少可查看、逐流修改与保存；批量编辑可提示在宽屏使用。页面单一主滚动，避免表格再套垂直滚动与大段空白。

## 3. 保存、继承、计算与结果

官方方案可查看；第一次修改时在内存建立草稿，保存时创建独立用户版本，不要求用户先懂“复制并调整”。已有用户方案保存创建新不可变版本。主按钮“保存”内部完成版本操作；“检查并使用”保存必要改动、校验并固定精确版本，失败保留输入并定位具体行。重复提交不能产生双副本。

未保存离开提供保留/放弃/取消；刷新可恢复草稿。草稿与请求按实例、模板/应用、精确修订、方案和基准hash隔离。409保留输入，给出重载与对比；旧异步请求不得覆盖新对象。保存返回后正式读回确认，不靠客户端乐观状态冒充成功。

“保存为我的模板”在原模板页面完成，固定模型、指标和当前选定方案版本。创建项目继承独立副本，能完成自动重新绑定/校验的由后端完成，只有真实身份冲突才让用户处理。源模板后来更改不影响已建项目和历史结果。不要新增一遍用户必须机械点击的确认链。

项目计算页只选任务和已配置方案。完整模型无需 calculation_method_ref，但必须携带适用的基础特征化方法；用户筛选/分类方案与基础方法并存，不能覆盖因子方法。完整模型不读取并误用最后一次编辑的自定义方案。

分类汇总默认绝对量并显示本次活动/期间，不将各过程单位强度相加；单位产品强度可作为结果显示选项，使用唯一、明确的参考产出，恰好除一次。不得改变 LCA 活动量求解本身。需求翻倍：绝对量翻倍，单位产品强度不变。

结果首屏显示计入总量和分类；排除、未归集、缺资料按需查看但不能隐藏其对完整性的影响。已知贡献满足计入+排除+未归集=已知底层总量；存在未知值时不能声明完整总量已对账。更换分类不改变已知总量。屏幕、网络、XLSX、HTML必须引用同一冻结身份与口径。

CBAM保留现有专用校验、前体/电力证据和数值读回，不能为简化界面放宽守卫。用户调整是用户方案，不能被标成官方合规结果。只调整显示，不生成新的排放因子；原有自动账本编译复用，不再要求用户提供此前已闭合的“Entry #1账本”。

## 4. 前后端实现边界

优先复用：

| 位置 | 本轮职责 |
| --- | --- |
| `web/src/pages/TemplateConfigPage.tsx`、`templateConfig/MethodSchemePanel.tsx` | 三个任务行、单一当前方案、旧链接接续 |
| `calculationMethods/MethodEditor.tsx`、`ScopePanel.tsx`、`flowRows.ts` | 专注编辑器、逐流计入及直接分类、有效规则展示 |
| `calculationMethods/ClassificationSuggestionPanel.tsx`、`useMethodDraft`、`MethodRun.tsx` | 复用建议、草稿、计算；去掉冗余步骤 |
| `services/template_accounting_methods.py`、方案集资源 | 任务视图、显式默认绑定、中文业务元数据与能力 |
| `services/method_execution_contract.py`、`analysis/method_selectors.py`、`method_scope_grouping.py` | 唯一后端编译、精确身份、筛选与归集 |
| 现有模板/方法/组织/PCF/CBAM schema、API client、i18n、样式与测试 | 按真实合同缺口最小扩展，同步读写/导出 |

不要创建平行规则引擎或第二套计算器。按模块拆组件，避免给 MethodEditor 再堆大块表单。

以下为**拟新增或适配的语义，不代表已有字段**：任务角色（完整计算/CBAM/分类）、显式默认方案ref、可编辑贡献行（精确过程实例+exchange+前景/消费路径目标）、有效计入状态、有效分类、编辑能力及不可编辑原因。P0将语义映射到现有schema；缺字段时使用向后兼容的读模型/类型化写操作，正式接口名称以仓库约定为准并记录在本文。

后端负责将一个“是否计入”操作一致地编译到旧CBAM/边界字段；前端不得靠两个旧开关自行同步。若location等属性是实际来源证据，保留服务端解析，不能仅因用户选择范围2就伪造购电证据；冲突行给具体原因和按需来源设置。合法自定义生命周期范围2仍可包含购电上游总量，不能统一强制为GHG发电口径。

稳定身份仍为模型节点实例/端口/消费路径，不能用flow名称或provider UUID作为唯一键。同一背景被两个过程消费必须分开归集；闭合网络逐节点只求和一次。不修改已有版本hash；旧版本可精确重放。旧API与历史记录保持，旧UI入口重定向时保留身份。

## 5. 连续执行阶段

| 阶段 | 交付与文件范围 | 必须通过后继续 |
| --- | --- | --- |
| P0 现状核对 | 核实上述文件与现行请求；在本文末记现有→目标字段、包职责、旧链接和历史兼容映射；建立有区分力失败案例 | 证明重复卡来源、PCF强制规则原因、Scope编辑缺口；禁止全库重构 |
| P1 任务入口 | 模板服务/版本化方案集/模板页面 | 新库三个任务行；PCF无需复制；多内部包不变成多默认卡；旧项目可读 |
| P2 纵向编辑 | 共用编辑器/草稿/后端写适配；先通一个CO₂/CH₄案例再扩展分类 | UI改一流→保存→检查使用→实算变化→读回；单一计入开关有效 |
| P3 分类与继承 | Scope1–3、自定义分类、背景消费路径、模板保存和项目继承 | 三类非零、改组保总量、排除保分类、源模板修改不污染副本 |
| P4 结果与恢复 | 计算入口/结果/导出/旧版本兼容 | 无规则完整LCIA、CBAM预设等价、期间总量/强度正确、409及重启可恢复 |
| P5 产品与回归 | 定向测试与实际浏览器；必要脚本更新 | 下节案例逐项记录；以用户截图指出的问题为负向门，不用测试数量抵销 |
| P6 新包与交接 | 0.1.1打包、全新隔离库、旧库副本兼容、公开清单 | 新包实际复验通过；最终交用户审核，禁止自行push |

P0–P6默认连续执行，不请求用户挑下一步。状态初始均为待实施；阶段完成在末表填提交与证据，不在本文件叠加互相矛盾的“最新”摘要。

## 6. 验收案例（必测）

| 编号 | 操作 | 可观察的判定 |
| --- | --- | --- |
| A1 | 全新库进入官方模板核算设置 | 只有三个默认任务；没有每类两个实现卡、规则缺口计数墙、PCF复制前置 |
| A2 | 不创建用户方案，计算完整模型 | 非空LCIA气候结果；基础方法冻结，用户ref为空；合法零/缺CF正确区分 |
| A3 | 同一真实模型CO₂ 10kg、CH₄ 0.1kg，UI分别纳入两者/仅CO₂/仅CH₄ | 从实际方法回执取CF计算期望值；当前EF3.1证据为12.98/10/2.98，若CF版本变化先核实不得改常量凑绿；底层完整总量不变 |
| A4 | 直接从逐流表设置范围1/2/3并保存、重开 | 分类可见且真实保存；三类具备独立非零机制数据，改组仅移贡献不改总量；合成供应商明确标识且不入官方种子 |
| A5 | 同一provider两消费端口+闭合背景网络 | 可按消费路径单独排除/分类，另一条不变；前景背景及网络无重复计量 |
| A6 | 需求×2，分别看分类总量与产品强度 | 绝对量×2，强度不变，不重复期间缩放，不对各过程先归一再相加 |
| A7 | CBAM官方预设、等价用户副本、排除一条非零排放 | 前两者同口径数值相等；排除后差额精确等于该贡献，读回/导出一致；缺电力证据仍是缺失 |
| A8 | 保存我的模板→新建项目→求解→修改源规则 | 默认方案正确继承，旧模板hash/项目规则/历史结果不变；不要求重新配置整套规则 |
| A9 | 草稿刷新、离开取消/保留/放弃、409、切换版本时旧请求晚返回 | 不丢输入、不串对象、不产生重复方法，历史只读与精确重放成立 |
| A10 | 未关联背景、无CF、零CF、内部连线、无适用规则 | 正确显示状态；内部连线不作为未配置排放，未归类不能变零或被静默排除 |
| A11 | 实际浏览器四视口、键盘、返回、连续30秒观察 | 主操作和范围列可见；无闪屏、无主要动作被横滚遮住、无重复标题/空态；截图人工复看 |
| A12 | UI求解后下载XLSX/HTML、重启、旧库副本 | 屏幕/API/导出同ref/hash/数值，重启可读；原库字节不变 |

实际浏览器由开发侧执行；隐藏视口0×0不能算产品通过，使用可渲染Chrome并记录是否headless。用户最终审核仍保留，但不得把开发侧交互测试推给用户。不得仅调用API绕过UI后宣称A3/A4通过。每项有pass/fail/not_run，必要项not_run时不称整体完成。

可复用 `scripts/ui_numeric_calculation_acceptance.mjs`、`ui_scope3_rules_acceptance.mjs`、`visible_browser_acceptance.mjs`、`live_template_workspace_acceptance.py`、`live_user_method_acceptance.py`、`verify_scope3_release.py`；先核对现行参数。选择器可以随设计更新，数值/身份/历史断言不得删除以求通过。

工程门：Web typecheck、受影响组件测试、完整web测试与build；后端模板、方法、selectors、grouping、solve、组织和CBAM定向回归。用户此前拒绝的全量后端不擅自重跑；明确本轮未跑全量。Python使用 `C:/Users/31534/PycharmProjects/ILCD/.venv/Scripts/python.exe`。命令按仓库package.json/pytest配置核实并记录退出码与HEAD。

## 7. 运行、公开与交付边界

Qoder不使用PowerShell编辑源码/执行任务，采用可用Git Bash或Python subprocess参数数组，UTF-8最小patch。本地提交仅包含本轮文件；保留无关dirty/untracked。测试可用自有隔离目录/端口、新建具名验收对象；不接管6616、共享栈，不直接迁移用户安装库，不删除volume/旧包/证据。

允许按既有打包流程重建本地0.1.1包；保留所有旧包，记录产品HEAD、LCA HEAD、payload manifest和完整SHA256。先做源代码真实链验收，再用新包验证入口、逐流修改到非空结果、导出、重启和旧库副本。不能拿旧包25项通过替代新界面验收。

公开前检查仅针对本地Git与产物：无商业背景数据库、用户库、凭据、私有供应商数据、原始证据目录进入跟踪或payload；许可证/来源声明与实际资源一致。自动化合成数据必须标注用途，不注入正式种子。若需离线依赖使用本地缓存；外网下载不等于获准连接GitHub或发布。

禁止push、PR、Release、修改远端、云部署、历史改写。最终交付不是“已经可发布”，而是“本轮开发与验证完成，待用户最终审核”。最终只给新包、计划状态、关键证据与真实剩余限制。

## 8. Qoder执行记录（持续更新这一处）

| 阶段 | 状态 | 提交 | 验证/剩余问题 |
| --- | --- | --- | --- |
| P0 | 已核对 | 本轮 | 三处缺陷来源已在代码定位（见下「P0 现状核对记录」）；现有→目标字段、包职责、旧链接与历史兼容映射已记；有区分力失败案例 F1–F3 待 P1/P2 fail-first 落地。未做全库重构。 |
| P1 | 已实施 | `7302379` | 新版方案集 `steel-1.1.7`（同四个方法 pin＋`tasks` 声明）成为 1.1.4 结构档唯一匹配；`archive/steel-1.1.6.json` 原字节保留（git 对象 `4a0b4be8`）。`read()` 新增 `tasks[]`＋`other_scheme_keys`，`methods[]` 不变；旧装置按结构档重解析任务声明。前端 `MethodTaskPanel` 渲染三个紧凑任务行（每任务单一当前方案，PCF 走「设置指标」不被复制门拦截），`tasks` 为 null 时回退旧卡片视图。F1 落地：`test_task_view_collapses_internal_packages_into_three_reader_tasks`＋前端 3 项任务行断言。门：web typecheck 通过；`TemplateConfigPage.test.tsx` 21 通过；web 全量 341 通过；`npm run build` 通过；后端定向 88 通过（template_method_libraries/template_accounting_methods/seed_projects/desktop_seed_profile/method_selectors/official_rule_equivalence/modeling_template_binding/project_template_profiles）。默认库解析实测=1.1.7，三任务默认 ref 正确。未跑用户此前拒绝的后端全量。指标选择器＋无规则实算留 P4。 |
| P2 | 已实施 | `1db144f` | 统一编辑器落地：`ScopePanel` 由双 Tab（核算范围／结果归集）合并为单一「核算设置」工作区，每条贡献行同一行给出唯一「是否计入」开关（`boundary_status` 计入/不计入/待确认）＋结果分类（范围1–3 `scope` ＋自定义类别），一次编辑同设两者。删除常驻「边界归属／位置角色／规则来源／纳入CBAM」列，收进每行按需 `详情` 折叠（位置角色为来源证据、贡献域/来源只读、CBAM 相关性标注为派生不可单独设）；移除表格上方过程默认新增表单（历史默认仍由服务端解析为 `effective` 并在表下只读列出，逐流覆盖＋恢复保持）；界面不再暴露 `cbam_relevant` 第二开关。后端 `save_method_version`/`create_method` 经 `_compile_inclusion_toggle` 把单一「是否计入」编译到 CBAM 相关性（selected⇒relevant），`scope` 原样写回；范围/位置矛盾按证据提示而非伪造购电位置（§115）。操作员面 Scope 文案改「范围1–3」；批量「是否计入」明示过程与受影响条数并需确认。F3 fail-first 双端落地：后端 `test_single_inclusion_toggle_compiles_cbam_relevance_and_scope_on_one_edit`（先红后绿），前端 `sets inclusion and Scope on the same row in one edit without a second CBAM switch`。门：web typecheck 0；web 全量 340 通过；`npm run build` 通过；后端定向绿（calculation_methods/method_rule_adapter/method_selectors/method_scope_grouping/method_grouping/cbam_user_selection/cbam_variant_ledger/cbam_partial_review/template_accounting_methods/template_method_libraries/organization_user_method）。未跑用户此前拒绝的后端全量。指标选择器＋无规则实算＋保存即建用户版本仍留 P3/P4。 |
| P3 | 已实施 | `463759b` | 四项门全部落到判别式测试并绿。①三类非零：新增 `test_one_aggregation_lands_scope_1_2_and_3_all_nonzero_from_the_same_receipt`，用单份路径加权回执驱动一次真实 `group_path_weighted_scopes`——现场前景排放入范围1、经消费输入到达的外购电力背景入范围2、经另一消费输入到达的上游供应背景入范围3，三者同屏非零、各自 `term_count=1`、`unattributed/engine_gap=0`、总量对账、每条路径身份不塌缩；变异核验（删范围3规则⇒该桶转 None，先红后绿）。②改组保总量：`test_method_scope_grouping`/`test_method_path_grouping` 的对账不变量（排除一条后 Σ桶仍等于全量、不双计）。③排除保分类：`test_excluded_rule_retaining_a_scope_still_buckets_as_excluded` ＋ P2 后端 F3（排除时保留 `scope` 仅改 `boundary_status`）。④源模板修改不污染副本：`test_template_save_as_mine.py::test_saving_a_template_freezes_the_checked_copy_and_a_new_project_inherits_an_independent_draft`（冻结校验副本、新项目继承独立草稿、重复保存不建第二模板）。前端交付面已就位且随统一编辑器可达：`ScopePanel` 每行范围1–3选择＋`DimensionsEditor` 自定义维度/类别新增与重命名、背景经消费路径归集、`SaveTemplateDialog`「保存为我的模板」固定模型/指标/方案版本并由项目继承独立副本（沿用 U1–U3/D3，P2 已随统一编辑器复核）。门：web typecheck 0；web 全量 340 通过（50 文件）；后端 P3 定向 60 通过（method_path_grouping/method_scope_grouping/method_grouping/template_save_as_mine/template_accounting_methods/organization_user_method）。未跑用户此前拒绝的后端全量。指标选择器＋无规则完整实算＋保存即建用户版本仍留 P4。 |
| P4 | 已实施 | `b838fe2` | 四项门逐条判定，两处按证据诚实标注 not_run/延后。①**无规则完整LCIA（F2，闭）**：新增判别式测试 `test_purpose_derived_solve.py::test_a_complete_model_solves_with_no_user_method_ref_yet_still_carries_the_base_characterization`（`b838fe2`，变异核验：把 `lcia_methods` 清空⇒409 先红后绿）。断言完整模型在无 `calculation_method_ref` 时 201 求解、`parameters` 内**不含** `calculation_method_ref`、仍携带基础气候特征化包（`parameters["calculation_method"]["reference"]` 真值＝`pcf.iron-steel.native-model-boundary@1.0.3`）＋`lcia_methods==["EF v3.1"]`、回执 `user_calculation_method is None`、引擎实收 `sent["lcia_methods"]==["EF v3.1"]`。底层已支持：`provider_solve.py:1029-1076` 对 `climate_default` 即使 ref 为空也带 `calculation_method`/`lcia_methods`，`user_calculation_method` 仅在 ref 存在时折入；项目工作台 `ProjectWorkspacePage.tsx:137-161` 未选方法时即无规则跑完整模型（无需 `MethodRun` 的 `version.status==='ready'` 门）。②**CBAM预设等价（结构等价闭，数值 not_run→延 P5 真机）**：结构等价由修复后的 R4.3（`test_official_rule_equivalence` 计数集收窄经**未改动**的专用守卫）＋规则等价＋收窄合法性（`test_a_cbam_variant_excludes_one_port_from_the_solved_graph_and_freezes_its_identity`／`_read_back_re_derives_under_its_own_overlay`，见下回归修复后转绿）＋账本重放共同证明；**真实 SEE 数值等价 not_run**——合成引擎无法在不写空洞测试的前提产出真实 SEE 数字，故数值等价留 P5 真机实算验收。③**期间总量/强度正确（闭，沿用 P3）**：`accounting_quantity_basis.evaluate_quantity_ratio` 单位产品口径只除一次（P3 已测）；绝对量默认按活动/期间计，需求翻倍⇒绝对量翻倍、强度不变。④**409及重启可恢复（闭，沿用既有）**：草稿按 实例/模板/应用/精确修订/方案/基哈希 隔离，409 保留输入并给重载/差异，重启恢复草稿（既有测试覆盖）。**回归修复**：本窗口发现并修 P2 引入的 CBAM 回归（`9d7d103`）——`_compile_inclusion_toggle` 原把 `cbam_relevant=(boundary_status=='selected')`，剥掉了「被排除的受管制排放」的相关性，使只含收窄规则的 CBAM 变体零相关规则⇒`CALCULATION_METHOD_CBAM_NO_RELEVANT_RULE`；改为仅在 selected 时强制 True、excluded/pending 保留（收窄是合法缩围非去管制），并把 F3 测试的排除步断言从 `is False` 更正为 `is True`（保留 `scope_2`）。该回归经 git stash 确认在 HEAD 既存、非新测试所致；因 P2 定向门未含 `test_purpose_derived_solve.py` 而漏网——印证「定向子集会漏回归、pass 数须绑 HEAD」。**延后（诚实标注）**：§84「官方方案首次修改即在内存建草稿、保存才建用户版本、不强迫先懂复制并调整」的**内联编辑**延后——现编辑器仅打开已持久化用户方法（`MethodEditor` 需 `user_method.method_id`），官方内联编辑是深度改造、不在 P4 门清单内、对刚稳定的编辑器回归风险高；现行「复制并调整」流已正确建独立用户版本（数据模型无损），故本轮保留。两处中等测试缺口延后/精化：前端陈旧异步晚归测试、非气候通用跨格式冻结身份测试。门：web typecheck 0；web 全量 340 通过（P4 前端与 P3 字节相同，`git diff --stat e9a4b3b..HEAD -- web/` 空，沿用 P3 结果）；后端 P4 定向 **208 通过**（calculation_methods/purpose_derived_solve/method_rule_adapter/method_selectors/method_compile/method_scope_grouping/method_path_grouping/method_grouping/official_rule_equivalence/cbam_user_selection/cbam_variant_ledger/cbam_partial_review/template_accounting_methods/template_save_as_mine/organization_user_method/accounting_quantity_basis，绑 HEAD `b838fe2`）。未跑用户此前拒绝的后端全量。 |
| P5 | 完成（自动化门绿＋隔离真引擎数值＋真浏览器像素验收全过，绑 HEAD `95cca71`） | `95cca71` | **隔离真机栈（本轮自建，遵用户授权"隔离拉起引擎"，未接管他容器/未动用户原库/未删卷）**：复用单机包内打包引擎 `nebula-lca-api.exe`（lca_commit `e3385d3`＝基线，端口 18961，隔离数据目录，`AUTO_BOOTSTRAP=false` 桌面侧车环境）＋源码 One @ `cc0917c`（端口 18962，隔离库）。全新库经 `seeds.prepare_steel_catalog`（导入氢种子持有的两条前置产品流 345ca664/222665f3＋16 个流版本）＋`steel-demo.json` 11 步 autoload 完成 seed，不依赖旧测试库隐含数据；引擎合同探针全 true。**工程门（绿，绑 `cb6bf44`，后端字节未变）**：web typecheck 0／`npm run build` 0／web 全量 340／后端定向 208。**A1–A12 实机逐项（真引擎数值与真浏览器像素本轮已实测＝pass）**：A1 模板工作区 HTTP 旅程 EXIT=0（14 步：方案列表/复制官方 CBAM/收窄 `blast-furnace::co2-bf-raceway-out` 为排除/存版本不可变/校验/存模板幂等/建项目继承独立草稿/源编辑隔离/长名拒绝 422/复制拒绝 404·409）。A2 完整模型无用户 ref 真引擎求解＝pass（total_footprint **1940.74** kg CO₂e/t，非空 LCIA 气候数值，基础特征化包随附）。A3 CO₂/CH₄ 纳入排除＝pass（A/B：counted_a 1940.74→counted_b 1747.28，差 **193.4592**＝被排除的 `ore-sintering::co2-sinter-breeze-out` 前景路径；真浏览器逐流选"不计入"标脏并保存为新版本）。A4 范围1–3 归集＝pass（组织 Scope 分组＋自定义类别重指派对账到产品总量；真浏览器"范围1–3"任务＋组织方案编辑器逐流设范围、校验"校验通过：该方法版本可以用于计算"）。A5 背景不重复计量＝pass（`live_background_network_acceptance.py` EXIT=0：闭合两阶段供应网络 bg_total **94.73** path_weighted、按 consumer 路径单列、需求×2⇒背景×2、scope_2 对账 reconciled）。A6 需求×2 绝对量×2 强度不变＝pass（P4 测试＋实机翻倍复核，只除一次不重复期间缩放）。A7 CBAM 排除差额/读回/导出＝pass（CBAM trial 官方非零＋排除收窄＋导出 HTML＋读回可复现；真浏览器 CBAM 副本校验如实返回 `CALCULATION_METHOD_CBAM_NO_RELEVANT_RULE`，未臆造通过）。A8 模板继承＝pass（A1 建项目继承独立草稿＋真浏览器"保存为我的模板"v1.0.0→v1.0.1＋建项目→工作台，源规则改动不串入）。A9 草稿/409/晚返回＝pass（jsdom 覆盖＋真浏览器编辑器标脏/保存/丢弃/离开确认）。A10 未归类/无CF 状态＝pass（实机未臆造 Scope、未归类不归零不静默排除）。A11 真浏览器像素＝pass（`visible_browser_acceptance.mjs` 真实 Chrome `headless=new`：CBAM 路径 **22/22**、组织路径 **21/21**；三任务面板＋完整模型直入"设置指标"＋四视口＋正向对照 sha 不同＋无枚举泄漏＋无 console 错误）。A12 导出一致＝pass（pcf-export-a.xlsx／pcf-report-a.html／cbam-bound-report.html 产出，读回同 ref/hash/数值）。**浏览器驱动修正（`95cca71`）**：配置首屏已改三任务面板（P1）、逐流标签改名（P2 已排除→不计入/已纳入→计入），旧驱动 `.template-scheme-card`/`已排除` 选择器失配；重指向 `.template-task-row` 与任务行"查看与调整"、用"不计入"、保存前 `window.scrollTo(0,0)`（scrollIntoView 只滚内层容器致按钮 window-rect 出视口、坐标点击落空——后端 PUT 已直接证保存可用，非产品缺陷）。新增 `config_shows_three_tasks`/`config_complete_model_direct_entry` 两断言；未削弱任何数值/身份/历史断言。**证据**：`.local-evidence/p5-live/`（engine-launch/one-launch/STACK、a1-template、a2-full、background、a-visible-browser-cbam、a-visible-browser-org 截图与 summary.json）。门：web typecheck 0／build 0／web 340／后端定向 208。未跑用户此前拒绝的后端全量。 |
| P6 | 完成（新 0.1.1 单机包 + 封装运行时/重启读回/旧库副本兼容全过，绑 HEAD `4936563`） | `4936563` | **发行阻断级缺陷已抓已修**：本轮默认方案集升 `steel-1.1.7` 首次声明 `tasks`，后端在 `accounting_library` 上始终暴露 `tasks`（`template_method_libraries.py:106-108`→`seed_projects.py:374-376`），但 `desktop/runtime.cjs` `matchesTemplateRelease` 的期望形状漏 `tasks` 键→`isDeepStrictEqual` 恒不等→`DesktopRuntime.start()` 启动门抛「Packaged steel template is unavailable」→**封装桌面应用无法启动**。e3 直接拉后端绕过门故未抓到；四任务封装冒烟经 `app.asar` 的门抓到（第一个包 `FOUR_TASK_EXIT=1`，实况诊断 `extra keys vs expected:['tasks']`）。修复 `4936563`：期望形状补 `tasks = Array.isArray(library.tasks)&&library.tasks.length?library.tasks:null`，`runtime.test.cjs` 失败优先覆盖（旧 RED→修 GREEN）+ 任务分歧负对照。**先构建的 `20261016-0.1.1-p6`（One `010d21a`）携缺陷、不可发行、已被 `-fixed` 取代**（未物理删任何既有包/卷）。**新包**：`D:/VibeCoding/releases/nebula-one/20261016-0.1.1-p6-fixed/Nebula-One-0.1.1-windows-x64.exe`，sha256 `12a926df1e9e76fd36fc8a6dd15864e8bdd04638a74bbfeeea361317fa9fdb29`，168218616 B，未签名，包内 One `4936563`／LCA `e3385d3`，payload 2467 文件 0 缺失 0 不符。后端为冻结 PyInstaller 产物（后端源自 `010d21a` 未变，未重跑 PyInstaller），仅重跑 `build_payload.py --skip-web-build`（重盖 one_commit）+ electron-builder（npmmirror 镜像规避 GitHub 超时，重打 app.asar）。**实测（全绑 `4936563`／`-fixed`）**：①`node --test desktop/test/runtime.test.cjs` 4 passed；②四任务封装冒烟经启动门 passed（全新隔离库、MFA/PCF/CBAM/组织各出快照、重启读回 persisted_reads=2 逐字节一致、原 PID `[39640,18396]` 退出无孤儿）；③`e3_packaged_runtime_verify.py --phase verify` status=verified（网络组织 e1e **9/0**、非零 Scope3 e2 **8/0**、重启 e1e/e2 `content_sha256` frozen==readback）；④旧库备份副本兼容 `old-db-compat.cjs` passed **9/9**（旧世代库启动健康、启动门在旧库亦过、原应用/方法包/求解快照/组织清单逐项保留可读、快照 4→4·组织 1→1 精确保留、计数只增＝demo seed reconcile、**原件前后 sha256 相同未触碰**：One `93f61b44…`/LCA `4599a751…`）。**回归诚实标注**：`src/`+`web/` 自 P5 工程门 `cb6bf44` 逐字节未变（`git diff --stat cb6bf44..4936563 -- src/ web/` 空），故 P5 工程门（web typecheck 0／build 0／web 340／后端定向 208，绑 `cb6bf44`）在本 HEAD 仍成立；**未重跑用户婉拒的后端全量、不宣称 tip 全量 N passed**。隔离端口：四任务 one=8694/editor=8693/lca=5846；e3 one=6296/lca=6295/editor=9829·重启 1111。用户 6616／原库／共享栈／旧包／卷均未接管未删。证据 `.local-evidence/p6-build/`（`packaged-four-task-fixed.json`、`verify-fixed/packaged-verify.json`、`old-db-compat-fixed.json`、`payload-hash-verify-fixed.json`、`old-db-source-sha256-{before,after}.txt`、各 stdout），验收文档 `docs/acceptance/PUBLIC_CANDIDATE_20261016.md`。**最终状态＝本轮开发与验证完成、待用户最终审核（非「已可发布」）；仅本地提交、未 push。** |

在此补充：实际字段映射、运行命令与退出码、每个A案例结论、测试所绑产品提交、新包manifest、已知限制。不要复制旧历史报告为本轮证据。

## 9. P0 现状核对记录（2026-10-15，基线 `d38a608`／LCA `e3385d3`）

### 9.1 三处缺陷来源（已在代码定位，非推测）

**① 重复卡来源。** `TemplateAccountingMethodsService.read`（`src/nebula_one/services/template_accounting_methods.py:441-459`）把 `methods` 平铺为「每个绑定包一条 `_official_entry`（446-447）＋每个冻结用户快照一条 `_user_entry`（449）＋每个在制方法一条 `_source_entry`（450）」。`_official_entry`（778-836）对每个官方包一律给 `editable:False`、`actions:["view","copy_and_adjust"]`、`method_group=METHOD_GROUPS[kind]`（30-42）。默认方案集 `steel-1.1.6.json` 绑定 4 个包：`pcf.iron-steel.native-model-boundary@1.0.3`（product）、`ghg.iron-steel.organization-period-model@1.0.6`（organization_period_inventory）、`nebula.organization-lifecycle-carbon.steel-model@1.0.10`（organization_lifecycle_carbon）、`cbam.eu.iron-steel.bf-bof-partial-review@1.0.7`（cbam）。`MethodSchemePanel.tsx:129-141` 按 `method_group` 分组、每条 `methods` 渲染一张 `SchemeCard`。故全新库「核算设置」＝**4 张大卡：产品 1／组织 2（期间清单＋生命周期碳）／CBAM 1**；组织两张并列即用户否定的「每类两套方法」。每张官方卡又带「复制并调整」主按钮（57）、缺口计数（54）与声明覆盖/未声明端口（48-53）＝「规则缺口计数墙」。全链路无「任务角色／单一当前预设」概念：方案集条目只有 `{package_id,version,content_sha256}`，`TemplateMethodLibrary` 且 `extra="forbid"`（`template_method_libraries.py:20`）。

**② PCF 强迫复制规则。** 官方 PCF 条目 `editable:False`、`user_method:None`、`actions:["view","copy_and_adjust"]`（815），唯一前进动作是 `copy_official`（461-538）建草稿用户方法。`MethodRun.tsx:38` 的运行按钮 `disabled` 除非 `version.status==='ready'`（即已校验的用户方法版本）；模板卡没有「用基础特征化方法直接算完整模型」的入口。底层其实支持：`solveContract.ts:52-56` 允许省略 `calculation_method_ref` 并携带 `climate_default`/`lcia_methods`。故缺陷在 UI 入口，不在求解合同——A2 可达。

**③ Scope 编辑缺口。** `ScopePanel.tsx` 由 `view` 分两个互斥视图，在 `MethodEditor.tsx:188-190` 落成两个 Tab：`scope` 视图列＝边界归属 `boundary_status`（201-205）＋位置角色 `location_role`（206-210）＋纳入CBAM `cbam_relevant` 开关（211-213）＋规则来源（229-230）；`grouping` 视图列＝结果分类 `scope`（215-219）＋自定义维度（220-227）＋来源。即「是否计入」（boundary_status）与「范围1–3」（scope）分属两 Tab，读者无法在同一贡献行同时设定；且 `boundary_status` 与 `cbam_relevant` 是两个可冲突开关（§2.2 禁止）。过程默认表单 `method-scope__defaults`（139-162，含方向/域选择＋新增按钮）位于流表上方，违反 §2.2 首屏预算与「不新增隐含过程默认继承体系」。

### 9.2 现有→目标字段映射（§4 拟新增语义落到现有 schema）

| 目标语义 | 现有载体 | 适配方向 |
| --- | --- | --- |
| 任务角色（完整计算/CBAM/分类） | 无；仅 `method_group`（METHOD_GROUPS） | 方案集声明 `task_role`；发 `steel-1.1.7`，`TemplateMethodLibrary` 增可选 `tasks`（向后兼容，旧 1.1.6 无 tasks 仍校验） |
| 显式默认方案 ref | 无；`read()` 平铺全部 bound refs | `tasks[].default_ref` 指唯一预设；其余归该任务「其他口径」 |
| 是否计入（唯一开关） | `boundary_status`(selected/excluded/pending) ＋ `cbam_relevant`(bool) 两开关 | 后端把单一「是否计入」一致编译到 `boundary_status`(+必要时 `cbam_relevant`)；前端只暴露一个开关 |
| 结果分类（Scope1-3/自定义） | `rule.scope` ＋ `rule.categories[dim]` | 与「是否计入」同表同行；排除保留原 `scope`，重新纳入可恢复 |
| 可编辑贡献行 | `ScopeRow`（`flowRows.ts:buildScopeRows`）按 `process::port` | 复用；内部连线/产品输出（`internal`/`output`）默认不进可核算表，只读可查 |
| 有效计入/有效分类 | `ScopeRow.effective = rule ?? process_default` | 复用 `effective`；`source`/来源证据收进按需详情 |
| 编辑能力/不可编辑原因 | `editable` ＋ `actions[]` | 复用；官方包 `editable:False` → 任务行「查看与调整」首次修改在内存建草稿，保存才建用户版本 |

### 9.3 包职责（合成任务，不要求用户懂内部包）

- **CBAM 任务**：`cbam_trial`（直接计量）＋`cbam_partial_review`（部分复核）是同一任务的两个内部包；§2.1 要求合成一个任务的结果章节/检查。当前 1.1.6 只绑 partial-review；trial 走 CBAM 专用链路（`services/cbam_trial.py`）。不得为简化界面放宽 CBAM 守卫（§3）。
- **范围1–3 任务**：`organization_lifecycle_carbon`（生命周期口径，默认）＋`organization_period_inventory`（GHG 发电口径对照，按需「其他口径」）。保留真实差异，不暗中合并/混算/冒称等价；合法自定义范围2仍可含购电上游总量（§4）。
- **完整模型计算任务**：`product_carbon_footprint`，取气候指标；是内置计算方式，非要求创建的用户方法。已有 PCF 自定义历史仍可在「其他方案」打开，不删不改写旧结果。

### 9.4 旧链接与历史兼容映射

- **深链**：`TemplateConfigPage.tsx` 用 `?tab=model|methods`（38）、`?method=<user_method_id>`（99-114）；`MethodEditor.tsx` 用 `?version=<n>`（52-55,163-165）。§2.2 要求旧深链带精确模板/模型/修订/方案/版本进新工作区、不静默落默认方案 → 新任务行入口须继续接受 `?method=`/`?version=` 并定位到对应任务的方案选择器。
- **历史只读**：官方包 immutable；用户方法版本 immutable＋`content_sha256`；旧 API `/api/v1/calculation-methods/*` 与 `/api/v1/project-templates/{id}/accounting-methods` 保留。`read()` 仍须输出 `methods[]`（旧消费方＋「其他自定义方案」列表），**新增** `tasks[]` 视图，不删 `methods`。
- **方案集版本**：`steel-1.1.6.json` 移入 `archive/`（原字节保留），`steel-1.1.7.json` 为唯一 profile 匹配——loader 对同 profile 多匹配抛 `TEMPLATE_METHOD_LIBRARY_AMBIGUOUS`（`template_method_libraries.py:51-52`），故不能并存。已安装库的 `method_pins`/`content_sha256` 不变；只有新建模板实例接收 1.1.7（`seed_projects.py:292-305`）。

### 9.5 有区分力失败案例（P1/P2 fail-first 落地，现均为 fail）

- **F1（P1）**：对绑定 1.1.7 的模板，`read()` 输出 `tasks` 恰为 3（complete_model/cbam/scope_classification），每任务唯一 `default_ref`；组织任务不再平铺两张并列官方卡。现 fail：无 `tasks` 字段，`methods` 为 4 条、组织 2 条。
- **F2（P1/P4）**：完整模型计算任务可不复制、不带 `calculation_method_ref`、携带基础气候方法直接求解得非空 LCIA 结果，用户 ref 为空。现 fail：`MethodRun` 要求 `version.status==='ready'` 的用户版本。
- **F3（P2）**：同一贡献行一次编辑同时设「是否计入」与「范围1–3」，后端编译到 `boundary_status`+`scope`，正式读回一致；界面不暴露 `cbam_relevant` 第二开关。现 fail：两者分属两 Tab/两开关。

数值/身份/历史断言不因选择器更新而删除（§6）。以上仅为 P0 核对结论，不代表 P1–P6 已实施。
