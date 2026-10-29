# 0.1.1 公开候选版验收（2026-10-16）

2026-10-16。本轮按[0.1.1 核算设置收敛计划](../ACCOUNTING_UX_011_RELEASE_PLAN.md) P0–P6 连续执行完成，开发与验证已结束，**待用户最终审核**。没有 push、PR、Release 或云端部署；仅本地提交。下方历史候选（20261015）不再是当前产品结论。

## 交付物

安装包：`D:/VibeCoding/releases/nebula-one/20261016-0.1.1-p6-fixed/Nebula-One-0.1.1-windows-x64.exe`。

- 大小：168218616 bytes；版本：0.1.1；未签名。
- SHA-256：`12a926df1e9e76fd36fc8a6dd15864e8bdd04638a74bbfeeea361317fa9fdb29`。
- 包内 One：`493656318daf293940269432877b52c93e61b4b1`；LCA：`e3385d3fd040425a597ecf97607f4935ff04606c`（引擎只读，本轮未改）。
- payload 2467 个文件逐项 SHA-256 校验，0 缺失、0 哈希差异（`payload-manifest.json` 记同一对提交号）。

**被取代的构建（切勿发行）**：本轮先构建的 `D:/VibeCoding/releases/nebula-one/20261016-0.1.1-p6/`（包内 One `010d21a`）其 `app.asar` 携带下述启动门缺陷、四任务封装冒烟在启动门失败，**无法启动、不可发行**，已被 `-fixed` 包取代。该目录及旧候选包可由用户自行删除；本轮未物理删除任何既有包或卷。

## 本轮修正：桌面启动门遗漏 `tasks`（发行阻断级，已修）

本轮默认核算方案集升为 `steel-1.1.7`，首次声明 `tasks`（三个读者任务：完整模型／CBAM／范围分类）。后端在 `accounting_library` 上**始终**暴露 `tasks` 键（无声明时为 `null`，见 `template_method_libraries.py:106-108` → `seed_projects.py:374-376`）。但桌面端 `desktop/runtime.cjs` 的 `matchesTemplateRelease` 构造的期望 `accounting_library` 形状**未带** `tasks` 键，`isDeepStrictEqual` 因多出一个键而恒不相等，`DesktopRuntime.start()` 的启动门据此抛出「Packaged steel template is unavailable」——**封装桌面应用完全无法启动**。

- **为何 e3 复验没抓到、四任务冒烟抓到了**：`scripts/e3_packaged_runtime_verify.py` 直接拉起打包后端（绕过 `app.asar` 与启动门），故对后端层通过；`desktop/test/packaged-runtime.cjs` 从 `app.asar` 取 `DesktopRuntime` 运行，**经过启动门**，因而在第一个包上判 `FOUR_TASK_EXIT=1`。实况诊断确认 `extra keys vs runtime.cjs expected: ['tasks']`、补 `tasks` 后 `deepEqual=True`。
- **修复（`4936563`）**：期望形状补 `tasks = Array.isArray(library.tasks) && library.tasks.length ? library.tasks : null`。`desktop/test/runtime.test.cjs` 以携带任务声明的真实夹具做**失败优先**覆盖（旧比较 RED、修复后 GREEN），并新增「任务声明分歧即不同核算版本、不得放行」的负对照。这是产品代码修复，非绕过。

## 实测结果（全部绑定 One `4936563` / `-fixed` win-unpacked）

| 检查 | 命令 | 结果与范围 |
| --- | --- | --- |
| 桌面运行时单元 | `node --test desktop/test/runtime.test.cjs` | 4 passed；含结构/方案集版本分离、`tasks` 失败优先修复与分歧负对照、哈希漂移、端口回退、handoff 绑定、编辑器代理 |
| 封装正式入口（经启动门） | `node desktop/test/packaged-runtime.cjs <win-unpacked> <fresh-data> <report>` | passed；全新隔离库自举，MFA/PCF/CBAM/组织四任务各出快照，停止后重启读回持久（persisted_reads=2 逐字节一致），原子进程 PID `[39640,18396]` 均已退出（无孤儿） |
| 封装网络组织 + 非零 Scope3 + 重启 | `python scripts/e3_packaged_runtime_verify.py --installation <win-unpacked> --data <fresh-data> --evidence <dir> --phase verify` | status=verified；e1e 网络组织归集 **9/0**、e2 非零 Scope3 **8/0**；重启后 e1e/e2 两条记录 `content_sha256` frozen==readback 逐字节一致 |
| 旧库备份副本兼容 | `node desktop/test/old-db-compat.cjs <win-unpacked> <backup-copy> <report>` | passed **9/9**；旧库启动健康（迁移在副本上跑通、启动门在旧世代库上亦通过）、全部原应用可按 id 读、方法包逐项保留、全部原求解快照列出且 MFA 可读、组织清单可读、owned 进程退出、存储层原应用/快照 id 无丢失 |

旧库副本来源为上一候选包 `20261015-0.1.1-ready` 的 `verification/four-task-data`（One 3 应用／10 方法包／4 求解快照／1 组织清单／3 期间／3 模型／1 seed 安装）。迁移后计数只增不减：应用 3→4、方法包 10→11、期间 3→4、模型 3→4（新增为桌面 demo seed 的合法 reconcile），求解快照 4→4、组织清单 1→1 **精确保留**。**原件前后 SHA-256 相同、未被触碰**：One `93f61b44a58450e291a04fa6d78c793fdf1a8cc00a82b8650e13b13bc88828da`、LCA `4599a7515c2c39e09f81a73bc28f44ba04c4cd15dde6da9a9c3e9d6b9a780518`（兼容运行只在副本上进行）。

后端/前端产品代码自 P5 工程门提交 `cb6bf44` 起**逐字节未变**（`git diff --stat cb6bf44..4936563 -- src/ web/` 为空；`95cca71..4936563` 仅改 `desktop/runtime.cjs`、其测试与本计划文档）。故 P5 的工程门证据（web typecheck 0／`npm run build` 0／web 全量 340／后端定向 208，绑 `cb6bf44`）在本 HEAD 仍成立。**本轮未重跑用户此前婉拒的后端全量套件，不宣称 tip 全量 N passed。** P5 的隔离真引擎数值与真浏览器像素验收（A1–A12，绑 `95cca71`）为本轮产品能力的机翼证据，见计划 §8 P5 行。

## 构建来源与命令（记录用）

后端为已冻结的 PyInstaller 产物（`build/desktop-backends/nebula-one-api`、`D:/VibeCoding/nebula-lca/build/desktop-backends/nebula-lca-api`）；因后端源自 `010d21a` 未变，本轮**未重跑 PyInstaller**，仅重跑 payload 组装（重盖 `one_commit`）与 electron-builder（用修复后的 `runtime.cjs` 重打 `app.asar`）。

```text
# 1) 重新组装 payload（复用冻结后端，重盖 manifest one_commit=4936563；前端源未变，跳过 web 构建）
build/desktop-venv/Scripts/python.exe desktop/build_payload.py \
    --lca-root D:/VibeCoding/nebula-lca --skip-web-build            # PAYLOAD_EXIT=0，Staged 2467 files

# 2) 重打 app.asar + NSIS 安装包（镜像规避 GitHub 下载超时；输出到两仓之外的干净目录）
cd desktop && ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ \
    ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/ \
    npm.cmd run build -- --config.win.signAndEditExecutable=false \
    --config.directories.output=D:/VibeCoding/releases/nebula-one/20261016-0.1.1-p6-fixed   # ELECTRON_BUILD_EXIT=0
```

隔离验收端口（各 harness 自取空闲环回口、自终止 owned PID，未接管他容器）：四任务 one=8694/editor=8693/lca=5846；e3 one=6296/lca=6295/editor=9829、重启 one=1111（PID lca=42888/one=9416/one_restarted=41916）。

结果证据位于安装包目录 `verification/`（`four-task-data`、`fresh-data`、`old-db-compat-data` 为隔离运行数据）与仓库忽略的 `.local-evidence/p6-build/`（`packaged-four-task-fixed.json`、`verify-fixed/packaged-verify.json`、`old-db-compat-fixed.json`、`payload-hash-verify-fixed.json`、各 stdout 日志、`old-db-source-sha256-{before,after}.txt`）。

## 公开内容检查与边界

- 本轮仅本地 Git 与产物检查：`git status` 干净，`.local-evidence/` 已被 `.gitignore` 忽略且未被跟踪（`git ls-files .local-evidence` 为空）；payload 组装期 `validate_public_payload` 通过（无 `ILCD_Unit_Groups.xlsx`／`elementary_flows_sample.csv`／`tiangong_processes.zip`／`china-grid-co2-2023.v1.json`／`ghg_ef31_v1.json` 等禁用旧资产、无 `solver-data`）。这是指定模式检查，不是完整安全认证；未连接 GitHub。
- payload 白名单不含运行数据库、ecoinvent 商业向量或认证商业映射包。公开时仅选择安装包、说明与校验和；**不得**把 `verification/` 数据库、用户数据或整个构建目录上传。数据来源以 `docs/DATA_PROVENANCE.md` 与 `docs/RETAINED_SOURCE_DECLARATIONS.md` 为准。
- 用户已安装实例 `127.0.0.1:6616`、用户原库、共享栈（18938/18931/18932）、所有旧包与卷**均未接管、未替换、未删除**；旧库兼容仅用**备份副本**。
- 真实业务数据缺项如实保留、不置零、不编造「官方 Scope 完整」：公开钢铁数据集仍无非电力物料供应商活动量；CBAM 合格电力因子 `ore-sintering::grid-electricity-in` 仍缺（ST-12）。非零 Scope3 的验收夹具是明确标注的合成机制数据，未注入官方种子。
- 未签名；服务定位为本机使用，不作为带鉴权的公网服务器。封装运行时验证运行的是安装包生成的实际资源与冻结后端，**不替代**干净 Windows 机器上的安装向导、SmartScreen 与最终人工体验审核。

**最终交付状态：本轮开发与验证完成，待用户最终审核（非「已可发布」）。**
