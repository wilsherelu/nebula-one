# 主线与暂存材料

2026-10-12 起，Nebula One 的开发、测试和打包目录统一为 `D:/VibeCoding/project/nebula-one`；建模和计算引擎目录统一为 `D:/VibeCoding/nebula-lca`。后续在两仓库的 `main` 上继续本地提交，正式授权发布前桌面版本保持 `0.1.1`。`release-candidates` 只代表历史候选状态，不再作为开发或构建入口。

One 保留公开仓库的提交历史，接入已验收的 `a81f345` 主线；旧实验仓库没有与该公开主线共有的提交历史，已保存在本地归档分支和 Git bundle 中，不并入将来要发布的 `main`。LCA 用正常合并提交 `e3385d3` 接入候选成果，保留原主线和已发布历史，合并后的产品文件与已验收候选树一致。

氢能、合成氨、炼厂及旧测试/实现文件保存在 `drafts/legacy-primary/`。其本地文件不在自动加载路径，不进入 Docker 上下文或桌面 payload，也不作为已验收方法注册。正式目录中的默认模板、种子和方法仍沿用已验收的公开钢铁配置。未提交文件、旧历史、候选证据和暂存材料的恢复副本位于 `D:/VibeCoding/archive/20261012-mainline-consolidation`，不上传公共仓库。

共享 Docker 项目继续使用 `nebula-one-public-current-20260929`，入口 `18938`、API `18931`、编辑器 `18932`，保留现有数据库及卷。配置保存在被忽略的 `deploy/local-test.env`，示例为 `deploy/local-test.env.example`。从 One 主目录执行：

```text
docker compose --env-file deploy/local-test.env -f deploy/compose.yml ps
docker compose --env-file deploy/local-test.env -f deploy/compose.yml build nebula-one nebula-lca-api
docker compose --env-file deploy/local-test.env -f deploy/compose.yml up -d --no-deps nebula-one nebula-lca-api
```

不要创建新的分支专用栈，也不要清库、删卷或全局 prune。桌面打包同样从主目录执行，LCA 参数使用主引擎目录；产物输出到仓库外：

```text
python desktop/build.py --lca-root D:/VibeCoding/nebula-lca --output D:/VibeCoding/releases/nebula-one/<日期>-0.1.1
```

现有 `20261012-0.1.1` 安装包保留原校验值和源码 pin，不因目录整理而改写。新构建应记录当次主线提交和 payload manifest。只推送经授权的 `main`，不推送旧实验归档分支、stash 或全部 refs。

## 2026-10-13 收口记录

旧 RC 与 Qoder 检出已移入 `D:/VibeCoding/archive/20261012-mainline-consolidation/checkouts/`，包括 `nebula-one-20261004`、`nebula-lca-20261004`、`nebula-lca-qoder-steel-c`、`nebula-one-qoder-b`、`nebula-one-rc-20260925` 和 `n1-ef31-baseline`。原 C 盘工作树保存在 `C:/Users/31534/.codex/worktrees-archive/20261012/`。移动保留了文件、未跟踪证据和本地缓存；空的 `release-candidates` 目录已移除。归档分支和 bundle 仅用于恢复，两个主目录的 `main` 是唯一继续维护的主线。

主目录验收：One 后端 757 项通过，前端 290 项通过，类型检查与生产构建通过；LCA 本轮相关测试 16 项通过。这不是 LCA 全量测试通过声明。One 产品目录与已验收 RC 一致，LCA 合并后的完整树与已验收 RC 一致。

共享栈已从主目录构建并更新，容器 Compose 来源为 `D:/VibeCoding/project/nebula-one/deploy/compose.yml`，One/API 健康接口均返回 200。项目、端口、数据库和持久卷保持原样，solver 未重建或重启。已有冻结快照 `b1b58c34-3c0e-411c-b12a-1fb2a4540b58` 经真实 HTTP 读回：总量 2035.472521 kg CO2-Eq，Scope 1 为 1940.739734、Scope 2 为 94.732787，贡献对账通过。Scope 3 无数据，未置零。

本轮只做本地主线整合与提交，未 push、发布或清理数据库。桌面版本继续为 `0.1.1`，既有安装包未改写。
