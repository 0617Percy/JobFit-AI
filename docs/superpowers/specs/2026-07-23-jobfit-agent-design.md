# JobFit Agent 产品与系统架构设计

**版本：** 1.0

**日期：** 2026-07-23

**状态：** 待用户审阅

**交付目标：** 48 小时内完成可运行、可演示、可部署、可测试且可作为 GitHub 作品集展示的 MVP

**当前阶段边界：** 本文只定义架构与验收合同，不包含业务代码实现

## 1. 执行摘要

JobFit Agent 是一个面向学生、应届生、实习申请者和初级求职者的证据约束型岗位匹配与简历诊断工具。系统接收一份中文或英文简历及一段中文或英文岗位描述，经过文档解析、结构化提取、逐项证据匹配、确定性评分、诊断与报告生成，输出可查看和下载的 Markdown 报告及 JSON 结果。

本项目采用：

- Python 3.11 或 3.12；
- Streamlit 单页面界面；
- 一个显式工作流编排器；
- 多个职责单一的本地工具模块；
- 受 Pydantic Schema 约束的大模型调用；
- 与大模型隔离的确定性评分引擎；
- 可替换的大模型供应商适配层；
- pytest 单元与集成测试；
- 无数据库、无登录、无向量库、无爬虫的本地优先架构。

Agent 特征来自“观察输入—选择并执行工具步骤—维护工作流状态—校验中间结果—失败时有限修复—生成最终产物”的受控工作流，而不是多个会话型 Agent 互相通信。所有最终分数、权重、上限和推荐等级由代码按明确规则计算；大模型不直接决定总分。

## 2. 当前环境事实

环境检查时的工作目录为本机新建的空白项目目录；该本机绝对路径不写入公开仓库。

- 目录为空，没有现有文件、子目录或同名业务项目。
- 目录不是 Git 仓库，没有分支、提交历史或远程地址。
- 没有 README、依赖配置或 `.gitignore`。
- 系统 PATH 中没有可执行的 `python`、`pip` 或 `uv`。
- Windows Python Launcher 存在，但没有发现已安装的系统 Python。
- 开发环境提供 Python 3.12.13；具体解释器路径属于本机实现细节，不作为项目依赖。
- 随附环境已包含 Pydantic 和 python-docx；未发现 Streamlit、pypdf、pytest、python-dotenv 和 OpenAI Python SDK。
- Git 2.49.0.windows.1 可用。
- 全局 Git 用户名和邮箱未配置；如提交因此失败，应由用户提供或配置真实身份，不写入伪造身份。

这些事实只描述当前机器状态。正式项目必须通过 `pyproject.toml` 声明全部依赖，并在项目虚拟环境中安装，不能依赖 Codex 随附环境。

## 3. 关键假设

1. MVP 单次处理一份简历和一份 JD，不保存历史记录。
2. 文件上限为 10 MiB；解析后的简历文本上限为 50,000 个 Unicode 字符，JD 上限为 30,000 个字符。
3. PDF 只支持具有可提取文本层的文件；扫描件和图片不执行 OCR。
4. DOCX 读取段落和表格文字，不追求页面版式重建。
5. 界面以中文为主，但结构化内容允许保留中英文原文。
6. 用户自行配置大模型服务并承担相应调用成本与数据政策责任。
7. MVP 支持一个生产供应商适配器和一个离线 Mock 适配器；模型名、API 地址、超时和密钥全部来自配置。
8. 大模型支持 JSON Schema 或等价结构化输出能力；不支持时使用严格 JSON 提示加本地 Pydantic 校验。
9. 不联网抓取公司或岗位信息；公司名、岗位名和 JD 仅来自用户输入或内置匿名示例。
10. 不将匹配分数解释为录用概率，也不替代招聘专业判断。
11. 同一份“已经通过校验的结构化输入”必须得到相同的权重、维度分数、总分上限和推荐等级；重新调用概率模型可能产生不同结构化输入，因此默认使用低随机性参数并允许保存 JSON 以复现评分。
12. 首次演示必须可通过 Mock 供应商完全离线运行，不要求真实 API 密钥，也不会产生 API 费用。
13. 当前空目录可安全初始化为本地 Git 仓库；任何远程创建、远程修改和推送均不在本阶段授权范围内。

## 4. 技术方案比较

评分采用 1 至 5 分，5 表示最有利。

| 维度 | Python + Streamlit + 结构化工作流 | Python API + React | 低代码 Agent 平台 |
|---|---:|---:|---:|
| 48 小时完成概率 | 5 | 2 | 4 |
| Agent 能力表达 | 5 | 5 | 3 |
| 技术作品集价值 | 4 | 5 | 2 |
| 开发复杂度 | 5 | 2 | 4 |
| 自动化测试难度 | 4 | 2 | 2 |
| 部署难度 | 4 | 2 | 3 |
| GitHub 展示效果 | 4 | 5 | 2 |
| 后续扩展能力 | 4 | 5 | 2 |
| 本地与离线可复现性 | 5 | 4 | 2 |
| 供应商可替换性 | 5 | 5 | 2 |

### 4.1 推荐：Python + Streamlit + 结构化工作流

该方案把时间投入到核心差异化能力：证据定位、匹配解释、确定性评分、防虚构和测试。Streamlit 足以承载上传、分步进度、标签页、表格和下载。业务逻辑放在 `src/jobfit`，`app.py` 只负责 UI 组合，因此不会形成难以测试的单文件演示。

### 4.2 备选：Python API + React

该方案的界面自由度和长期扩展性最高，但需要额外处理 API 合同、跨域、异步状态、前后端构建、部署和两套测试。48 小时内会挤压评分、证据校验和文档质量，不适合作为 MVP 首选。

### 4.3 备选：低代码 Agent 平台

低代码可快速拼接提示词和节点，但工作流定义、结构化验证、评分纯函数、测试夹具和部署复现通常依赖特定平台。它削弱代码作品集价值，也增加平台锁定和隐私路径不透明的风险。

## 5. 产品范围和用户流程

### 5.1 主流程

1. 用户上传 PDF、DOCX、TXT，或直接粘贴简历文本。
2. 系统验证文件类型、大小和非空性，解析并显示文本预览。
3. 用户输入岗位名称、公司名称与 JD，或加载匿名示例。
4. 用户明确点击“开始分析”。
5. 编排器依次执行：
   - 输入校验；
   - 文档解析与文本标准化；
   - 简历结构化提取；
   - JD 结构化提取；
   - 逐项证据匹配；
   - 证据与覆盖完整性校验；
   - 确定性评分；
   - 优势、缺口与投递建议生成；
   - 简历改写建议生成；
   - 面试问题生成；
   - 最终一致性和防虚构校验；
   - Markdown 与 JSON 渲染。
6. UI 用标签页展示综合结论、逐项匹配、简历优化、面试准备和结构化数据。
7. 用户分别下载 Markdown 和 JSON；默认不在磁盘持久化上传文件或报告。

### 5.2 状态机

工作流状态枚举：

`IDLE → VALIDATING_INPUT → PARSING_RESUME → EXTRACTING_RESUME → EXTRACTING_JOB → MATCHING_EVIDENCE → VALIDATING_MATCHES → SCORING → GENERATING_ADVICE → VALIDATING_REPORT → COMPLETED`

任一步失败进入 `FAILED`，状态中保存安全的错误码、用户可理解信息和可重试阶段。解析失败允许用户返回输入区并粘贴文本；模型阶段失败允许对该阶段执行一次结构修复和一次完整重试；评分或验证失败不得输出看似完整的报告。

## 6. 系统架构与数据流

```text
Streamlit UI
    │ AnalysisRequest
    ▼
WorkflowOrchestrator ──────────────── ProgressEvent
    │
    ├─ DocumentParser ─────────────── DocumentContent
    ├─ ResumeExtractor ────────────── ResumeProfile
    ├─ JobRequirementExtractor ────── JobProfile
    ├─ EvidenceMatcher ────────────── RequirementMatch[]
    ├─ ResultValidator ────────────── ValidationResult
    ├─ ScoringEngine ──────────────── MatchScoreSummary
    ├─ AdviceGenerator ────────────── Diagnosis + Rewrites + Questions
    ├─ ResultValidator ────────────── ValidationResult
    └─ ReportRenderer ─────────────── AnalysisReport / Markdown / JSON

LLM-backed modules → LLMClient protocol → ProviderAdapter or MockLLMClient
Pure local modules → parser, scorer, validator, renderer, configuration, logging
```

### 6.1 数据所有权

- `DocumentContent` 是简历原文的唯一证据源。
- `ResumeProfile` 只保存可回溯到 `DocumentContent` 的结构化事实。
- `JobProfile` 保存 JD 原文与每项要求的来源片段。
- `RequirementMatch` 引用 `JobRequirement.requirement_id` 和 `EvidenceItem.evidence_id`。
- `MatchScoreSummary` 只读取已校验的要求和匹配结果，不调用大模型。
- 建议与改写只读取已校验事实、匹配结果和确定性分数。
- `AnalysisReport` 是不可变的最终聚合对象，Renderer 不改变业务结论。

### 6.2 模块接口

| 模块 | 输入 | 输出 | 依赖 |
|---|---|---|---|
| DocumentParser | 文件字节、文件名、MIME 或粘贴文本 | DocumentContent | pypdf（BSD-3-Clause，仅文本层、不含 OCR）、python-docx、标准库 |
| ResumeExtractor | DocumentContent | ResumeProfile | LLMClient、Pydantic |
| JobRequirementExtractor | JD 文本、可选岗位/公司名 | JobProfile | LLMClient、Pydantic |
| EvidenceMatcher | ResumeProfile、JobProfile、DocumentContent | RequirementMatch 列表 | LLMClient、Pydantic |
| ScoringEngine | JobRequirement 列表、RequirementMatch 列表 | MatchScoreSummary | Decimal、纯函数 |
| AdviceGenerator | 已校验匹配与分数 | 诊断、改写、面试题 | LLMClient、Pydantic |
| ResultValidator | 原文与任一结构化阶段结果 | ValidationResult | 纯本地校验规则 |
| ReportRenderer | AnalysisReport | Markdown 字符串、JSON 字节 | 模板与 Pydantic 序列化 |
| WorkflowOrchestrator | AnalysisRequest、ProgressSink | AnalysisReport | 上述接口 |

### 6.3 运行时接口

#### AnalysisRequest

`request_id: str` 必填；`resume_file: UploadedDocumentInput | None = None`；`pasted_resume_text: str | None = None`；`job_description_text: str` 必填；`job_title: str | None = None`；`company_name: str | None = None`；`llm_mode: Literal["provider","mock"]` 必填。`resume_file` 与 `pasted_resume_text` 至少提供一个；两者同时提供时，用户在 UI 中明确选择哪一个作为证据源，不执行隐式拼接。

#### UploadedDocumentInput

`filename: str` 必填且只保留基本文件名；`media_type: str` 必填；`content: bytes` 必填；`size_bytes: int` 必填。该对象只在解析阶段存在，不序列化到报告。

#### ProgressEvent 与 ProgressSink

`ProgressEvent` 包含 `request_id: str`、`stage: WorkflowStage`、`progress_percent: int`、`message_key: str`、`recoverable: bool`，全部必填。`progress_percent` 范围为 0 至 100。`ProgressSink` 是只含 `publish(event: ProgressEvent) -> None` 的协议；Streamlit 适配器只把 message_key 映射为界面文字，不读取业务对象。

## 7. 数据模型

所有模型使用 Pydantic v2，配置为 `extra="forbid"`。时间使用带时区 ISO 8601；标识符使用本次运行内稳定的字符串；分数使用 `Decimal` 或经统一量化的浮点输出。可选字段未确认时为 `None`，集合字段默认空列表，不用空字符串表达未知。

### 7.1 公共枚举

| 枚举 | 允许值 |
|---|---|
| LanguageCode | `zh`, `en`, `mixed`, `unknown` |
| RequirementType | `responsibility`, `must_have`, `preferred`, `implicit` |
| RequirementCategory | `eligibility`, `technical_skill`, `experience_project`, `domain_business`, `education_language`, `communication_keyword` |
| Importance | `critical`, `high`, `medium`, `low` |
| HardConditionKind | `none`, `work_authorization`, `degree_level`, `graduation_window`, `language_minimum`, `experience_minimum`, `required_certificate`, `location_availability` |
| MatchStatus | `matched`, `partial`, `not_matched`, `unknown` |
| ConfidenceLevel | `high`, `medium`, `low` |
| GapRemediability | `wording`, `evidence_needed`, `learning_practice`, `hard_to_fix_short_term` |
| RecommendationLevel | `priority_apply`, `optimize_then_apply`, `try_apply`, `not_priority` |
| ValidationSeverity | `error`, `warning`, `info` |
| WorkflowStage | 状态机中定义的全部状态 |

### 7.1.1 LLM 草稿与确定性组装

大模型输出 Schema 与最终领域模型分离，防止模型写入计算字段：

- `JobRequirementDraft` 包含 JobRequirement 除 `requirement_id`、`priority_factor` 和 `weight` 外的提取字段。代码按 `source_start_char`、`source_end_char`、`normalized_key` 排序后生成 `req-001` 形式的稳定 ID，再计算因子和权重。
- `RequirementMatchDraft` 包含 RequirementMatch 除 `match_score` 外的字段，并引用已存在的 requirement_id。代码校验证据后写入固定状态分值。
- `AdviceBundleDraft` 包含 `strengths`、`gaps`、`recommendation_reasoning`、`rewrite_suggestions` 和 `interview_questions`。代码使用评分引擎产生的 RecommendationLevel 组装最终 ApplicationRecommendation，忽略草稿中任何等级或分数文本。

简历项目、经历和证据 ID 同样由代码按原文字符起点排序后生成，不接受模型提供的可生效 ID。若两个项目共享相同起点，则依次使用字符终点和规范化文本排序。所有“最后一项吸收四舍五入差额”的操作均以 requirement_id 字典序最后一项为目标，确保相同结构化输入得到相同结果。

### 7.2 文档和证据模型

#### DocumentContent

| 字段 | 类型 | 必填/默认 | 说明 |
|---|---|---|---|
| document_id | str | 必填 | 本次运行内唯一标识 |
| source_kind | Literal[`pdf`,`docx`,`txt`,`pasted_text`] | 必填 | 来源类型 |
| original_filename | str \| None | 默认 None | 仅文件输入存在；展示前清理路径 |
| media_type | str \| None | 默认 None | 检测到的 MIME |
| byte_size | int \| None | 默认 None | 文件字节数 |
| raw_text | str | 必填 | 解析出的原始文本 |
| normalized_text | str | 必填 | 统一换行和空白后的证据基准文本 |
| language | LanguageCode | 默认 `unknown` | 文档主要语言 |
| segments | list[TextSegment] | 默认空列表 | 可定位段落、页或表格单元 |
| content_sha256 | str | 必填 | 内容哈希，用于运行内一致性检查，不写日志 |
| warnings | list[str] | 默认空列表 | 非致命解析告警 |

#### TextSegment

`segment_id: str` 必填；`text: str` 必填；`start_char: int` 必填；`end_char: int` 必填；`page_number: int | None = None`；`section_hint: str | None = None`。字符区间采用左闭右开，必须满足 `normalized_text[start_char:end_char] == text`。

#### EvidenceItem

`evidence_id: str` 必填；`document_id: str` 必填；`segment_id: str` 必填；`quote: str` 必填；`start_char: int` 必填；`end_char: int` 必填；`page_number: int | None = None`；`evidence_kind: Literal["direct","contextual"]` 必填；`confidence: Decimal` 必填且范围 0 至 1。Validator 必须验证引文与字符区间完全一致。

### 7.3 简历模型

#### ResumeProfile

| 字段 | 类型 | 必填/默认 | 说明 |
|---|---|---|---|
| resume_id | str | 必填 | 结构化简历标识 |
| document_id | str | 必填 | 引用 DocumentContent |
| language | LanguageCode | 必填 | 简历语言 |
| basic_info | BasicInfo | 默认空模型 | 仅提取原文明确内容 |
| education | list[EducationItem] | 默认空列表 | 教育经历 |
| experiences | list[ExperienceItem] | 默认空列表 | 实习或工作经历 |
| projects | list[ProjectItem] | 默认空列表 | 项目经历 |
| skills | list[SkillItem] | 默认空列表 | 技能和工具 |
| achievements | list[AchievementItem] | 默认空列表 | 奖项和可验证成果 |
| certificates | list[CertificateItem] | 默认空列表 | 证书 |
| languages | list[LanguageItem] | 默认空列表 | 语言能力 |
| additional_information | list[ResumeFact] | 默认空列表 | 其他明确事实 |
| extraction_warnings | list[str] | 默认空列表 | 缺失或歧义说明 |

#### BasicInfo

`name: str | None = None`；`email: str | None = None`；`phone: str | None = None`；`location: str | None = None`；`target_title: str | None = None`；`evidence_ids: list[str] = []`。PII 只用于当前内存中的分析，不进入日志和匿名示例。

#### EducationItem

`education_id: str`、`institution: str | None`、`degree: str | None`、`major: str | None`、`start_date: str | None`、`end_date: str | None`、`coursework: list[str] = []`、`gpa_text: str | None`、`raw_text: str`、`evidence_ids: list[str]`。`education_id`、`raw_text`、至少一个有效 evidence_id 必填。

#### ExperienceItem

`experience_id: str`、`organization: str | None`、`role: str | None`、`start_date: str | None`、`end_date: str | None`、`bullets: list[ResumeBullet]`、`raw_text: str`、`evidence_ids: list[str]`。标识符、原文和 evidence_ids 必填。

#### ProjectItem

`project_id: str`、`name: str | None`、`role: str | None`、`start_date: str | None`、`end_date: str | None`、`technologies: list[str] = []`、`bullets: list[ResumeBullet] = []`、`raw_text: str`、`evidence_ids: list[str]`。标识符、原文和 evidence_ids 必填。

#### ResumeBullet

`bullet_id: str`、`text: str`、`action_terms: list[str] = []`、`outcome_terms: list[str] = []`、`quantified_metrics: list[str] = []`、`evidence_ids: list[str]`。所有提取值必须能在引用证据中定位。

#### SkillItem

`skill_id: str`、`name: str`、`skill_type: Literal["language","framework","tool","method","domain","soft_skill","other"]`、`proficiency_text: str | None = None`、`evidence_ids: list[str]`。不得从职位或项目常识推断未写明技能。

#### AchievementItem、CertificateItem、LanguageItem、ResumeFact

- `AchievementItem`: `achievement_id`, `name`, `issuer: str | None`, `date: str | None`, `result_text: str | None`, `evidence_ids`。
- `CertificateItem`: `certificate_id`, `name`, `issuer: str | None`, `date: str | None`, `evidence_ids`。
- `LanguageItem`: `language_id`, `language`, `proficiency_text: str | None`, `evidence_ids`。
- `ResumeFact`: `fact_id`, `fact_type`, `text`, `evidence_ids`。

每个模型的标识符、主要文本和至少一个有效 evidence_id 必填，其余字段默认 None。

### 7.4 岗位模型

#### JobProfile

| 字段 | 类型 | 必填/默认 | 说明 |
|---|---|---|---|
| job_id | str | 必填 | 岗位标识 |
| title | str \| None | 默认 None | 用户输入优先，其次从 JD 提取 |
| company | str \| None | 默认 None | 用户输入优先，其次从 JD 提取 |
| language | LanguageCode | 必填 | JD 语言 |
| summary | str | 必填 | 不引入外部事实的岗位摘要 |
| requirements | JobRequirementCollection | 必填 | 去重后的要求 |
| keywords | list[str] | 默认空列表 | 只来自 JD 文本 |
| extraction_warnings | list[str] | 默认空列表 | 歧义和缺失信息 |

#### JobRequirementCollection

`items: list[JobRequirement]` 必填且至少一项；`deduplication_notes: list[str] = []`；`source_coverage_ratio: Decimal` 必填且范围 0 至 1。每个 requirement_id 唯一。`source_coverage_ratio` 由代码计算为“所有要求 source 区间去重后的非空白字符数 ÷ JD 中职责与任职要求段的非空白字符数”；若无法识别这些段落，则分母使用完整 JD 的非空白字符数。该值只用于提取覆盖告警，不进入分数。

#### JobRequirement

| 字段 | 类型 | 必填/默认 | 说明 |
|---|---|---|---|
| requirement_id | str | 必填 | 唯一标识 |
| requirement_text | str | 必填 | 原子化、可判断的要求 |
| source_text | str | 必填 | JD 原始支持片段 |
| source_start_char | int | 必填 | JD 字符起点 |
| source_end_char | int | 必填 | JD 字符终点 |
| requirement_type | RequirementType | 必填 | 要求类型 |
| category | RequirementCategory | 必填 | 唯一主要评分维度 |
| importance | Importance | 必填 | 重要程度 |
| mandatory | bool | 必填 | JD 是否明确为必须 |
| hard_condition_kind | HardConditionKind | 默认 `none` | 只有明确硬门槛可设置 |
| normalized_key | str | 必填 | 去重与关键词映射键 |
| priority_factor | Decimal | 由代码填充 | 单项相对因子 |
| weight | Decimal | 由代码填充 | 归一化后的百分制分值 |

隐性要求必须满足：`requirement_type="implicit"`、`mandatory=false`、`hard_condition_kind="none"`、`importance` 不高于 `medium`，并引用能支持该推断的 JD 片段。隐性要求总权重不超过最终有效总权重的 10%。

### 7.5 匹配与评分模型

#### RequirementMatch

| 字段 | 类型 | 必填/默认 | 说明 |
|---|---|---|---|
| requirement_id | str | 必填 | 引用 JobRequirement |
| match_status | MatchStatus | 必填 | 四态判断 |
| match_score | Decimal | 由代码填充 | 状态映射结果，模型不得提交 |
| evidence_items | list[EvidenceItem] | 默认空列表 | 来自简历原文 |
| reasoning | str | 必填 | 克制、可验证的解释 |
| confidence | Decimal | 必填 | 0 至 1 |
| missing_evidence_note | str \| None | 默认 None | 无证据或不足时必填 |
| improvement_suggestion | str | 必填 | 不引入新事实 |

`matched` 至少需要一个直接证据；`partial` 至少需要一个直接或上下文证据；`not_matched` 或 `unknown` 允许空证据，但必须提供 missing_evidence_note。简历未写明通常标记 `unknown`，只有简历明确与要求冲突时标记 `not_matched`。

#### DimensionScore

`category: RequirementCategory`、`base_points: Decimal`、`effective_points: Decimal`、`earned_points: Decimal`、`active: bool`、`requirement_ids: list[str]`、`coverage_ratio: Decimal`。全部必填并由评分代码生成。

#### MatchScoreSummary

`raw_score: Decimal`、`score_cap: Decimal`、`final_score: Decimal`、`dimension_scores: list[DimensionScore]`、`mandatory_coverage_ratio: Decimal`、`strong_evidence_coverage_ratio: Decimal`、`confirmed_hard_blockers: list[str]`、`unverified_hard_blockers: list[str]`、`cap_reasons: list[str]`、`recommendation_level: RecommendationLevel`。全部由代码生成。

### 7.6 诊断、改写和面试模型

#### StrengthItem

`title: str`、`summary: str`、`requirement_ids: list[str]`、`evidence_ids: list[str]`、`why_it_matters: str`。必须引用至少一个要求和一个有效证据。

#### GapItem

`title: str`、`summary: str`、`requirement_ids: list[str]`、`remediability: GapRemediability`、`risk_level: Importance`、`recommended_action: str`、`user_confirmation_needed: bool`。不得把 `unknown` 描述为用户一定不具备。

#### ApplicationRecommendation

`level: RecommendationLevel`、`reasoning: list[str]`、`blocking_requirement_ids: list[str]`、`before_applying_actions: list[str]`。level 由评分引擎写入；生成器只解释，不得升级等级。

#### RewriteSuggestion

`suggestion_id: str`、`original_text: str`、`rewritten_text: str`、`reason: str`、`requirement_ids: list[str]`、`evidence_ids: list[str]`、`introduced_claims: list[str] = []`、`user_confirmation_needed: list[str] = []`。若 introduced_claims 非空，该条不进入可直接采用列表，只进入“需确认”列表。

#### InterviewQuestion

`question_id: str`、`question: str`、`intent: str`、`answer_framework: list[str]`、`resume_evidence_ids: list[str] = []`、`requirement_ids: list[str]`、`emphasis: list[str]`、`risks_to_avoid: list[str]`。最终必须恰好五项，优先覆盖高权重要求与主要缺口。

### 7.7 报告和校验模型

#### AnalysisReport

`report_id: str`、`schema_version: Literal["1.0"]`、`generated_at: datetime`、`job_profile: JobProfile`、`resume_profile: ResumeProfile`、`matches: list[RequirementMatch]`、`score_summary: MatchScoreSummary`、`strengths: list[StrengthItem]`、`gaps: list[GapItem]`、`recommendation: ApplicationRecommendation`、`rewrite_suggestions: list[RewriteSuggestion]`、`interview_questions: list[InterviewQuestion]`、`limitations: list[str]`、`validation: ValidationResult`。所有字段必填；优势和缺口最多各三项，面试题恰好五项。

#### ValidationResult

`valid: bool`、`issues: list[ValidationIssue]`、`checked_rules: list[str]`。`ValidationIssue` 包含 `code: str`、`severity: ValidationSeverity`、`message: str`、`object_ref: str | None = None`。存在任一 error 时 valid 为 false。

## 8. 确定性评分机制

### 8.1 基础维度

| 维度 | 基础分 | 定义 |
|---|---:|---|
| eligibility | 20 | 工作许可、地点、毕业时间、最低年限等基本资格 |
| technical_skill | 25 | 编程语言、框架、工具、数据与 AI 技术 |
| experience_project | 25 | 项目、实习、职责规模和相关场景 |
| domain_business | 15 | 业务分析、产品、行业知识、成果导向 |
| education_language | 10 | 学历、专业、课程、证书和语言 |
| communication_keyword | 5 | 沟通协作、岗位关键词和表达覆盖 |
| **合计** | **100** | |

“成果与证据质量”不单独重复计分，而是通过匹配状态和强证据覆盖率进入投递门槛；这样避免同一证据在经历相关性与证据质量中重复加分。

### 8.2 状态映射

```text
matched      = 1.0
partial      = 0.6
not_matched  = 0.0
unknown      = 0.0
```

`unknown` 与 `not_matched` 数值相同，但语义、硬门槛和报告措辞不同。前者表示当前简历无法证明；后者表示简历存在明确冲突。模型只输出状态，`match_score` 由代码覆盖写入。

### 8.3 单项相对因子

重要性因子：

```text
critical = 4
high     = 3
medium   = 2
low      = 1
```

类型因子：

```text
must_have     = 1.00
responsibility= 0.90
preferred     = 0.70
implicit      = 0.50
```

明确 mandatory 的乘数为 1.25，否则为 1.00。

```text
priority_factor_i =
    importance_factor_i
  × type_factor_i
  × mandatory_factor_i
```

所有因子由本地代码根据枚举计算，大模型不得返回可生效的权重。

### 8.4 缺失维度和权重归一化

若某维度没有任何要求，该维度标记为 inactive，其基础分按比例分配给其他 active 维度：

```text
effective_points_d =
    100 × base_points_d / Σ(base_points of active dimensions)
```

某 active 维度内的单项权重：

```text
weight_i =
    effective_points_dimension(i)
    × priority_factor_i
    / Σ(priority_factor of requirements in same dimension)
```

要求权重使用 `Decimal` 计算，中间精度保留 8 位小数，展示值保留 2 位。最后一个要求吸收因四舍五入产生的维度内微小差额，确保单项权重和严格为 100.00。

隐性要求先按正常公式计算；若隐性要求总权重超过 10.00，则按比例压缩至 10.00，释放的分值按非隐性要求现有权重比例重新分配。

### 8.5 分数公式

```text
earned_i = weight_i × status_value_i
raw_score = Σ earned_i

dimension_earned_d = Σ earned_i in dimension d
dimension_coverage_d =
    dimension_earned_d / effective_points_d
```

`raw_score` 限制在 0 至 100。强证据覆盖率按权重计算：状态为 matched 或 partial、至少有一条字符区间校验通过的证据、且 match confidence 不低于 0.70 的要求，计入强证据分子。

mandatory coverage 按 mandatory 要求权重计算；若 JD 没有 mandatory 要求，值为 1.0。

### 8.6 硬性条件和总分上限

只有同时满足 `mandatory=true`、`hard_condition_kind != none` 且要求来自明确 JD 原文的项目才是硬门槛。隐性要求永远不能触发上限。

按最严格规则取最小上限：

| 条件 | 总分上限 | 推荐等级上限 |
|---|---:|---|
| 任一硬门槛为 not_matched | 49 | not_priority |
| 任一硬门槛为 unknown | 69 | try_apply |
| 任一 critical mandatory 非硬门槛为 not_matched | 69 | try_apply |
| 两项及以上 high/critical mandatory 为 not_matched | 69 | try_apply |
| 无上述条件 | 100 | 不额外限制 |

```text
final_score = min(raw_score, score_cap)
```

报告必须列出触发上限的 requirement_id 和原因。学历、工作许可、毕业时间等未在简历中出现时通常为 unknown，不得写成用户确定不满足。

### 8.7 投递建议

推荐等级由确定性代码按顺序选择，生成器只能解释：

1. 若存在 confirmed hard blocker：`not_priority`。
2. 否则若 final_score ≥ 80、mandatory coverage ≥ 0.85、strong evidence coverage ≥ 0.70 且没有 critical mandatory 缺口：`priority_apply`。
3. 否则若 final_score ≥ 68、mandatory coverage ≥ 0.65 且没有 confirmed hard blocker：`optimize_then_apply`。
4. 否则若 final_score ≥ 50 且没有 confirmed hard blocker：`try_apply`。
5. 其他情况：`not_priority`。

若硬门槛 unknown，等级最高为 `try_apply`，并要求用户先确认。诊断中的可修复程度用于排序行动建议，不得覆盖上述等级。

## 9. 大模型使用边界

### 9.1 交给大模型

- 从简历原文提取显式结构化事实及其证据区间候选；
- 将 JD 拆成原子化要求，分类并判断明确的 must/preferred；
- 在已提取事实中检索每项要求的相关证据；
- 基于证据选择四态匹配并生成克制理由；
- 基于已校验匹配和确定性分数生成优势、缺口解释；
- 在不新增事实的前提下优化简历表述；
- 生成五道面试题与回答框架。

### 9.2 必须由代码完成

- 文件类型、大小、空值和文本长度校验；
- 文本标准化、字符区间和引文一致性校验；
- ID 唯一性、引用完整性和要求覆盖检查；
- 重要性、类型、mandatory 因子；
- 单项权重、缺失维度重归一化、隐性要求 10% 上限；
- 状态数值映射、维度分和总分；
- 硬门槛上限、推荐等级；
- Pydantic Schema 校验；
- JSON 序列化与 Markdown 渲染；
- 敏感日志过滤和下载文件名清理。

### 9.3 调用节点与次数

正常生产路径使用四次调用：

1. `extract_resume`：DocumentContent → ResumeProfile；
2. `extract_job`：JD → JobProfile；
3. `match_evidence`：校验后的 ResumeProfile + JobProfile → RequirementMatch[]；
4. `generate_advice_bundle`：校验后的事实、匹配与分数 → strengths、gaps、recommendation explanation、rewrites、questions。

简历与 JD 提取可由编排器并行执行，但第一版可顺序执行以简化 Streamlit 进度和错误恢复。单次调用携带任务所需最小文本；不发送文件元数据中的本地路径。

### 9.4 提示词管理

提示词保存在 `src/jobfit/prompts/*.md`，由版本化 `PromptRegistry` 加载。`PromptRegistry` 暴露 `load(task_name: str, version: str) -> PromptTemplate`；`PromptTemplate` 只包含 `task_name`、`version`、`system_text` 和 `user_template`，启动时缺文件或版本不匹配即报配置错误。每个提示词包含：

- 角色和唯一任务；
- 输入边界标记；
- 明确禁止新增事实；
- 枚举和值域；
- 证据引用要求；
- 中英文处理规则；
- 输出 Schema；
- 未知信息的标准表达；
- 少量正反例。

提示词版本写入运行元数据，但完整简历、完整输出和提示词拼接结果不进入日志。

### 9.5 结构化输出与失败修复

1. 优先使用供应商原生 JSON Schema/structured output。
2. 接收结果后立即执行 Pydantic `model_validate`，`extra="forbid"`。
3. 首次校验失败时，只发送原输出、精简后的校验错误和同一 Schema，进行一次结构修复。
4. 修复仍失败时，对该阶段进行一次完整重试。
5. 第二次完整结果仍失败则终止该阶段，返回 `LLM_SCHEMA_INVALID`，UI 显示安全错误和重试按钮。
6. 不将部分无效结果传入评分，不在前端用字典猜测字段。

默认温度为 0 或供应商允许的最低值；超时 60 秒；每次调用最多两次网络尝试，采用 1 秒和 2 秒指数退避并加入小幅抖动。429、5xx 和超时可重试；认证错误、无效配置和内容过长不自动重复。

### 9.6 供应商适配

`LLMClient` 协议只暴露 `generate_structured(task, schema, messages, settings)`。生产适配器读取 `JOBFIT_LLM_PROVIDER`、`JOBFIT_LLM_MODEL`、`JOBFIT_LLM_API_KEY`、可选 `JOBFIT_LLM_BASE_URL`；Mock 适配器读取固定 JSON 夹具。业务模块不得导入具体供应商 SDK。

## 10. 防虚构与结果校验

### 10.1 证据闭环

每一条简历事实必须引用 EvidenceItem；每个 EvidenceItem 必须通过：

- document_id 和 segment_id 存在；
- 字符区间合法；
- `normalized_text[start:end]` 与 quote 完全相等；
- 不允许引用 JD 作为简历事实证据。

每个 JobRequirement 必须引用 JD 的精确字符区间。每个 RequirementMatch 必须恰好对应一个 JobRequirement，最终集合与 requirements 一一覆盖。

### 10.2 匹配约束

- `matched` 无直接证据：降为 `unknown` 并记录 error，报告生成前要求修复。
- `partial` 无任何证据：降为 `unknown`。
- 低 confidence 不自动提高或降低状态，但会影响强证据覆盖率。
- 未在简历中发现信息时用“当前简历未提供足够证据”，不写“用户不会”。

### 10.3 改写约束

Validator 对每条改写执行：

1. original_text 必须能由 evidence_ids 回溯。
2. rewritten_text 中新增的数字、百分比、货币、日期、专有工具名、组织名和职位级别必须已出现在引用证据。
3. “主导、负责、独立、上线、商业化、提升、降低、用户数、收入”等高风险强化词若原证据无对应表达，标记 `UNSUPPORTED_CLAIM_TERM`。
4. introduced_claims 非空时，该建议只能显示在“需用户确认”区域，不能标记为可直接复制。
5. 任一 error 未修复的建议从最终可采用列表移除，并在 validation issues 中说明。

该机制不能从理论上证明所有语义都无新增，但能建立可测试的来源约束和保守失败策略。README 必须说明输出仍需用户核对。

### 10.4 最终报告不变量

- requirements 与 matches 数量相等且 ID 集合一致；
- 单项权重和为 100.00；
- 所有状态分值来自固定映射；
- raw_score、cap 和 final_score 可重新计算一致；
- recommendation.level 与评分规则一致；
- 优势不超过三项且都有有效证据；
- 缺口不超过三项且不把 unknown 写成确认缺失；
- 面试题恰好五项；
- Markdown 和 JSON 来自同一个 AnalysisReport；
- ValidationResult.valid 为 true 才允许下载最终报告。

## 11. 错误处理和降级

| 场景 | 错误码 | 用户行为/系统降级 |
|---|---|---|
| 空文件或空文本 | `INPUT_EMPTY` | 阻止分析，提示上传或粘贴 |
| 超过大小或文本上限 | `INPUT_TOO_LARGE` | 阻止调用，提示裁剪 |
| 不支持扩展名/MIME | `FILE_TYPE_UNSUPPORTED` | 提示改用 PDF、DOCX、TXT 或粘贴 |
| PDF 无文本层 | `PDF_TEXT_EMPTY` | 提示扫描件暂不支持，允许粘贴 |
| DOCX/PDF 损坏 | `DOCUMENT_PARSE_FAILED` | 保留其他输入，允许粘贴 |
| 缺 API key | `LLM_CREDENTIALS_MISSING` | 生产模式阻止分析；可切换匿名 Mock 演示 |
| 认证失败 | `LLM_AUTH_FAILED` | 不重试，提示检查配置 |
| 限流/超时/5xx | `LLM_TRANSIENT_ERROR` | 有限重试；失败后保留输入供手动重试 |
| Schema 无效 | `LLM_SCHEMA_INVALID` | 一次修复、一次完整重试，随后停止 |
| 证据引用无效 | `EVIDENCE_INVALID` | 尝试一次 matcher 修复；仍失败则停止 |
| 评分不变量失败 | `SCORING_INVARIANT_FAILED` | 不输出分数，记录无 PII 的 error |
| 报告校验失败 | `REPORT_VALIDATION_FAILED` | 禁止下载，显示可操作错误 |

页面级异常捕获只展示友好信息和短 request_id；开发日志保留异常类型和栈，但不得含输入正文。

## 12. 配置、日志、安全与隐私

### 12.1 配置

使用 `pydantic-settings` 从环境变量和本地 `.env` 读取：

```text
JOBFIT_LLM_PROVIDER=openai
JOBFIT_LLM_MODEL=<user-selected-model>
JOBFIT_LLM_API_KEY=<secret>
JOBFIT_LLM_BASE_URL=<optional>
JOBFIT_LLM_TIMEOUT_SECONDS=60
JOBFIT_LLM_MAX_RETRIES=2
JOBFIT_MAX_UPLOAD_MB=10
JOBFIT_LOG_LEVEL=INFO
JOBFIT_DEMO_MODE=false
```

`.env.example` 只放字段名和安全说明，不放可用密钥或私有地址。配置对象在应用启动时校验；密钥在 `repr`、错误信息和日志中始终脱敏。

### 12.2 日志

使用标准 `logging`，输出阶段、耗时、状态、模型供应商、模型别名、token usage（若 SDK 返回）、request_id、错误码。禁止记录：

- 完整简历或 JD；
- 姓名、邮箱、手机号、地址；
- API key、Authorization header、完整模型响应；
- 上传文件字节和本地绝对路径。

输入只记录字符数、文件类型和不可逆内容哈希前 8 位；生产默认 INFO，本地诊断 DEBUG 仍执行 PII 过滤器。日志默认写 stderr，不默认长期写文件。

### 12.3 隐私生命周期

- 上传内容只在当前 Streamlit 会话内存中处理；
- 不默认保存上传文件、原始文本或报告；
- 用户点击下载时在内存中生成字节；
- 会话重置后释放状态；
- 示例简历使用虚构姓名与 `example.com` 邮箱，不含真实电话或地址；
- README 明确说明数据会发送到用户配置的大模型服务；
- Mock 演示不发送外部请求；
- 不把匹配分数描述为真实录用概率。

### 12.4 Git 安全

`.gitignore` 必须覆盖 `.env`、虚拟环境、缓存、日志、用户上传目录、生成报告、IDE 与系统文件。正式上传前执行：

- `git status --ignored` 检查忽略规则；
- `git grep` 检查常见密钥前缀、Authorization、密码赋值；
- 对待提交历史执行敏感信息扫描；
- 人工检查示例中的邮箱、电话、地址和公司内部内容；
- 从干净环境安装、测试和启动；
- 确认工作区干净、分支为 main、远程目标正确。

## 13. 项目目录

```text
jobfit-agent/
├─ app.py                         # Streamlit 入口，只做页面组合和会话状态
├─ README.md
├─ pyproject.toml
├─ .env.example
├─ .gitignore
├─ LICENSE
├─ src/
│  └─ jobfit/
│     ├─ __init__.py
│     ├─ config.py                # Settings 与启动校验
│     ├─ errors.py                # 领域错误码和安全消息
│     ├─ logging_config.py        # PII 过滤和 request_id
│     ├─ models/
│     │  ├─ common.py
│     │  ├─ document.py
│     │  ├─ resume.py
│     │  ├─ job.py
│     │  ├─ matching.py
│     │  ├─ advice.py
│     │  └─ report.py
│     ├─ parsers/
│     │  ├─ base.py
│     │  ├─ text.py
│     │  ├─ pdf.py
│     │  ├─ docx.py
│     │  └─ service.py
│     ├─ extractors/
│     │  ├─ resume.py
│     │  └─ job.py
│     ├─ matching/
│     │  └─ evidence_matcher.py
│     ├─ scoring/
│     │  ├─ policy.py
│     │  └─ engine.py
│     ├─ generators/
│     │  ├─ diagnosis.py
│     │  ├─ rewrite.py
│     │  └─ interview.py
│     ├─ validators/
│     │  ├─ evidence.py
│     │  ├─ rewrite.py
│     │  └─ report.py
│     ├─ reporting/
│     │  ├─ markdown.py
│     │  └─ json_export.py
│     ├─ prompts/
│     │  ├─ resume_extraction.md
│     │  ├─ job_extraction.md
│     │  ├─ evidence_matching.md
│     │  └─ advice_bundle.md
│     ├─ llm/
│     │  ├─ protocol.py
│     │  ├─ openai_adapter.py
│     │  ├─ mock_adapter.py
│     │  └─ structured_runner.py
│     └─ workflow/
│        ├─ state.py
│        └─ orchestrator.py
├─ tests/
│  ├─ fixtures/
│  │  ├─ sample_resume.txt
│  │  ├─ sample_resume.docx
│  │  ├─ sample_resume.pdf
│  │  ├─ sample_job_description.txt
│  │  ├─ llm_responses/
│  │  └─ expected/
│  ├─ unit/
│  │  ├─ test_parsers.py
│  │  ├─ test_models.py
│  │  ├─ test_scoring.py
│  │  ├─ test_validators.py
│  │  ├─ test_reporting.py
│  │  └─ test_config.py
│  └─ integration/
│     ├─ test_mock_workflow.py
│     └─ test_streamlit_smoke.py
├─ examples/
│  ├─ sample_resume.txt
│  ├─ sample_job_description.txt
│  └─ expected_report_example.json
├─ docs/
│  ├─ superpowers/specs/2026-07-23-jobfit-agent-design.md
│  ├─ product-spec.md
│  ├─ implementation-plan.md
│  └─ github-release-checklist.md
└─ assets/
   └─ screenshots/
```

本轮只创建架构文档和必要的 `.gitignore`。其余结构在架构获批后的实施计划中按阶段建立。

## 14. UI 与报告设计

### 14.1 Streamlit 页面

- 页头：项目说明、隐私提示、演示模式状态。
- 输入区：
  - Step 1 上传或粘贴简历，显示解析预览和警告；
  - Step 2 岗位名、公司名、JD、加载示例；
  - Step 3 开始分析按钮和配置可用性提示。
- 进度区：使用状态机阶段生成中文状态，不展示模型内部推理。
- 结果区：
  - 综合结论；
  - 逐项匹配；
  - 简历优化；
  - 面试准备；
  - 结构化数据。
- 下载区：Markdown 和 JSON 两个独立按钮。

### 14.2 Markdown 报告顺序

1. 报告元信息与免责声明；
2. 岗位基本信息；
3. 综合结论、最终分数与上限原因；
4. 分维度评分；
5. 岗位要求逐项匹配表；
6. 三项核心优势；
7. 三项主要缺口与修复类型；
8. 投递建议及投递前行动；
9. 简历保留、强化、弱化和排序建议；
10. 原始表述、优化表述、理由、要求映射、待确认信息；
11. 五道面试题与回答框架；
12. 分析限制与用户核对提醒。

JSON 使用 `AnalysisReport` 的 `schema_version=1.0`，以 UTF-8、缩进 2 空格输出。Markdown 与 JSON 不包含 API key、内部提示词、日志栈或本地路径。

## 15. 测试策略

### 15.1 单元测试

1. TXT UTF-8 和 UTF-8 BOM 解析；
2. DOCX 段落与表格解析；
3. 文本型 PDF 分页解析；
4. 空文件和空文本；
5. 不支持文件类型和扩展名/MIME 不一致；
6. Pydantic 缺字段、非法枚举、extra 字段；
7. 证据字符区间与引用完整性；
8. 四种匹配状态映射；
9. importance/type/mandatory 因子；
10. 单维度和多维度权重和；
11. 缺失维度重新归一化；
12. 隐性要求 10% 上限；
13. 分维度得分和总分；
14. 硬门槛 confirmed/unknown 上限；
15. 推荐等级边界值；
16. Markdown 章节和特殊字符；
17. JSON Schema 版本和可反序列化；
18. 改写新增数字、工具和强化词拦截；
19. 缺配置、缺 API key 和 Mock 模式；
20. PII 日志过滤。

评分测试使用表驱动和参数化用例，关键边界使用精确 Decimal 断言。评分引擎不得导入 LLM SDK。

### 15.2 集成测试

固定夹具包括匿名简历、匿名 JD、四个模型阶段的固定 JSON 响应、预期要求、预期匹配、精确预期分数和最终报告关键字段。`MockLLMClient` 按 task 名返回夹具，测试完整 orchestrator：

```text
input → parse → extract → match → validate → score → advice → validate → render
```

断言：

- 不访问网络；
- 不读取真实 API key；
- 每项要求恰好有匹配；
- 精确分数和推荐等级符合策略；
- 五道面试题；
- Markdown 和 JSON 同源；
- 失败夹具产生规定错误码而非崩溃。

Streamlit 使用 `streamlit.testing.v1.AppTest` 做启动、示例加载、按钮和结果标签页的烟雾测试。

### 15.3 验收命令

计划中的标准命令：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m streamlit run app.py
```

上传前还需在新的临时虚拟环境重复安装与测试，并用 Mock 示例完成一次端到端演示。当前阶段不执行这些未来依赖安装和业务测试。

## 16. 48 小时实施边界

### 16.1 必须完成

- Streamlit 单页输入、进度、结果标签页和下载；
- PDF、DOCX、TXT、粘贴文本；
- 简历和 JD 结构化提取；
- 逐项证据匹配；
- 确定性评分、缺失维度、硬门槛和推荐等级；
- 优势、缺口、投递建议；
- 证据约束型简历改写；
- 五道面试题；
- 最终一致性和基础防虚构校验；
- Markdown 和 JSON；
- 匿名示例和离线 Mock 演示；
- 核心单元、集成和 UI 烟雾测试；
- 完整 README、架构、实施说明和发布检查表；
- 阶段化本地 Git 提交。

### 16.2 明确不实现

- OCR 和图片简历；
- 精准版式恢复和简历编辑器；
- PDF 报告导出；
- React/API 前后端分离；
- 数据库、账号、多用户与历史报告；
- 向量数据库、复杂 RAG 和多 Agent 通信；
- 招聘网站抓取和链接解析；
- 多岗位对比；
- Docker、付费、复杂动画和国际化界面；
- 自动创建 GitHub 仓库或自动推送。

如时间不足，保留顺序为：正确评分与证据校验 > 离线演示与测试 > 报告完整性 > UI 美化。增强项不能占用 MVP 验收时间。

## 17. 本地 Git 策略

当前空目录可初始化 Git 并将分支命名为 `main`。不添加远程，不执行 push，不修改用户的全局 Git 配置。

建议提交序列，每个提交只包含实际完成且已验证的内容：

1. `docs: add JobFit Agent architecture`
2. `chore: initialize project structure and configuration`
3. `test: define models and scoring contracts`
4. `feat: add resume document parsers`
5. `feat: add structured resume and job extraction`
6. `feat: add evidence matching workflow`
7. `feat: add deterministic scoring engine`
8. `feat: add diagnosis rewrite and interview generators`
9. `feat: add report validation and exports`
10. `feat: add Streamlit interface`
11. `test: add offline integration and UI tests`
12. `docs: complete README and release checklist`
13. `fix: resolve final validation issues`，仅在确有修复时创建。

每次提交前运行与改动相称的测试；最终提交前运行完整测试。禁止把未完成特性包装成完成提交，禁止压缩成一个巨大提交。

若 Git 因未配置用户身份拒绝提交，本地文件和暂存区保持安全，向用户报告并等待其配置真实身份；不使用虚构姓名或邮箱绕过。

## 18. GitHub 发布策略

本地 MVP 完成并经用户明确授权前，不执行 `git remote add`、`gh repo create`、`git push` 或 Pull Request。

### 18.1 上传前门禁

- 全部测试通过且结果有命令输出；
- Mock 端到端演示通过；
- 从干净虚拟环境成功安装和启动；
- README 覆盖项目简介、功能、截图、工作流、架构、技术栈、目录、安装、环境变量、启动、示例、输出、测试、评分、隐私、限制和路线图；
- `.env.example` 无真实值，`.env` 被忽略且未进入历史；
- 密钥扫描和隐私人工检查通过；
- 没有真实简历、手机号、地址、私人邮箱或内部材料；
- 没有缓存、虚拟环境、日志、上传文件和生成报告；
- main 分支、工作区干净、提交历史清晰；
- 用户确认仓库公开性、许可证与目标 GitHub 账号。

### 18.2 仓库建议

- Name: `jobfit-agent`
- Description: `An evidence-grounded AI agent for job matching, resume diagnosis and interview preparation.`
- Topics: `ai-agent`, `resume-analysis`, `job-matching`, `streamlit`, `python`, `llm`, `pydantic`, `career-tools`
- License: 建议 MIT，但只有用户确认后才加入最终许可证和发布设置。

## 19. 风险与降级

| 风险 | 影响 | 预防 | 降级 |
|---|---|---|---|
| 模型 Schema 不稳定 | 工作流中断 | 原生结构化输出、严格 Schema、低温度 | 一次修复和一次完整重试，随后安全失败 |
| 证据字符区间由模型给错 | 匹配不可追溯 | 本地全文精确查找和 segment 引用 | 找不到则证据无效，状态降为 unknown |
| PDF 提取质量差 | 简历事实缺失 | 页面级预览和警告 | 用户粘贴纯文本 |
| 需求提取过细或重复 | 权重失真 | 原子化规则、normalized_key 去重 | Validator 拒绝重复 ID/键，重新提取 |
| 大模型产生强化表述 | 虚构风险 | 证据 IDs、词项与数字校验 | 移入需确认区或删除该建议 |
| 模型服务不可用 | 无法现场演示 | 固定 Mock 供应商与匿名示例 | 完全离线演示 |
| 依赖安装耗时 | 延误开发 | 精简依赖、锁定兼容范围 | 使用 Python 3.11/3.12 新虚拟环境 |
| Streamlit 状态重跑 | 重复调用和费用 | session_state 缓存已验证阶段结果 | 用户显式按钮触发，按 request_id 去重 |
| 48 小时范围过大 | 质量下降 | 严格 MVP 顺序 | 取消 UI 美化、PDF 导出、Docker和扩展项 |
| Git 身份缺失 | 无法提交 | 开始前检查 | 等待用户配置真实身份，不影响文件成果 |
| 密钥或 PII 入库 | 严重隐私事故 | ignore、日志过滤、匿名夹具、扫描 | 阻止发布并清理历史后重新审查 |

## 20. 可逐项验收清单

- [ ] README 可让新用户在干净环境安装和运行。
- [ ] TXT、DOCX、文本型 PDF 均有成功测试。
- [ ] 空文件、不支持类型和解析失败不会令应用崩溃。
- [ ] 解析失败时可使用粘贴文本继续。
- [ ] 用户可输入岗位名、公司名和 JD，或加载匿名示例。
- [ ] ResumeProfile 和 JobProfile 通过 Pydantic 严格校验。
- [ ] 每项岗位要求都有唯一类别、来源区间和匹配结果。
- [ ] matched/partial 均有通过字符区间校验的简历证据。
- [ ] unknown 不被表述为用户确定不具备。
- [ ] 单项权重和为 100.00，评分可独立复算。
- [ ] 缺失维度、隐性要求上限和硬门槛规则均有边界测试。
- [ ] 大模型不能写入最终权重、状态分值、总分和推荐等级。
- [ ] 综合分、分维度分、上限原因和硬门槛可解释。
- [ ] 最多三项核心优势和三项主要缺口符合证据约束。
- [ ] 投递建议与确定性规则一致。
- [ ] 改写不会无依据新增数字、工具、职责级别和成果。
- [ ] 恰好生成五道面试题及回答框架。
- [ ] Markdown 和 JSON 来自同一报告对象并可下载。
- [ ] 缺 API key 有明确提示，Mock 演示无需 API key。
- [ ] 普通测试只使用 Mock 或固定夹具，不产生 API 费用。
- [ ] 日志不包含完整简历、JD、PII 和密钥。
- [ ] 示例数据匿名且不含真实隐私。
- [ ] `.env`、虚拟环境、缓存、日志和用户上传文件不会进入 Git。
- [ ] 完整单元、集成和 UI 烟雾测试通过。
- [ ] 本地提交按阶段形成，默认分支为 main。
- [ ] 上传前安全门禁全部通过。
- [ ] 未经用户明确授权没有 GitHub 远程创建、修改或推送。

## 21. 架构自审结论

### 21.1 范围

架构只包含 48 小时内直接支撑 MVP 的单机组件。数据库、向量库、多 Agent、React/API、OCR、PDF 导出和 Docker 均被排除，不阻塞核心闭环。

### 21.2 职责与一致性

Parser、Extractor、Matcher、Scorer、Generator、Validator、Renderer 和 Orchestrator 均有唯一主职责和明确类型边界。模型 ID、证据引用、要求覆盖和报告引用关系一致。UI 不执行业务判断，供应商适配器不参与评分。

### 21.3 评分可执行性

维度总分、状态映射、单项因子、缺失维度重归一化、隐性要求上限、Decimal 精度、硬门槛上限和推荐等级均已定义。大模型不生成生效权重和最终分数。

### 21.4 防虚构和结构稳定性

事实通过字符区间回溯，匹配通过 requirement/evidence ID 闭环，改写执行数字、专名和高风险词检查。所有 LLM 输出执行严格 Schema、有限修复和保守失败，不把无效部分传给评分。

### 21.5 安全与 Git

内存优先处理、日志脱敏、匿名示例、Mock 演示和发布前扫描覆盖主要隐私风险。当前阶段只允许本地初始化和提交，不配置远程、不上传。Git 身份缺失时不伪造作者。

本规格未发现互相矛盾的数据字段、未定义的评分接口或依赖增强功能才能完成的 MVP 路径。
