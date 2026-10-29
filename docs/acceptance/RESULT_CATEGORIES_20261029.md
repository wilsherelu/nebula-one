# 结果分类单机包复核

2026-10-29。接回 Qoder `83e32f8`，工作树干净。R5 的旧普通自定义方法只读/转换与无效分类显式修复两项已核实，独立定向 `test_result_category.py` 16 passed。

本轮另作两处收尾：转换失败复用已有错误适配器，重名时提示改名；历史归集的 GET、列表、JSON 导出和重复 POST 返回原冻结字段，不由当前 schema 补默认值污染旧摘要。后者增加旧记录 API 回归，两个受影响套件 29 passed。前端方法页 47 passed，typecheck/build 通过。

产品提交 `6f807ee`、`75c1018`。新包保持0.1.1，输出至 `D:/VibeCoding/releases/nebula-one/20261029-0.1.1-result-categories/`；此前安装文件保留。引擎仍为 `f255d3ecad9f79d6ef298fac642e62188bada099`。

Qoder 已报告全量前端378项、后端167项通过，相关命令与真实源码实例证据保留在主方案末尾。本轮未把这些数量算作独立重跑。`test_project_template_profiles` 的1.0.10/1.0.11断言失败在Qoder起始提交同样存在，本轮未修改或宣布通过。

验收边界：分类决定本口径是否归集，“无”不影响默认 LCA/PCF 完整计算；已分类但缺因子/背景数据仍显示缺项和已知小计。专用 CCER、碳市场、双控算法尚未接入；用户尚未最终确认界面体验。

最终包内验收通过：2576个载荷逐项摘要一致；从上一包的隔离数据启动新版保留原模板；MFA、PCF、CBAM、组织四任务通过。真实引擎分类小计267.9072/193.4592 kg CO2-Eq，交并集对账一致；模板浏览器10项、结果浏览器8项、完整后端重启读回通过，HTTP/控制台/浏览器异常为空。已查看最终包桌面截图，两个R5反例在包内真实API及浏览器再次通过。

安装文件 `Nebula-One-0.1.1-windows-x64.exe`，166890196字节，未签名；SHA-256 `8aa4195ab3a70736a2ca4fcd4c22ebb506b332bd06557cc661137cfbed0e6b31`。NSIS与内嵌7z解包通过，2650文件与受测win-unpacked逐项一致；解包后的真实Electron程序启动通过。未执行系统安装向导。

证据目录 `.local-evidence/result-categories-20261029/packaged/`，另有 `electron-smoke.json`；交付目录的 `verification/` 同步副本。当前源码文档补记不改变已冻结安装文件。
