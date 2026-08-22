# JobFit Agent 正式岗位知识审核模板

## 1. 审核角色与职责

### Researcher

- 打开原页面，核验标题、发布主体、URL、日期和访问状态；
- 记录来源等级、适用地区、时效性和版权边界；
- 不复制完整 JD 或报告，不将搜索摘要当作来源；
- 将来源初始状态设为 `pending`。

### Author

- 基于已登记来源进行原创归纳；
- 使用当前 Seed Schema、稳定 ID 和合法枚举；
- 区分岗位知识、候选人证据和评分规则；
- 为每个条目建立直接来源和交叉验证记录；
- 不自行批准刚刚编写的条目。

### Reviewer

- 检查事实、岗位边界、实习生层级、来源、版权和安全；
- 核验条目没有夸大、岗位污染或候选人事实；
- 决定 `approved`、需要修改或 `rejected`；
- 审核意见必须可操作并关联条目 ID。

### Publisher

- 检查版本完整性、审核状态、content hash、引用关系和发布门禁；
- 确认所有正式内容均可公开归纳；
- 先完成 draft 导入和只读验收，再显式发布；
- 不在同一动作中生成内容并自动批准发布。

同一人可以承担多个角色，但必须分步骤留下独立记录。Author 完成编写后，至少进行一次独立的 Reviewer 检查，再由 Publisher 执行版本级门禁。

## 2. 单条知识审核表

### 2.1 基础信息

| 字段 | 填写内容 |
| --- | --- |
| 知识条目 ID |  |
| 岗位画像 ID / 名称 |  |
| 条目类型 | role profile / requirement / evidence pattern / interview question / chunk / source |
| 编写人 |  |
| 审核人 |  |
| 审核日期 |  |
| 知识版本 | 2026.08.1 |
| 直接 source ID |  |
| 交叉验证 source ID |  |

### 2.2 内容审核

- [ ] 条目确实属于目标岗位，而不是相邻岗位主体内容。
- [ ] 条目符合实习生或早期职业层级。
- [ ] 纳入和排除边界清晰，没有混入纯算法、数据工程、投资研究等相邻职责。
- [ ] 有明确、可访问的直接来源。
- [ ] 内容为原创归纳，没有大段复制。
- [ ] 没有夸大来源结论，没有把“常见”写成“必须”。
- [ ] 没有把单一企业工具或流程写成行业通用要求。
- [ ] 没有候选人事实、真实简历、真实 JD 或客户信息。
- [ ] 没有改变匹配、评分、hard blocker 或推荐等级边界。
- [ ] `is_common_hard_blocker` 仅作为岗位知识提示。
- [ ] 不包含歧视性或受保护特征要求。
- [ ] 不包含网页指令、Prompt Injection、HTML 或脚本。
- [ ] 字符数、列表数量和枚举值符合 Seed Schema。

### 2.3 来源审核

- [ ] URL 已实际打开，协议为 HTTP(S)。
- [ ] 页面标题与发布主体明确且相互一致。
- [ ] 发布日期真实；无法确认时明确记录“未确认”。
- [ ] `source_type` 与实际来源性质一致。
- [ ] 来源等级和 `reliability_level` 合理。
- [ ] `license_note` 包含权利主体、使用边界和仓库保存范围。
- [ ] 允许在公开仓库保存元数据和原创归纳。
- [ ] 没有完整网页、完整 JD、付费报告正文或大段连续引用。
- [ ] 核心要求满足第二来源交叉验证规则。
- [ ] 页面易失风险和建议复核周期已记录。
- [ ] 来源适用地区和层级没有被过度外推。

### 2.4 技术审核

- [ ] ID 前缀、字符集和稳定性符合规范。
- [ ] 所有外键引用存在且属于同一知识版本。
- [ ] JSON 无重复 key、无额外字段、UTF-8 可解析。
- [ ] `review_status` 使用 `pending`、`approved` 或 `rejected`。
- [ ] `requirement_type`、`importance`、`strength` 等枚举合法。
- [ ] Evidence Pattern 的负面内容位于 `negative_example`，未使用不存在的 `negative` strength。
- [ ] source checksum、chunk content hash 和版本 content hash 可复算。
- [ ] Seed Loader 可加载，引用校验通过。
- [ ] draft 导入可回滚且不会创建仓库内 SQLite。
- [ ] 不含本机绝对路径、用户名、凭据或内部错误信息。

### 2.5 审核结论

选择一项：

- [ ] `approved`：内容、来源、版权和技术约束均通过。
- [ ] revise：保持 `pending`，完成下列修改后重新审核。
- [ ] `rejected`：不进入本知识版本，并记录拒绝原因。

修改意见：

>

Reviewer 签署：____________________

## 3. 岗位画像批次审核表

每个岗位画像完成一批 requirements、patterns 和 questions 后执行：

- [ ] 岗位名称、别名、纳入和排除边界一致。
- [ ] 画像没有与相邻岗位混合。
- [ ] 同一企业来源占比不超过 30%。
- [ ] 核心要求均有一个高权威直接来源或两个独立来源。
- [ ] 工具品牌与底层能力分开。
- [ ] 要求类型和 importance 分布合理，没有把全部条目写成 `must_have` 或 `critical`。
- [ ] 每条 requirement 至少有可解释的 evidence pattern。
- [ ] Interview questions 覆盖主要能力维度，且为原创改写。
- [ ] 所有来源、要求、模式和问题均已审核。
- [ ] 不存在跨岗位画像、跨岗位族或跨版本引用。
- [ ] 条目总量在质量目标范围内，无重复凑数。

批次结论：approved / revise / rejected

## 4. 版本发布审核表

### 4.1 文件与 Schema

- [ ] `manifest.json` 和固定 10 个 JSON 文件齐全，无额外文件。
- [ ] Seed Schema 为 `1.0`，知识版本为 `2026.08.1`。
- [ ] 知识版本 Seed 初始状态为 `draft`。
- [ ] 所有 JSON 可解析、无重复 key、无额外字段。
- [ ] ID、枚举、长度、数量、URL、日期和 hash 均合法。

### 4.2 内容完整性

- [ ] 三个岗位族均有 active role profile。
- [ ] 每个 active role profile 至少有一个 active requirement。
- [ ] 所有正式 role、dimension、requirement、pattern、source、chunk 和 question 均为 `approved`。
- [ ] 每个 requirement、pattern、question 和 chunk 都有来源。
- [ ] 每个来源均被使用，`license_note` 非空。
- [ ] `source_role_links` 无重复且关系语义正确。
- [ ] 不存在 draft、retired、跨版本或缺失来源的引用。
- [ ] content hash 与规范化 Seed 复算结果一致。

### 4.3 安全与版权

- [ ] 未提交完整第三方网页、完整 JD 或付费报告正文。
- [ ] 所有条目为原创归纳，短引用符合使用边界。
- [ ] 不含真实简历、候选人、客户或企业内部资料。
- [ ] 不含路径、邮箱、手机号、身份证、密钥或 Prompt。
- [ ] 不含 HTML、脚本、网页指令或 Prompt Injection。
- [ ] 不含歧视性要求。
- [ ] 所有来源的公开仓库使用边界已批准。

### 4.4 产品边界

- [ ] 知识要求未进入 JD 要求列表或评分分母。
- [ ] common hard blocker 未自动触发封顶。
- [ ] reliability 未转换为评分权重。
- [ ] Evidence Pattern 未成为候选人 Resume Evidence。
- [ ] 产品分析实习生未进入本版本。
- [ ] 用户简历、JD 和报告未被持久化。

### 4.5 技术验收

- [ ] 当前 Loader 可加载正式目录。
- [ ] content hash 计算确定。
- [ ] draft 首次导入成功。
- [ ] 重复导入幂等。
- [ ] 发布门禁对未审核、缺来源和 hash 不一致均 Fail Closed。
- [ ] 临时数据库中的检索、Citation、Report 1.1、Markdown/JSON 和 UI 合成验收通过。
- [ ] FTS5 与关键词回退均产生确定性结果。
- [ ] 测试不访问网络、不调用真实模型、不在仓库留下 SQLite。
- [ ] 在正式导入运行时数据库前已完成完整回归。

### 4.6 Publisher 决策

- [ ] 批准 draft 导入。
- [ ] 批准发布为 `published`。
- [ ] 暂缓发布并返回修改。
- [ ] 拒绝本版本。

Publisher：____________________

日期：____________________

发布备注：

>

## 5. Fail-Closed 条件

出现以下任一情况立即停止发布：

- 来源 URL、主体、日期或版权边界被编造；
- 核心 requirement 只有 Low 来源；
- 任何正式条目未审核或来源缺失；
- 发现大段复制、真实 JD、候选人或客户数据；
- content hash、引用或版本不一致；
- Seed Loader、draft 导入或发布门禁失败；
- 知识内容被用于改变评分、hard blocker 或候选人事实；
- 正式数据库只能通过手工编辑才能工作。
