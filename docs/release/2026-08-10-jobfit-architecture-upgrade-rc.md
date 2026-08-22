# JobFit架构升级Release Candidate

- 日期：2026-08-10
- 软件版本：1.1.0
- 架构标签：B7-B9 GitHub Source Upload RC
- Global Rules：1.0.0
- Prompt Pack：1.0.0（candidate）
- Scoring Rules：1.0.0
- Analysis Engine：1.0.0
- Knowledge：2026.08.1
- Knowledge Canonical Hash：`346542eb0c405643a08ebc4bffdab9b5bce22a1b7227f5ad2b27f12e3d1ef7f4`

## 候选内容

本候选新增与当前生产页面并行的`app_v2.py`，把B1-B6冻结契约组装成七阶段Streamlit体验：新分析、简历输入、岗位描述输入、确认与澄清、正在分析、分析报告、更新与重新分析。

报告以推荐结论优先，独立展示Hard资格边界与候选人Evidence，并将Rewrite、Recover、Build明确分区。Build永远表示未来行动，最多3项；重新分析生成新的不可变Analysis Run，不覆盖本次会话中的历史结果。

## 自动化验收范围

- 42个业务案例，H02/H03按B6局部恢复语义执行，不再延期；
- 8个Range Golden、2个Guard Golden、2个Relational Golden；
- 6个Pair测试；
- 三个岗位族各自覆盖高、中、低匹配的P01-P08完整链路；
- Hard与Critical召回、Recommendation Accuracy、Core Requirement Recall；
- Knowledge OFF/ON核心结果不变、Prompt Injection、Recover、Seniority、F0-F3和增量重算；
- 当前`app.py`与v2 `app_v2.py`的AppTest和HTTP健康；
- Python 3.12 Fresh Clone安装、知识重建、完整测试、branch coverage、Ruff、pip check与Git门禁。

精确分子、分母、失败Case ID及命令结果保存在仓库外的`JobFit-GitHub-RC-Evidence.json`，避免用概括性“PASS”替代证据。

## 不变量

1. B2评分、Hard、Critical、Confidence与Recommendation规则未重开。
2. P01-P08、B4澄清与B6历史/增量重算职责未改变。
3. 知识不能成为候选人Evidence，也不能改变`AnalysisCore`。
4. `app.py`保持现有生产入口；v2是并行候选入口。
5. 用户材料与Analysis历史不默认持久化。
6. 没有新增Runtime依赖、真实LLM调用或外部服务依赖。

## 已知限制与人工门禁

- v2历史仅保存在当前Streamlit会话内存中；
- 真实模型质量、成本和供应商数据处理仍由部署方配置并负责；
- Action Quality人工评分为`PENDING_HUMAN`；
- 耐久持久化决策为`DEFERRED_BY_AUTHORITY`；
- GitHub源码上传候选通过不等于生产切换批准；
- 在人工体验签字和持久化决策完成前，`PRODUCTION_CUTOVER_READY=NO`。

## 发布操作边界

本候选只允许生成本地提交、`git archive`源码包和仓库外验收证据。不执行push、PR、merge、tag、GitHub Release，也不修改`v1.0.0`标签或远程配置。
