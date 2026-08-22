# JobFit Agent 正式岗位知识编制规范

## 1. 目的

本规范约束 JobFit Agent 正式 JSON Seed 的内容编写、ID、字段、来源映射、数量和安全边界。它以当前 `KnowledgeSeedBundle`、Seed Loader 和发布门禁为事实来源，不建立第二套格式。

首个拟议正式知识版本为 `2026.08.1`。当前生产配置仍默认 `2026.07.1`；本阶段只记录调整建议，实际配置变更留到 Phase 11.9B 或 11.9C 统一完成。

## 2. Seed 包结构

正式版本目录必须包含 `manifest.json` 和以下 10 个 JSON 文件，文件名与顺序必须匹配当前 Loader：

1. `knowledge_base_version.json`
2. `job_families.json`
3. `role_profiles.json`
4. `competency_dimensions.json`
5. `role_requirements.json`
6. `evidence_patterns.json`
7. `knowledge_sources.json`
8. `knowledge_chunks.json`
9. `interview_questions.json`
10. `source_role_links.json`

约束：

- `manifest.json` 的 `schema_version` 使用当前 Seed Schema `1.0`。
- 正式 Seed 中的知识版本初始状态只能是 `draft`。
- 所有模型拒绝额外字段，列表按稳定 ID 规范化。
- JSON 使用 UTF-8，不允许重复 key、NaN、Infinity、HTML、私钥、凭据、本机路径、真实手机号或身份证格式。
- JSON Seed 是事实源；SQLite 仅是可重建的运行时副本。

## 3. 稳定 ID 与 code

| 实体 | ID 前缀 | 示例 |
| --- | --- | --- |
| 知识版本 | `kbv-` | `kbv-2026-08-1` |
| 岗位族 | `jf-` | `jf-ai-application` |
| 岗位画像 | `rp-` | `rp-ai-application-intern` |
| 能力维度 | `cd-` | `cd-ai-workflow` |
| 岗位要求 | `kr-` | `kr-ai-application-structured-output` |
| 证据模式 | `ep-` | `ep-ai-application-structured-output-strong` |
| 来源 | `ks-` | `ks-ai-openai-applied-agent` |
| 知识片段 | `kc-` | `kc-ai-evaluation-summary` |
| 面试问题 | `iq-` | `iq-ai-debugging-01` |

ID 只能使用小写 ASCII 字母、数字和连字符，并在发布后保持不变。`code` 使用小写字母、数字、下划线或连字符。改写文案不应更换 ID；概念发生实质变化时创建新 ID，并在新版本中明确替代关系。

## 4. 通用内容规则

每条正式知识必须：

- 可追溯到已审核来源；
- 使用原创归纳，不大段复制网页；
- 区分“常见”“优先”和“必须”；
- 区分通用能力与企业特有工具；
- 符合实习生层级，不下放高级岗位资历；
- 不包含候选人事实、不推断候选人具备能力；
- 不预测录用概率或薪酬；
- 不包含年龄、性别、籍贯等受保护特征要求；
- 不修改现有六维评分、权重、hard blocker 和推荐等级；
- 不把知识要求加入本次 JD 的评分分母。

知识维度仅用于解释和展示。`scoring_category_hint` 是可选展示提示，不自动映射现有 ScoringEngine 六维权重。

## 5. Knowledge Version

`knowledge_base_version.json`：

- `id`：建议 `kbv-2026-08-1`；
- `version`：建议 `2026.08.1`；
- `name`：清楚描述首批三岗位正式知识；
- `description`：说明覆盖范围、来源策略和不含用户数据；最多 500 字符；
- `status`：必须为 `draft`。

发布后的 `content_hash` 由规范化 Seed 复算，不手写到版本 Seed。软件版本、报告 Schema 版本、知识版本和检索策略版本必须分开。

## 6. Job Family 与 Role Profile

### 6.1 首批岗位族

- `jf-ai-application`
- `jf-data-analysis`
- `jf-technology-strategy`

每个岗位族包含非空 `description`、最多 30 个去重别名、同一知识版本 ID 和 `is_active=true`。

### 6.2 首批岗位画像

第一版建议每个岗位族一个核心实习生画像：

- `rp-ai-application-intern`
- `rp-data-analyst-intern`
- `rp-technology-strategy-intern`

只有经来源证明存在清晰、可检索差异时才增加子画像；第一版总画像控制在 3—5 个。

字段规则：

- `code` 使用稳定英文语义；
- `name` 同时兼顾用户可读性和岗位边界；
- `seniority` 固定表达实习生或早期职业层级；
- `industry` 可为空，除非画像确实限定行业；
- `description` 1—1000 字符，说明纳入、排除和层级；
- `aliases` 最多 30 个，去重并按稳定顺序；
- `keywords` 最多 50 个，通用能力与特定工具分开；
- `review_status` 只有人工审核后才设为 `approved`；
- `source_role_links` 至少连接直接支撑和边界来源。

## 7. Competency Dimension

### 7.1 AI 应用实习生

- AI 模型应用；
- Python 与工程实现；
- Prompt 与结构化输出；
- Agent 与工作流；
- 数据处理；
- 评估与调试；
- 部署与集成；
- 业务理解；
- 沟通表达。

### 7.2 数据分析实习生

- SQL；
- 数据清洗；
- Python 分析；
- 指标体系；
- 统计分析；
- 可视化；
- 业务洞察；
- 报告表达；
- 协作沟通。

### 7.3 技术战略实习生

- 技术趋势研究；
- 行业与竞争分析；
- 战略结构化；
- 技术商业价值；
- 研究方法；
- 报告写作；
- 管理层表达；
- 跨部门沟通。

同义维度可跨画像复用，但 code 必须稳定。`display_order` 显式设置且确定；`scoring_category_hint` 仅用于展示提示，Phase 11.9B 默认留空，除非审核者能证明不会造成评分误解。

## 8. Role Requirement

每个岗位编制 12—18 条核心要求，总计目标 40—50 条。字段规则：

- `title`：短、具体、可独立理解；
- `description`：1—1000 字符，描述岗位通常需要的行为或产出；
- `requirement_type`：必须使用现有值 `responsibility`、`must_have`、`preferred` 或 `implicit`；
- `importance`：使用 `low`、`medium`、`high` 或 `critical`；
- `is_common_hard_blocker`：仅是知识提示，不能触发当前评分封顶；
- `expected_evidence`：最多 20 条，描述通常认可的简历证据形式；
- `weak_evidence`：最多 20 条，描述缺少范围、行动或结果的弱表述；
- `negative_signals`：最多 20 条，描述需要澄清的风险，不作候选人事实；
- `keywords`：最多 50 个，去重，避免品牌词堆砌；
- `source_id`：使用最直接的一手来源；
- `review_status`：逐条人工审核；
- `is_active`：首版正式条目为 true。

编写规则：

1. `must_have` 和 `critical` 需要一个直接高权威来源，或两个独立的 A/B 级来源交叉验证。
2. Low 来源不能单独支撑 `must_have` 或 `critical`。
3. 单一企业工具通常写入关键词或示例，不写成通用 `must_have`。
4. `implicit` 不得在未出现在当前 JD 时进入评分。
5. `is_common_hard_blocker=true` 不代表本次 JD 已确认 hard blocker，也不能触发 49/69 分封顶。

## 9. Evidence Pattern

每个岗位编制 12—20 条，总计目标 40—60 条。现有 `strength` 只允许：

- `strong`
- `medium`
- `weak`

“negative”不是合法强度枚举。负面或不充分情况应写入 `negative_example`、requirement 的 `negative_signals`，或在描述中标为需确认。

字段规则：

- `role_requirement_id` 必须属于同一版本和岗位画像；
- `evidence_type` 使用稳定 code，如 `project_outcome`、`implementation_detail`、`analysis_artifact`；
- `description` 说明“应寻找何种证据”，不能声称候选人已经具备；
- `positive_example`、`weak_example`、`negative_example` 各最多 500 字符；
- `source_id` 指向支持该证据形式的来源；
- `review_status` 必须单独审核。

示例必须匿名、原创且不含真实候选人经历。Evidence Pattern 不是 Resume Evidence，不得包含简历字符区间。

## 10. Interview Question

每个岗位编制 8—12 道，总计 24—36 道。问题必须原创改写，不复制企业真实面试题。

字段规则：

- `question`：1—500 字符；
- `question_type`：`project_deep_dive`、`technical`、`business_scenario`、`gap_validation` 或 `collaboration_motivation`；
- `expected_points`：1—10 条，描述关注点而非标准答案；
- `follow_up_questions`：最多 5 条；
- `difficulty`：`basic`、`medium` 或 `advanced`，以实习生层级为基准；
- `source_id`：支撑能力维度或问题场景的来源；
- `review_status`：逐题人工审核。

知识库问题只用于参考，最终报告的五道面试题仍由现有 Generator 和 Validator 控制。

## 11. Knowledge Chunk

第一版优先使用结构化字段，每个岗位只保留 0—5 个确有必要的 chunk。

- `chunk_text` 为 1—2000 字符的原创归纳；
- `section` 最多 120 字符；
- `keywords` 最多 50 个；
- `role_profile_id` 可选，但岗位专属 chunk 必须显式关联画像；
- `start_offset` 和 `end_offset` 必须同时存在或同时为空；
- `content_hash` 对规范化 chunk 文本复算；
- 不保存网页指令、HTML、长篇原文、Prompt Injection 或候选人事实。

如果结构化 requirement、pattern 或 question 足以表达内容，不创建 chunk。

## 12. Knowledge Source 与 Source Role Link

每个来源必须包含：

- 稳定 `ks-` ID；
- 非空标题；
- 现有 `source_type`；
- 发布主体；
- HTTP(S) URL；
- 可确认时填写带时区的 `published_at`；
- 带时区的 `collected_at`；
- 最多 1000 字符的 `license_note`；
- `primary`、`high`、`medium` 或 `low`；
- `pending`、`approved` 或 `rejected`；
- 对审核采用的规范化来源材料计算 SHA-256 `checksum`。

`source_role_links` 的 `relation_type` 使用：

- `supports`：直接支撑岗位画像；
- `contrasts`：支撑相邻或排除边界；
- `background`：提供趋势、行业或方法背景。

同一 source、role、version 组合只能出现一次。

## 13. 来源到条目的映射流程

1. Researcher 登记来源元数据和版权边界。
2. Reviewer 先批准来源是否可用于公开仓库归纳。
3. Author 为每个条目选择最直接的 `source_id`，并在人工审核记录中列出交叉验证来源。
4. Role Profile 用 `source_role_links` 表达支持、对照和背景关系。
5. Requirement、Pattern、Question 和 Chunk 的 source 必须存在、属于同一版本并通过审核。
6. 发布前检查所有来源被实际引用，所有知识条目都有来源，且没有跨版本引用。

## 14. 措辞标准

推荐用语：

- “该岗位通常需要……”
- “常见的可信证据包括……”
- “在部分岗位中可能作为优先项……”
- “该要求应以本次 JD 为准……”
- “需要进一步确认范围、行动和结果……”

禁止用语：

- “候选人已经掌握……”
- “具备该能力即可获得录用……”
- “所有公司都要求……”
- “必须精通……”（除非本次 JD 明确且来源足以支持）
- “该知识要求将扣分/加分……”
- 对年龄、性别、籍贯、婚育等受保护特征的要求。

## 15. 数量与去重

| 岗位 | Role Profile | Requirement | Evidence Pattern | Interview Question | Source | Chunk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AI 应用实习生 | 1—2 | 12—18 | 12—20 | 8—12 | 5—8 | 0—5 |
| 数据分析实习生 | 1—2 | 12—18 | 12—20 | 8—12 | 5—8 | 0—5 |
| 技术战略实习生 | 1—2 | 12—18 | 12—20 | 8—12 | 5—8 | 0—5 |

首版总量控制为 3—5 个画像、40—50 条要求、40—60 条证据模式、24—36 道问题、15—24 个来源和少量 chunk。相同语义只保留一个主条目；跨岗位共通能力可复用维度，但岗位要求必须保持画像边界。

## 16. 编制完成门禁

- [ ] 目录含 manifest 和固定 10 个 JSON 文件。
- [ ] 所有 ID、code、枚举和字段长度符合真实 Schema。
- [ ] 所有列表已去重并可确定性排序。
- [ ] 所有引用存在且属于同一知识版本。
- [ ] 每条 requirement、pattern、question、chunk 有来源。
- [ ] 每个来源有 `license_note`、访问日期、checksum 和审核状态。
- [ ] 所有正式条目为原创归纳，无大段第三方正文。
- [ ] 没有候选人事实、真实 JD、客户资料、路径或凭据。
- [ ] common hard blocker、可靠性和知识维度均不改变评分。
- [ ] Seed Loader、content hash、draft 导入和发布前检查全部通过。
