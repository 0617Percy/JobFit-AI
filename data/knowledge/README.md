# JobFit Agent 正式知识目录

## 1. 事实源与运行时副本

受版本控制的 JSON Seed 是岗位知识的唯一事实源。SQLite 数据库是由已审核 Seed 显式导入后生成的运行时副本，可以重建，不得手工维护，也不得提交 Git。

当前目录包含正式知识Seed版本`2026.08.1`。该版本控制Seed保持`draft`，182个可审核实体均已由Publisher批准为`approved`；生产运行数据库尚未导入或发布。测试合成知识继续放在测试专用fixture中，不得迁入正式目录。

## 2. 当前目录

首个正式版本使用：

```text
data/knowledge/
├── README.md
└── versions/
    └── 2026.08.1/
        ├── manifest.json
        ├── knowledge_base_version.json
        ├── job_families.json
        ├── role_profiles.json
        ├── competency_dimensions.json
        ├── role_requirements.json
        ├── evidence_patterns.json
        ├── knowledge_sources.json
        ├── knowledge_chunks.json
        ├── interview_questions.json
        └── source_role_links.json
```

`versions/2026.08.1/`由Phase 11.9B创建，并在Phase 11.10C-F完成Publisher批准状态转换。事实源文件仍保持`knowledge_base_version.status=draft`；`published`只存在于显式发布后的SQLite生命周期中。

## 3. 编写与发布流程

```text
来源核验
→ 来源元数据登记
→ 原创归纳
→ 单条人工审核
→ 岗位批次审核
→ 严格 Seed 校验
→ 计算 content hash
→ 临时 SQLite draft 导入
→ 幂等和检索验收
→ Publisher 审核
→ 显式发布 published 版本
```

禁止：

- 手工编辑 SQLite；
- 自动抓取招聘网站；
- 保存完整第三方网页或完整 JD；
- 将 LLM 草稿自动标记为 `approved`；
- 将用户简历、JD 或报告写入公共知识库；
- 在仓库内创建运行时数据库文件。

## 4. Phase 11.9B 精确任务书

### 4.1 版本与范围

- 正式知识版本：`2026.08.1`
- 版本 ID：`kbv-2026-08-1`
- Seed Schema：`1.0`
- 初始状态：`draft`
- 岗位族：AI 应用、数据分析、技术战略
- 产品分析实习生：不纳入，延后至 v1.1.x

当前应用配置默认知识版本仍是`2026.07.1`。`2026.08.1`已经完成Publisher批准和临时SQLite发布验证，但生产默认配置只能在Phase 11.10D完成正式运行数据库导入、publish和回归验收后切换。

### 4.1.1 当前批准状态

- 版本控制Seed状态：`draft`
- 可审核实体：182个，全部`approved`
- Approved Canonical Hash：`346542eb0c405643a08ebc4bffdab9b5bce22a1b7227f5ad2b27f12e3d1ef7f4`
- 临时SQLite：已完成导入、幂等、publish、检索、Citation、Report和UI验证
- 默认运行数据库：未导入、未发布
- 默认知识版本：`2026.07.1`

### 4.2 Role Profile

首批创建三个核心画像：

- `rp-ai-application-intern`
- `rp-data-analyst-intern`
- `rp-technology-strategy-intern`

只有实际编制中发现清晰、来源充分的差异时才增加子画像；总数不得超过 5。

### 4.3 条目数量目标

| 岗位 | Requirement | Evidence Pattern | Interview Question | Source | Chunk |
| --- | ---: | ---: | ---: | ---: | ---: |
| AI 应用实习生 | 14—16 | 14—18 | 8—10 | 7 | 0—3 |
| 数据分析实习生 | 14—16 | 14—18 | 8—10 | 7 | 0—3 |
| 技术战略实习生 | 12—16 | 12—18 | 8—10 | 7 | 0—3 |

总目标：40—48 条 requirements、40—54 条 patterns、24—30 道 questions、21 个候选 sources，以及仅在结构化字段不足时使用的少量 chunks。质量不达标时允许少于上限，不得重复凑数。

### 4.4 Source ID 清单

AI 应用：

- `ks-ai-openai-emerging-talent`
- `ks-ai-openai-applied-agent`
- `ks-ai-anthropic-effective-agents`
- `ks-ai-microsoft-ai-103`
- `ks-ai-nist-rmf-1-0`
- `ks-ai-skills-england-st0763`
- `ks-ai-google-managing-ml-projects`

数据分析：

- `ks-da-apple-japan-data-analyst-intern`
- `ks-da-amazon-bi-intern-3149400`
- `ks-da-microsoft-pl-300`
- `ks-da-google-data-analytics-certificate`
- `ks-da-onet-bi-analysts`
- `ks-da-skills-england-st0118`
- `ks-da-bls-operations-research`

技术战略：

- `ks-ts-openai-competitive-intelligence`
- `ks-ts-amazon-wwtd-strategy-2990306`
- `ks-ts-bcg-digital-consultant`
- `ks-ts-oecd-sti-outlook-2025`
- `ks-ts-jrc-technology-foresight-2023`
- `ks-ts-uk-futures-toolkit-2024`
- `ks-ts-wef-future-jobs-2025`

21个来源已经完成版权、适用范围、条目映射和动态页面复核，并在Phase 11.10C-F设为`approved`。企业岗位页只保存元数据和原创归纳；后续新增、替换或扩展来源必须重新审核。

### 4.5 Competency Dimension 清单

AI 应用：`ai_model_application`、`python_engineering`、`prompt_structured_output`、`agent_workflow`、`data_processing`、`evaluation_debugging`、`deployment_integration`、`business_understanding`、`communication`。

数据分析：`sql`、`data_cleaning`、`python_analysis`、`metrics_framework`、`statistical_analysis`、`visualization`、`business_insight`、`reporting`、`collaboration`。

技术战略：`technology_trend_research`、`industry_competitive_analysis`、`strategic_structuring`、`technology_business_value`、`research_methods`、`report_writing`、`executive_communication`、`cross_functional_communication`。

这些是知识层维度，`scoring_category_hint` 默认留空，不改变现有六维评分。

### 4.6 文件编制顺序

1. 创建 `manifest.json` 和 draft `knowledge_base_version.json`。
2. 编写 `knowledge_sources.json`，完成 URL、日期、license、checksum 和来源审核。
3. 编写 `job_families.json` 与 `role_profiles.json`，完成岗位边界审核。
4. 编写 `competency_dimensions.json`，确认不映射评分权重。
5. 编写 `source_role_links.json`，标记 supports、contrasts 和 background。
6. 按岗位分三批编写 `role_requirements.json`。
7. 在每批 requirement 审核后编写 `evidence_patterns.json`。
8. 编写原创 `interview_questions.json`。
9. 仅在必要时编写 `knowledge_chunks.json`，否则提交空列表。
10. 运行全包校验、content hash、临时 draft 导入和发布前验收。

### 4.7 每批审核门禁

- 来源批：URL 实际可访问；标题、主体、日期、license 和公开仓库边界明确。
- 画像批：纳入、排除、相邻岗位和实习生层级通过审核。
- Requirement 批：直接来源和交叉来源齐全；类型和 importance 未夸大。
- Pattern 批：只描述证据形式，不包含候选人事实；negative 使用合法字段。
- Question 批：原创、符合层级、expected points 和 follow-up 合法。
- 版本批：所有正式条目 `approved`、引用闭合、content hash 一致、无不安全文本。

任一门禁失败时保持 draft，不执行运行时数据库导入或发布。

### 4.8 Seed 验证顺序

当前仓库没有独立的知识Seed CLI，不应在文档中声称存在。多行验证代码应写入仓库外临时`.py`文件，再由项目Python执行，避免Windows PowerShell对复杂`python -c`引号的破坏。正式合同测试会从实际Seed重新计算Canonical Hash。

正式Seed验证使用实际存在的测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/knowledge/test_official_seed_contract.py
.\.venv\Scripts\python.exe -m pytest tests/integration/test_official_knowledge_publication.py
.\.venv\Scripts\python.exe -m pytest tests/knowledge
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

`test_official_seed_contract.py`锁定数量、审核状态、内容Hash和状态边界；`test_official_knowledge_publication.py`覆盖临时SQLite导入、幂等、publish、immutable、三岗位检索隔离、Citation、Report和Streamlit UI。

### 4.9 正式数据库导入前验收条件

- 固定 10 个 JSON 与 manifest 全部通过 Loader。
- 21 个候选来源完成逐项审核；未批准来源已删除或替换。
- 每条知识均为原创归纳并有已批准来源。
- 三个岗位的边界和数量达到质量目标。
- 所有 review status 为发布允许的 `approved`。
- content hash 可重复计算且结果稳定。
- 临时 SQLite 首次 draft 导入成功，重复导入幂等。
- 不存在跨岗位、跨版本、缺来源或未审核引用。
- 评分、EvidenceMatcher、Prompt 和用户数据边界未改变。
- 完整测试、Ruff、pip check 和 diff check 通过。
- Reviewer 与 Publisher 完成版本审核并显式授权。

上述Publisher与临时SQLite门禁已经满足，但这不等于生产发布。Phase 11.10D获得单独授权前，不导入用户默认运行数据库，不在生产SQLite发布`2026.08.1`，也不修改默认知识版本`2026.07.1`。
