# JobFit Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 48 小时内交付可本地运行、可离线演示、可测试、可部署并具备 GitHub 作品集质量的证据约束型岗位匹配与简历诊断 MVP。

**Architecture:** 使用 Python 3.11/3.12、Streamlit 单页 UI、显式 WorkflowOrchestrator、Pydantic v2 结构化模型、可替换 LLMClient、离线 Mock 供应商和纯函数 ScoringEngine。大模型只负责语义提取、证据候选、解释和建议；权重、分数、硬门槛、推荐等级、引用校验和最终报告不变量全部由本地代码控制。

**Tech Stack:** Python 3.11/3.12、Streamlit、Pydantic v2、pydantic-settings、pypdf（BSD-3-Clause，仅提取 PDF 文本层、不含 OCR）、python-docx、OpenAI Python SDK、python-dotenv、pytest、pytest-cov、Ruff、标准 logging。

## Global Constraints

- 最高优先级规格为 `docs/superpowers/specs/2026-07-23-jobfit-agent-design.md`，实现不得修改其产品边界和评分规则。
- 单次只分析一份简历和一份 JD；不保存历史记录。
- 文件上限 10 MiB；简历文本上限 50,000 个 Unicode 字符；JD 上限 30,000 个字符。
- 支持 TXT、DOCX、文本型 PDF 和粘贴文本；不执行 OCR。
- Pydantic 模型统一使用 `extra="forbid"`；未知值用 `None` 或空列表，不用推断补全。
- 普通测试只使用固定夹具和 MockLLMClient，不允许产生外部请求或 API 费用。
- 最终权重、状态数值、维度分、总分上限和推荐等级只能由确定性代码生成。
- `matched` 必须有直接证据，`partial` 必须至少有直接或上下文证据。
- 未证明的能力使用 `unknown`，不能描述为用户确定不具备。
- 默认不持久化简历、JD、模型完整响应或生成报告。
- 日志不得包含完整简历、JD、姓名、邮箱、电话、地址、密钥、Authorization header 或本地绝对路径。
- 未经用户明确授权，不添加 Git 远程、不创建 GitHub 仓库、不执行 push、不创建 Pull Request。
- 不引入数据库、RAG、向量库、多 Agent 通信、微服务、OCR、PDF 导出、React 或 Docker。
- 根目录现有 `.agents/` 属于环境辅助目录，只读保护，不纳入产品实现或 Git 提交。

---

## 1. 基线状态

计划生成时已核验：

- 分支：`main`
- 工作区：干净
- 最新提交：`7ee075d docs: add JobFit Agent architecture`
- Git 远程：0
- 架构文件：存在，1040 行
- 架构文件 SHA-256：`F93A1A86BFB2E05340590F8F99036196A850A6ADEE99CBEEA3C858CE49A0F40E`
- Git 作者：已配置
- 业务代码：尚未创建

本计划只新增实施计划文档，不修改架构文件。

## 2. 最小实施澄清

架构本身可执行，不需要重新设计。实施中采用两个不扩大范围的组织性澄清：

1. `ResumeProfile` 只保存 `evidence_id`，不内嵌完整 EvidenceItem。实现时在 `WorkflowState` 中维护仅运行期使用的 `EvidenceRegistry`，负责 `evidence_id → EvidenceItem` 查找；它不新增持久化能力，也不改变 AnalysisReport Schema。
2. 架构规定第四次模型调用生成完整 advice bundle，而目录将诊断、改写和面试拆成三个文件。实现时新增 `src/jobfit/generators/advice_bundle.py` 作为薄门面，只执行一次 LLM 调用，再交给三个规则模块校正和过滤。

## 3. Phase 0–9 总览

| Phase | 目标 | 对应任务 | 产出门槛 | 预计 |
|---|---|---|---|---:|
| 0 | 项目基础建设 | Task 1 | 可安装、配置与日志测试通过 | 3.0h |
| 1 | 核心数据模型 | Task 2 | 严格 Schema 与引用模型测试通过 | 4.0h |
| 2 | 文档解析 | Task 3 | TXT/DOCX/PDF/异常测试通过 | 3.5h |
| 3 | LLM 适配层 | Task 4–5 | Mock、Prompt、结构修复、生产适配测试通过 | 5.5h |
| 4 | 简历与 JD 提取 | Task 6 | 固定输出可组装为稳定领域模型 | 3.0h |
| 5 | 证据匹配和评分 | Task 7–8 | 证据闭环与精确 Decimal 评分通过 | 7.0h |
| 6 | 诊断与生成 | Task 9 | 规则不允许模型升级推荐或新增事实 | 3.0h |
| 7 | Validator 和报告 | Task 10 | 报告不变量、Markdown、JSON 通过 | 3.0h |
| 8 | 工作流与 Streamlit | Task 11–12 | Mock 端到端可运行、UI 可下载 | 6.0h |
| 9 | 测试和 GitHub 准备 | Task 13–14 | 全量测试、README、安全检查和截图 | 4.5h |
|  | 风险缓冲 | 全阶段 | 修复依赖、SDK 与平台差异 | 5.5h |
|  | **合计** |  |  | **48.0h** |

## 4. 48 小时时间安排

### Day 1 上午：0–8 小时

- 0:00–3:00：Task 1，项目结构、依赖、配置、日志。
- 3:00–7:00：Task 2，全部 Pydantic 模型和模型测试。
- 7:00–8:00：模型边界复查和 Phase 0–1 提交核验。

### Day 1 下午：8–16 小时

- 8:00–11:30：Task 3，TXT、DOCX、PDF 与统一解析服务。
- 11:30–14:30：Task 4，LLM 协议、Mock、PromptRegistry。
- 14:30–16:00：Task 5 前半，StructuredRunner 的失败—修复状态机。

### Day 1 晚间：16–24 小时

- 16:00–17:00：Task 5 后半，生产适配器及无网络单测。
- 17:00–20:00：Task 6，ResumeExtractor 与 JobRequirementExtractor。
- 20:00–23:00：Task 7，EvidenceMatcher 与 EvidenceValidator。
- 23:00–24:00：运行 Day 1 全量测试、整理独立提交、保留恢复点。

### Day 2 上午：24–32 小时

- 24:00–28:00：Task 8，权重、归一化、硬门槛和推荐等级。
- 28:00–31:00：Task 9，诊断、改写、面试题和建议门面。
- 31:00–32:00：评分重算、边界值和防虚构专项核验。

### Day 2 下午：32–40 小时

- 32:00–35:00：Task 10，最终 Validator、Markdown、JSON。
- 35:00–37:30：Task 11，WorkflowState 与 Orchestrator。
- 37:30–40:00：Task 12 前半，输入、进度、异常和状态管理。

### Day 2 晚间：40–48 小时

- 40:00–41:00：Task 12 后半，结果标签页和下载。
- 41:00–43:30：Task 13，固定夹具、集成测试、Streamlit 烟雾测试。
- 43:30–45:30：Task 14，README、发布检查表、匿名示例和截图。
- 45:30–48:00：缓冲：干净环境安装、全量测试、安全扫描、演示修复。

## 5. 开发依赖关系

```text
Project Config + Errors + Logging
              ↓
      Pydantic Models
              ↓
   ┌──────────┴──────────┐
   ↓                     ↓
Document Parsers      LLM Protocol
                         ↓
                 Mock + PromptRegistry
                         ↓
                StructuredRunner + Provider
                         ↓
               Resume/JD Extractors
                         ↓
               EvidenceMatcher
                         ↓
               EvidenceValidator
                         ↓
              Deterministic Scoring
                         ↓
                 Advice Bundle
                         ↓
             Report/Rewrite Validators
                         ↓
                WorkflowOrchestrator
                         ↓
                  Streamlit UI
                         ↓
          Offline Integration + Docs + QA
```

不存在运行时循环依赖：

- `models` 不导入 parser、LLM、scoring 或 UI。
- `scoring` 只导入模型和 policy。
- `validators` 只导入模型及纯本地规则。
- `reporting` 不导入 UI。
- `workflow` 依赖所有领域接口，但领域模块不反向导入 workflow。
- `app.py` 只导入 config、workflow、reporting 和模型。

## 6. 文件级任务清单

| 文件 | 操作 | 内容 | 对应测试 | 时间 |
|---|---|---|---|---:|
| `pyproject.toml` | 创建 | 包元数据、Python 范围、运行/开发依赖、pytest 与 Ruff 配置 | 安装与收集测试 | 0.5h |
| `.env.example` | 创建 | 安全环境变量样例，无真实值 | `test_config.py` | 0.2h |
| `.gitignore` | 修改 | 增加干净环境验证目录 `.verify-venv/` | `git check-ignore` | 0.1h |
| `src/jobfit/__init__.py` | 创建 | 版本和包导出 | import smoke | 0.1h |
| `src/jobfit/config.py` | 创建 | `Settings`、Mock/生产配置校验 | `test_config.py` | 0.7h |
| `src/jobfit/errors.py` | 创建 | `ErrorCode`、`JobFitError`、安全消息 | `test_config.py` | 0.4h |
| `src/jobfit/logging_config.py` | 创建 | PII/密钥过滤和 request_id | `test_logging.py` | 0.6h |
| `src/jobfit/models/common.py` | 创建 | 公共枚举、StrictModel、运行时输入/进度模型 | `test_models.py` | 0.7h |
| `src/jobfit/models/document.py` | 创建 | 文档、段落、证据、EvidenceRegistry | `test_models.py` | 0.6h |
| `src/jobfit/models/resume.py` | 创建 | 简历结构与事实模型 | `test_models.py` | 0.8h |
| `src/jobfit/models/job.py` | 创建 | JD、要求草稿、最终要求模型 | `test_models.py` | 0.6h |
| `src/jobfit/models/matching.py` | 创建 | 匹配草稿、最终匹配、评分模型 | `test_models.py` | 0.5h |
| `src/jobfit/models/advice.py` | 创建 | 优势、缺口、推荐、改写、面试题 | `test_models.py` | 0.4h |
| `src/jobfit/models/report.py` | 创建 | ValidationResult、AnalysisReport | `test_models.py` | 0.4h |
| `src/jobfit/parsers/base.py` | 创建 | `DocumentParser` 协议与文本规范化 | `test_parsers.py` | 0.4h |
| `src/jobfit/parsers/text.py` | 创建 | TXT/BOM/粘贴文本解析 | `test_parsers.py` | 0.5h |
| `src/jobfit/parsers/docx.py` | 创建 | 段落与表格单元提取 | `test_parsers.py` | 0.7h |
| `src/jobfit/parsers/pdf.py` | 创建 | 页面级文本提取与空文本检测 | `test_parsers.py` | 0.7h |
| `src/jobfit/parsers/service.py` | 创建 | 类型/大小/来源选择和统一路由 | `test_parsers.py` | 0.7h |
| `src/jobfit/llm/protocol.py` | 创建 | 泛型 `LLMClient`、任务、消息和设置 | `test_llm.py` | 0.5h |
| `src/jobfit/llm/mock_adapter.py` | 创建 | 按任务返回固定 Pydantic 响应 | `test_llm.py` | 0.6h |
| `src/jobfit/llm/prompt_registry.py` | 创建 | 版本化 Prompt 文件加载 | `test_llm.py` | 0.5h |
| `src/jobfit/llm/structured_runner.py` | 创建 | Schema 校验、一次修复、一次完整重试 | `test_llm.py` | 1.2h |
| `src/jobfit/llm/openai_adapter.py` | 创建 | 生产结构化输出、错误翻译、用量元数据 | `test_llm.py` | 0.9h |
| `src/jobfit/prompts/resume_extraction.md` | 创建 | 显式事实和证据区间提取提示 | extractor tests | 0.4h |
| `src/jobfit/prompts/job_extraction.md` | 创建 | 原子要求、类型、类别和硬门槛提示 | extractor tests | 0.4h |
| `src/jobfit/prompts/evidence_matching.md` | 创建 | 四态匹配和引用约束提示 | matcher tests | 0.3h |
| `src/jobfit/prompts/advice_bundle.md` | 创建 | 优势、缺口、改写和五题提示 | generator tests | 0.3h |
| `src/jobfit/extractors/resume.py` | 创建 | 草稿校验、精确区间查找、稳定 ID、ResumeProfile | `test_extractors.py` | 1.5h |
| `src/jobfit/extractors/job.py` | 创建 | 要求去重、稳定 ID、source coverage、JobProfile | `test_extractors.py` | 1.5h |
| `src/jobfit/matching/evidence_matcher.py` | 创建 | 批量匹配、状态组装和本地分值覆盖 | `test_matching.py` | 1.8h |
| `src/jobfit/validators/evidence.py` | 创建 | 引文区间、引用完整性和 match 降级 | `test_validators.py` | 1.2h |
| `src/jobfit/scoring/policy.py` | 创建 | 常量、Decimal 因子和阈值 | `test_scoring.py` | 0.8h |
| `src/jobfit/scoring/engine.py` | 创建 | 权重、分数、cap、coverage、recommendation | `test_scoring.py` | 3.2h |
| `src/jobfit/generators/advice_bundle.py` | 创建 | 单次 LLM 调用和 AdviceBundleDraft | `test_generators.py` | 1.0h |
| `src/jobfit/generators/diagnosis.py` | 创建 | 证据排序、最多三项、确定性推荐注入 | `test_generators.py` | 0.7h |
| `src/jobfit/generators/rewrite.py` | 创建 | 可直接采用/需确认分区 | `test_generators.py` | 0.6h |
| `src/jobfit/generators/interview.py` | 创建 | 恰好五题、要求覆盖和风险字段 | `test_generators.py` | 0.7h |
| `src/jobfit/validators/rewrite.py` | 创建 | 数字、专名、角色强化词与 introduced_claims | `test_validators.py` | 1.0h |
| `src/jobfit/validators/report.py` | 创建 | 覆盖、重算、推荐和题数不变量 | `test_validators.py` | 1.0h |
| `src/jobfit/reporting/markdown.py` | 创建 | 12 节 Markdown 报告 | `test_reporting.py` | 0.6h |
| `src/jobfit/reporting/json_export.py` | 创建 | UTF-8、schema_version 1.0 JSON | `test_reporting.py` | 0.4h |
| `src/jobfit/workflow/state.py` | 创建 | WorkflowStage、WorkflowState、进度与证据索引 | `test_workflow.py` | 0.7h |
| `src/jobfit/workflow/orchestrator.py` | 创建 | 阶段顺序、失败策略、最终报告组装 | `test_workflow.py` | 1.8h |
| `app.py` | 创建 | 输入、显式触发、进度、标签页和下载 | `test_streamlit_smoke.py` | 3.5h |
| `tests/conftest.py` | 创建 | 共享工厂、网络禁用和固定 Decimal | 全测试 | 0.4h |
| `tests/unit/test_config.py` | 创建 | 环境变量与缺密钥 | Task 1 | 0.4h |
| `tests/unit/test_logging.py` | 创建 | PII 与密钥不落日志 | Task 1 | 0.3h |
| `tests/unit/test_models.py` | 创建 | 严格模型和非法引用 | Task 2 | 1.0h |
| `tests/unit/test_parsers.py` | 创建 | 四输入与异常 | Task 3 | 1.0h |
| `tests/unit/test_llm.py` | 创建 | Mock、Prompt、修复、生产错误映射 | Task 4–5 | 1.0h |
| `tests/unit/test_extractors.py` | 创建 | 稳定 ID、去重和覆盖率 | Task 6 | 0.8h |
| `tests/unit/test_matching.py` | 创建 | 四态、空证据和分值覆盖 | Task 7 | 0.7h |
| `tests/unit/test_scoring.py` | 创建 | 精确权重、cap 和推荐边界 | Task 8 | 1.3h |
| `tests/unit/test_generators.py` | 创建 | 推荐不可升级、三项/五题 | Task 9 | 0.7h |
| `tests/unit/test_validators.py` | 创建 | 证据、改写、报告不变量 | Task 7/10 | 1.0h |
| `tests/unit/test_reporting.py` | 创建 | Markdown 顺序和 JSON 同源 | Task 10 | 0.5h |
| `tests/unit/test_workflow.py` | 创建 | 状态顺序和安全失败 | Task 11 | 0.6h |
| `tests/integration/test_mock_workflow.py` | 创建 | 完整离线路径和失败夹具 | Task 13 | 1.0h |
| `tests/integration/test_streamlit_smoke.py` | 创建 | 示例加载、标签页和下载 | Task 13 | 0.7h |
| `tests/fixtures/*` | 创建 | 匿名文本、PDF/DOCX、四阶段 JSON、预期结果 | Task 13 | 1.2h |
| `examples/sample_resume.txt` | 创建 | 匿名中文简历 | integration | 0.2h |
| `examples/sample_job_description.txt` | 创建 | 匿名 AI 应用实习 JD | integration | 0.2h |
| `examples/expected_report_example.json` | 创建 | 经同一 Schema 生成的演示结果 | integration | 0.3h |
| `README.md` | 创建 | 安装、演示、架构、评分、隐私和限制 | clean install | 1.0h |
| `docs/github-release-checklist.md` | 创建 | 密钥、隐私、文件、工程和 Git 门禁 | security scan | 0.4h |
| `assets/screenshots/jobfit-agent-demo.png` | 创建 | 本地 Mock 演示截图 | 人工检查 | 0.4h |

时间列中测试文件的时间已计入其对应 Task，总计以 Phase 表为准，不能重复相加。

## 7. 详细实施任务

### Task 1 — Phase 0：项目基础、配置、错误和日志

**Files:**

- Create: `pyproject.toml`
- Create: `.env.example`
- Modify: `.gitignore`
- Create: `src/jobfit/__init__.py`
- Create: `src/jobfit/config.py`
- Create: `src/jobfit/errors.py`
- Create: `src/jobfit/logging_config.py`
- Create: `tests/unit/test_config.py`
- Create: `tests/unit/test_logging.py`

**Interfaces:**

- Produces: `Settings.load() -> Settings`
- Produces: `Settings.validate_runtime(mode: Literal["provider","mock"]) -> None`
- Produces: `ErrorCode`, `JobFitError(code, user_message, recoverable, cause=None)`
- Produces: `configure_logging(level: str) -> None`
- Produces: `SensitiveDataFilter.filter(record: logging.LogRecord) -> bool`
- Produces: `log_event(logger: logging.Logger, event: str, **metadata: object) -> None`

- [ ] **Step 1: 创建虚拟环境和安装项目元数据**

在本机使用 Python 3.12：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

`pyproject.toml` 使用 `src` layout，`requires-python = ">=3.11,<3.13"`。运行依赖范围：

```toml
dependencies = [
  "streamlit>=1.40,<2",
  "pydantic>=2.9,<3",
  "pydantic-settings>=2.5,<3",
  "pypdf>=5,<7",
  "python-docx>=1.1,<2",
  "openai>=1.50,<3",
  "python-dotenv>=1.0,<2",
]

[project.optional-dependencies]
dev = [
  "pytest>=8,<10",
  "pytest-cov>=5,<8",
  "ruff>=0.8,<1",
]

[tool.pytest.ini_options]
addopts = "-ra --strict-markers"
filterwarnings = ["error"]
```

安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Expected: exit code 0；`python -c "import jobfit"` 成功。

在 `.gitignore` 增加 `.verify-venv/`，并运行：

```powershell
git check-ignore -q --no-index .verify-venv/check.txt
```

Expected: exit code 0。

- [ ] **Step 2: 先写配置失败测试**

`tests/unit/test_config.py` 至少包含：

```python
def test_provider_mode_requires_api_key(monkeypatch):
    monkeypatch.setenv("JOBFIT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("JOBFIT_LLM_MODEL", "test-model")
    monkeypatch.delenv("JOBFIT_LLM_API_KEY", raising=False)
    settings = Settings()

    with pytest.raises(JobFitError) as exc:
        settings.validate_runtime("provider")

    assert exc.value.code is ErrorCode.LLM_CREDENTIALS_MISSING


def test_mock_mode_does_not_require_api_key(monkeypatch):
    monkeypatch.setenv("JOBFIT_DEMO_MODE", "true")
    monkeypatch.delenv("JOBFIT_LLM_API_KEY", raising=False)
    Settings().validate_runtime("mock")
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_config.py -q
```

Expected: FAIL，原因是 `jobfit.config` 尚不存在。

- [ ] **Step 3: 实现严格配置合同**

`Settings` 精确字段：

```python
class Settings(BaseSettings):
    llm_provider: str = "openai"
    llm_model: str = ""
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_timeout_seconds: int = Field(default=60, ge=1, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=2)
    max_upload_mb: int = Field(default=10, ge=1, le=10)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    demo_mode: bool = False
```

配置前缀为 `JOBFIT_`，读取 `.env`，SecretStr 的 repr 不得显示实际值。

- [ ] **Step 4: 先写日志脱敏测试再实现 Filter**

Filter 测试输入包含邮箱、手机号、`Authorization: Bearer` 和 API key，断言 caplog 中只保留 `[REDACTED]`。`log_event` 使用字段白名单，只接受阶段、耗时、状态、供应商、模型别名、token usage、request_id、错误码、字符数、文件类型和哈希前 8 位；测试传入 `resume_text` 和 `person_name` 时必须丢弃这两个字段，避免依赖无法可靠识别任意姓名的正则。

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_config.py tests/unit/test_logging.py -q
```

Expected: 全部 PASS。

- [ ] **Step 5: 静态检查并提交**

```powershell
.\.venv\Scripts\python.exe -m ruff check src/jobfit/config.py src/jobfit/errors.py src/jobfit/logging_config.py tests/unit/test_config.py tests/unit/test_logging.py
git diff --check
git add pyproject.toml .env.example .gitignore src/jobfit tests/unit/test_config.py tests/unit/test_logging.py
git commit -m "chore: initialize project structure and configuration"
```

Commit gate: 配置和日志测试通过；`.env` 未被跟踪；不提交 `.venv/`。

### Task 2 — Phase 1：核心 Pydantic 模型

**Files:**

- Create: `src/jobfit/models/common.py`
- Create: `src/jobfit/models/document.py`
- Create: `src/jobfit/models/resume.py`
- Create: `src/jobfit/models/job.py`
- Create: `src/jobfit/models/matching.py`
- Create: `src/jobfit/models/advice.py`
- Create: `src/jobfit/models/report.py`
- Create: `tests/unit/test_models.py`

**Interfaces:**

- Produces all enums from spec section 7.1.
- Produces `StrictModel` with `ConfigDict(extra="forbid", validate_assignment=True)`.
- Produces final models and internal transport models: `ResumeExtractionDraft`, `JobExtractionDraft`, `JobRequirementDraft`, `RequirementMatchDraft`, `AdviceBundleDraft`.
- Produces runtime-only `EvidenceRegistry.get(evidence_id: str) -> EvidenceItem`.

- [ ] **Step 1: 写枚举和 extra 字段失败测试**

```python
def test_models_forbid_extra_fields():
    with pytest.raises(ValidationError):
        TextSegment(
            segment_id="seg-001",
            text="Python",
            start_char=0,
            end_char=6,
            unexpected=True,
        )


def test_implicit_requirement_cannot_be_mandatory():
    payload = make_requirement_draft(
        requirement_type=RequirementType.IMPLICIT,
        mandatory=True,
    )
    with pytest.raises(ValidationError):
        JobRequirementDraft.model_validate(payload)
```

Expected first run: FAIL with import error.

- [ ] **Step 2: 实现 common.py 和 document.py**

`common.py` 定义所有枚举、`AnalysisRequest`、`UploadedDocumentInput`、`ProgressEvent`。`document.py` 定义：

```python
class EvidenceRegistry:
    def __init__(self, items: Iterable[EvidenceItem]) -> None: ...
    def get(self, evidence_id: str) -> EvidenceItem: ...
    def require_many(self, evidence_ids: Sequence[str]) -> list[EvidenceItem]: ...
```

`TextSegment` model validator 必须检查 `0 <= start_char < end_char`。EvidenceItem 检查 confidence 在 0–1。

- [ ] **Step 3: 实现 resume.py 和 job.py**

按架构逐字段实现。集合字段统一 `Field(default_factory=list)`。JobRequirementDraft validator 强制：

```text
implicit → mandatory=false
implicit → hard_condition_kind=none
implicit → importance ∈ {medium, low}
source_start_char < source_end_char
```

- [ ] **Step 4: 实现 matching.py、advice.py、report.py**

`ResumeExtractionDraft` 包装带 quote/start/end 的简历事实候选；`JobExtractionDraft` 包装岗位摘要、关键词和 `JobRequirementDraft` 列表。`RequirementMatchDraft` 不含 `match_score`。`ApplicationRecommendation.level` 必填但只允许评分引擎或组装器传入。`AnalysisReport.interview_questions` 使用长度恰好 5 的字段约束；strengths/gaps 最大 3。

- [ ] **Step 5: 验证引用和序列化测试**

增加测试：

```python
def test_analysis_report_requires_five_questions(valid_report_payload):
    valid_report_payload["interview_questions"] = valid_report_payload["interview_questions"][:4]
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(valid_report_payload)


def test_secret_or_bytes_do_not_appear_in_report_schema():
    schema = AnalysisReport.model_json_schema()
    rendered = json.dumps(schema)
    assert "llm_api_key" not in rendered
    assert "UploadedDocumentInput" not in rendered
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_models.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add src/jobfit/models tests/unit/test_models.py
git commit -m "feat: add core data models"
```

### Task 3 — Phase 2：文档解析管线

**Files:**

- Create: `src/jobfit/parsers/base.py`
- Create: `src/jobfit/parsers/text.py`
- Create: `src/jobfit/parsers/docx.py`
- Create: `src/jobfit/parsers/pdf.py`
- Create: `src/jobfit/parsers/service.py`
- Create: `tests/unit/test_parsers.py`
- Create: `tests/fixtures/sample_resume.txt`
- Create: `tests/fixtures/sample_resume.docx`
- Create: `tests/fixtures/sample_resume.pdf`

**Interfaces:**

- Produces `normalize_text(raw: str) -> tuple[str, list[TextSegment]]`
- Produces `TextDocumentParser.parse(content: bytes, filename: str) -> DocumentContent`
- Produces `DocxDocumentParser.parse(content: bytes, filename: str) -> DocumentContent`
- Produces `PdfDocumentParser.parse(content: bytes, filename: str) -> DocumentContent`
- Produces `DocumentParserService.parse_request(request: AnalysisRequest, selected_source: Literal["file","text"]) -> DocumentContent`

- [ ] **Step 1: 创建匿名三格式夹具**

三个夹具表达同一份虚构简历，邮箱只使用 `lin.x@example.com`，不含电话和地址。PDF 必须含真实文本层；DOCX 同时含段落和两列表格。

- [ ] **Step 2: 先写成功和失败测试**

测试名至少包括：

```text
test_txt_parser_handles_utf8_bom
test_docx_parser_reads_paragraphs_and_tables
test_pdf_parser_preserves_page_numbers
test_empty_file_raises_input_empty
test_scanned_pdf_raises_pdf_text_empty
test_unsupported_extension_raises_file_type_unsupported
test_mime_extension_mismatch_is_rejected
test_pasted_text_is_selected_explicitly
test_both_sources_without_selection_is_rejected
test_file_over_ten_mib_is_rejected_before_parse
```

Run expected FAIL：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_parsers.py -q
```

- [ ] **Step 3: 实现规范化和 TXT**

规范化规则固定为 CRLF/CR→LF、行尾空格移除、连续空行最多两个；不得改变正文字符内容。DocumentContent 使用 SHA-256，日志只允许哈希前 8 位。

- [ ] **Step 4: 实现 DOCX 与 PDF**

DOCX 顺序为段落出现顺序后接表格逐行单元格；每个单元格生成 segment。PDF 每页生成 page_number，从 1 开始；全部页面 trim 后为空时抛 `PDF_TEXT_EMPTY`。

- [ ] **Step 5: 实现统一 Service 并运行测试**

Service 在打开解析器前检查大小、来源选择、扩展名与允许 MIME。捕获第三方异常并转换为 `DOCUMENT_PARSE_FAILED`，cause 只写内部日志类型。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_parsers.py -q
.\.venv\Scripts\python.exe -m ruff check src/jobfit/parsers tests/unit/test_parsers.py
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add src/jobfit/parsers tests/unit/test_parsers.py tests/fixtures/sample_resume.*
git commit -m "feat: add document parsing pipeline"
```

### Task 4 — Phase 3A：LLM 协议、Mock 和 PromptRegistry

**Files:**

- Create: `src/jobfit/llm/protocol.py`
- Create: `src/jobfit/llm/mock_adapter.py`
- Create: `src/jobfit/llm/prompt_registry.py`
- Create: `src/jobfit/prompts/resume_extraction.md`
- Create: `src/jobfit/prompts/job_extraction.md`
- Create: `src/jobfit/prompts/evidence_matching.md`
- Create: `src/jobfit/prompts/advice_bundle.md`
- Create: `tests/unit/test_llm.py`

**Interfaces:**

```python
T = TypeVar("T", bound=BaseModel)

class LLMTask(StrEnum):
    EXTRACT_RESUME = "extract_resume"
    EXTRACT_JOB = "extract_job"
    MATCH_EVIDENCE = "match_evidence"
    GENERATE_ADVICE_BUNDLE = "generate_advice_bundle"

class LLMMessage(StrictModel):
    role: Literal["system", "user"]
    content: str

class LLMSettings(StrictModel):
    model: str
    timeout_seconds: int = 60
    max_retries: int = 2
    temperature: float = 0.0

class PromptTemplate(StrictModel):
    task_name: str
    version: str
    system_text: str
    user_template: str

class LLMClient(Protocol):
    def generate_structured(
        self,
        *,
        task: LLMTask,
        response_model: type[T],
        messages: Sequence[LLMMessage],
        settings: LLMSettings,
    ) -> T: ...
```

`PromptRegistry.load(task_name: str, version: str) -> PromptTemplate`。

- [ ] **Step 1: 写 Mock 和 Prompt 失败测试**

```python
def test_mock_client_returns_validated_model(fixture_dir):
    client = MockLLMClient.from_directory(fixture_dir)
    result = client.generate_structured(
        task=LLMTask.EXTRACT_JOB,
        response_model=JobExtractionDraft,
        messages=[],
        settings=LLMSettings(model="mock", timeout_seconds=1),
    )
    assert isinstance(result, JobExtractionDraft)


def test_prompt_registry_rejects_unknown_version(prompt_root):
    with pytest.raises(JobFitError) as exc:
        PromptRegistry(prompt_root).load("extract_job", "9.9")
    assert exc.value.code is ErrorCode.PROMPT_NOT_FOUND
```

- [ ] **Step 2: 实现协议和 Mock**

Mock 按 `LLMTask.value + ".json"` 查找，必须经过 response_model.model_validate；文件缺失或无效分别映射 `MOCK_FIXTURE_MISSING` 和 `LLM_SCHEMA_INVALID`。Mock 不导入 OpenAI SDK，不读取 API key。

- [ ] **Step 3: 实现 PromptRegistry 和四个提示词**

每个 Markdown 文件头固定：

```yaml
---
task: extract_resume
version: "1.0"
---
```

正文必须包含输入边界、禁止新增事实、允许枚举、证据区间、unknown 语义和仅 JSON 输出要求。PromptRegistry 使用本地轻量解析读取固定四行文件头，不引入 YAML 依赖，并校验 task/version 与文件头一致。

- [ ] **Step 4: 运行无网络测试**

在 `tests/conftest.py` 增加自动 fixture，将 `socket.socket.connect` 替换为抛异常；仅带 `@pytest.mark.live_api` 的测试可解除，普通套件中不创建 live_api 测试。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_llm.py -q
```

Expected: PASS，且网络禁用 fixture 未触发失败。

- [ ] **Step 5: 提交**

```powershell
git add src/jobfit/llm/protocol.py src/jobfit/llm/mock_adapter.py src/jobfit/llm/prompt_registry.py src/jobfit/prompts tests/unit/test_llm.py tests/conftest.py
git commit -m "feat: add llm protocol mock provider and prompts"
```

### Task 5 — Phase 3B：结构修复运行器和生产适配器

**Files:**

- Create: `src/jobfit/llm/structured_runner.py`
- Create: `src/jobfit/llm/openai_adapter.py`
- Modify: `tests/unit/test_llm.py`

**Interfaces:**

- Produces `StructuredRunner.run(task, response_model, messages, settings) -> T`
- Produces `OpenAIAdapter.generate_structured(...) -> T`
- Translates provider failures to `LLM_AUTH_FAILED`, `LLM_TRANSIENT_ERROR`, `LLM_SCHEMA_INVALID`

- [ ] **Step 1: 写三段失败路径测试**

使用 `ScriptedFakeClient` 返回序列：

```python
def test_runner_repairs_once_then_succeeds():
    client = ScriptedFakeClient([
        '{"wrong": true}',
        VALID_JOB_JSON,
    ])
    result = StructuredRunner(client).run(...)
    assert result.title == "AI应用开发实习生"
    assert client.calls == 2


def test_runner_stops_after_repair_and_one_full_retry():
    client = ScriptedFakeClient([
        '{"wrong": 1}',
        '{"wrong": 2}',
        '{"wrong": 3}',
    ])
    with pytest.raises(JobFitError) as exc:
        StructuredRunner(client).run(...)
    assert exc.value.code is ErrorCode.LLM_SCHEMA_INVALID
    assert client.calls == 3
```

认证错误必须调用一次；429/5xx/timeout 最多按 Settings 进行两次网络尝试。

- [ ] **Step 2: 实现 StructuredRunner**

状态顺序固定：

```text
initial → repair → full_retry → fail
```

repair 消息只含原始无效输出、精简 Pydantic 错误和相同 JSON Schema，不含 Python 栈。完整重试重新使用原 messages。

- [ ] **Step 3: 实现 OpenAIAdapter**

使用官方 SDK 客户端注入构造：

```python
class OpenAIAdapter:
    def __init__(self, client: OpenAI, settings: Settings) -> None: ...
```

调用供应商结构化 parse 接口，模型、base URL、timeout 从 Settings 读取；业务模块不得 import `openai`。单测使用 fake client，检查参数但不联网。

- [ ] **Step 4: 测试和提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_llm.py -q
git add src/jobfit/llm/structured_runner.py src/jobfit/llm/openai_adapter.py tests/unit/test_llm.py
git commit -m "feat: add structured llm runner and provider adapter"
```

### Task 6 — Phase 4：简历与 JD 结构化提取

**Files:**

- Create: `src/jobfit/extractors/resume.py`
- Create: `src/jobfit/extractors/job.py`
- Create: `tests/unit/test_extractors.py`
- Create: `tests/fixtures/llm_responses/extract_resume.json`
- Create: `tests/fixtures/llm_responses/extract_job.json`

**Interfaces:**

- `ResumeExtractor.extract(document: DocumentContent) -> tuple[ResumeProfile, EvidenceRegistry]`
- `JobRequirementExtractor.extract(jd_text: str, title: str | None, company: str | None) -> JobProfile`

- [ ] **Step 1: 写稳定 ID 和错误区间测试**

```python
def test_resume_ids_are_stable_for_same_draft(document, runner):
    first, first_registry = ResumeExtractor(runner).extract(document)
    second, second_registry = ResumeExtractor(runner).extract(document)
    assert first.model_dump() == second.model_dump()
    assert first_registry.ids() == second_registry.ids()


def test_job_extractor_rejects_source_text_not_at_range(job_extractor):
    with pytest.raises(JobFitError) as exc:
        job_extractor.extract("要求熟悉 Python", None, None)
    assert exc.value.code is ErrorCode.EVIDENCE_INVALID
```

- [ ] **Step 2: 实现 ResumeExtractor**

LLM draft 中每个事实候选必须携带 quote/start/end；代码验证 `normalized_text[start:end] == quote`，按 start/end/normalized text 排序，生成 `ev-001`、`edu-001`、`exp-001`、`proj-001` 等稳定 ID。无效候选不得进入 ResumeProfile。

- [ ] **Step 3: 实现 JobRequirementExtractor**

用户传入 title/company 非空时优先。要求按 source_start/source_end/normalized_key 排序，去重 normalized_key；生成 `req-001`。source coverage ratio 按规格公式本地计算。重复项保留一项并写入 deduplication_notes。

- [ ] **Step 4: 失败处理测试**

覆盖空要求集合、隐性要求违规、超过 JD 30,000 字符、Schema 修复失败。不得返回部分 JobProfile。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_extractors.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add src/jobfit/extractors tests/unit/test_extractors.py tests/fixtures/llm_responses/extract_resume.json tests/fixtures/llm_responses/extract_job.json
git commit -m "feat: add structured resume and job extraction"
```

### Task 7 — Phase 5A：证据匹配与证据校验

**Files:**

- Create: `src/jobfit/matching/evidence_matcher.py`
- Create: `src/jobfit/validators/evidence.py`
- Create: `tests/unit/test_matching.py`
- Create: `tests/unit/test_validators.py`
- Create: `tests/fixtures/llm_responses/match_evidence.json`

**Interfaces:**

- `EvidenceMatcher.match(resume, job, document, registry) -> list[RequirementMatch]`
- `assemble_match(draft: RequirementMatchDraft) -> RequirementMatch`
- `EvidenceValidator.validate_matches(document, registry, requirements, matches) -> tuple[list[RequirementMatch], ValidationResult]`

- [ ] **Step 1: 写四态和覆盖失败测试**

参数化断言：

```python
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (MatchStatus.MATCHED, Decimal("1.0")),
        (MatchStatus.PARTIAL, Decimal("0.6")),
        (MatchStatus.NOT_MATCHED, Decimal("0.0")),
        (MatchStatus.UNKNOWN, Decimal("0.0")),
    ],
)
def test_match_score_is_overwritten_by_code(status, expected):
    assert assemble_match(make_draft(status=status)).match_score == expected
```

另测 requirement ID 集合不一致、matched 无 direct、partial 无证据、quote 区间错误和 JD 证据冒充简历证据。

- [ ] **Step 2: 实现 EvidenceMatcher**

将全部 requirements 一次发送给模型，要求每个 ID 恰好一次。组装时忽略草稿中的任何分数字段。无简历证据时使用 `unknown`；只有简历明确冲突才允许 `not_matched`。

- [ ] **Step 3: 实现 EvidenceValidator**

规则：

```text
matched + 无direct → unknown + EVIDENCE_REQUIRED
partial + 无证据 → unknown + EVIDENCE_REQUIRED
非法字符区间 → 删除证据 + EVIDENCE_INVALID
要求ID缺失或重复 → error，整阶段失败
```

Matcher 修复只允许一次；修复仍有 error 时抛 `EVIDENCE_INVALID`，不得进入 scoring。

- [ ] **Step 4: 运行测试和提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_matching.py tests/unit/test_validators.py -q
git add src/jobfit/matching src/jobfit/validators/evidence.py tests/unit/test_matching.py tests/unit/test_validators.py tests/fixtures/llm_responses/match_evidence.json
git commit -m "feat: add evidence matching and grounding validation"
```

### Task 8 — Phase 5B：确定性评分引擎

**Files:**

- Create: `src/jobfit/scoring/policy.py`
- Create: `src/jobfit/scoring/engine.py`
- Create: `tests/unit/test_scoring.py`

**Interfaces:**

```python
class ScoringEngine:
    def score(
        self,
        requirements: Sequence[JobRequirement],
        matches: Sequence[RequirementMatch],
    ) -> MatchScoreSummary: ...
```

- [ ] **Step 1: 先写 policy 常量测试**

明确断言：

```python
assert sum(BASE_POINTS.values(), Decimal("0")) == Decimal("100")
assert STATUS_VALUES[MatchStatus.PARTIAL] == Decimal("0.6")
assert IMPORTANCE_FACTORS[Importance.CRITICAL] == Decimal("4")
assert TYPE_FACTORS[RequirementType.IMPLICIT] == Decimal("0.50")
assert MANDATORY_MULTIPLIER == Decimal("1.25")
```

- [ ] **Step 2: 写权重和缺失维度测试**

构造只有 technical_skill 和 experience_project 的要求，断言两个有效维度各 50.00；同维度内按 factor 比例分配，最后 requirement_id 字典序末项吸收差额，总和精确 100.00。

- [ ] **Step 3: 写隐性要求上限测试**

构造隐性要求初始权重超过 10，断言压缩后隐性权重和为 10.00，释放分值按非隐性现有比例分配。

- [ ] **Step 4: 写硬门槛和推荐边界测试**

至少覆盖：

```text
confirmed hard blocker → cap 49, not_priority
unknown hard blocker → cap 69, recommendation ≤ try_apply
critical mandatory not_matched → cap 69
two high mandatory not_matched → cap 69
score 80 + mandatory .85 + strong .70 → priority_apply
score 68 + mandatory .65 → optimize_then_apply
score 50 → try_apply
score 49.99 → not_priority
```

- [ ] **Step 5: 实现纯函数 policy 和 engine**

全部 Decimal 常量使用字符串构造。计算顺序：

```text
validate one-to-one IDs
→ active dimensions
→ effective points
→ priority factors
→ per-dimension weights
→ implicit cap redistribution
→ status earnings
→ dimension summaries
→ mandatory/strong evidence coverage
→ score cap
→ deterministic recommendation
```

`scoring/` 不得导入任何 LLM 或 Streamlit 模块。

- [ ] **Step 6: 精确重算与提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_scoring.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_models.py tests/unit/test_matching.py tests/unit/test_scoring.py -q
git add src/jobfit/scoring tests/unit/test_scoring.py
git commit -m "feat: add deterministic scoring engine"
```

### Task 9 — Phase 6：诊断、改写和面试问题

**Files:**

- Create: `src/jobfit/generators/advice_bundle.py`
- Create: `src/jobfit/generators/diagnosis.py`
- Create: `src/jobfit/generators/rewrite.py`
- Create: `src/jobfit/generators/interview.py`
- Create: `tests/unit/test_generators.py`
- Create: `tests/fixtures/llm_responses/generate_advice_bundle.json`

**Interfaces:**

- `AdviceBundleGenerator.generate(resume, job, matches, score) -> AdviceBundleDraft`
- `finalize_diagnosis(draft, score, registry) -> tuple[list[StrengthItem], list[GapItem], ApplicationRecommendation]`
- `partition_rewrites(items, registry) -> tuple[list[RewriteSuggestion], list[RewriteSuggestion]]`
- `finalize_questions(items, requirements) -> list[InterviewQuestion]`

- [ ] **Step 1: 写“模型不能升级推荐”测试**

```python
def test_llm_cannot_upgrade_recommendation(score_summary, advice_draft):
    score_summary.recommendation_level = RecommendationLevel.TRY_APPLY
    advice_draft.recommendation_reasoning = ["建议优先投递"]

    _, _, recommendation = finalize_diagnosis(
        advice_draft, score_summary, evidence_registry
    )

    assert recommendation.level is RecommendationLevel.TRY_APPLY
```

- [ ] **Step 2: 写三项与五题约束测试**

优势和缺口按关联 requirement weight、risk、confidence 排序，最多三项；没有足够证据时少于三项并加入 limitation，不能补造。面试题去重后必须恰好五项；不足时本阶段失败并请求一次结构修复。

- [ ] **Step 3: 实现单次 AdviceBundle 调用**

输入只含已校验事实、requirement/match、score summary；不传完整本地路径和密钥。提示中明确推荐等级只供解释，不可生成替代等级。

- [ ] **Step 4: 实现规则后处理**

Gap 使用四种 remediability。Rewrite 的 `introduced_claims` 非空时进入需确认列表。InterviewQuestion 优先覆盖高权重要求和主要缺口，每题保留 requirement IDs。

- [ ] **Step 5: 运行测试和提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_generators.py -q
git add src/jobfit/generators tests/unit/test_generators.py tests/fixtures/llm_responses/generate_advice_bundle.json
git commit -m "feat: add diagnosis rewrite and interview generation"
```

### Task 10 — Phase 7：防虚构 Validator 与报告导出

**Files:**

- Create: `src/jobfit/validators/rewrite.py`
- Create: `src/jobfit/validators/report.py`
- Create: `src/jobfit/reporting/markdown.py`
- Create: `src/jobfit/reporting/json_export.py`
- Modify: `tests/unit/test_validators.py`
- Create: `tests/unit/test_reporting.py`

**Interfaces:**

- `RewriteValidator.validate(suggestion, registry) -> ValidationResult`
- `ReportValidator.validate(report, document, registry) -> ValidationResult`
- `render_markdown(report: AnalysisReport) -> str`
- `render_json(report: AnalysisReport) -> bytes`

- [ ] **Step 1: 写无依据改写失败测试**

参数化加入原证据不存在的数字、百分比、货币、日期、工具名、组织名、职位等级和高风险词。期望 issue codes 分别可定位；存在 error 的建议不进入可直接采用列表。

- [ ] **Step 2: 写报告不变量测试**

逐项破坏 requirements/matches ID 集合、权重和、raw score、cap、recommendation、五题、证据 ID，断言 `valid=False` 且含稳定 error code。

- [ ] **Step 3: 实现 RewriteValidator 和 ReportValidator**

数字使用正则提取并按规范化字符串比较；高风险词表固定在模块常量中。ReportValidator 调用 ScoringEngine 重算而不信任报告原值。只有零 error 时才允许下载。

- [ ] **Step 4: 写 Markdown 和 JSON 测试**

Markdown 断言 12 节顺序、unknown 标准措辞和免责声明。JSON 断言：

```python
payload = json.loads(render_json(report).decode("utf-8"))
assert payload["schema_version"] == "1.0"
assert payload["score_summary"]["final_score"] == "76.40"
assert "llm_api_key" not in json.dumps(payload)
```

- [ ] **Step 5: 实现 Renderer 并提交**

Renderer 只读 AnalysisReport，不计算分数或修改 recommendation。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_validators.py tests/unit/test_reporting.py -q
git add src/jobfit/validators src/jobfit/reporting tests/unit/test_validators.py tests/unit/test_reporting.py
git commit -m "feat: add report validation and exports"
```

### Task 11 — Phase 8A：WorkflowState 与 Orchestrator

**Files:**

- Create: `src/jobfit/workflow/state.py`
- Create: `src/jobfit/workflow/orchestrator.py`
- Create: `tests/unit/test_workflow.py`

**Interfaces:**

- `WorkflowState` 保存 request、stage、中间模型、EvidenceRegistry、错误和最终报告。
- `ProgressSink.publish(event: ProgressEvent) -> None`
- `WorkflowOrchestrator.run(request: AnalysisRequest, progress: ProgressSink) -> AnalysisReport`

- [ ] **Step 1: 写状态顺序测试**

使用 fake modules 记录调用，断言顺序完全为：

```text
VALIDATING_INPUT
PARSING_RESUME
EXTRACTING_RESUME
EXTRACTING_JOB
MATCHING_EVIDENCE
VALIDATING_MATCHES
SCORING
GENERATING_ADVICE
VALIDATING_REPORT
COMPLETED
```

- [ ] **Step 2: 写安全失败测试**

让 parser、runner、validator、scorer 分别抛 JobFitError，断言 stage 为 FAILED、ProgressEvent 不含原文、报告未返回。recoverable 只由错误定义决定。

- [ ] **Step 3: 实现 Orchestrator**

每阶段只调用一个公开接口；通过构造函数注入依赖。不得在 orchestrator 内复制评分、解析或验证逻辑。最终 ValidationResult.valid 为 false 时抛 `REPORT_VALIDATION_FAILED`。

- [ ] **Step 4: 测试和提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_workflow.py -q
git add src/jobfit/workflow tests/unit/test_workflow.py
git commit -m "feat: add agent workflow orchestrator"
```

### Task 12 — Phase 8B：Streamlit 单页界面

**Files:**

- Create: `app.py`
- Create: `tests/integration/test_streamlit_smoke.py`

**Interfaces:**

- UI 只创建 AnalysisRequest、调用 orchestrator、渲染 AnalysisReport、调用 reporting 下载。
- `st.session_state` 键固定：`request_id`, `parsed_preview`, `analysis_report`, `analysis_error`, `analysis_running`, `selected_source`, `demo_mode`。

- [ ] **Step 1: 写 AppTest 启动失败测试**

```python
def test_app_starts_without_api_key_in_mock_mode(monkeypatch):
    monkeypatch.setenv("JOBFIT_DEMO_MODE", "true")
    app = AppTest.from_file("app.py").run()
    assert not app.exception
    assert app.title[0].value == "JobFit Agent"
```

- [ ] **Step 2: 实现输入和显式触发**

页面包含文件上传、粘贴文本、来源单选、文本预览、岗位名、公司名、JD、示例按钮和开始分析按钮。上传或文本变化不得自动触发 LLM。

- [ ] **Step 3: 实现进度与状态去重**

点击后创建 request_id；同一 request_id 正在运行时禁用按钮。ProgressSink 映射中文阶段文字，不显示内部推理或模型原始 JSON。

- [ ] **Step 4: 实现五个结果标签页和下载**

标签页：

```text
综合结论
逐项匹配
简历优化
面试准备
结构化数据
```

ValidationResult.valid 为 true 才显示 Markdown/JSON 下载按钮。错误区显示用户安全消息、request_id 和粘贴文本兜底建议。

- [ ] **Step 5: AppTest 与本地烟雾测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_streamlit_smoke.py -q
.\.venv\Scripts\python.exe -m streamlit run app.py --server.headless true
```

Expected: 测试 PASS；本地服务启动，无 traceback。完成手动查看后正常停止进程。

- [ ] **Step 6: 提交**

```powershell
git add app.py tests/integration/test_streamlit_smoke.py
git commit -m "feat: add Streamlit analysis interface"
```

### Task 13 — Phase 9A：匿名夹具和离线端到端测试

**Files:**

- Create/complete: `tests/conftest.py`
- Create: `tests/integration/test_mock_workflow.py`
- Create: `tests/fixtures/sample_job_description.txt`
- Create: `tests/fixtures/llm_responses/*.json`
- Create: `tests/fixtures/expected/analysis_report.json`
- Create: `examples/sample_resume.txt`
- Create: `examples/sample_job_description.txt`
- Create: `examples/expected_report_example.json`

**Interfaces:**

- `build_mock_orchestrator(fixture_root: Path) -> WorkflowOrchestrator`
- 完整离线路径输出可验证 AnalysisReport。

- [ ] **Step 1: 固定匿名数据**

示例只使用虚构组织“星河实验室”和 `example.com` 邮箱。所有四阶段 JSON 与同一文本证据区间一致。预期分数使用 ScoringEngine 生成后人工复算一次，不手写猜测值。

- [ ] **Step 2: 写端到端成功测试**

```python
def test_mock_workflow_is_deterministic(mock_orchestrator, sample_request):
    first = mock_orchestrator.run(sample_request, RecordingProgressSink())
    second = mock_orchestrator.run(sample_request, RecordingProgressSink())
    assert first.score_summary == second.score_summary
    assert len(first.interview_questions) == 5
    assert first.validation.valid is True
```

- [ ] **Step 3: 写端到端失败测试**

固定失败夹具覆盖 invalid schema、invalid evidence、hard blocker unknown、rewrite unsupported claim。断言稳定错误码或确定性 cap，不允许前端崩溃。

- [ ] **Step 4: 全量测试和覆盖率**

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=jobfit --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check .
git diff --check
```

Gate:

- 测试 0 failures；
- scoring、validators、parsers 分支覆盖率各不低于 90%；
- 项目总覆盖率不低于 80%；
- 普通测试没有网络连接；
- 无 pytest warning 被忽略。

- [ ] **Step 5: 提交**

```powershell
git add tests examples
git commit -m "test: add offline integration and UI tests"
```

### Task 14 — Phase 9B：README、截图和发布安全门禁

**Files:**

- Create: `README.md`
- Create: `docs/github-release-checklist.md`
- Create: `assets/screenshots/jobfit-agent-demo.png`
- Modify only if verification proves necessary: `.gitignore`

**Interfaces:**

- README 成为全新环境的唯一启动入口。
- 发布检查表必须逐项记录命令和实际结果。

- [ ] **Step 1: 编写 README**

按以下固定顺序：

```text
项目名称和一句话简介
核心功能
产品截图
Agent工作流
系统架构
技术栈
项目目录
安装步骤
环境变量
Mock启动
生产模型启动
示例输入输出
测试命令
确定性评分
证据与防虚构
隐私说明
限制
后续方向
免责声明
```

Windows 命令和通用 `python` 命令同时给出；不包含本机 Codex Python 绝对路径。

- [ ] **Step 2: 捕获本地 Mock 截图**

以 Mock 模式启动，在本地浏览器完成匿名示例分析，截图必须显示综合分、维度、证据表和隐私提示，不显示真实用户名、本地路径或 API 配置。

- [ ] **Step 3: 创建发布检查表**

检查表包含密钥、PII、缓存、构建产物、安装、启动、测试、Git、远程授权九组门禁。许可证不在用户确认前创建。

- [ ] **Step 4: 干净环境安装和安全检查**

使用新临时虚拟环境验证：

```powershell
python -m venv .verify-venv
.\.verify-venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.verify-venv\Scripts\python.exe -m pytest
```

随后验证：

```powershell
git status --ignored --short
git grep -n -I -E "(sk-[A-Za-z0-9_-]{16,}|Authorization:|password[[:space:]]*=|api[_-]?key[[:space:]]*=)"
git ls-files
git log --oneline --decorate
git diff --check
```

`.verify-venv/` 必须命中 Task 1 写入的忽略规则，不能提交。任何扫描命中均人工判断，真实密钥或 PII 命中直接阻止发布。

- [ ] **Step 5: 文档提交**

```powershell
git add README.md docs/github-release-checklist.md assets/screenshots/jobfit-agent-demo.png
git commit -m "docs: complete README and release checklist"
```

最终 gate：`git status --short` 为空，分支 main，remote 仍为空。停止并等待用户单独授权 GitHub 操作。

## 8. Git Commit 计划

| 序号 | Commit | 稳定阶段门槛 |
|---:|---|---|
| 1 | `chore: initialize project structure and configuration` | 安装、配置和日志测试通过 |
| 2 | `feat: add core data models` | 全部严格 Schema 测试通过 |
| 3 | `feat: add document parsing pipeline` | TXT/DOCX/PDF 和异常测试通过 |
| 4 | `feat: add llm protocol mock provider and prompts` | 无网络 Mock 与 Prompt 测试通过 |
| 5 | `feat: add structured llm runner and provider adapter` | 修复状态机和错误映射测试通过 |
| 6 | `feat: add structured resume and job extraction` | 稳定 ID、区间、去重测试通过 |
| 7 | `feat: add evidence matching and grounding validation` | 一对一覆盖和证据规则通过 |
| 8 | `feat: add deterministic scoring engine` | 精确 Decimal、cap、推荐边界通过 |
| 9 | `feat: add diagnosis rewrite and interview generation` | 推荐不可升级、防虚构前置规则通过 |
| 10 | `feat: add report validation and exports` | 报告重算、Markdown、JSON 通过 |
| 11 | `feat: add agent workflow orchestrator` | 状态顺序和失败策略通过 |
| 12 | `feat: add Streamlit analysis interface` | AppTest 和本地启动通过 |
| 13 | `test: add offline integration and UI tests` | 全量离线测试和覆盖率门槛通过 |
| 14 | `docs: complete README and release checklist` | 干净安装、安全检查和截图通过 |

规则：

- 每个提交只包含其任务文件。
- 测试失败、格式检查失败或存在未解释的敏感扫描命中时不得提交。
- 不使用 `--no-verify`。
- 不 squash 已经形成的真实阶段历史。
- 修复仅在真实缺陷出现时使用 `fix:`，不预造修复提交。
- `.env`、虚拟环境、日志、上传文件、临时报告和模型缓存永不提交。

## 9. 测试计划

### 9.1 测试金字塔

| 层级 | 范围 | 是否联网 | 关键断言 |
|---|---|---|---|
| 模型单测 | Pydantic 字段、枚举、引用 | 否 | extra 禁止、字段范围、五题 |
| 纯函数单测 | scoring、validator、renderer | 否 | Decimal 精确、可重算、防虚构 |
| 适配器单测 | parser、LLM、prompt | 否 | 错误翻译、有限重试、Mock |
| 工作流单测 | orchestrator fake modules | 否 | 状态顺序、安全失败 |
| 离线集成 | 全 Mock 主流程 | 否 | 相同输入同分、报告有效 |
| UI 烟雾 | Streamlit AppTest | 否 | 输入、示例、标签页、下载 |
| 人工演示 | 本地 Mock 页面 | 否 | 视觉与操作闭环 |
| 可选生产烟雾 | 用户配置模型 | 是 | 仅用户主动运行，不进普通测试 |

### 9.2 核心边界用例

- 0 字节、只有空白、BOM、破损文件、超限、MIME 冲突。
- PDF 有文本、无文本、多页；DOCX 段落和表格。
- invalid enum、extra 字段、缺 evidence_id、重复 requirement_id。
- 四态映射、只有一个 active 维度、全部六维、隐性要求超 10。
- 49/50、67.99/68、69/80 等推荐边界。
- confirmed 与 unknown hard blocker。
- matched 无 direct、partial 无证据、错误 quote。
- 改写新增数字、工具、组织、职责级别和强化词。
- 面试题 4、5、6 条及重复问题。
- Markdown 特殊字符与中英文；JSON Decimal 字符串。
- 缺 API key、Mock 无 key、429、认证、超时、invalid schema。
- Streamlit 重跑不重复调用。

### 9.3 每次提交最低验证

```powershell
.\.venv\Scripts\python.exe -m pytest <本任务测试文件> -q
.\.venv\Scripts\python.exe -m ruff check <本任务文件>
git diff --check
```

Day 1、Day 2 和最终提交分别运行完整：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

## 10. 风险和降级方案

| 风险 | 概率 | 影响 | 预防 | 降级 |
|---|---|---|---|---|
| OpenAI SDK 结构化接口与预期不同 | 中 | 中 | 供应商调用只封装在一个文件，fake client 先锁合同 | 保持 Mock 全功能；生产适配器只支持已验证接口 |
| LLM Schema 持续不合法 | 中 | 高 | 原生 Schema、低温度、一次修复、一次完整重试 | 安全失败，不输出半成品 |
| 模型给出错误字符区间 | 高 | 高 | 本地精确 substring 校验和 EvidenceRegistry | 删除证据并降为 unknown；仍不完整则停止 |
| PDF/DOCX 第三方解析异常 | 中 | 中 | 小文件、异常翻译、匿名夹具 | 提供粘贴文本兜底 |
| 评分权重四舍五入不为 100 | 中 | 高 | Decimal、中间 8 位、末项吸收差额 | 评分不变量失败并阻止报告 |
| 隐性要求重分配产生负权重 | 低 | 高 | 表驱动边界测试和 non-negative assert | 终止 scoring，不展示分数 |
| 改写产生新增事实 | 中 | 高 | Evidence ID、数字、专名和强化词检查 | 移入需确认区或移除 |
| Streamlit rerun 重复调用 | 中 | 中 | session_state request_id 和显式按钮 | 禁用按钮；缓存已完成报告 |
| 真实 API 不可用 | 中 | 中 | Mock 是第一等实现 | 全程使用匿名 Mock 演示 |
| Windows 依赖安装失败 | 中 | 中 | Python 3.12 venv、精简纯 Python 依赖 | 尝试 Python 3.11；不引入 Docker |
| 测试夹具与原文区间漂移 | 中 | 高 | 同源匿名文本、固定哈希、精确预期 | 重新生成全部相关夹具并一次提交 |
| 48 小时不足 | 中 | 高 | 42.5h 功能预算 + 5.5h 缓冲 | 按下述删减顺序执行 |
| 密钥或 PII 进入 Git | 低 | 极高 | ignore、网络隔离、匿名数据、git grep | 阻止任何远程授权并清理历史 |

### 10.1 时间不足时的删减顺序

保留：

1. 模型、parser、Mock、extractor。
2. EvidenceMatcher、EvidenceValidator、ScoringEngine。
3. ReportValidator、Markdown/JSON。
4. 最小 Streamlit 输入、结果和下载。
5. 核心单元测试和 Mock 端到端测试。
6. README 安装、隐私、评分和限制。

优先删减：

1. UI 颜色、图表和非必要布局；
2. 生产模型 token usage 展示；
3. 多种示例岗位，只保留一套；
4. 非关键动画或进度细节；
5. 截图数量，只保留一张完整示例图。

不得删减：

- 确定性评分；
- 硬门槛；
- 证据字符区间校验；
- 防虚构基础检查；
- Mock 测试；
- Markdown/JSON；
- 密钥与隐私门禁。

结论：在依赖安装和供应商 SDK 无重大阻塞的情况下，48 小时可完成。即使生产 API 适配受阻，Mock 路径仍能形成完整可运行、可演示和可测试的 MVP；生产适配器必须明确显示不可用原因，不能伪装成功。

## 11. 规格覆盖自审

| 架构规格 | 实施任务 | 验证证据 |
|---|---|---|
| 输入限制、隐私和配置 | Task 1、3、12、14 | 配置、parser、AppTest、安全扫描 |
| 全部数据模型和枚举 | Task 2 | 严格 Pydantic 单测 |
| TXT/DOCX/PDF/粘贴文本 | Task 3 | 四类输入与异常参数化测试 |
| 可替换 LLM、Mock、Prompt、修复 | Task 4–5 | 禁网单测、调用次数与错误码 |
| ResumeProfile 和 JobProfile | Task 6 | 稳定 ID、区间、去重、coverage |
| 逐项证据与四态匹配 | Task 7 | 一一覆盖、direct/contextual 规则 |
| 权重、缺失维度、隐性要求、硬门槛 | Task 8 | Decimal 精确边界测试 |
| 优势、缺口、推荐、改写、五题 | Task 9 | 模型不可升级推荐、最多三项、恰好五题 |
| 防虚构和报告不变量 | Task 10 | 重算、词项、数字、引用和同源导出 |
| 显式 Agent 状态机 | Task 11 | 调用顺序和 FAILED 路径 |
| Streamlit 输入、进度、标签页、下载 | Task 12 | AppTest 与本地烟雾测试 |
| 离线集成和匿名示例 | Task 13 | 两次运行同分、零网络 |
| README、截图、发布门禁 | Task 14 | 干净安装、git grep、工作区检查 |
| 未授权不执行远程操作 | 所有任务 | remote 保持为空，最终停止点 |

自审结论：

- 架构 27 项验收要求均能映射到具体任务和验证命令。
- 公开类型名、函数签名和后续消费者已在前序任务定义。
- 无循环依赖。
- 无依赖增强功能才能完成的 MVP 路径。
- 两项最小实施澄清已在本计划第 2 节明确，不修改架构结论。
- 未发现规格覆盖缺口。

## 12. 第一批开发任务

架构批准并进入编码后，从 Task 1 开始，顺序不能跳过：

1. 使用本机 Python 3.12.13 创建 `.venv`。
2. 创建 `pyproject.toml` 和 `.env.example`。
3. 先创建 `tests/unit/test_config.py` 与 `tests/unit/test_logging.py`，运行并确认因模块缺失而失败。
4. 实现 `config.py`、`errors.py`、`logging_config.py` 的最小代码。
5. 运行配置和日志测试至通过。
6. 执行 Ruff、`git diff --check`。
7. 创建第一条实现提交：

```text
chore: initialize project structure and configuration
```

Task 1 未通过前，不开始 Pydantic 领域模型；Task 2 未通过前，不开始 parser 或 LLM 适配层。

## 13. 执行停止点

本计划完成后保持规划状态：

- 不创建 `pyproject.toml`、`app.py`、`src/`、`tests/` 或示例业务文件；
- 不修改架构规格；
- 不运行依赖安装；
- 不创建 Git 远程；
- 不执行 push；
- 等待用户确认执行方式后才进入 Task 1。
