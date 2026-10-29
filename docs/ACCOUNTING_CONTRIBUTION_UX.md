# 0.1.1 修改方案：默认 LCIA 与自定义核算规则分开

> 2026-10-27 更新：用户已否定旧编辑器体验，后续统一按 [Flow 标签与结果归集开发方案](QODER_FLOW_TAGGING_PLAN_20261027.md) 实施，底层先行。先定义标签及分类，再逐过程逐流匹配，结果按标签筛选汇总；下文的双开关编辑、版本展开区及分类置底要求已被替代。历史验收记录保留，不代表新方案已实现。

2026-10-17 · 修订 v3 · Qoder 最终开发任务书。

**2026-10-18 收尾覆盖说明：** 本文下方阶段记录保留历史现场，当前状态以 [公共运行时收尾](acceptance/PUBLIC_RUNTIME_CLOSEOUT_20261018.md) 为准。公共因子源的身份/覆盖分离已实现；最终 0.1.1 包的四任务、导出、重启、实际桌面窗口和四视口浏览器验收通过。默认 LCIA 位于模型设置，按精确方法声明读取；规则页只管理 CBAM、范围1–3及用户规则。总量/单位产品由冻结参考产出统一换算，缺因子显示小计与清单。开发侧完成，等待用户最终审核；未推送。

本方案以用户最新要求为准，替代此前“完整模型计算作为一类核算方案”的设计。Codex 本轮只交付开发文档；用户将本文件交给 Qoder 后，Qoder 按第五节顺序连续实施、验证并打包，不再逐阶段询问是否继续。此前通过的工程检查不代表本轮产品通过。

## 用户任务

### 2026-10-18 用户实测后的界面修订

本节已实施并在修订包验证，详细结果见[模板核算界面修订验收](acceptance/TEMPLATE_UI_REVISION_20261018.md)。以下记录保留设计与触发原因，开发侧修复通过不替代用户最终体验审核。

此前“开发侧通过”仅覆盖已执行的路径，用户新建自定义方案触发 `PROJECT_TEMPLATE_UNAVAILABLE`，产品验收重开。本轮以模板列表、规则列表和规则编辑为边界，连续修复并复验，不沿用旧包结论。

使用者在桌面选择模板后，应先决定“调整 CBAM 计入项”或“划分范围1–3”，也可创建自定义分类。规则列表保留两张等宽卡：标题、简短用途、当前方案、操作；其他自定义方案用紧凑列表。使用现有 Arco 控件、蓝色主操作、共享字体与间距，不增加宣传色块。默认 LCIA 留在模型与数据。

打开规则后使用聚焦编辑：紧凑模板标题、返回方案列表、规则名称与状态；主操作是保存规则，分类建议为次操作。版本选择和复制收进“更多设置”，模板新建项目/保存模板和外层标签页在编辑时隐藏。编辑内容使用白色面板，左侧220px过程导航，右侧流列表；只持久显示是否计入和结果分类，来源证据按需展开。流筛选同行排列并有明确标签，减少长说明。返回、刷新仍定位同一模板、方法和精确版本，原有未保存确认保留。

模板编辑清单由模板聚合接口直接返回精确来源版本的展示图，不依赖项目填报绑定；展示名称复用后端版本化本地化资源，不改保存图和身份哈希。缺图/版本失配明确拒绝，不能切换到最新版本或吞掉错误。模板模式的校验仍对规则绑定版本执行。

设备策略为桌面优先（1280×800、1440×900及150%），390px提供单列与逐流卡片，次要操作自动换行。验收必须包含无填报模板的源应用中新建自定义方案、编辑CO₂/CH₄/范围分类、保存再读回，以及两个列表和编辑器的真实截图；不得用模拟编辑器组件证明真实链路通过。

**产品碳足迹直接使用底层 LCA 模型和默认 LCIA 气候指标，不是用户自定义核算方法，不需要创建、复制、逐流声明或校验规则。** 默认 LCIA 还可以承载已支持的其他环境影响指标；本轮不额外承诺完整 EPD 编制功能。

**自定义规则只解决两个问题：哪些贡献计入，以及计入后归到哪一类。** CBAM 是带有特定约束的边界预设；范围1–3是结果归集预设；用户可在同一个编辑器中调整或建立自己的类别。自定义规则不能改变基本流的特征化因子、伪造缺失的背景贡献或修改默认 LCIA 的原始结果。

两条流程共用同一个底层 LCA 模型、精确版本和背景关联。模板保存模型与预设规则；项目继承独立副本，历史结果保持冻结。

## 一、导航和页面

### 模板工作区

保留两个页签：

- **模型与数据**：过程、流、模型连接、背景关联、参考产品与产量。默认评价指标放在这里的简洁信息区，例如“气候变化 · EF 3.1”；详情中显示版本和来源。它是计算设置，不是核算规则。
- **核算规则**：只展示“CBAM”“范围1–3”及用户命名的其他规则。删除“完整模型计算”卡片和两个同名的产品碳足迹下拉选项；这里不再有 PCF 方案。

默认规则每种只显示一个明确的当前预设；历史版本、内部包及被预设引用的子组件不能自动变成并列方法。可选的不同业务口径必须有真实差别、中文说明和明确来源；没有这些信息的包保留追溯能力，不暴露为普通用户选项。

规则卡只保留名称、简短用途与“查看 / 调整”。内置规则第一次调整时创建用户副本，随后继续编辑该副本。不要每次点“调整”都生成新方法。用户自行“另存方案”时才创建另一份。

“新建规则”在当前模板内打开名称及结果分类设置，提交后进入同一编辑器。不得跳到旧应用级方法目录，不要求重新选择模型、修订或数据版本。

### 项目计算入口

“产品碳足迹”直接使用默认 LCIA，显示参考产品、计算需求、评价指标与背景缺项。点击计算不出现用户规则选择，不要求“检查并使用”某个自定义 PCF 方法。

“CBAM”“范围1–3”“自定义分析”才显示对应的规则选择、版本和检查结果。已选规则不适用时明确指出问题，不回退默认规则。

结果页把“产品碳足迹”和“按规则核算结果”分开。自定义边界排除 CH₄ 后，默认 LCIA 总量仍保持不变，只有该规则的计入量、排除量和归集结果变化。

### 计算设置：计算目标与结果口径（本轮必须实现）

这是默认 LCIA 与自定义分析共用的设置，不是第三种方法或规则。模板在“模型与数据”中保存默认值；项目在计算前确认实际目标，结果页可切换合法的显示口径。

首屏用一个紧凑设置区表达：

```text
计算目标    [粗钢 ▼]    数量 [1,000] [kg ▼]
结果口径    [本次总量] [单位产品]
单位产品时  每 [1] [kg ▼] 粗钢
评价指标    气候变化 · EF 3.1        [查看来源]
```

| 设置 | 业务含义与交互 |
| --- | --- |
| 计算目标（功能单位） | 选择模型中可用的参考产品/服务，输入需求数量与兼容单位；显示完整描述，如“生产 1,000 kg 粗钢”。不能只存一段自由文本，必须绑定精确参考产出身份 |
| 本次总量 | 显示满足本次需求的 LCIA scores；组织任务显示指定批次或期间总量，并明确期间。单位例如 kg CO₂-eq，不带产品分母 |
| 单位产品 | 用同一次求解的总量除以对应参考产出，再换算到选定基准，如每 1 kg、每 1 t；结果必须带分母单位，例如 kg CO₂-eq/kg 粗钢 |
| 默认值 | 产品碳足迹默认单位产品，范围1–3默认总量，自定义分析默认总量。CBAM 的法定专用指标继续使用其固定单位；用户切换的总量/强度只作用于辅助展示，不能改变既有专用公式或法定分母 |

不要用含糊的“是否归一化”复选框。这里实现的是按参考产出折算；LCIA 中按人均、地区参考值的归一化以及权重加总不在本轮范围内。

功能单位还可能包含质量、寿命、服务性能等条件；本轮保留模型已有功能描述并绑定量化参考，不自动声称仅选了“1 kg”就满足任何比较研究的全部功能等价条件。

#### 唯一换算规则

设同一次求解的总贡献为 T，参考产出为 Q，选定展示基准为 b。Q 与 b 先使用有来源的单位换算转换到同一计量单位，然后计算 `单位产品结果 = T × b / Q`。

- 生产 1,000 kg 粗钢、总贡献 2,000 kg CO₂-eq，则本次总量为 2,000；每 1 kg 为 2；每 1 t 为 2,000。此处是便于核验的算术案例，不写入产品或官方数据。
- 改变需求数量、参考产品或模型数据，需要生成对应的新计算，不把旧结果线性放大冒充引擎新求解。固定技术模型下需求翻倍的验收应观察总量翻倍、单位产品结果不变。
- 仅切换总量/单位产品或 kg/t 基准，复用同一冻结的求解快照，由服务端统一生成结果投影；不修改图、排放规则、活动量或原始快照，不重复求解。
- 所有计入、排除、未归集、范围分类、过程贡献使用同一基准换算；不能只换总数而让分项仍保持总量口径。未知贡献仍为缺项，不能参与除法后变成零。
- 不对各个过程各自除以产量，再把所得强度相加；不重复除已经是强度的旧 PCF 结果。先确认每个原始字段的总量/强度语义，保留总量为统一来源。
- 多产品或多需求向量没有单一可解释分母时，允许总量查看，单位产品入口禁用并解释原因。不得随便选第一项、按名称推断或偷偷新增分摊；只有已有明确的目标产品归属结果才允许按该产品换算。
- 参考产出/基准缺失、为零、负数、NaN/无穷、单位不兼容、身份不属于当前模型版本，服务端明确拒绝单位产品换算；不得回退分母 1。负的影响贡献可以合法存在，不与非法的负产出混淆。

#### 前后端契约与持久化

优先复用现有 `project_workspace` 的 demand、`demand_mode: reference_output|explicit`、精确模型版本以及 `analysis/pcf.py` 中的功能单位解析，避免另建第二套需求来源。Qoder 首阶段记录各字段对应关系，确认“参考产量”和“求解需求”如何形成 Q，不凭同名字段假定相等。

下列为本轮拟新增或适配的逻辑契约，**不是声称现有 API 已支持**：

| 契约内容 | 必须包含的语义 |
| --- | --- |
| 计算目标 | 精确模型/修订、目标过程/输出端口/流身份、需求数量及单位；改变目标进入求解指纹 |
| 结果口径 | total 或 per_reference_output、展示基准数量及单位、分母对应身份；不能只存 normalized 布尔值 |
| 冻结来源 | snapshot、评价方法/指标、原始总贡献、实际参考产出数量/单位及来源、换算比例；自定义分析另含规则/执行身份 |
| 读回与导出 | 返回转换后的总数和全部分项、完整结果单位和口径；同一结果投影标识随导出冻结，屏幕、API、XLSX、HTML 必须匹配 |

服务端是正式换算的唯一实现，前端只做输入校验、格式化和显示。结果投影缓存/导出指纹包含 snapshot、指标、规则身份（若有）、口径、基准数量和单位；纯展示切换不改变底层 solve_hash。需求或规则变化则按已有计算身份机制产生对应新结果。慢请求不能把上一口径覆盖到新选择。

模板保存默认计算目标与口径；新项目继承独立设置。结果页切换为该快照的查看选择，不悄悄修改模板或下一次计算需求。历史记录有完整依据才能换算；缺依据只保留原始口径和原结果，显示不可换算原因，不篡改旧 hash。新旧 API/数据库兼容由适配层处理，必要迁移先在副本验证。

## 二、逐过程逐流的语义

- 基本流：用精确流身份及评价因子计算贡献；可选择是否计入及结果类别。缺因子是缺项，不是零。
- 外购中间流：设置的是该消费路径的上游贡献。须关联背景供应过程或有可追溯的供应数据，单凭数量和“计入”开关不能产生排放。
- 模型内部连接：保留模型物料传递和求解关系，排放在对应生产过程计算一次；不重复挂外购背景、不把中间产品质量当排放。界面显示内部传递，不作为新增碳贡献的计入开关。
- 产品输出：保留参考产品及产量用途，不当成直接排放；不在本轮扩展下游、替代或分摊算法。

内部传递的“无需单独计入”不等于删除内部连接，也不等于排除生产该中间产品的过程排放。是否计入生产过程的基本流，应到该过程的基本流行设置。

上述类型必须由精确图连接、端口类型和背景绑定确定，不能用名字或“没有背景关联”反推为内部流。若一个输入存在部分内部供给及部分外部供给，须区分两部分的真实路径；不能把整个输入一概锁成内部流，也不能对整个输入重复挂背景。现有接口不能分辨时返回可定位的问题，不猜测。

外购输入既有背景关联又有手工因子等其他来源时，必须显式确定采用哪个来源，并验证没有重复计量。没有可用来源时显示“待关联背景”，不能因选中“计入”而出现零贡献或完整覆盖。

基本流缺适用因子时显示“缺评价因子”；已明确排除和缺因子是两种状态。真正数值为零也要保留其计算来源。

## 三、规则编辑器

沿用现有模板工作区、过程列表、逐流表。逐流名称下显示其业务类型及计算来源。内部连接和产品输出保留可读行，但不能批量选择成新的贡献；旧规则仍可见、可移除，不静默改历史记录。外购流提示关联背景要求。来源/版本折叠，不增加技术列。桌面优先，390px可读；不再以按钮能点击代替用户理解与数值验证。

主表固定为“流与来源 / 是否计入 / 结果分类”。基本流显示排放或资源及单位；外购流显示供应过程和关联状态；内部传递显示相连过程和不重复计量说明。内部流放入“内部传递与产品量”折叠区域，默认优先展示可操作贡献，避免几十行无关选项。

左侧选择过程，右侧编辑其贡献。批量操作只影响明确选中的可编辑行，提交前列出修改数量。搜索电力、热、蒸汽、燃料等只用于筛选；自动分类先预览建议与依据，再由用户确认，不自动写入。

范围1–3直接作为结果分类选择项；可增设自己的分类。不要求用户理解“贡献域”“规则层级”等内部术语。“是否计入”和“结果分类”相互独立，排除时保留已选分类，重新计入后可以恢复原分组。

范围1–3沿用本产品确认的生命周期归集口径：允许购电生命周期贡献归入自定义范围2。不得默认替换为 GHG Protocol 发电口径；若显式提供 GHG 对照预设，必须单独标明其不同要求。

保存区统一为“保存”“检查”“试算”。保存生成不可变版本；检查错误定位到具体过程和流；试算展示计入、排除、未归集及缺项。底部提供一个回到模板的入口，避免重复返回链接。中文模式使用已有模型中文元数据；缺中文时保留原名，不在前端硬编码 UUID 翻译表。

## 四、前后端改造清单

| 模块 | 改造要求 |
| --- | --- |
| `template_accounting_methods.py` / 模板方案集 | 默认 LCIA 与规则集合分别返回；只有明确业务预设进入规则选项。旧包可按精确引用追溯，禁止删除旧快照依赖或用 latest 替换 |
| `TemplateConfigPage` / `MethodTaskPanel` / `ModelDataPanel` | PCF 从规则页移到模型计算信息；新建规则留在模板内；禁止再次引入旧方法目录 |
| `MethodList` / `MethodEditor` | 新建只面向边界与归集规则；普通入口不提供 PCF 规则类型。旧自定义 PCF 记录可读、历史结果可重放，不能直接删除或静默改 purpose |
| `flowRows` / `ScopePanel` | 用图和绑定生成基本流、外购路径、内部传递、产品量四类；只对真实贡献显示计入与归集控件；支持缺项与部分供给识别 |
| 求解入口 / `method_execution_contract` | 默认 LCIA 不带用户规则依赖；自定义分析绑定精确规则版本/hash，基础评价方法仍独立冻结。前端移除选项不能代替后端检查 |
| `project_workspace` / `ProjectDataForm` / `ProjectWorkspacePage` / API schema | 复用现有需求契约提供目标数量、参考产品及单位；区别改计算目标与改结果显示；非法目标在后端拒绝 |
| `analysis/pcf.py` / 结果投影服务 / 各导出模块 | 核清总量与强度字段后共用一个换算实现；分类分项与总数同步转换，冻结分母和投影身份；不得新增前端算法副本 |
| 结果与导出 | 默认 LCIA 与自定义结果分别标识；都能追溯模型、指标和数据来源；规则结果额外冻结规则与执行身份，屏幕/API/导出一致 |
| 桌面启动门与打包 | 如返回结构变化，同步实际 runtime.cjs 门及负对照；必须经 app.asar 启动验收，不允许直接拉后端冒充桌面启动 |

底层参考产量与需求求解仍由 LCA 引擎处理。产品碳足迹按参考产品呈现；范围归集展示本次批次或期间总量，不再对各过程额外做一次产品强度归一化，不重复乘期间系数。

## 五、分步实施顺序

1. **清点与冻结**：记录当前 Git、旧库方法/快照依赖、默认 LCIA 请求和结果；读取图中的内部连接与背景消费路径，列出真实字段。先建立 CO₂/CH₄ 基准案例，不调整结果来迎合界面。
2. **拆开两条流程并贯通计算设置**：修改模板聚合与项目入口，移除规则页的 PCF，修复新建规则跳旧目录。先做一条纵向链：选择参考产出/需求→真实默认 LCIA→总量/单位产品切换→导出。确保完全没有用户规则的新库也可计算，分母与精确快照一致，再扩展到自定义结果。
3. **按贡献类型重做编辑**：基本流与外购路径分别提示、内部流不提供新增贡献开关；背景关联进入已有数据编辑能力，返回时保持模板/过程上下文。先补判别性测试，再最小修改。
4. **数值与历史接缝**：完成规则纳入/排除、范围重分组、需求缩放、结果口径切换、非法分母/单位负对照、重复计量负对照及历史重放。修正根因，不用只隐藏 UI 的方式掩盖后端问题。
5. **真实 UI 与包**：按下列案例从用户按钮完整走到结果和导出，检查截图；通过后才重建 0.1.1 并用封装运行时复验。用户最终审核前禁止 push、PR、Release 或云部署。

每步本地小提交并更新验收表；日常实现选择按本方案继续，不反复要求用户决定下一步。发现真实口径冲突时明确列出冲突依据与影响，不伪造标准或业务数据。

## 六、必须完成的验收案例

| 案例 | 通过条件 |
| --- | --- |
| 新库默认 PCF | 无任何用户规则，从模板建项目直接 LCIA 得到非空结果和导出；规则页没有 PCF、完整计算或重复 PCF 选项 |
| 单过程 CO₂/CH₄ | 10 kg CO₂、0.1 kg CH₄，因子从实际引擎回执读出；若本次为 1/29.8，则原始 LCIA=12.98，排除 CH₄ 的自定义结果=10，排除=2.98；改规则后原始 LCIA 与旧结果不变 |
| 内部连接 | 两过程通过中间产品连接，内部传递保留；各过程基本排放恰计一次。相同名称不能影响身份判定；批量全选不把内部产品数量当排放 |
| 外购背景 | 两个过程共用同一背景数据集，仍按各自消费路径贡献计量；数量和单位转换有来源；排除一路不影响另一路及前景排放 |
| 缺失背景/因子 | 缺背景、缺因子、明确排除、真实零四种状态可区分，不出现虚假 100% 覆盖或完整 PCF 结论 |
| 范围归集 | 同一非零贡献从类别 A 移到 B，两类变化正负相抵，总量不变；购电生命周期可按产品自定义口径归入范围2；外购非电供应链用明确标注的机制数据验证范围3 |
| 需求翻倍 | 批次贡献总量恰好翻倍，产品强度不变，无二次缩放 |
| 总量/强度/单位转换 | 同一真实快照测 total、每1 kg、每1 t；验证 `强度 × Q / b = 总量`，所有范围、计入/排除/未归集分项同步且对账；截图能读出目标、需求、分母与单位 |
| 仅切换显示 | total→per_reference_output→total 后原始 snapshot/solve_hash 不变，无新求解任务；结果投影/导出身份按口径区分；快速切换后旧响应不覆盖新口径 |
| 目标变更 | 改需求或参考产出必须实际重新求解并冻结新身份，旧快照及导出保持不变；不能复用错误目标的缓存 |
| 分母负对照 | 零、负数、缺失、非有限数、跨模型身份、kg/kWh不兼容、无归属的多产品均明确拒绝单位产品结果，不产生默认分母或 NaN 导出 |
| 历史兼容 | 已有强度字段不被再次除产量；缺分母来源的旧记录原样可读并明确不能换算，不靠猜测补齐 |
| CBAM 预设/副本 | 原预设结果不变，用户副本调整真实非零基本流后自定义计入量确实改变；被排除量保留账目；不得把用户变体称为官方监管结论 |
| 保存与继承 | 保存为我的模板→建项目→独立规则副本；修改来源不改已定稿模板/历史项目；重启读回版本和 hash 一致 |
| UI 与导出 | 1440×900、1280×800、150% 缩放、390px可读；从新建规则到试算无需进入旧方法目录；屏幕/API/XLSX/HTML 数值及冻结身份一致，空结果判失败 |
| 桌面 | 全新隔离库经 app.asar 启动门、四任务、重启读回；旧库仅用备份副本兼容验证，原用户库字节不变 |

不把单测、DOM 可达或页面无报错当成整体验收；逐案例记录通过/失败/未跑、产品提交和证据文件。当前旧包不满足本方案，不能沿用旧包“已完成”结论。

## 七、本轮工作区处理

写本方案前已有未提交的导航、文案、默认包选项和流只读处理。这些是临时修改，不代表本方案完成。继续实施时逐项审查保留或修正，尤其“仅把完整模型计算改名为产品碳足迹并仍留在规则页”已经被本方案否定。不得误提交为最终产品。

本轮不新增差额法、CCER 公式、分摊编辑器、额外活动量×因子模块或任意算法脚本。已有对应数据接入与历史计算保持兼容。

## 八、Qoder 开工与回交约束

- 唯一 One 主线：`D:/VibeCoding/project/nebula-one`，本方案修订前 HEAD 为 `824518e`。从包含本 v3 文档的当前主线继续，不切回 release-candidates，不重置现有未提交修改。开工先记录实际 HEAD、diff 和未跟踪文件，再逐项处理第七节临时修改。
- 可写范围：本方案列明的 One 前端模块、API/schema、服务、分析/导出、模板元数据、对应测试与桌面必要适配。源码优先最小 UTF-8 patch；Qoder 不用 PowerShell 写代码、不整文件重写。中文名称来自项目 i18n/数据元信息，不编造逐 UUID 映射。
- LCA 位于 `D:/VibeCoding/nebula-lca`；默认复用既有引擎，只有实际公共接口缺失才做有测试的最小适配并单独提交。不得把结果显示换算移入求解器、不得复制一套求解或特征化算法。
- Python 使用 `C:/Users/31534/PycharmProjects/ILCD/.venv/Scripts/python.exe`；已有桌面构建虚拟环境按当前打包脚本使用。沿用仓库 pytest、web typecheck/vitest/build 与真实验收驱动；按当前改动补行为断言，不仅更换旧断言文案。无需反复跑用户此前拒绝的全量后端，报告实际定向覆盖和未跑项。
- 真实验证可使用自行创建、明确命名的隔离应用/数据库/端口及测试活动量；不得覆盖用户 6616 原库、接管无关服务、删除旧包/卷或商业数据。环境不可达时先核对服务身份及已有启动脚本，使用可清理的隔离实例，不直接把全部真链路交给用户验收。
- 公开包不得包含商业数据库、凭据或用户数据库；合成机制数据明确标识并保持在测试范围。版本始终为 0.1.1，仅本地提交，禁止自行 push、PR、Release、连接 GitHub 或云部署。
- 每阶段在本文维护实际状态、提交、测试命令/退出码与证据路径。最终回交包含新包绝对路径、SHA256、两仓产品提交、payload 核验、真实数值对账、逐案例结论及剩余缺项；不能用“完成阶段”掩盖未通过案例。

### 执行记录（由 Qoder 更新）

| 阶段 | 当前状态 | 回交所需证据 |
| --- | --- | --- |
| 1 清点与冻结 | 已完成（HEAD 起点 `abfd0b7`；本方案前未提交的临时改动已逐项审查：后端 `_task_view` 收敛、`isContributionRow`、流类型标签、内联新建规则均符合本方案，予以保留并纳入提交 `a48b9df`；被否定的“完整模型计算改名 PCF 仍留规则页”已纠正） | 字段映射：需求 Q＝`project_workspace.ProjectInputs.amounts`→`ProviderDemandItem.amount`+`demand_mode`（reference_output/explicit）；参考产出身份＝`reference_flow_uuid`；总量 T＝`analysis/pcf.py::build_product_pcf` 的 `total_footprint.value`（当前**无除法**）；`exports/pcf.py:333` 把总量误标“单位产品气候变化”为待修显示缺陷；solve_hash（`results.py:236-296`）不含展示口径，故 total↔单位产品切换复用同一快照 |
| 2 默认 LCIA 与计算设置 | 进行中 | 已落地：规则页只留 CBAM／范围1–3＋用户规则，默认 LCIA 指标移入「模型与数据」只读信息区（`a48b9df`，web 346 项全绿、后端 `test_template_accounting_methods` 19 项通过）；后端唯一换算原语 `per_reference_output`（`T×b/Q`，除一次、非法分母/单位/负总量全部负对照、仅冻结换算基不含快照）（`23b6c8b`，29 项通过）。**真实引擎口径已证（守门 #1）**：隔离起栈（源码引擎 exe＋源码 One，独立端口/新库，只回收自记录 PID）对同一单过程模型求解 Q 与 2Q，CO₂ 基础流合计 2000→4000 kg 恰好翻倍、单位需求强度恒为 2.0、solve_hash 随需求变化；并用历史真实钢铁快照交叉核验“CO₂ 基础流合计 1940.739734 == 特征化 `total_footprint` 1940.739734”，坐实特征化是对基础量的线性映射、`analysis/pcf.py` 原样复制、上游未预先归一化，故 `T×b/Q` 只除一次。判定器：`scripts/verify_demand_linear_scaling.py`＋`scripts/linear_scaling_run.py`（合成单过程机制数据，明确标注非设施/CBAM 结果）。**守门 #2 结果链已落地**：后端唯一投影 `analysis/result_basis.py::project_result_basis`（`total` 逐字节恒等、保留历史 hash/ETag；`per_reference_output` 复用 `per_reference_output` 原语除一次，把同一 `T×b/Q` 比率施加到总量＋每个分项＋每个热点，份额比值不变、缺项保持为缺口、负量合法，重算投影产物自身 `content_sha256` 但 `source_snapshot` 求解哈希不变即切换口径非重算）；`services/pcf.py` 在两条 analyze 返回处统一投影，xlsx/html 自动继承；请求契约 `ProductCarbonFootprintCreate.result_basis/base_amount/base_unit`（强度口径必须带正质量基准、单位限 kg/t，否则 422），`ProductCarbonFootprintOut.result_basis` 仅在投影存在时序列化（`response_model_exclude_unset`）以保持 `total` 历史字节不变；GET 导出路由透出口径 Query、ETag 反映投影哈希；`exports/pcf.py` 标题按真实口径命名（修掉“总量误标单位产品”显示缺陷）并披露口径/换算比/基准哈希/原始总量；前端 `ProductCarbonFootprintPanel` 增「结果口径」总量↔单位产品切换＋可编辑「每 N kg/t」，参考产出非质量单位时禁用单位产品并给原因（不乱猜分母），`AnalysisResultsPage` 持有口径状态并按其 keying 查询/复用同一快照，`client.ts` 导出带口径。测试：`tests/test_result_basis.py`（恒等/per-kg/per-t/全行同比/求解哈希复用/溯源/负量与缺项/schema 守卫）＋`tests/test_product_pcf.py` HTTP 端到端（切换复用 solve_hash、结果重标度、xlsx ETag 不同、html 标题随口径）＋web 面板口径切换与禁用用例，web 348 项全绿、typecheck 干净（提交 `4b8bafe`＋`ce0a33f`）。**守门 #3 参考产出身份已加固**：`analysis/result_basis.py::_reference_output_identity` 作为读侧守卫，要求冻结需求恰绑唯一参考产出选择器（输出端口 `reference_exchange_id`／过程实例 `process_uuid`／参考流 `reference_flow_uuid` 三选一，遵 provider `require_one_selector`），把所选选择器、其值与模型版本（`system_revision_id`＋`model_graph_sha256`）逐字记入 `result_basis.reference_output`；绑定数为 0 或多（共享流无端口/过程可分辨）时抛 `UNIT_BASIS_REFERENCE_OUTPUT_AMBIGUOUS` 422、绝不臆造“分母为 1”，`total` 恒等返回故调用方自动回落总量、页面把该 422 作错误呈现。诚实边界：真实产品 PCF 经 `_functional_unit` 强制恰一条需求且 `require_one_selector` 保证参考流选择器唯一，故“歧义分母”对现有真实模型不可达，属防御性后端守卫；前端可观测的“保持总量＋禁用单位产品给原因”由 `ResultBasisControl` 对非质量基准（如 kWh）禁用达成（用户不会触达 422）。新增 `tests/test_result_basis.py` 断言：绑定位记录选择器/值/`binding`/`model_version`、无选择器与双选择器两个负对照抛 `..._AMBIGUOUS`、`process_uuid` 单选择器可定分母（提交 `f2988d1`，定向 4 文件 65 项通过）。**计算目标首屏与需求绑定已在既有一层落实**：项目入口 `ProfessionalProjectPage` 绑定参考产品＋核算规模＋单位（信息不全则拒绝计算并提示补齐），后端需求派生对多/缺目标产出抛 `PROJECT_REFERENCE_OUTPUT_AMBIGUOUS`、`calculation.multipleTargets` 提示核对求解需求，与守门 #3 读侧守卫构成“多目标→保持总量/给原因”双层防护。**本阶段功能项已全部落地**，唯一遗留“EF3.1 运行时特征化数值对账”本轮**已建完整判定器并实跑，命中真实引擎侧 EF3.1 资产版本错配而如实记为 not_run（非 One 代码缺陷、非投影缺陷）**：新增 `scripts/verify_pcf_basis_reconciliation.py`（隔离起同一模型解 Q=1 kg 与 Q=1000 kg 两条真实特征化 PCF，断言引擎特征化总量随需求线性、`per_reference_output` 服务端投影之每 kg == 引擎独立 1 kg 特征化值——即 `T×b/Q` 对真实 EF3.1 只除一次、且以“独立第二求解”为参照而非投影自证、每 t＝每 kg×1000、切换口径复用同一 `source_snapshot` 求解哈希、参考产出身份绑 `reference_flow_uuid`＋模型版本、非法基准 kWh 负对照），已并入通用隔离运行器 `scripts/linear_scaling_run.py --verifier`（仅回收自记录两子 PID 38864/20220）。**实跑被引擎 `POST /api/provider/v1/solve` 以 `EF31_INDICATOR_METADATA_MISMATCH` 拒绝**：引擎运行时 `indicator_index.csv` 哈希 `d41e72b826…`（源码引擎与桌面 packaged 两处**逐字节相同**，故非陈旧可换目录）与 One 溯源/官方方法所钉的期望 `fed89fc7d1…`（`docs/DATA_PROVENANCE.md`、`pcf-ef31-foreground` 自称“legacy indicator_index.csv”）版本不一致，引擎判定 legacy 源无法精确对齐指标单位元数据。守门 #1 当年特意走 `mfa` 求解＋历史快照交叉正是为绕开此未对齐项，与本诊断一致。**不得以改钉哈希强行转绿**（引擎只读、且属真实资产版本差），须由可供给对齐数据集一侧完成 EF3.1 运行时资产对齐后复跑本判定器即可闭合；四视口截图归阶段 5。**本轮实际覆盖**：`tests/test_result_basis.py`＋`tests/test_product_pcf.py`＋`test_accounting_quantity_basis.py`＋`test_native_product_pcf.py` 定向 65 项绿、web 全量 349 项绿（HEAD 绑 `f2988d1..094d320` 后）。 **2026-10-17 复跑闭合，取代上方"阻塞/not_run"记录——按需求1证据修复，未改钉哈希、未放宽守卫、未走 MFA**：错因查清为两层。①**装载链错配**：桌面 `desktop/runtime.cjs:128` 与判定器运行器 `scripts/linear_scaling_run.py` 把 `NEBULA_LCA_EF31_DIR` 指向 `_internal/data/EF3.1`（LCIA 单位投影、无 `ecoinvent_category`）并塞进特征化 runtime 列表，触发引擎 legacy 对齐守卫 `EF31_INDICATOR_METADATA_MISMATCH`；引擎实际特征化用的是 `solver-data/EF3.1`（`identity_runtime_indicator_sha256=43cb3acd`，带 `ecoinvent_category`，与引擎 `desktop_entry.py` 省略该目录一致），故把两处指向改到 `solver-data/EF3.1`（装错即修装载链）。②**方法包指标身份过期**：装载链对齐后 `pcf-ef31-foreground@1.0.2` 的 `formula_graph.total_indicator_key` 仍是 `method_en|indicator_en` 复合键，而真实引擎发出 `ecoinvent_category` 规范键 `climate change`，报 `PCF_TOTAL_INDICATOR_NOT_UNIQUE match_count=0`；经正式版本化新建 `pcf.product.ef31.foreground@1.0.3`（`total_indicator_key="climate change"`、分量 `climate change: fossil/biogenic/land use and land use change`），置为 `_OFFICIAL_FILES` 唯一默认（避免 `_choose` 歧义）、1.0.2 冻结留存供历史绑定，同步更新 seed/测试/文档引用。另核 `d41e72b8` 与 `fed89fc7` 仅行尾 CRLF 之差（剥 CR 后逐字节相同），packaged CRLF 是陈旧构建产物，靠字节保真重建（`.gitattributes eol=lf`＋`copy2`）自然消除。 **复跑同一判定器 `scripts/verify_pcf_basis_reconciliation.py` 全 7 项断言通过**（`passed:true`、`[verifier] exit=0`、`RUNNER_EXIT=0`）：合成单过程模型（CO₂ 10 kg＋CH₄ 0.1 kg，明确标注非设施/监管结果）Q=1 kg 特征化总量 12.98、Q=1000 kg 为 12980.0 kg CO2-Eq 恰随需求线性；服务端 `per_reference_output` 投影之每 kg == 引擎独立 1 kg 特征化值（`T×b/Q` 只除一次、以独立第二求解为参照而非投影自证），每 t == 每 kg×1000；切换口径复用同一 `source_snapshot`（solve_hash 不变、非重算）；参考产出身份绑 `reference_flow_uuid=f4c2a1b3-…`＋模型版本（`system_revision_id=27d53421-…`＋`model_graph_sha256=cf48cf8c-…`）；非法基准 kWh 负对照拒绝换算并保持总量。证据 `.local-evidence/pcf-reconciliation/run-20261017T110315Z/`（隔离端口/新库，仅回收自记录 PID）。守门 #2/#3 真实数值闭合；四视口截图仍归阶段 5。 **守门 #3 需求 3「唯一命中」补查（同日续，取代仅绑选择器的旧口径）**：把「填一个选择器」与「命中唯一产出」分开——`_reference_output_identity` 新增对冻结快照 `scaled_technosphere_exchanges` 的实际产出解析，按所选选择器匹配 `direction==output` 的产出行，命中数 ≠1（同流被两过程产出、或一过程两端口、或零产出）即抛 `UNIT_BASIS_REFERENCE_OUTPUT_AMBIGUOUS`（details 记 `match_count`＋`producing_process_uuids`）、绝不臆造分母，恰一命中则把**实际**的 `producing_process_uuid`/`producing_exchange_id` 冻入并令 `identity` 等于该产出端口（非裸流 id）。实跑暴露并修正一处接缝缺陷：`services/pcf.py` 先前只在 native-background 分支传 `producing_outputs`，前台 `build_product_pcf` 分支漏传致投影 `reference_output` 无 producing 字段——现两分支统一传 `snapshot.scaled_technosphere_exchanges`。真实引擎复跑 `scripts/verify_pcf_basis_reconciliation.py` 现 **8 项断言全绿**（新增 `reference_output_uniquely_resolved_and_frozen`，`passed:true`、`RUNNER_EXIT=0`）：绑定的 `reference_flow_uuid=f4c2a1b3-…` 解析到**另一个**实际命中 `producing_process_uuid=ea66dbd3-…`、`producing_exchange_id=identity=unit-process::product`，坐实「解析结果验证＋冻结实际命中身份」；数值仍 12.98/12980.0、每 kg==引擎独立 1 kg、每 t==每 kg×1000、切换复用 solve_hash、kWh 拒绝。单元 `tests/test_result_basis.py` 新增 5 项（两过程/零产出/同过程两端口三负对照＋唯一命中冻结），`tests/test_product_pcf.py` 前台 HTTP 端到端补断言钉住该接缝防再漏（定向两文件 33 项 EXIT=0）。证据 `.local-evidence/pcf-reconciliation/run-20261017T113148Z/`。 |
| 3 贡献分类编辑 | 进行中 | 守门 #4 `isContributionRow` 已重审并证：模型对“同一流程两个供给方”以两个独立端口表达，一个端口的 `internal`（是否有边指向它）与其背景供给结构互斥——`services/project_background.py::background_ports` 恰为前端 `internalTargets` 的补集，`method_contribution_binding.py:50` 按消费交换路径键定 `upstream`/`direct`。故剔除内部传递输入只免重复计量（其排放随产生过程边计入模型求解），绝不连带丢弃同流外购端口之背景贡献；判定器不变（无需改码），新增负对照 `flowRows.test.ts`“同流程一端口内部供、另一端口外购”钉死该接缝（提交 `094d320`，16 项通过）。待办：基本流/背景/内部传递逐流修改链与缺项在阶段 4 数值/历史案例复核。 |
| 4 数值与兼容 | 待执行 | 第六节数值/异常/历史案例、真实引擎回执 |
| 5 UI 与 0.1.1 单机包 | **封装验收未通过（RED）**（UI 操作验收已闭合；公共 EF3.1 包已重建并逐字节核验 payload，但封装启动门在种子第 6 步就失败，四任务无法开始——记为**阻断项 B7**，详见 `docs/evidence/COMMERCIAL_DATA_INVENTORY_20261017.md` 第六节。新包 `D:/VibeCoding/releases/nebula-one/20261018-0.1.1-v3-public-ef31/`（SHA256 `883c7506a1cd2432f6e752cc19fbe62508bc5676e3c32ddee8097df6f03e0751`）与三个旧候选包一样标记**不可发行**。根因：公共特征化只有气候指标（1099 条因子全 `row=1`），而官方公共电力背景 Process 排放 SO₂/NOx（无 GWP，JRC 源 `6209b35f-…` 里确实不存在），引擎 `resolve_catalog` 的身份解析（`provider_v1.py:1481`）沿用默认 `require_elementary_factor_coverage=True` → `ELEMENTARY_FLOW_CF_NOT_FOUND`。按指令"不猜测、不置零""禁止放宽守卫"，本轮**报告缺口并交用户裁决**（候选 a 补如实溯源的非气候指标行／b 最小改引擎准入合同／c 换官方示例背景），未自行选路。本轮已落地的两个非猜测修复：`d42e960`（种子守卫不再把引擎特征化缺口谎报成"源漂移"，改抛引擎自己的 code＋流 UUID，失败优先已证）、`15a261f`（封装门从安装目录读公共供给资源并断言不解析回源码树，落实"无源码资产目录的隔离环境"）；`tests/test_open_process_supply.py` 7 项、四文件合并 30 项通过 | 实际截图、封装启动门、重启/旧库副本、新包 hash。**诚实纠正上方 1–4 阶段"闭合"的验证对象**：需求 1/2/3 的"真实引擎 7→8 项断言全绿"是 `scripts/linear_scaling_run.py` 起的**源码引擎 dist**（`nebula-lca-api/dist/.../_internal/` 同时含 `runtime/ef31` 与 `solver-data/EF3.1`，带 `ecoinvent_category`）上验证的；`desktop/runtime.cjs:128` 被改指 `solver-data/EF3.1` 对源码引擎成立，但**公共构建** `nebula-lca-public.spec` 不打该目录、且 `build_payload.validate_public_payload` 明令禁止 `solver-data` 路径名。**2026-10-17 对 `20261017-0.1.1-v3/win-unpacked`（全新隔离端口/新库，仅回收自记录 PID）跑真实封装启动门复现**：①HEAD 引擎侧车启动即在 `_bootstrap_reference_data_if_needed`→`load_ef31_flow_uuid_set`→`_resolve_ef31_flow_index_path` 抛 `FileNotFoundError: .../_internal/solver-data/EF3.1` → "Backend exited before startup"；②把 `NEBULA_LCA_EF31_DIR` 改指实存的 `_internal/data/EF3.1`（`LCIA_unit` 列、无 `ecoinvent_category`）后引擎能起，但 `climate_default` 求解返回空 `lcia_results`（`method=None`、0 行）→ `/default-method` = `CLIMATE_METHOD_UNAVAILABLE` → POST PCF 422（官方默认与自建项目两条路径均如此）。`/api/desktop/status` 地面真值：指向含三 CSV 的 `ecoinvent_category` 目录时 `ef31_runtime_source_count=1`（flows 89070），证明卡点仅是公共包缺该特征化 runtime。**e3 封装门 e1e 9/0、e2 8/0、重启读回 sha 一致**（org/Scope/MFA 路径加权不依赖前台 EF v3.1 特征化，故这些过而 PCF 不过）。**最小修复**：把 solver 仓 `data/EF3.1` 三张 CSV（`flow_index`/`lcia_factors` 与已随包的 `data/EF3.1` **逐字节相同**，只 `indicator_index.csv` 末列由 `LCIA_unit` 换成 `ecoinvent_category`）经 `nebula-lca-public.spec` 打进公共包的非 `solver-data` 路径，并令 `runtime.cjs` 指过去——不改引擎代码、不改钉哈希、不放宽守卫、不动权威 `data/EF3.1` 元数据。**此为公开数据/许可边界 + 两仓构建链决策**（`validate_public_payload` 是刻意排除商业 solver 数据的守卫；所缺内容实测仅为公开 EF3.1 类别标签），且本工作区 auto-mode 权限门会拦截该打包改动与 override 验证，**属用户裁决**，故未擅自转绿。e3 门与新包 hash 见 `.local-evidence/v3-packaged-gate/`（新包 `Nebula-One-0.1.1-windows-x64.exe` SHA256 `09327c7567b71f9a9069521c43ceeef7a28e66e38874da2e2adff1c4e28b9f51`，168,231,304 字节）。 **2026-10-17 UI 操作验收（源码栈＋公共 EF3.1 单一特征化源）已闭合**：`scripts/v3_ui_acceptance_run.py --engine-source --seed-demo --ef31-dir D:/VibeCoding/nebula-lca/nebula-lca-solver/data/EF3.1-public`，隔离端口 11431/11432＋全新库＋`prepare_steel_catalog` 先于 One 启动，仅回收自记录 PID（引擎 46024／One 6624）；证据 `.local-evidence/v3-ui-labels/run-20261017T180623Z/`。**归属门地面真值**（`engine-ef31-runtime-sources.json`）：合并后 `ef31_runtime_source_count=1`，唯一源 `EF3.1-public`（1101 flows），`ecoinvent_lcia_runtime_available=false`，即本轮界面数值全部出自许可可核验的公共特征化数据、无 ecoinvent 衍生表混入；`[ui-setup] total T=12980.0`（每 kg 12.98）。**三套真 headless Chrome＋CDP 判据同轮全绿**：result-basis 23 项 0 失败 0 notRun、scope-editor 14 项 0 失败 0 notRun、labels 54 项 0 失败 1 notRun；四视口截图齐备（1280×800、1440×900、150% 缩放、390px）。**指令二两类流状态在真实 5 过程钢铁项目上实测成立（不再是 notRun）**：走遍全部 5 个过程（7/8/7/2/4 行）后，10 条外购投入行**逐行**写「外购投入：背景关联状态及上游贡献 · 未关联背景，上游贡献不计入」（该演示模型未配置背景供给，故"未关联"为真值而非漏判），4 条内部传递行**逐行**写「内部传递，不单独计入」且计入/贡献列为 `—`（保留模型连接、不重复计量）；范围分类下拉一次点击即得「范围1／范围2／范围3」（沿用星云口径，未换标准）；缺口分行按 API 自身 coverage 桶分开呈现（本轮非空桶 `unattributed_exchange_ids`；`未匹配因子` 因引擎 `ELEMENTARY_FLOW_CF_NOT_FOUND` 守卫在夹具上不可达，每轮均记录探测结果而不伪造）。**驱动可靠性修复**（`scripts/browser/cdp.mjs`）：CDP `send` 加超时并在 ws close/error 时拒绝挂起调用、事件缓冲有界（超限计数不吞判据）、`Page.javascriptDialogOpening` 自动接受并记录、`Inspector.targetCrashed`/`Target.detachedFromTarget` 记为异常、`Page.navigate` 丢回复时经 `location.assign`／新标签恢复，全部异常由 `cdp_session_had_no_lost_replies` 断言（本轮 `anomalies: []`）。**诚实边界（1 项 notRun）**：`unsaved_draft_guard_objects_before_leaving_the_scope_editor` 无法在本 CDP 会话取证——headless Chrome 全程未发出任何 `Page.javascriptDialogOpening`（`dialogs: []`），故记 notRun 并附地面真值；该未保存保护由 jsdom 套件 `web/src/pages/CalculationMethodsPage.test.tsx` 断言。前两轮间歇性 `page_navigate_no_reply`＋`session_unresponsive`（`run-20261017T174506Z`／`run-20261017T175201Z`）根因即 Phase C 改选另一个分类值把草稿弄脏→下一次导航触发模态 beforeunload 提示、渲染进程在提示被回答前不应答任何命令；本轮改为「重新点选已选中项」关闭下拉（草稿保持干净）后连跑无异常。**仍未闭合**：最终 EXE 在无源码资产目录的隔离环境中的四任务＋XLSX/HTML 导出＋重启读回（#135/#136/#142）——按用户裁定，**不能再用源码运行通过替代封装验收**；旧候选包继续标记不可发行。 |
