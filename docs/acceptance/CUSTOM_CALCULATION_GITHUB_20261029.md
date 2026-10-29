# 自定义方法实算及 GitHub 同步

2026-10-29。用户授权：使用新版自定义功能新建方法并核对计算，无问题后推送 GitHub。全程由主代理独立完成，无子代理。

测试加载 `20261029-0.1.1-inline-categories/win-unpacked/resources/app.asar` 中的运行时及包内后端，隔离数据在 `.local-evidence/custom-final-20261029/data`。模板浏览器脚本从可见界面新建结果分类方法、定义和分配分类、保存检查、保存模板、创建项目、修改生产输入，并验证规则继承；后续 `scripts/ui_custom_calculation_acceptance.mjs` 从可见界面再次检查继承方法，进入项目点击“核算→开始计算”，实际求解并进入结果页。

需求为1000 kg产品，分类包含烧结过程两条独立CO₂交换：焦粉燃烧193.4592 kg、碳酸盐分解74.448 kg，真实引擎CF均为1 kg CO₂-eq/kg。两项之和267.9072 kg CO₂-eq，与页面及保存的分类结果逐项一致；未分类流仍留在默认物理计算中。已分类无数值缺项为0；完整默认结果的覆盖边界仍以页面披露为准。

证据：`.local-evidence/custom-final-20261029/template/summary.json`（10项通过）与 `calculation-final/summary.json`、`custom-calculated.png`。首轮取证脚本使用不存在的单快照GET路径返回404，已改为读取正式列表中的冻结快照，产品计算本身成功；修正后完整复跑通过。

同步目标为 `git@github.com:wilsherelu/nebula-one.git` 的 `main`，核查时远端为 `7e22ac0adc7a7452879136e540e669f4a9a19549`。既有交接要求不公开原开发main历史；因此使用当前已提交树的公开源码审计结果，以该远端提交为父追加一个源码同步提交，不重写本地开发历史、不force push、不发布Release或部署。具体上传身份及结果记录在本地交付目录的同步回执中。
