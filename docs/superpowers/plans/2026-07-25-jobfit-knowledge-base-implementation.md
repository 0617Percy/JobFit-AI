# JobFit Agent v1.1.0 Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变候选人证据、确定性评分和推荐等级规则的前提下，为 JobFit Agent 增加可关闭、可降级、版本化且带来源引用的本地岗位知识增强层。

**Architecture:** 使用严格 Pydantic 领域 Schema 隔离业务与持久层，以 `KnowledgeRepository` Protocol 隔离 SQLAlchemy ORM，以 SQLite 保存从版本化 JSON seed 构建的 published 知识；结构化过滤和 FTS5/关键词召回后统一进行确定性重排。知识在 `JobProfile` 生成后检索，只增强解释、诊断和面试参考，不能成为 Resume Evidence、不能进入评分分母，也不能触发 hard blocker。知识不可用时回退 v1.0 流程；已经声明的知识引用不合法时 fail closed。

**Tech Stack:** Python 3.11/3.12、Pydantic v2、SQLAlchemy 2.x、SQLite、可选 FTS5、标准库 JSON/`hashlib`/`sqlite3`、Streamlit、pytest、pytest-cov、Ruff；v1.1.0 不使用 Alembic、向量数据库、embedding、PostgreSQL、网络抓取或真实模型测试。

## Global Constraints

- 最高优先级规格为 `docs/superpowers/specs/2026-07-25-jobfit-knowledge-base-design.md`。
- v1.0 证据、评分、封顶和推荐等级规则不可修改。
- `JobProfile.requirements` 继续只来自本次 JD；知识要求不得自动加入。
- `RequirementMatch` 的证据只能来自简历 `EvidenceRegistry`。
- `ScoringEngine.score(requirements, matches)` 的公开输入契约保持不变。
- 知识库不能保存简历、JD、报告、模型响应或用户 PII。
- 只有 published version 中 approved + active 的内容可以进入分析。
- 知识不可用应 warning + 基础流程继续；虚假 Citation 应 fail closed。
- 普通测试必须完全离线，不读取真实 API Key，不访问网络。
- 运行时 SQLite 不提交 Git；正式 seed 才进入版本控制。
- 每个阶段先写失败测试，再写最小实现，再跑专项测试和全量回归。
- 每个阶段形成一个独立、可回滚的本地 commit；不得把 11.1—11.10 压成单次提交。
- 实施过程中不自动 push、merge、tag 或 Release；每个远程动作另行授权。
- 不在代码、测试、文档、日志或错误消息中写入本机绝对路径。

---

## 1. 基线与依赖关系

### 1.1 开始前门禁

- [ ] 确认当前分支为 `feature/knowledge-base-v1.1`。
- [ ] 确认工作区干净，且 HEAD 是已审阅的设计文档提交。
- [ ] 确认 `main` 和 `v1.0.0` 未被修改。
- [ ] 运行基线：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

- [ ] 记录实际测试数，不在实现计划中预设新增后的测试总数。

### 1.2 开发依赖关系

```text
11.1 Knowledge Schemas + Config + Protocol
                     ↓
11.2 SQLAlchemy + SQLite Repository
                     ↓
11.3 JSON Seed + Version Publishing
                     ↓
11.4 FTS/Keyword Search + Deterministic Ranking
                     ↓
11.5 KnowledgeRetriever
                     ↓
11.6 Workflow Optional Integration
                     ↓
11.7 Generator + Citation Validators
                     ↓
11.8 Report + Export + UI
                     ↓
11.9 Reviewed Production Seeds
                     ↓
11.10 Full Regression + v1.1 Release Preparation
```

不允许出现以下反向依赖：

- `models` 导入 ORM、Repository、Workflow 或 UI；
- `scoring` 导入 knowledge；
- `matching` 导入 SQLAlchemy；
- `reporting` 查询数据库；
- `app.py` 直接创建 Session 或计算检索分数。

### 1.3 阶段总览

| Phase | 目标 | 建议投入 | 主要门禁 |
|---|---|---:|---|
| 11.1 | 领域 Schema、配置、Protocol | 0.5—1 天 | 无 DB 依赖、纯模型测试 |
| 11.2 | SQLite 持久层 | 1—1.5 天 | 约束、事务、临时 DB |
| 11.3 | Seed 和版本管理 | 1—1.5 天 | 幂等、hash、publish |
| 11.4 | 检索与回退 | 1—1.5 天 | FTS/fallback 等价 |
| 11.5 | Retriever | 1 天 | 排序、限额、污染保护 |
| 11.6 | Workflow | 1 天 | 可关闭、soft fallback |
| 11.7 | Generator/Validator | 1—1.5 天 | Citation、事实边界 |
| 11.8 | Report/Export/UI | 1—1.5 天 | 向后兼容、同源导出 |
| 11.9 | 三岗位正式 Seed | 1.5—2 天 | 来源与许可证人工审核 |
| 11.10 | 全回归与发布准备 | 1 天 | 干净环境和独立复现 |

时间是实施估算，不改变阶段边界。若前一阶段停止条件触发，不进入后一阶段。

---

## 2. Phase 11.1：领域 Schema、配置与 Repository Protocol

### 2.1 目标

建立不依赖数据库的知识领域契约、枚举、配置和错误码。完成后，上层代码可以针对 Protocol 编写测试，但项目仍无 SQLAlchemy 依赖和数据库实现。

### 2.2 文件

| 文件 | 操作 | 内容 |
|---|---|---|
| `src/jobfit/models/knowledge.py` | 新增 | Knowledge version、Citation、检索对象、Context、Warning、Capabilities |
| `src/jobfit/models/report.py` | 暂不修改 | 报告字段延后到 11.8，避免过早破坏 fixture |
| `src/jobfit/models/__init__.py` | 修改 | 导出知识领域模型 |
| `src/jobfit/knowledge/__init__.py` | 新增 | 只导出公共协议 |
| `src/jobfit/knowledge/protocol.py` | 新增 | `KnowledgeRepository`、`KnowledgeRetriever`、`KnowledgeSeedImporter` Protocol |
| `src/jobfit/knowledge/query.py` | 新增 | frozen 查询对象和 limit 常量 |
| `src/jobfit/config.py` | 修改 | 增加知识配置，但不要求 DB 存在 |
| `src/jobfit/errors.py` | 修改 | 稳定知识错误码与安全消息 |
| `.env.example` | 修改 | 增加不含真实路径的知识配置示例 |
| `tests/unit/test_knowledge_models.py` | 新增 | 模型不变量 |
| `tests/unit/test_knowledge_protocol.py` | 新增 | 假 Repository / Retriever 的契约测试 |
| `tests/unit/test_config.py` | 修改 | 知识配置默认值和非法值 |
| `tests/unit/test_errors.py` | 修改 | 安全错误消息 |

### 2.3 接口和实现步骤

- [ ] 先为以下失败情况写模型测试：
  - unknown field；
  - `available` 无 published version；
  - `unavailable` 携带 Citation；
  - relevance 超出 0—1；
  - duplicate Citation ID；
  - Knowledge ID 前缀错误；
  - excerpt 超过 240 字符。
- [ ] 定义枚举：
  - `KnowledgeVersionStatus`
  - `KnowledgeReviewStatus`
  - `KnowledgeSourceType`
  - `ReliabilityLevel`
  - `KnowledgeQuestionType`
  - `KnowledgeRetrievalStatus`
- [ ] 实现：
  - `KnowledgeBaseVersionInfo`
  - `KnowledgeCitation`
  - `RetrievedRoleProfile`
  - `RetrievedRequirement`
  - `RetrievedEvidencePattern`
  - `RetrievedInterviewQuestion`
  - `KnowledgeWarning`
  - `KnowledgeSearchCapabilities`
  - `KnowledgeContext`
  - `KnowledgeRetrievalResult`
- [ ] 使用现有 `StrictModel` 和 `Decimal`，禁止 ORM 类型。
- [ ] 定义 frozen `RoleProfileQuery` 和 `KnowledgeSearchQuery`。
- [ ] 定义设计文档中的 Repository/Retriever/Importer Protocol。
- [ ] 配置字段：

```python
knowledge_enabled: bool = True
knowledge_version: str | None = None
knowledge_db_path: Path | None = None
knowledge_search_mode: Literal["auto", "fts5", "keyword"] = "auto"
knowledge_requirement_limit: int = 12
knowledge_prompt_char_limit: int = 8000
```

- [ ] 配置只校验类型和范围，不在 Settings 初始化时打开数据库。
- [ ] 增加安全错误码：
  - `KNOWLEDGE_CONFIG_INVALID`
  - `KNOWLEDGE_DB_UNAVAILABLE`
  - `KNOWLEDGE_VERSION_UNAVAILABLE`
  - `KNOWLEDGE_RETRIEVAL_FAILED`
  - `KNOWLEDGE_CITATION_INVALID`
  - `KNOWLEDGE_BOUNDARY_VIOLATION`
  - `KNOWLEDGE_SEED_INVALID`
- [ ] 所有错误消息禁止带绝对路径、SQL 或知识全文。

### 2.4 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_knowledge_models.py tests/unit/test_knowledge_protocol.py tests/unit/test_config.py tests/unit/test_errors.py
.\.venv\Scripts\ruff.exe check .
git diff --check
```

随后运行完整 pytest。

### 2.5 验收

- [ ] 领域层不导入 SQLAlchemy。
- [ ] Protocol 可以由内存 Fake 实现。
- [ ] KnowledgeContext 状态不变量可由 Pydantic 阻止。
- [ ] 当前 v1.0 流程未引用新配置时行为不变。
- [ ] 没有数据库文件、迁移或 seed。

### 2.6 Commit

```text
feat: add knowledge domain schemas and protocols
```

### 2.7 风险与停止条件

风险：把知识模型与 `EvidenceItem` 混合，或让配置初始化依赖数据库。
停止条件：任何知识 Citation 可以通过类型系统进入 `EvidenceRegistry`；任何基线测试因数据库不存在而失败。

---

## 3. Phase 11.2：SQLAlchemy 与 SQLite 持久层

### 3.1 目标

实现 schema 初始化、连接管理、ORM 和只读 Repository。所有测试使用临时数据库，不创建仓库内运行时 SQLite。

### 3.2 文件

| 文件 | 操作 | 内容 |
|---|---|---|
| `pyproject.toml` | 修改 | 新增 `SQLAlchemy>=2.0,<3` |
| `.gitignore` | 修改 | 忽略运行时 DB 和 sidecar |
| `src/jobfit/knowledge/db.py` | 新增 | 用户数据目录、Engine、Session、pragma、schema revision |
| `src/jobfit/knowledge/orm.py` | 新增 | 10 个必须表和 FKs/constraints |
| `src/jobfit/knowledge/repository.py` | 新增 | `SqlAlchemyKnowledgeRepository` |
| `src/jobfit/knowledge/mappers.py` | 新增 | ORM → Pydantic |
| `src/jobfit/knowledge/schema.py` | 新增 | 当前 schema revision 和初始化 |
| `tests/unit/test_knowledge_db.py` | 新增 | 连接、路径、pragma、损坏 |
| `tests/unit/test_knowledge_orm.py` | 新增 | 字段和约束 |
| `tests/unit/test_knowledge_repository.py` | 新增 | 只读查询和过滤 |
| `tests/integration/test_knowledge_sqlite.py` | 新增 | 临时 SQLite 集成 |

### 3.3 测试先行

- [ ] 写失败测试：数据库路径不得默认为仓库根目录。
- [ ] 写失败测试：foreign key 必须启用。
- [ ] 写失败测试：duplicate version/code、非法 enum、断裂 FK 被拒绝。
- [ ] 写失败测试：published version 无 published_at 被拒绝。
- [ ] 写失败测试：Repository 不返回 pending/rejected/retired/inactive。
- [ ] 写失败测试：Repository 返回值不是 ORM。
- [ ] 写失败测试：损坏 DB 返回稳定错误，不暴露路径。

### 3.4 实现步骤

- [ ] 增加唯一运行依赖 SQLAlchemy，不引入 Alembic。
- [ ] 用 SQLAlchemy 2.x typed declarative models 实现：
  - `knowledge_base_versions`
  - `job_families`
  - `role_profiles`
  - `competency_dimensions`
  - `role_requirements`
  - `evidence_patterns`
  - `knowledge_sources`
  - `knowledge_chunks`
  - `interview_questions`
  - `source_role_links`
- [ ] JSON 数组存为 canonical JSON TEXT，由 mapper/Pydantic 校验。
- [ ] 实现 `schema_revision` 元数据表或等价固定 revision。
- [ ] Engine 设置：
  - foreign_keys=ON；
  - busy_timeout；
  - 写库可选 WAL；
  - `pool_pre_ping` 或等价健康检查；
  - Session 不跨线程共享。
- [ ] 默认路径使用 OS 用户数据目录。
- [ ] 分析 Repository 使用短生命周期只读 Session。
- [ ] `get_published_version` 选择显式版本或 `published_at` 最新版本，并用稳定 ID 打破同时间排序。
- [ ] `get_version` 可读取 retired 版本元数据供旧报告审计，但不得把 retired 版本返回给新分析。
- [ ] Repository 所有查询同时过滤 version、approved、active。
- [ ] `limit` 统一 clamp。
- [ ] Mapper 只返回领域对象。

### 3.5 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_knowledge_db.py tests/unit/test_knowledge_orm.py tests/unit/test_knowledge_repository.py tests/integration/test_knowledge_sqlite.py
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\ruff.exe check .
git diff --check
```

随后运行完整 pytest。

### 3.6 验收

- [ ] 临时 SQLite 可创建、读取和关闭。
- [ ] 所有必须约束由数据库和领域双重验证。
- [ ] 分析层无法取得写 Session。
- [ ] Repository 无 ORM 泄漏。
- [ ] DB 不存在或损坏不会泄露路径。
- [ ] 仓库内没有 `.sqlite*` 文件。

### 3.7 Commit

```text
feat: add sqlite knowledge repository
```

### 3.8 风险与停止条件

风险：SQLite JSON/约束行为与 Python 校验不一致；Windows 文件锁导致测试残留。
停止条件：临时数据库无法可靠释放；Repository 必须暴露 Session 才能工作；引入 SQLAlchemy 后 v1.0 安装或测试失败。

---

## 4. Phase 11.3：JSON Seed 导入与版本管理

### 4.1 目标

实现严格 JSON package 校验、canonical hash、事务导入、幂等、显式 publish 和安全重建。只添加匿名测试 seed，不添加正式岗位知识。

### 4.2 文件

| 文件 | 操作 | 内容 |
|---|---|---|
| `src/jobfit/knowledge/seed_models.py` | 新增 | manifest 和 seed Pydantic Schema |
| `src/jobfit/knowledge/seed_loader.py` | 新增 | 读取、校验、canonical hash |
| `src/jobfit/knowledge/importer.py` | 新增 | 单事务 draft 导入、publish、rebuild |
| `src/jobfit/knowledge/cli.py` | 新增 | validate/init/rebuild/inspect |
| `tests/fixtures/knowledge/minimal_valid/` | 新增 | 匿名最小 seed |
| `tests/fixtures/knowledge/invalid_*/` | 新增 | 最小错误夹具 |
| `tests/unit/test_knowledge_seed_models.py` | 新增 | Schema |
| `tests/unit/test_knowledge_seed_loader.py` | 新增 | hash、路径和 JSON |
| `tests/unit/test_knowledge_importer.py` | 新增 | 幂等和回滚 |
| `tests/integration/test_knowledge_seed_lifecycle.py` | 新增 | draft→published→retired |

### 4.3 实现步骤

- [ ] 为缺文件、未知文件、重复 ID、缺 source、非法 review status 写失败测试。
- [ ] 为 JSON key 顺序和换行差异不影响 hash 写测试。
- [ ] 为 same version + same hash 幂等写测试。
- [ ] 为 same version + different hash 拒绝覆盖写测试。
- [ ] 为导入中途失败全事务回滚写测试。
- [ ] 实现 manifest 白名单，拒绝 `../` 和绝对路径。
- [ ] 按设计文档顺序生成 canonical SHA-256。
- [ ] 所有 seed ID 显式提供并验证前缀。
- [ ] 只允许 `pending/approved/rejected`，但 publish 门禁要求所有被启用内容 approved。
- [ ] `import_draft` 不自动 publish。
- [ ] `publish_version` 验证：
  - 来源存在；
  - source license_note 非空；
  - 所有 active 内容 approved；
  - 外键完整；
  - hash 与 manifest 一致；
  - published_at 由本地代码写入 UTC。
- [ ] published 内容不可原地更新。
- [ ] 被 published 版本引用的 source 不可原地更新；来源变化创建新 source ID。
- [ ] rebuild 写入临时 DB、校验后原子替换。
- [ ] CLI 输出计数和 hash，不输出绝对路径或全文。

### 4.4 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_knowledge_seed_models.py tests/unit/test_knowledge_seed_loader.py tests/unit/test_knowledge_importer.py tests/integration/test_knowledge_seed_lifecycle.py
.\.venv\Scripts\ruff.exe check .
git diff --check
```

随后运行完整 pytest。

### 4.5 验收

- [ ] 同一 seed 重复导入不产生重复记录。
- [ ] 同版本不同内容不能覆盖。
- [ ] published 版本不可修改。
- [ ] 非 approved 内容不能发布。
- [ ] 任一错误回滚全部写入。
- [ ] 测试 seed 不含真实公司、简历或内部 JD。

### 4.6 Commit

```text
feat: add versioned knowledge seed imports
```

### 4.7 风险与停止条件

风险：canonical hash 在平台间不稳定；导入器允许部分成功。
停止条件：Windows 和测试环境对同一 seed 得到不同 hash；失败后存在部分 published 数据；导入器可绕过人工 publish。

---

## 5. Phase 11.4：结构化检索、FTS5 与确定性回退

### 5.1 目标

实现文本规范化、FTS 能力探测、候选召回和确定性重排。FTS5 不可用时结果仍可靠。

### 5.2 文件

| 文件 | 操作 | 内容 |
|---|---|---|
| `src/jobfit/knowledge/normalization.py` | 新增 | NFKC、中英文 token/bigram、停用词 |
| `src/jobfit/knowledge/ranking.py` | 新增 | Decimal role/requirement score |
| `src/jobfit/knowledge/fts.py` | 新增 | FTS5 探测、虚拟表、重建、查询 |
| `src/jobfit/knowledge/repository.py` | 修改 | 结构化过滤、FTS/LIKE 候选召回 |
| `src/jobfit/knowledge/query.py` | 修改 | 检索阈值、候选 pool、稳定 tie-break |
| `tests/unit/test_knowledge_normalization.py` | 新增 | 中英文和 Unicode |
| `tests/unit/test_knowledge_ranking.py` | 新增 | 公式和边界 |
| `tests/unit/test_knowledge_fts.py` | 新增 | 能力探测和安全查询 |
| `tests/integration/test_knowledge_search_modes.py` | 新增 | FTS/fallback 等价 |

### 5.3 实现步骤

- [ ] 先写 NFKC、casefold、空白、英文词、中文 bigram 测试。
- [ ] 写 SQL wildcard、引号和 FTS 操作符输入安全测试。
- [ ] 写 role_score 和 requirement_score 精确 Decimal 测试。
- [ ] 写阈值 0.45/0.35 和同分 stable ID 测试。
- [ ] 写 FTS 强制模式不可用时明确配置错误测试。
- [ ] 写 auto 模式不可用时 fallback 测试。
- [ ] 写 FTS 与 fallback 对相同 fixture 返回同一最终顺序测试。
- [ ] FTS 只召回最多 100 个候选。
- [ ] fallback 只扫描已经过 version/review/role 过滤的有限集合。
- [ ] 对 FTS/LIKE 候选统一调用 `ranking.py`。
- [ ] BM25 只作为召回内部信息，不进入领域 relevance。
- [ ] 所有查询参数化，LIKE `%` 和 `_` 正确转义。
- [ ] FTS 派生表可重建，不进入 source hash。

### 5.4 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_knowledge_normalization.py tests/unit/test_knowledge_ranking.py tests/unit/test_knowledge_fts.py tests/integration/test_knowledge_search_modes.py
.\.venv\Scripts\ruff.exe check .
git diff --check
```

随后运行完整 pytest。

### 5.5 验收

- [ ] 相同输入输出稳定。
- [ ] FTS 可用与不可用都通过。
- [ ] 最终排序不直接依赖 BM25。
- [ ] SQL/FTS 特殊字符不能改变查询结构。
- [ ] 只返回 published/approved/active。
- [ ] limit 和 tie-break 可复现。

### 5.6 Commit

```text
feat: add deterministic knowledge search
```

### 5.7 风险与停止条件

风险：中文无分词导致召回弱；FTS/fallback 候选不一致。
停止条件：三个首批岗位名称无法用规则稳定识别；FTS 与 fallback 在固定 fixture 上产生不同最终 top results；用户输入可导致 SQL/FTS 语法错误。

---

## 6. Phase 11.5：KnowledgeRetriever

### 6.1 目标

把 `JobProfile` 转换成有版本、限额、引用和 warning 的 `KnowledgeContext`，并实现岗位歧义和跨岗位污染保护。

### 6.2 文件

| 文件 | 操作 | 内容 |
|---|---|---|
| `src/jobfit/knowledge/retriever.py` | 新增 | `DefaultKnowledgeRetriever` |
| `src/jobfit/knowledge/noop.py` | 新增 | 关闭模式实现 |
| `src/jobfit/knowledge/conflicts.py` | 新增 | JD 与知识差异检测 |
| `src/jobfit/knowledge/query.py` | 修改 | 默认 limits |
| `tests/unit/test_knowledge_retriever.py` | 新增 | 排序、limit、状态 |
| `tests/unit/test_knowledge_conflicts.py` | 新增 | JD 优先 |
| `tests/integration/test_knowledge_retrieval.py` | 新增 | Repository→Context |

### 6.3 实现步骤

- [ ] 为 disabled/no version/no DB/no match/ambiguous 写失败测试。
- [ ] 为三种首批岗位方向写匿名检索 fixture。
- [ ] 为技术战略与数据分析的关键词交叉写污染测试。
- [ ] 为 top two 不同岗位族、分差 `<=0.05` 写 ambiguous 测试。
- [ ] 为 requirement/evidence/question/chunk/source limits 写测试。
- [ ] 为 Citation 去重、单来源最多两个 chunk 写测试。
- [ ] 为相同输入结果完全相同写测试。
- [ ] 实现 query terms，只使用 JobProfile title、company-independent keywords、requirements 和 JD 摘要字段，不记录完整 JD。
- [ ] 首先取得 pinned published version。
- [ ] 搜索最多 3 个 role profiles。
- [ ] ambiguous 时只返回候选画像和 warning，不检索 profile-specific 内容。
- [ ] 可用时检索 requirements、patterns、questions、sources。
- [ ] 构建 Citation，并按稳定 ID 去重。
- [ ] 检测知识与 JobRequirement 的参考差异，但不修改 JobProfile。
- [ ] `NoOpKnowledgeRetriever` 返回 `disabled`。
- [ ] 捕获预期 DB/retrieval 错误并转为 `unavailable`；编程错误不吞掉。

### 6.4 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_knowledge_retriever.py tests/unit/test_knowledge_conflicts.py tests/integration/test_knowledge_retrieval.py
.\.venv\Scripts\ruff.exe check .
git diff --check
```

随后运行完整 pytest。

### 6.5 验收

- [ ] Retriever 不调用 LLM。
- [ ] 不保存 JobProfile 或 JD。
- [ ] 跨岗位污染测试通过。
- [ ] 无结果/故障返回安全 Context。
- [ ] Citation 有 source/version/checksum。
- [ ] Context 不含数据库路径。

### 6.6 Commit

```text
feat: add job knowledge retriever
```

### 6.7 风险与停止条件

风险：岗位标题过于通用；异常被过度吞掉。
停止条件：歧义岗位仍注入 profile-specific 内容；编程错误被伪装成普通 warning；Context 含完整 JD。

---

## 7. Phase 11.6：Workflow 可选接入

### 7.1 目标

在 `EXTRACTING_JOB` 后检索知识，把可选 Context 带到报告阶段；Matcher 和 Scoring 的输入保持不变。

### 7.2 文件

| 文件 | 操作 | 内容 |
|---|---|---|
| `src/jobfit/models/common.py` | 修改 | 增加 `RETRIEVING_KNOWLEDGE` |
| `src/jobfit/workflow/state.py` | 修改 | 可选 context/warnings |
| `src/jobfit/workflow/orchestrator.py` | 修改 | 调用 Retriever、soft fallback |
| `src/jobfit/workflow/factory.py` | 修改 | 注入 SQLite 或 NoOp retriever |
| `src/jobfit/workflow/__init__.py` | 修改 | 公共导出 |
| `src/jobfit/config.py` | 修改 | 路径解析和模式组装 |
| `src/jobfit/demo.py` | 修改 | Demo 使用 NoOp 或匿名测试知识 |
| `tests/unit/test_workflow_state.py` | 修改 | 新状态合法迁移 |
| `tests/unit/test_orchestrator.py` | 修改 | 调用顺序和失败控制 |
| `tests/integration/test_mock_workflow.py` | 修改 | 启停知识 |
| `tests/integration/test_knowledge_workflow.py` | 新增 | soft fallback 和边界 |

### 7.3 实现步骤

- [ ] 先更新状态机失败测试。
- [ ] 新阶段顺序：

```text
EXTRACTING_JOB
→ RETRIEVING_KNOWLEDGE
→ MATCHING_EVIDENCE
```

- [ ] 为知识启用/禁用/无库/损坏/无匹配写测试。
- [ ] 为 Retriever 抛预期领域错误后 Matcher 仍执行写测试。
- [ ] 为 Retriever 编程错误按安全策略失败写测试。
- [ ] 为 Matcher 调用参数没有 KnowledgeContext 写 spy 测试。
- [ ] 为 ScoringEngine 调用 requirements 与 v1.0 完全相同写 spy 测试。
- [ ] 把 knowledge enabled/version/hash/policy version 加入 request fingerprint。
- [ ] 失败知识请求不能作为成功增强结果缓存。
- [ ] Factory 不在 UI 中泄露 DB 组装细节。
- [ ] Demo 默认无需 `.env` 或数据库也能完整运行。

### 7.4 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_workflow_state.py tests/unit/test_orchestrator.py tests/integration/test_mock_workflow.py tests/integration/test_knowledge_workflow.py
.\.venv\Scripts\ruff.exe check .
git diff --check
```

随后运行完整 pytest。

### 7.5 验收

- [ ] 知识检索位置正确。
- [ ] Matcher 不接收知识。
- [ ] Scoring 输入和结果不变。
- [ ] 知识不可用不阻塞基础报告。
- [ ] Progress 单调递增。
- [ ] 缓存不会跨知识版本复用。

### 7.6 Commit

```text
feat: integrate optional knowledge retrieval workflow
```

### 7.7 风险与停止条件

风险：新状态破坏 Streamlit 进度；soft fallback 吞掉核心错误。
停止条件：知识关闭时 v1.0 流程结果变化；Matcher/Scoring 收到知识要求；状态机可跳过 Evidence Validator。

---

## 8. Phase 11.7：Generator、Prompt 与知识 Validator

### 8.1 目标

让一次 AdviceBundle 调用可以参考受限、已审核的知识，同时建立 Citation、边界和 Prompt Injection 防护。不得改变评分或匹配。

### 8.2 文件

| 文件 | 操作 | 内容 |
|---|---|---|
| `src/jobfit/models/advice.py` | 修改 | Advice draft 可选 knowledge citation IDs |
| `src/jobfit/generators/advice_bundle.py` | 修改 | 传入 bounded reference knowledge |
| `src/jobfit/generators/common.py` | 修改 | 安全知识序列化和字符限额 |
| `src/jobfit/prompts/archive/generate_advice_bundle.1.1.md` | 新增 | 保存当前 1.1 Prompt 快照 |
| `src/jobfit/prompts/generate_advice_bundle.md` | 修改 | reference knowledge 边界和 citation |
| `src/jobfit/llm/prompt_registry.py` | 修改 | Prompt 版本升级 |
| `src/jobfit/validators/knowledge.py` | 新增 | Citation 和评分/证据边界 |
| `src/jobfit/validators/report.py` | 修改 | 调用 knowledge validator |
| `src/jobfit/validators/__init__.py` | 修改 | 导出 |
| `tests/unit/test_knowledge_prompt_context.py` | 新增 | 限额和 injection 文本 |
| `tests/unit/test_knowledge_validator.py` | 新增 | Citation/边界 |
| `tests/unit/test_generators.py` | 修改 | citation 与事实约束 |
| `tests/integration/test_knowledge_advice.py` | 新增 | Mock bundle |

### 8.3 实现步骤

- [ ] 实施前确认当前 Prompt 基线仍为 1.1；若已经漂移，停止并重新评审计划。
- [ ] 将当前 Prompt 归档为 `generate_advice_bundle.1.1.md`，把活动版本递增为 1.2，并更新 Registry/指纹测试。
- [ ] Prompt 明确 reference knowledge 不是候选人事实或 JD 新要求。
- [ ] MVP 仍不向 JobExtractor、ResumeExtractor 或 EvidenceMatcher 传知识。
- [ ] Advice payload 只包含：
  - bounded role summary；
  - bounded requirements；
  - evidence pattern descriptions；
  - interview dimensions；
  - citation IDs；
  - knowledge version。
- [ ] 总字符不超过配置上限，裁剪顺序稳定。
- [ ] 移除控制字符，把知识放在数据区而非 system 指令。
- [ ] LLM 只能返回已提供的 citation IDs。
- [ ] Rewrite 不得因知识新增工具、数字、组织、职责或部署事实；继续使用现有 Rewrite Validator。
- [ ] Recommendation level 继续从 `MatchScoreSummary` 本地组装。
- [ ] 实现 `KnowledgeCitationValidator`、`KnowledgeBoundaryValidator`、`KnowledgeReportValidator`。
- [ ] 对评分边界写核心回归：

```python
assert score_with_knowledge == score_without_knowledge
```

- [ ] 不存在 Citation、未发布版本、version/hash 不一致时 fail closed。
- [ ] 知识 DB 在检索阶段不可用时 Context 无 Citation，允许基础报告。

### 8.4 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_knowledge_prompt_context.py tests/unit/test_knowledge_validator.py tests/unit/test_generators.py tests/integration/test_knowledge_advice.py
.\.venv\Scripts\ruff.exe check .
git diff --check
```

随后运行完整 pytest，并重点检查 scoring/matching/validator 回归。

### 8.5 验收

- [ ] Prompt 版本可追溯。
- [ ] 知识字符和数量受限。
- [ ] 注入性文本只作为数据。
- [ ] LLM 不能创建 Citation。
- [ ] 知识不改变 rewrite 事实边界。
- [ ] 推荐等级和评分完全由现有本地代码生成。

### 8.6 Commit

```text
feat: add grounded knowledge advice citations
```

### 8.7 风险与停止条件

风险：AdviceBundle 同一 Prompt 中的知识污染改写；Prompt Injection；伪造 Citation。
停止条件：LLM 能让未提供 Citation 通过；知识中的工具或成果进入可直接采用改写；启用知识改变 recommendation level。

---

## 9. Phase 11.8：AnalysisReport、导出与 Streamlit

### 9.1 目标

以可选字段升级报告 Schema，保持 v1.0 加载兼容；Markdown、JSON 和 UI 从同一个已验证报告读取知识参考。

### 9.2 文件

| 文件 | 操作 | 内容 |
|---|---|---|
| `src/jobfit/models/report.py` | 修改 | schema 1.0/1.1 和可选知识字段 |
| `src/jobfit/validators/report.py` | 修改 | version/citation/report 不变量 |
| `src/jobfit/reporting/json_export.py` | 修改 | 1.1 官方序列化 |
| `src/jobfit/reporting/markdown.py` | 修改 | “岗位知识参考”章节 |
| `src/jobfit/reporting/_guards.py` | 修改 | 禁止路径/内部字段 |
| `src/jobfit/workflow/orchestrator.py` | 修改 | 将 Context 交给报告构建 |
| `app.py` | 修改 | 新标签、warning、来源 |
| `tests/unit/test_models.py` | 修改 | v1.0/1.1 round-trip |
| `tests/unit/test_report_validator.py` | 修改 | knowledge 不变量 |
| `tests/unit/test_json_reporting.py` | 修改 | 可选字段、稳定输出 |
| `tests/unit/test_markdown_reporting.py` | 修改 | 知识章节、免责声明 |
| `tests/integration/test_report_exports.py` | 修改 | 同源和 Citation |
| `tests/integration/test_streamlit_interactions.py` | 修改 | 标签、关闭、warning |
| `tests/integration/test_streamlit_smoke.py` | 修改 | 默认 Mock |

### 9.3 实现步骤

- [ ] 先为 v1.0 fixture 在新模型下加载写测试。
- [ ] `schema_version` 接受 `"1.0"` 和 `"1.1"`。
- [ ] 新报告使用 `"1.1"`，旧报告知识字段默认 None/空列表。
- [ ] 增加精简 `KnowledgeReportContext`，不直接导出全部 `KnowledgeContext`。
- [ ] Report Validator 验证：
  - version/hash；
  - citations；
  - no knowledge 状态；
  - requirement/match/scoring 集合不变；
  - warning 安全；
  - 无数据库路径。
- [ ] JSON 继续 `model_dump_json` 路径，禁止手写第二套数据。
- [ ] Markdown 加知识章节和固定免责声明。
- [ ] Markdown 只输出摘要、来源名称、URL 和 Citation ID。
- [ ] UI 增加“岗位知识参考”标签。
- [ ] UI 不导入 Repository 或 SQLAlchemy。
- [ ] 下载不重新检索或调用模型。
- [ ] 输入或知识版本变化使旧报告过期。

### 9.4 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_models.py tests/unit/test_report_validator.py tests/unit/test_json_reporting.py tests/unit/test_markdown_reporting.py tests/integration/test_report_exports.py tests/integration/test_streamlit_smoke.py tests/integration/test_streamlit_interactions.py
.\.venv\Scripts\ruff.exe check .
git diff --check
```

随后运行完整 pytest。

### 9.5 验收

- [ ] v1.0 JSON 可加载。
- [ ] v1.1 JSON 可 round-trip。
- [ ] Markdown/JSON/UI 使用同一报告。
- [ ] 五个原标签内容不回归，新标签不含业务计算。
- [ ] 知识免责声明可见。
- [ ] 无长知识原文、DB 路径或 PII。

### 9.6 Commit

```text
feat: add knowledge references to reports and ui
```

### 9.7 风险与停止条件

风险：严格 `AnalysisReport` 破坏旧 fixture；UI 直接查询 DB；导出内容膨胀。
停止条件：v1.0 报告无法加载；Markdown 和 JSON 核心数字不一致；下载触发第二次分析；UI 出现数据库路径。

---

## 10. Phase 11.9：首批正式知识 Seed

### 10.1 目标

创建三个岗位方向的高质量、原创归纳、来源明确、经过人工审核的正式 published seed。该阶段是内容治理阶段，不修改评分规则。

### 10.2 文件

| 文件 | 操作 | 内容 |
|---|---|---|
| `data/knowledge/versions/<version>/manifest.json` | 新增 | 文件清单和 hash 元数据 |
| `data/knowledge/versions/<version>/knowledge_base_version.json` | 新增 | draft/published 元数据 |
| `data/knowledge/versions/<version>/job_families.json` | 新增 | 三个岗位族 |
| `data/knowledge/versions/<version>/role_profiles.json` | 新增 | 3—9 个画像 |
| `data/knowledge/versions/<version>/competency_dimensions.json` | 新增 | 解释维度 |
| `data/knowledge/versions/<version>/role_requirements.json` | 新增 | 每方向 10—20 条 |
| `data/knowledge/versions/<version>/evidence_patterns.json` | 新增 | 每方向 10—20 条 |
| `data/knowledge/versions/<version>/knowledge_sources.json` | 新增 | 每方向 3—8 个来源 |
| `data/knowledge/versions/<version>/knowledge_chunks.json` | 新增 | 必要短摘要/短引用 |
| `data/knowledge/versions/<version>/interview_questions.json` | 新增 | 每方向 10—15 题 |
| `data/knowledge/versions/<version>/source_role_links.json` | 新增 | 来源支持关系 |
| `docs/knowledge-curation-guide.md` | 新增 | 收集、审核、引用和许可证规则 |
| `tests/integration/test_production_knowledge_seed.py` | 新增 | 正式 seed 门禁 |

### 10.3 内容流程

- [ ] 用户或维护者确认实际知识版本号，默认 `2026.07.1`。
- [ ] 只使用允许公开引用的资料。
- [ ] 为每个 source 填写 publisher、URL、日期、license_note、reliability。
- [ ] 以原创归纳为主，必要短引用不超过合理范围。
- [ ] AI 应用实习生内容完成双向去重。
- [ ] 数据分析实习生内容完成双向去重。
- [ ] 技术战略实习生内容完成双向去重。
- [ ] 技术战略与数据分析的交叉能力显式标注，不共享 profile-specific 要求。
- [ ] common hard blocker 逐条人工审核并附解释。
- [ ] 面试问题覆盖五种类型。
- [ ] 每条 requirement/pattern/question 可追溯 source。
- [ ] 导入 draft，运行自动门禁。
- [ ] 人工抽样审阅全部高/critical 条目。
- [ ] 显式 publish。

### 10.4 测试

```powershell
.\.venv\Scripts\python.exe -m jobfit.knowledge.cli validate-seed --source data/knowledge/versions/<version>
.\.venv\Scripts\python.exe -m pytest tests/integration/test_production_knowledge_seed.py
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
git diff --check
```

另外执行文档/数据轻量安全扫描：

- 不含简历、手机号、私人邮箱和本机路径；
- 不含长篇第三方网页复制；
- URL 与 license_note 完整；
- content hash 匹配。

### 10.5 验收

- [ ] 三个岗位方向达到规定最小数量。
- [ ] 所有 active 内容 approved。
- [ ] 所有要求、模式和问题有来源。
- [ ] 来源权利和引用边界经人工确认。
- [ ] 正式 seed 幂等导入并成为 published。
- [ ] “产品分析实习生”未被弱内容凑入首批。

### 10.6 Commit

```text
data: add reviewed job knowledge seed
```

### 10.7 风险与停止条件

风险：来源授权不明确、知识质量不均、为了数量复制网页。
停止条件：任一 active 内容无来源；license_note 无法确认；出现真实候选人数据；来源材料只能通过大段复制表达。

---

## 11. Phase 11.10：完整回归与 v1.1.0 发布准备

### 11.1 目标

完成全量离线测试、覆盖率、干净环境初始化、Mock 演示、报告兼容、安全和独立克隆准备，但不自动创建 tag、Release 或 push。

### 11.2 文件

| 文件 | 操作 | 内容 |
|---|---|---|
| `tests/integration/test_knowledge_end_to_end.py` | 新增 | 启用知识完整路径 |
| `tests/integration/test_knowledge_failure_paths.py` | 新增 | DB/FTS/Citation 失败 |
| `tests/integration/test_end_to_end.py` | 修改 | v1.0 基础模式回归 |
| `tests/integration/test_failure_paths.py` | 修改 | fail closed 边界 |
| `README.md` | 修改 | v1.1 功能、初始化、限制、隐私 |
| `docs/github-release-checklist.md` | 修改 | 知识门禁 |
| `docs/architecture.md` 或现有等价文档 | 按实际存在情况修改 | 架构和 Schema 版本 |
| `.env.example` | 复核 | 配置说明 |
| `assets/screenshots/` | 可选修改 | 仅在用户授权后更新匿名截图 |

### 11.3 测试矩阵

- [ ] TXT/DOCX/PDF/粘贴文本 + Knowledge enabled。
- [ ] Knowledge disabled 的 v1.0 完整路径。
- [ ] DB 不存在、损坏、schema 不符。
- [ ] 无 published version、无匹配、ambiguous。
- [ ] FTS5 和 fallback。
- [ ] 无简历证据仍 unknown。
- [ ] Knowledge requirement 不进入评分。
- [ ] common hard blocker 不触发 cap。
- [ ] Citation 伪造、过期、跨版本。
- [ ] Advice Prompt Injection 夹具。
- [ ] v1.0/v1.1 JSON round-trip。
- [ ] Markdown/JSON/UI 同源。
- [ ] Mock 不联网。
- [ ] Session cache 按 version/hash 失效。
- [ ] Runtime DB 和分析输入不进入 Git。

### 11.4 质量命令

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest --cov=src/jobfit --cov-branch --cov-report=term-missing
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

重点分支覆盖：

- Knowledge models/seed/repository/retriever/validators；
- Scoring/Evidence Validator 基线不得下降；
- Workflow fallback；
- Reporting guards。

### 11.5 干净环境

- [ ] 在仓库外或被忽略目录创建全新 venv。
- [ ] `pip install -e ".[dev]"`。
- [ ] `pip check`。
- [ ] 从正式 seed 初始化运行时 DB。
- [ ] 完整 pytest。
- [ ] 启动 Streamlit。
- [ ] Mock 分析启用知识。
- [ ] Mock 分析禁用知识。
- [ ] Markdown/JSON 下载。
- [ ] 删除/隔离运行时 DB 后基础模式仍成功。
- [ ] 检查控制台不含 PII、Prompt、SQL、绝对路径。

### 11.6 发布文档

- [ ] README 说明知识不是候选人证据。
- [ ] README 说明知识不改变评分。
- [ ] README 说明 seed、运行时 DB 和重建。
- [ ] README 说明 FTS fallback。
- [ ] README 说明三个首批岗位。
- [ ] README 说明不保存用户简历。
- [ ] 发布清单包含来源/许可证人工审核。
- [ ] 不伪造测试数量、在线地址或模型效果。

### 11.7 验收

- [ ] 全部测试 0 失败。
- [ ] 干净环境可安装、初始化、运行。
- [ ] 基础模式和增强模式都可演示。
- [ ] 评分在两种模式完全一致。
- [ ] v1.0 报告可加载。
- [ ] 正式 seed 来源和许可证无阻塞。
- [ ] Git 工作区只含预期发布改动。
- [ ] 未创建运行时 DB、日志、报告或上传文件的 tracked 文件。

### 11.8 Commit

建议拆成两个稳定提交：

```text
test: complete knowledge base regression coverage
docs: prepare JobFit Agent v1.1.0 release
```

### 11.9 风险与停止条件

风险：新依赖在 Python 3.11/3.12 或 Windows 失败；正式 seed 许可证未完成；基础模式回归。
停止条件：任一基线评分变化、独立环境无法初始化、用户数据落盘、来源审核未通过或 v1.0 报告无法加载。此时不得创建 v1.1.0 tag/Release。

---

## 12. 文件级总清单

### 12.1 新增产品代码

```text
src/jobfit/
├─ models/
│  └─ knowledge.py
└─ knowledge/
   ├─ __init__.py
   ├─ protocol.py
   ├─ query.py
   ├─ db.py
   ├─ orm.py
   ├─ schema.py
   ├─ mappers.py
   ├─ repository.py
   ├─ seed_models.py
   ├─ seed_loader.py
   ├─ importer.py
   ├─ cli.py
   ├─ normalization.py
   ├─ ranking.py
   ├─ fts.py
   ├─ retriever.py
   ├─ conflicts.py
   └─ noop.py
```

`validators/knowledge.py` 在 Phase 11.7 新增。其他文件只在其对应阶段按最小范围修改。

### 12.2 新增测试

```text
tests/
├─ fixtures/
│  └─ knowledge/
├─ unit/
│  ├─ test_knowledge_models.py
│  ├─ test_knowledge_protocol.py
│  ├─ test_knowledge_db.py
│  ├─ test_knowledge_orm.py
│  ├─ test_knowledge_repository.py
│  ├─ test_knowledge_seed_models.py
│  ├─ test_knowledge_seed_loader.py
│  ├─ test_knowledge_importer.py
│  ├─ test_knowledge_normalization.py
│  ├─ test_knowledge_ranking.py
│  ├─ test_knowledge_fts.py
│  ├─ test_knowledge_retriever.py
│  ├─ test_knowledge_conflicts.py
│  ├─ test_knowledge_prompt_context.py
│  └─ test_knowledge_validator.py
└─ integration/
   ├─ test_knowledge_sqlite.py
   ├─ test_knowledge_seed_lifecycle.py
   ├─ test_knowledge_search_modes.py
   ├─ test_knowledge_retrieval.py
   ├─ test_knowledge_workflow.py
   ├─ test_knowledge_advice.py
   ├─ test_production_knowledge_seed.py
   ├─ test_knowledge_end_to_end.py
   └─ test_knowledge_failure_paths.py
```

### 12.3 正式知识数据

正式 seed 仅在 Phase 11.9 创建：

```text
data/knowledge/versions/<version>/*.json
```

运行时数据库不得位于该目录。

---

## 13. 阶段通用提交门禁

每个 Phase 提交前：

- [ ] 专项测试通过。
- [ ] 完整 pytest 通过。
- [ ] Ruff 通过。
- [ ] `pip check` 在依赖变更阶段通过。
- [ ] `git diff --check` 通过。
- [ ] `git status --short` 只有本阶段文件。
- [ ] 无 `.env`、SQLite、缓存、日志、报告、用户上传或本机路径。
- [ ] 无真实 API 请求。
- [ ] 无评分、匹配或推荐规则的未授权改动。
- [ ] Commit message 与实际完成范围一致。

若阶段只改文档或 seed，可按风险缩小测试，但必须说明依据；Phase 11.9 的正式 seed 必须跑 importer 和完整回归。

---

## 14. 关键回归断言

以下测试应跨阶段长期保留：

```python
# 1. Knowledge never becomes resume evidence.
assert all(item.source_type == EvidenceSourceType.RESUME for match in matches for item in match.evidence_items)

# 2. Knowledge never changes the scored requirement set.
assert {item.requirement_id for item in score_inputs} == {
    item.requirement_id for item in job_profile.requirements
}

# 3. Knowledge never changes deterministic scoring.
assert score_enabled == score_disabled

# 4. Knowledge-only blocker cannot cap a score.
assert knowledge_context.requirements[0].is_common_hard_blocker is True
assert score_summary.score_cap == expected_cap_from_job_profile_only

# 5. Citations are from one published version.
assert {citation.knowledge_version_id for citation in report.knowledge_citations} <= {
    report.knowledge_base_version.id
}

# 6. Old reports remain loadable.
assert AnalysisReport.model_validate(v1_report_fixture).schema_version == "1.0"
```

实际测试使用完整模型和 fixture，不复制业务算法到测试中。

---

## 15. 发布前停止规则

出现以下任一情况时，停止在当前 Phase，不继续集成或发布：

1. KnowledgeContext 可以被当作候选人 Evidence；
2. 启用知识后 scoring 输入或输出发生变化；
3. 通用 hard blocker 触发当前 JD 封顶；
4. FTS 不可用时基础分析失败；
5. published 版本可被原地覆盖；
6. Citation 无法映射 source/chunk/version；
7. 用户简历、JD 或报告写入知识库；
8. seed 来源权利不明确；
9. v1.0 报告无法加载；
10. 运行时 DB、日志、报告或本地路径进入 Git；
11. 普通测试访问网络或要求真实 API Key；
12. 任一阶段只能通过扩大到向量库、后台或 PostgreSQL 才能完成。

停止后先提交诊断和最小调整建议，不能用降低证据或评分标准来“通过”。

---

## 16. Phase 11.1 开始清单

架构获批后，下一步只执行 Phase 11.1：

- [ ] 再次核对分支、HEAD、工作区。
- [ ] 运行完整基线。
- [ ] 创建 `test_knowledge_models.py` 的失败测试。
- [ ] 实现 `models/knowledge.py`。
- [ ] 创建 Protocol 和查询对象。
- [ ] 增加配置与错误码。
- [ ] 运行专项和完整测试。
- [ ] 只提交 `feat: add knowledge domain schemas and protocols`。
- [ ] 停止并等待 Phase 11.2 授权。

不得在 Phase 11.1 提前添加 SQLAlchemy、数据库、迁移、seed、Prompt、Workflow 或 UI 实现。
