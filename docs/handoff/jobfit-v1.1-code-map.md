# JobFit Agent v1.1 代码地图

## 1. 阅读顺序

建议新代码编写者按以下顺序阅读：

1. `src/jobfit/workflow/orchestrator.py`
2. `src/jobfit/workflow/factory.py`
3. `src/jobfit/models/`
4. `src/jobfit/knowledge/`
5. `src/jobfit/matching/` 与 `src/jobfit/scoring/`
6. `src/jobfit/generators/` 与 `src/jobfit/validators/`
7. `src/jobfit/reporting/`
8. `app.py`
9. 对应测试

本文只记录职责、接口和边界，不粘贴完整源代码。

## 2. 目录结构与职责

| 路径 | 职责 |
| --- | --- |
| `app.py` | Streamlit 组合层、session state、输入过期判断、结果标签与下载；UI 只读取 `AnalysisReport` |
| `src/jobfit/models/` | Pydantic 领域模型：文档、简历、JD、匹配、评分、建议、知识、报告 |
| `src/jobfit/parsers/` | TXT/DOCX/PDF 解析、标准化、Segment 和 Evidence 字符索引 |
| `src/jobfit/extractors/` | 调用 LLM 提取 `ResumeProfile` 和 `JobProfile`，再由本地代码分配稳定 ID |
| `src/jobfit/knowledge/` | 知识 Schema、SQLite、Seed、版本、搜索、Repository、Retriever 与路径解析 |
| `src/jobfit/workflow/` | 依赖组装、状态机、缓存、指纹和端到端编排 |
| `src/jobfit/generators/` | Advice Bundle、改写、面试题和受限知识参考区块 |
| `src/jobfit/validators/` | Resume Evidence、改写、Citation、Report 和知识报告验证 |
| `src/jobfit/matching/` | LLM 语义判断与本地证据约束；不计算最终分数 |
| `src/jobfit/scoring/` | 确定性权重、分数、封顶和推荐等级 |
| `src/jobfit/reporting/` | 验证后报告映射、Markdown 和 JSON 导出 |
| `src/jobfit/llm/` | Provider 协议、Mock/OpenAI 适配、结构化运行、重试、Prompt Registry |
| `tests/unit/` | 纯模型、函数、验证器、工作流单元测试 |
| `tests/knowledge/` | SQLite、Seed、搜索、Repository、Retriever 和正式 Seed 合同测试 |
| `tests/integration/` | Mock 全链路、知识 Advice、Report、Streamlit 和失败路径 |
| `tests/fixtures/` | 匿名测试输入和专用夹具 |
| `data/knowledge/` | 受版本控制 JSON Seed；运行时 SQLite 不在此目录提交 |
| `docs/knowledge/` | 来源、编制、审核和人工决策文档 |

## 3. 当前核心执行链路

```text
Parse resume / Parse JD
→ Extract ResumeProfile
→ Extract JobProfile
→ Retrieve KnowledgeContext
→ EvidenceMatcher
→ EvidenceValidator
→ ScoringEngine
→ AdviceBundleGenerator
→ KnowledgeCitationValidator
→ build_analysis_report / build_report_knowledge_section
→ KnowledgeReportValidator
→ Markdown / JSON / Streamlit
```

知识检索发生在 `JobProfile` 提取后、EvidenceMatcher 前。知识 Advice 失败时回退基础 Advice；知识关闭、不可用、无匹配或歧义不会阻断基础分析。

## 4. 核心类与函数

### 4.1 Workflow

#### `src/jobfit/workflow/orchestrator.py` — `WorkflowOrchestrator`

- 构造：全部依赖关键字注入，包括 parser、extractor、matcher、validator、scoring、generator、knowledge retriever、renderer 和 cache。
- 入口：`run(request: AnalysisRequest, *, selected_source: str, progress: ProgressSink | None = None) -> WorkflowResult`。
- 输出：成功时包含 `AnalysisReport`、Markdown、JSON、事件与 fingerprint；失败时包含安全错误。
- 不变量：Retriever 每次实际分析调用一次；Matcher 和 Scoring 参数不含知识；只捕获允许恢复的知识数据库错误；未知异常 Fail Closed。
- 主要调用方：`app.py`、Mock demo 和集成测试。
- 修改风险：阶段顺序、缓存 begin/finish、知识回退或报告组装变化会影响大量回归测试。

#### `src/jobfit/workflow/state.py` — `WorkflowState`

- 类型：session-only dataclass。
- 保存：文档、ResumeProfile、JobProfile、KnowledgeContext、KnowledgeAdviceTrace、matches、score、advice、report 和导出文本。
- 状态顺序：`VALIDATING_INPUT` 到 `COMPLETED`，包含 `RETRIEVING_KNOWLEDGE`。
- 不变量：只能按 `_STAGE_SEQUENCE` 前进；终态后不能继续迁移；UI 进度回调失败不改变业务流程。
- 风险：改变字段或状态顺序会破坏缓存、UI 进度和阶段测试。

#### `src/jobfit/workflow/factory.py`

- `build_workflow_orchestrator(settings, *, client=None, cache=None, prompt_root=None, knowledge_retriever=None) -> WorkflowOrchestrator`：应用组合根。
- `build_knowledge_retriever(settings) -> KnowledgeRetriever`：关闭时返回 NoOp；文件缺失、Schema 不兼容或 published 版本缺失时返回 unavailable；不自动建库或导入 Seed。
- `build_knowledge_runtime_identity(settings) -> str`：生成 UI 过期检测身份，不包含 API key、知识正文或用户输入。
- 风险：不要把 SQLite 初始化、Seed 发布或用户输入处理放进 factory。

### 4.2 Knowledge Repository 与数据库

#### `src/jobfit/knowledge/protocol.py` — `KnowledgeRepository`

- 同步 Protocol；输入为 `RoleProfileQuery`、`KnowledgeSearchQuery`、ID、版本和 limit。
- 返回纯领域模型或空列表/`None`。
- 主要方法：`get_version`、`get_published_version`、`get_search_capabilities`、`search_role_profiles`、`get_role_profile`、`search_requirements`、`search_evidence_patterns`、`search_interview_questions`、`get_sources`、`get_citations`、`citation_exists`。
- 不变量：不暴露 SQLAlchemy Session、Engine、Row 或 ORM。

#### `src/jobfit/knowledge/repository.py` — `SqliteKnowledgeRepository`

- 构造：`SqliteKnowledgeRepository(database, *, search_mode=auto, search_index=None, search_enabled=True)`。
- 职责：对 published/approved/active 知识执行结构化过滤、FTS/关键词召回、确定性排序、limit 和领域映射。
- 无结果：返回 `None` 或空列表，不当作异常。
- 错误：转换为不泄露 SQL、正文和路径的 `KnowledgeDatabaseError`。
- 风险：任何过滤条件放宽都可能让 draft、retired 或跨版本内容进入分析。

#### `src/jobfit/knowledge/db.py` — `KnowledgeDatabase`

- 构造：`KnowledgeDatabase(path, *, busy_timeout_ms=5000)`；同步 SQLAlchemy Engine 和短 Session。
- 接口：`ensure_compatible_schema()`、`schema_version()`、`dispose()`；内部 `_session_scope()` 负责 commit/rollback/close。
- 初始化：`initialize_knowledge_schema(database) -> None`；只显式创建空库，设置 `PRAGMA user_version=1`。
- PRAGMA：`foreign_keys=ON`、`busy_timeout`。
- 风险：构造 Engine 不等于允许建库；应用 factory 必须继续先检查文件存在。

### 4.3 Seed 与版本

#### `src/jobfit/knowledge/importer.py` — `KnowledgeSeedImporter`

- 入口：`import_seed(bundle: KnowledgeSeedBundle, *, mode: SeedImportMode = CREATE) -> SeedImportResult`。
- 职责：验证 bundle、计算 canonical hash、单事务写入 draft；同内容幂等；只允许明确的 draft 替换模式。
- 不变量：不能覆盖 published 内容；ORM 写入仍需保持所有引用和审核状态。
- 风险：任何“方便导入”的宽松转换都会削弱 Seed 合同和发布门禁。

#### `src/jobfit/knowledge/versioning.py` — `KnowledgeVersionPublisher`

- `publish(version_id, *, published_at=None) -> SeedPublishResult`：检查全部实体 approved、hash 和引用后显式发布。
- `retire(version_id) -> SeedRetireResult`：显式退役已发布版本。
- 不变量：published 内容不可通过公共接口原地覆盖；未审核实体必须阻断发布。

### 4.4 搜索与 Retriever

#### `src/jobfit/knowledge/fts.py` — `KnowledgeSearchIndex`

- `detect()`：探测 FTS5。
- `capabilities(mode, *, enabled=True)`：决定 FTS5、关键词回退或 disabled。
- 负责派生索引的创建、重建、完整性检查和候选查询；派生索引不是知识事实源。
- 风险：不能让索引损坏影响核心表或静默混用版本。

#### `src/jobfit/knowledge/ranking.py`

- 当前没有名为 `DeterministicKnowledgeRanker` 的类。
- 对应实现是纯函数：`score_role_candidate`、`score_requirement_candidate`、`score_text_candidate`、`rank_knowledge_candidates`。
- 使用 `Decimal`、固定公式、固定量化和稳定 ID tie-break；相关度不是候选人匹配分。
- 风险：修改公式或阈值会改变岗位画像解析、缓存身份和污染防护，需要专项回归。

#### `src/jobfit/knowledge/retriever.py`

- `build_role_resolution_query(job_profile: JobProfile) -> RoleProfileQuery`：从结构化 JobProfile 构造去重、受限、稳定查询；不重新解析文件。
- `build_knowledge_cache_identity(context, *, requirement_limit, prompt_char_limit) -> str`：只使用状态、版本、hash、模式、策略、画像和预算，不使用路径或正文。
- `NoOpKnowledgeRetriever.retrieve_for_job(...) -> KnowledgeContext`：返回合法 disabled Context，不访问 Repository。
- `DefaultKnowledgeRetriever(repository, *, enabled=True, requested_version=None, search_mode=auto, requirement_limit=12, prompt_char_limit=8000, retrieval_strategy_version="1.0")`。
- `retrieve_for_job(job_profile, *, limit=12) -> KnowledgeContext`：识别画像、处理 ambiguous/no-match、检索当前画像专属要求/模式/问题、验证 Citation、应用数量与字符预算。
- 不变量：ambiguous/no-match 不返回画像专属详情；只使用单一 published 版本；所有 Citation 必须可回查。

### 4.5 Generator 与 Citation

#### `src/jobfit/generators/knowledge_reference.py` — `build_knowledge_reference_block`

- 签名：`build_knowledge_reference_block(context: KnowledgeContext, *, max_characters: int) -> KnowledgeReferenceBlock | None`。
- 只对 available、单一画像、已验证且受预算约束的 Context 生成 `REFERENCE_KNOWLEDGE`。
- 明确告诉模型：知识不是候选人事实、不是 Resume Evidence、不能新增 JD 要求或改变评分。
- 风险：不得移除边界提示、允许半条目截断或透传不可信指令。

#### `src/jobfit/generators/advice_bundle.py` — `AdviceBundleGenerator`

- `generate(resume, job, matches, score, registry, *, request_id) -> GeneratedAdvice`：原基础路径。
- `generate_with_knowledge(..., knowledge_context, request_id) -> KnowledgeGenerationResult`：使用受限知识区块并返回 Advice 与未信任 Citation sidecar。
- 不变量：Advice 仍需本地 finalize；知识不改变 matches 或 score；正常 Mock 基础路径保持四次模型调用。

#### `src/jobfit/validators/knowledge.py` — `KnowledgeCitationValidator`

- `validate_or_raise(*, context, citation_uses, provided_citation_ids, advice) -> tuple[KnowledgeCitationUse, ...]`。
- 验证 Citation 来自实际提供集合、当前 Context/版本/画像，并且 `used_by` 指向真实 Advice 项。
- 无效引用 Fail Closed 到安全回退，不输出模型原始 sidecar。

### 4.6 Report 与导出

#### `src/jobfit/reporting/knowledge.py` — `build_report_knowledge_section`

- 签名：`build_report_knowledge_section(context, trace, advice) -> ReportKnowledgeSection`。
- 纯函数；不访问数据库、不重新检索、不调用模型。
- available 输出受限岗位参考和已验证引用；disabled/unavailable/no-match/ambiguous 使用安全空状态。

#### `src/jobfit/validators/report.py`

- `build_analysis_report(*, document, resume, job, matches, score, advice, registry, ..., knowledge_context=None, knowledge_advice_trace=None) -> AnalysisReport`。
- 先复算 Evidence 和 Scoring 不变量，再映射知识部分，生成 frozen Report 1.1。
- `ReportValidator` 复算 score、推荐、改写和面试题规则，不能信任调用方传入的派生结果。

#### `src/jobfit/validators/report_knowledge.py` — `KnowledgeReportValidator`

- `validate(report: AnalysisReport) -> list[ValidationIssue]`。
- 验证 1.0/1.1 合同、状态载荷、版本/画像/Citation/used_by、路径/SQL/Prompt 安全和评分隔离。

#### `src/jobfit/models/report.py` — `AnalysisReport`

- `schema_version` 支持 `1.0` 和 `1.1`，新报告默认 `1.1`。
- 1.0 不允许 knowledge 字段；1.1 必须有 `ReportKnowledgeSection`。
- 非知识字段语义保持 v1.0：匹配、分数、推荐、改写、恰好五道面试题和 ValidationResult。

#### 导出入口

- Markdown：`src/jobfit/reporting/markdown.py::render_markdown(report) -> str`。
- JSON：`src/jobfit/reporting/json_export.py::render_json(report) -> str`。
- 两者都先执行 `ensure_exportable`，只从同一个已验证 AnalysisReport 生成，不重新计算业务结果。

## 5. 核心数据模型

| 模型 | 位置 | 核心含义与边界 |
| --- | --- | --- |
| `JobProfile` | `models/job.py` | 包含 `jd_text`、摘要、keywords 和确定性规范化的 `JobRequirementCollection`；知识要求不能写入此集合 |
| `ResumeProfile` | `models/resume.py` | 结构化简历事实及 Evidence IDs；默认只在内存和报告对象中存在，不写知识库 |
| `RequirementMatch` | `models/matching.py` | 每个 JD requirement 的状态、Resume Evidence、理由和程序映射分；matched 必须有 direct evidence |
| `AnalysisReport` | `models/report.py` | frozen 最终聚合；1.0 无知识字段，1.1 必须有紧凑知识部分 |
| `KnowledgeContext` | `models/knowledge.py` | Retriever 的有界、只读领域输出；包含版本、画像、参考要求、模式、问题、Citation 和 warning |
| `KnowledgeCitation` | `models/knowledge.py` | 岗位知识来源引用，绝不是 Resume Evidence；URL 仅 HTTP(S) |
| `RetrievedRoleProfile` | `models/knowledge.py` | 画像及确定性相关度、命中项和 Citation IDs；相关度不是匹配分 |
| `RetrievedRequirement` | `models/knowledge.py` | 岗位参考要求；`is_common_hard_blocker` 不触发评分封顶 |
| `KnowledgeAdviceTrace` | `models/knowledge_advice.py` | session-only 已验证 Citation 使用 sidecar；报告只映射必要摘要 |
| `ReportKnowledgeSection` | `models/report_knowledge.py` | 报告用户视图；状态不变量阻止 ambiguous/no-match 暴露专属内容 |

## 6. 不可破坏边界

1. Knowledge Citation 和 Evidence Pattern 不能成为 Resume Evidence。
2. KnowledgeContext 不能作为 `EvidenceMatcher.match` 参数，也不能进入 EvidenceRegistry。
3. `ScoringEngine.score(requirements, matches)` 签名和确定性规则不能由知识改变。
4. 知识要求不能加入 `JobProfile.requirements` 或评分分母。
5. `is_common_hard_blocker` 不能触发 49/69 分封顶；只有当前 JD 的已确认 hard condition 可影响封顶。
6. ambiguous 和 no-match 不得注入单一岗位画像 requirements、patterns 或 questions。
7. Citation 必须来自本次受限 KnowledgeContext、当前 published 版本和当前画像。
8. 用户简历、JD、报告和模型输出默认不持久化到公共知识表。
9. JSON Seed 是知识事实源；SQLite 和 FTS 是可重建运行时副本。
10. published 知识不可通过公共 Importer 覆盖或静默降级。
11. 默认 Mock 不依赖数据库、API Key 或网络。
12. unknown 表示 Resume Evidence 不足，不等于候选人不会。

## 7. 配置契约

不要读取或记录本机 `.env`。下表只记录代码默认值。

| 环境变量 | 默认值 | 用途 | 影响缓存/过期身份 | 创建文件 | 敏感性 |
| --- | --- | --- | --- | --- | --- |
| `JOBFIT_APP_ENV` | `development` | 环境标签 | 否 | 否 | 否 |
| `JOBFIT_LLM_PROVIDER` | `openai` | LLM Provider | 是，进入基础 fingerprint | 否 | 否 |
| `JOBFIT_LLM_MODEL` | 空 | Provider 模型 | 是，进入基础 fingerprint | 否 | 否 |
| `JOBFIT_LLM_API_KEY` | 空 | 真实 Provider 凭据 | 否，明确不进入缓存 | 否 | **是** |
| `JOBFIT_LLM_BASE_URL` | 空/`None` | OpenAI 兼容服务地址 | 当前不直接进入 fingerprint | 否 | 可能包含内部基础设施信息 |
| `JOBFIT_LLM_TIMEOUT_SECONDS` | `60` | 单次请求超时 | 否 | 否 | 否 |
| `JOBFIT_LLM_MAX_RETRIES` | `2` | 最大重试，范围 0—2 | 否 | 否 | 否 |
| `JOBFIT_MAX_UPLOAD_MB` | `10` | 上传大小限制 | 否 | 否 | 否 |
| `JOBFIT_MAX_RESUME_CHARS` | `50000` | 简历解析/提取上限 | 否 | 否 | 否 |
| `JOBFIT_MAX_JD_CHARS` | `30000` | JD 提取上限 | 否 | 否 | 否 |
| `JOBFIT_LOG_LEVEL` | `INFO` | 日志级别 | 否 | 否 | 否 |
| `JOBFIT_DEMO_MODE` | `false` | 演示模式标记 | 通过请求运行模式间接区分 | 否 | 否 |
| `JOBFIT_KNOWLEDGE_ENABLED` | `true` | 是否启用知识增强 | 是 | 否 | 否 |
| `JOBFIT_KNOWLEDGE_VERSION` | `2026.07.1` | 请求的 published 知识版本 | 是 | 否 | 否 |
| `JOBFIT_KNOWLEDGE_DB_PATH` | 空/平台用户数据目录 | 运行时 SQLite 路径覆盖 | 路径本身不进入身份；版本/hash/状态进入 | Settings 与解析不创建；显式初始化才创建 | 路径属于本地信息，不得进入报告 |
| `JOBFIT_KNOWLEDGE_SEARCH_MODE` | `auto` | `auto`、`fts5` 或 `keyword` | 是 | 否 | 否 |
| `JOBFIT_KNOWLEDGE_REQUIREMENT_LIMIT` | `12` | Retriever 要求上限 | 是 | 否 | 否 |
| `JOBFIT_KNOWLEDGE_PROMPT_CHAR_LIMIT` | `8000` | Context/Prompt 字符预算 | 是 | 否 | 否 |
| `JOBFIT_KNOWLEDGE_RETRIEVAL_STRATEGY_VERSION` | `1.0` | 检索策略身份 | 是 | 否 | 否 |

Prompt 版本、Citation Validator 版本和 Advice 策略版本是代码常量，由 factory 加入知识缓存身份，不是环境变量。

## 8. UI 入口

- `app.py::_get_orchestrator()`：Mock 使用 session-local `DemoRuntime`；Provider 模式使用 Settings、知识 runtime identity 和 factory。
- `app.py::_render_results()`：六个标签，包括“岗位知识参考”。
- `app.py::_render_knowledge_reference()`：只读取 `AnalysisReport.knowledge`，不访问 SQLite、Retriever 或内部 sidecar。
- 下载按钮直接使用 WorkflowResult 中同一报告生成的 Markdown/JSON。
- 输入和知识 runtime identity 变化会设置 `analysis_stale`；旧报告不能继续下载为当前结果。

## 9. 修改前检查清单

- 明确目标 HEAD 和允许修改的文件。
- 确认补丁没有更改 Scoring、Matcher、EvidenceRegistry 或 Prompt 边界，除非用户明确授权。
- 新代码先写或更新针对性测试；本交接后的 Codex 不自行设计修复。
- 知识内容变更必须保持 Seed Schema、review status、来源、canonical hash 和发布门禁。
- 任何运行时数据库都只能位于临时目录或用户数据目录，不能提交 Git。
- 运行用户指定测试并按 runbook 返回原始失败摘要；未经授权不得自动修复。
