# JobFit Agent v1.1 当前开发状态

## 1. 文档定位

本文是 JobFit Agent v1.1 开发职责冻结时的交接记录。本文不批准知识内容、不授权发布，也不代替 Git、测试输出或外部交接包 manifest。

由于 Git commit 不能在自身内容中可靠记录自身哈希，本文记录的是交接文档提交前的代码与知识基线；包含本文的最终归档 HEAD 由仓库外 manifest 记录。

## 2. 项目状态

| 项目 | 状态 |
| --- | --- |
| 开发分支 | `feature/knowledge-base-v1.1` |
| 交接前完整 HEAD | `e206a3a195dc92b30950f86c91e79feff9db1e92` |
| 交接前短 HEAD | `e206a3a` |
| 稳定 `main` HEAD | `55dc7d4f4c135c4153c8fecaee698c9f90653953` |
| `v1.0.0` | 本地 annotated tag，指向稳定 `main` HEAD；v1.0 已公开发布并完成独立验收 |
| 交接开始工作区 | 干净 |
| 功能分支远程状态 | 没有远程跟踪分支，当前 v1.1 提交未 push |
| 当前测试基线 | 730 passed；本交接提交后必须重新完整验证 |
| 生产默认知识版本 | `2026.07.1` |
| 正式 Seed 版本 | `2026.08.1` |
| 正式 Seed 状态 | `draft`；AI 应用知识及来源均为 `pending` |
| 默认运行数据库 | 未导入正式 Seed，未发布正式知识 |

## 3. 已完成阶段

### Phase 11.0：岗位知识库架构设计与实施计划

- 核心成果：确定 SQLite + SQLAlchemy、JSON Seed、FTS5/关键词回退、知识与候选人证据隔离、版本与来源审核机制。
- 主要提交：`a064db0 docs: design job knowledge base architecture`
- 主要文件：`docs/superpowers/specs/2026-07-25-jobfit-knowledge-base-design.md`、`docs/superpowers/plans/2026-07-25-jobfit-knowledge-base-implementation.md`。
- 测试结果：文档阶段未增加运行代码；沿用 v1.0 的 363 项稳定基线。
- 未完成边界：没有领域 Schema、数据库、Seed 或工作流实现。

### Phase 11.1：知识领域 Schema、配置与 Protocol

- 核心成果：建立纯 Pydantic 知识模型、查询模型、Repository/Retriever Protocol、warning/error code 和配置契约。
- 主要提交：`e35bd49 feat: add knowledge domain schemas and protocols`
- 主要文件：`src/jobfit/models/knowledge.py`、`src/jobfit/knowledge/protocol.py`、`src/jobfit/knowledge/query.py`、`src/jobfit/config.py`。
- 测试结果：阶段完成时累计 411 项通过。
- 未完成边界：没有 SQLite、ORM 或具体 Repository。

### Phase 11.2：SQLite 持久层与 Repository

- 核心成果：隔离本地 dotenv 对测试的影响；加入 SQLAlchemy 2.x；完成 10 张表、显式 Schema 初始化、Mapper 和只读 Repository。
- 主要提交：`e3c3b45 test: isolate settings tests from local dotenv`、`4bee904 feat: add sqlite knowledge repository`
- 主要文件：`src/jobfit/knowledge/db.py`、`orm.py`、`mappers.py`、`paths.py`、`repository.py`、`schema.py`。
- 测试结果：阶段专项、完整回归、Ruff、pip check 和隔离环境验证通过；当前 730 项继续覆盖这些能力。
- 未完成边界：没有 Seed 导入、发布状态机或 FTS。

### Phase 11.3：版本化 Seed 导入与发布机制

- 核心成果：严格 JSON Seed、重复 key 拒绝、引用校验、canonical hash、幂等 draft 导入、显式发布与退役门禁。
- 主要提交：`c2fe61c feat: add versioned knowledge seed imports`
- 主要文件：`src/jobfit/knowledge/seed_models.py`、`seed_loader.py`、`importer.py`、`versioning.py`。
- 测试结果：Seed 模型、Loader、Importer、版本转换和生命周期集成测试通过。
- 未完成边界：没有正式知识内容和搜索索引。

### Phase 11.4：确定性知识搜索

- 核心成果：FTS5 能力探测、派生索引、关键词回退、确定性归一化与排序；查询只返回 published/approved/active 内容。
- 主要提交：`21f4510 feat: add deterministic knowledge search`
- 主要文件：`src/jobfit/knowledge/fts.py`、`normalization.py`、`ranking.py`、`repository.py`。
- 测试结果：阶段完成时累计 615 项通过。
- 未完成边界：没有岗位画像最终识别或工作流接入。

### Phase 11.5：KnowledgeRetriever 与污染防护

- 核心成果：实现 `DefaultKnowledgeRetriever`、岗位画像识别、歧义/no-match/unavailable/disabled 状态、跨画像隔离、预算与缓存身份。
- 主要提交：`4e2f553 feat: add job knowledge retriever`
- 主要文件：`src/jobfit/knowledge/retriever.py`、`protocol.py`、`repository.py`、`src/jobfit/models/knowledge.py`。
- 测试结果：阶段完成时累计 635 项通过。
- 未完成边界：没有工作流、Prompt、Report 或 UI 接入。

### Phase 11.6：Workflow 与缓存指纹

- 核心成果：在 JobProfile 后、EvidenceMatcher 前注入可选知识检索；增加 `RETRIEVING_KNOWLEDGE`；知识身份进入最终报告缓存键。
- 主要提交：`cde3406 feat: integrate optional knowledge retrieval workflow`
- 主要文件：`src/jobfit/workflow/orchestrator.py`、`state.py`、`factory.py`。
- 测试结果：专项和完整回归通过；Matcher、Scoring 和默认 Mock 行为保持兼容。
- 未完成边界：知识尚未进入 Advice Prompt 或报告。

### Phase 11.7：Advice 知识引用与 Citation 验证

- 核心成果：生成受限 `REFERENCE_KNOWLEDGE` 区块；校验模型提出的 Citation；非法引用回退到无知识 Advice；保留内部 `KnowledgeAdviceTrace`。
- 主要提交：`87b957b feat: add grounded knowledge advice citations`
- 主要文件：`src/jobfit/generators/knowledge_reference.py`、`advice_bundle.py`、`src/jobfit/validators/knowledge.py`、`src/jobfit/models/knowledge_advice.py`。
- 测试结果：阶段完成时累计 688 项通过。
- 未完成边界：引用仍未进入报告和导出。

### Phase 11.8A：AnalysisReport 1.1 与导出

- 核心成果：AnalysisReport 1.1、1.0 读取兼容、知识报告模型、报告映射与 Validator、Markdown/JSON 知识导出。
- 主要提交：`f4c98d8 feat: add knowledge references to reports and exports`
- 主要文件：`src/jobfit/models/report.py`、`report_knowledge.py`、`src/jobfit/reporting/knowledge.py`、`markdown.py`、`src/jobfit/validators/report_knowledge.py`。
- 测试结果：阶段完成时累计 707 项通过。
- 未完成边界：没有 Streamlit 知识展示或生产 Retriever 组装。

### Phase 11.8B：Streamlit 展示与应用组装

- 核心成果：新增“岗位知识参考”标签；UI 只读取验证后的报告；生产模式安全组装 Retriever；合成 Seed 端到端验证五种状态、下载和过期机制。
- 主要提交：`01bb582 feat: add knowledge references to streamlit`
- 主要文件：`app.py`、`src/jobfit/workflow/factory.py`、知识应用与 Streamlit 集成测试。
- 测试结果：阶段完成时累计 725 项通过，并完成 headless Streamlit 健康检查。
- 未完成边界：没有正式岗位知识和默认运行数据库。

### Phase 11.9A：正式知识编制政策

- 核心成果：确定三岗位边界、来源准入和版权政策、编制规范、审核清单及正式 Seed 目录说明。
- 主要提交：`676f55f docs: define official knowledge authoring process`
- 主要文件：`docs/knowledge/*.md`、`data/knowledge/README.md`。
- 测试结果：文档阶段未修改代码，基线保持 725 项。
- 未完成边界：没有正式 Seed。

### Phase 11.9B1：AI 应用实习生 draft Seed

- 核心成果：建立 `2026.08.1` 完整 Seed 包，含 1 个岗位画像、11 个维度、15 条要求、17 个证据模式、10 道问题和 7 个来源；全部为 draft/pending。
- 主要提交：`242d74a data: add draft ai application knowledge seed`
- 主要文件：`data/knowledge/versions/2026.08.1/*.json`、`docs/knowledge/reviews/2026.08.1-ai-application-review.md`、正式 Seed 合同测试。
- 测试结果：Loader、canonical hash、临时 SQLite 幂等导入和发布拒绝门禁通过；累计 730 项通过。
- 未完成边界：用户未批准，未进入默认数据库，未发布。

### Phase 11.9B1-R：AI 应用知识人工审核建议

- 核心成果：逐条审阅岗位画像、Requirements、Patterns、Questions 和来源；形成 10 项用户决策，不修改 Seed。
- 主要提交：`e206a3a docs: review ai application knowledge seed`
- 主要文件：`docs/knowledge/reviews/2026.08.1-ai-application-user-decision.md`。
- 测试结果：仅文档变更，执行 diff/range 检查；测试基线仍为 730 项。
- 未完成边界：全部用户选择仍为 `pending_user_decision`。

## 4. 当前正式知识状态

- 正式知识版本：`2026.08.1`。
- 版本状态：`draft`。
- AI 应用实习生知识：全部 `pending`，用户尚未批准。
- 数据分析实习生：尚未编制。
- 技术战略实习生：尚未编制。
- 生产默认 `JOBFIT_KNOWLEDGE_VERSION`：仍为 `2026.07.1`。
- 默认运行数据库：未导入 `2026.08.1`，仓库不提交运行时 SQLite。
- Published 正式知识：不存在。
- 发布门禁：用户决策 → B1-F 执行批准修改并复核 → 三岗位编制与统一审核 → 全部实体 approved → 临时 draft 导入、hash 与检索验收 → 明确 Publisher 授权 → 更新生产版本并发布。

## 5. 未完成事项与推荐顺序

1. 执行 AI 应用岗位用户审核决定。
2. 在 Phase 11.9B1-F 锁定 AI 应用正式知识。
3. 编制并审核数据分析岗位知识。
4. 编制并审核技术战略岗位知识。
5. 完成三岗位术语、维度、来源和污染边界统一审核。
6. 在临时数据库完成 draft 导入与发布门禁；获得明确授权后再导入运行数据库并发布。
7. 执行 v1.1 完整回归、干净环境、独立克隆和 Mock/知识双路径验收。
8. 更新版本、README 和发布清单，准备 v1.1 发布。

## 6. 主要风险

- 生产默认知识版本仍是 `2026.07.1`，与 draft Seed `2026.08.1` 不一致；在正式发布阶段必须统一变更。
- 当前没有 published 知识或默认运行数据库；启用知识但数据库不可用时只会安全回退，不能展示正式增强结果。
- AI 应用知识仍有 Requirement 类型、importance、来源日期和维度复用决策未锁定。
- 数据分析与技术战略知识缺失，因此 `2026.08.1` 还不是完整三岗位版本。
- `pyproject.toml` 项目版本仍为 `0.1.0`；v1.1 发布准备阶段必须明确软件版本更新策略。
- 功能分支尚未 push；外部交接包是快照，不替代 Git 远程备份。

## 7. 后续角色冻结

从本交接提交开始，Codex 不再主动设计功能、编写业务代码、重构、修复 Bug、修改知识内容、决定 Requirement 类型、决定审核状态、批准或发布知识，或修改生产配置。

后续 Codex 只执行：

1. 接收明确的补丁或完整文件；
2. 检查目标 HEAD；
3. 按原样转存；
4. 应用补丁；
5. 运行用户指定测试；
6. 按运行结果反馈；
7. 仅在明确授权时提交；
8. 不 push。
