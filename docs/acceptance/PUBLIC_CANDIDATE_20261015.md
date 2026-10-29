# 0.1.1 公开候选版验收

2026-10-15。开发侧已完成本轮公开候选版整理，等待用户安装试用及最终公开审核。没有 push、PR、Release 或云端部署。

## 交付物

安装包：`D:/VibeCoding/releases/nebula-one/20261015-0.1.1-public-candidate/Nebula-One-0.1.1-windows-x64.exe`。

- 大小：169054501 bytes；版本：0.1.1；未签名。
- SHA-256：`b6ceb1c37f5477cdc8dfcd6b89c7fd51310cc921201f9236dbe9649d75cb8717`。
- 包内 One：`2ad81de827648100a8970223b86e1aee3e41ed79`；LCA：`e3385d3fd040425a597ecf97607f4935ff04606c`。
- 后续兼容验收脚本和本文提交不改变包内产品代码。2509 个 payload 文件逐项校验，无缺失或哈希差异。

## 本轮修正

默认核算方案集使用 1.1.6，结构模板仍为 1.1.4。实际封装启动暴露桌面端把这两个版本当成同一版本的问题，已在 `f57c8b2` 修复。启动现在核对方案集声明、内容哈希及结构模板身份，拒绝篡改或歧义；旧版无方案集的模板仍按其旧契约检查。启动失败时的验收进程也会清理自身子进程。

自定义范围1–3继续采用生命周期贡献归集，允许将购电生命周期贡献归入自定义范围2。显式选择的 GHG 对照方法单独执行其口径要求，不覆盖自定义方案。方法包保持版本化；旧方案和旧快照不跟随新默认版本改变。

旧库兼容脚本原先误要求方法包总数不变，新版本注册会使该断言失败。现核对全部原方法的 id、package_id、version、content_sha256、manifest 逐项不变，并要求 API 可读；新增方法合法。原失败报告保留为 `verification/old-compat.json`，修正后在另一份全新备份上复验，未复用升级后的副本。

## 实测结果

| 检查 | 结果与范围 |
| --- | --- |
| 受影响后端回归 | 117 passed；未重跑全量后端，不宣称全量通过 |
| 前端 | 337 passed；typecheck、build exit 0；既有大 chunk 告警仍在 |
| 桌面运行时 | 4 passed，包含结构/方案集版本分离、哈希漂移和旧版兼容 |
| 封装正式入口 | MFA、PCF、CBAM、组织四任务通过，重启后持久结果可读 |
| 封装模板方案 | 18 项真实接口检查通过，包括默认身份、官方与复制规则等价 |
| 封装自定义规则 UI | 25 项浏览器断言通过，非零 Scope3、排除、重分组、下载与读回 |
| 封装整体复验 | 14 项通过，含2509文件校验、Excel/HTML内容核对和同库重启 |
| 旧库备份兼容 | 9 项通过；全部旧应用、方法、快照及组织清单保留可读 |

结果证据位于安装包目录的 `verification/four-task-final.json`、`verification/scope3-final/release-scope3.json`、`verification/scope3-final/template-library/summary.json`、`verification/scope3-final/ui/`、`verification/old-compat-final.json`。命令日志位于仓库忽略的 `.local-evidence/public-ready-*.log`。

主要复验命令（以仓库根目录执行，参数使用隔离目录）：

```text
node --test desktop/test/runtime.test.cjs
node desktop/test/packaged-runtime.cjs <win-unpacked> <fresh-data> <report.json> --official-defaults
python scripts/verify_scope3_release.py --installation <win-unpacked> --data <fresh-data> --evidence <evidence-dir>
node desktop/test/old-db-compat.cjs <win-unpacked> <fresh-backup-copy> <report.json>
```

旧库原件前后 SHA-256 相同：One `60d6835d42bfee671aad12d71286fc381e8eb91dd384b3a591b362b84cd24c46`；LCA `ec82160939af243f8b582ae3ff2c72fdb2ef3ed6904cba0d2e1c9f198b64afb4`。用户6616实例、用户原库、所有旧安装包均未接管或替换。

## 公开内容检查与边界

当前701个跟踪文件的密钥特征扫描无命中；本地历史的数据库、私钥和商业向量敏感路径检查无命中。这是指定模式检查，不是完整安全认证。未连接 GitHub。原始本地 evidence/review 材料保留并忽略。

payload 白名单不含运行数据库、ecoinvent 商业向量或认证商业映射包；certifi 的 PEM 为公共 CA 证书。LCA 后端1407个文件与既有 e3385d3 封装逐项一致，本轮未改引擎。公开时仅选择安装包、说明和校验和；不得把 verification 数据库、用户数据或整个构建目录上传。

数据来源说明以 `docs/DATA_PROVENANCE.md` 和 `docs/RETAINED_SOURCE_DECLARATIONS.md` 为准：已追溯的条目不再误写成未知，但仍有3个单位组缺单条XML来源链，明确保留该披露。第三方声明中 number-precision 和 size-sensor 保留包元数据及 README 的许可证声明，未伪造独立许可证正文。最终公开审核应包含这些来源声明。

真实钢铁的非电供应商数据、CBAM适用电力因子及设施证据仍有缺项；非零 Scope3 的验收夹具是明确标识的机制数据，未装入官方种子。自定义规则等价与数值变化已验，不等于法规合规认证，也不代表任意公式编辑器或所有专用计算均已改为声明式核。

本轮验证运行的是安装包生成的实际资源和冻结后端，不替代干净Windows机器上的安装向导、SmartScreen和最终人工体验审核。安装包未签名，服务定位为本机使用，不作为带鉴权的公网服务器。此前MFA退出/CBAM稳定性7项属于上一候选包记录，本轮没有将其重标为新包实测。
