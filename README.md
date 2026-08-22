# JobFit AI

> 面向大学生、应届生与 0–2 年职场新人的 AI 岗位适配分析助手。

**当前版本：Public Beta · v1.1.0-beta.1**

JobFit AI 通过分析你的 **简历 + 目标岗位 JD**，帮助你回答几个求职中最关键的问题：

- 这个岗位到底适不适合我？
- 我的优势在哪里？
- 哪些要求还缺少证据或需要进一步确认？
- 这份简历应该怎么优化？
- 面试最可能被追问什么？
- 现在应该优先补什么，还是直接投递？

JobFit AI 的目标不是简单做关键词匹配，而是把岗位要求、简历证据和求职建议连接起来，形成一份**可解释、可追踪、面向实际投递决策的岗位适配分析报告**。

---

## 适合谁使用

JobFit AI 主要面向：

- 在校大学生
- 应届毕业生
- 0–2 年工作经验的早期职场候选人
- 正在寻找 AI、数据、产品、技术及相关岗位的人群

尤其适合：

> 经历并不少，但不知道自己的项目、竞赛、实习和技能到底能否支撑目标岗位的人。

---

## 核心能力

### 1. 岗位要求拆解

从 JD 中识别并结构化岗位要求，包括：

- 核心职责
- 硬性门槛
- 支撑能力
- 加分项
- 岗位级别与经验要求

避免只依赖关键词数量判断匹配度。

---

### 2. 简历证据分析

从简历中提取能够支持岗位要求的真实经历，例如：

- 项目经历
- 实习 / 兼职经历
- 技能与工具
- 课程与专业背景
- 竞赛与成果
- 可验证的个人贡献

JobFit AI 不会为了提高匹配度主动虚构不存在的经历。

---

### 3. 岗位要求 × 简历证据匹配

逐项判断：

- 当前简历是否存在相关证据
- 证据与岗位要求的相关程度
- 当前能力是否可以确认
- 哪些项目可以直接支撑岗位
- 哪些要求仍然缺少证据

---

### 4. 岗位匹配分

JobFit AI 会基于结构化的岗位要求与简历证据匹配结果，通过规则系统计算岗位匹配分。

匹配分用于辅助判断：

> 当前简历与该岗位之间的整体适配程度。

它不是招聘通过率，也不代表企业最终录用概率。

---

### 5. 投递建议

系统综合考虑：

- 岗位匹配情况
- 硬性资格条件
- 岗位级别匹配
- 关键能力缺口
- 当前分析置信度

给出相对保守的投递建议。

例如：

- 优先投递
- 建议投递
- 挑战投递
- 暂不建议投递

---

### 6. 简历优化建议

JobFit AI 会区分不同类型的问题：

- 已经做过，但简历表达不够清晰
- 已经存在相关经历，但证据没有被充分呈现
- 当前确实缺少某项能力或项目，需要后续补强

避免把“优化简历”简单理解成包装经历。

---

### 7. 面试准备

根据：

- 目标岗位要求
- 你的简历经历
- 当前优势
- 证据不足项
- 潜在风险点

生成针对性的面试问题与准备方向。

重点不是生成通用题库，而是回答：

> 面试官为什么可能问这个问题，以及你应该准备什么证据。

---

## 使用流程

Public Beta 当前采用三步流程：

### ① 上传材料

提供：

- 简历
- 目标岗位 JD

简历支持粘贴文本，也可根据当前版本支持的文件格式上传。

---

### ② 信息确认

JobFit AI 会先解析简历和 JD。

在进入完整分析前，你可以检查关键信息是否正确。

---

### ③ 生成岗位分析报告

确认后，系统自动完成分析并生成完整报告，包括：

- 总体结论
- 投递建议
- 岗位匹配分
- 硬性门槛状态
- 岗位优势
- 待确认与待补强项
- 岗位要求逐项匹配
- 简历优化建议
- 下一步行动建议
- 面试准备
- 分析依据与边界

---

# 本地运行

## 环境要求

推荐：

- Python 3.11
- Python 3.12

建议使用独立虚拟环境。

---

## Windows

```powershell
git clone https://github.com/0617Percy/JobFit-AI.git
cd JobFit-AI

python -m venv .venv

.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

.\.venv\Scripts\python.exe -m streamlit run app_v2.py
```

启动后访问：

```text
http://localhost:8501
```

---

## macOS / Linux

```bash
git clone https://github.com/0617Percy/JobFit-AI.git
cd JobFit-AI

python3 -m venv .venv

./.venv/bin/python -m pip install -e ".[dev]"

./.venv/bin/python -m streamlit run app_v2.py
```

---

# 分析模式

## 演示模式

无需 API Key。

适合：

- 查看产品流程
- 本地体验界面
- 开发调试
- 快速了解 JobFit AI 的报告结构

---

## DeepSeek 分析

真实岗位分析需要使用 DeepSeek API。

JobFit AI 采用 **BYOK（Bring Your Own Key）** 模式：

> 用户使用自己的 DeepSeek API Key。

启动应用后：

1. 在侧边栏选择 **DeepSeek 分析**
2. 输入自己的 DeepSeek API Key
3. 可先进行连接验证
4. 上传简历与 JD
5. 开始岗位分析

JobFit AI 不会在仓库中附带任何真实 API Key。

请勿将真实 API Key 提交到 Git。

如需使用环境变量，请参考：

```text
.env.example
```

---

# Beta 版本说明

JobFit AI 当前仍处于 **Public Beta** 阶段。

使用时请注意以下边界。

### 1. 分析结果可能存在一定运行差异

JobFit AI 的部分环节需要大语言模型完成语义理解，例如：

- 岗位要求识别
- 简历证据理解
- 要求与证据之间的语义判断

因此，即使输入相同的 Resume 与 JD，不同运行之间仍可能出现少量语义结果差异。

匹配分的计算规则本身是规则化的，但其上游结构化语义结果可能受到模型输出影响。

---

### 2. “缺少证据”不等于“没有能力”

如果当前简历没有足够信息证明某项能力，JobFit AI 会优先将其视为：

> 当前证据不足 / 能力待确认

而不是直接判断：

> 候选人不具备该能力。

---

### 3. 硬性资格需要人工确认

例如：

- 毕业届次
- 学历
- 工作年限
- 专业限制
- 身份 / 地域 / 时间要求

如果简历中没有足够信息，系统可能将其标记为“待确认”。

最终仍应以招聘企业真实要求为准。

---

### 4. 匹配分不是录用概率

JobFit AI 的匹配分表示：

> 当前已知简历证据与岗位要求之间的结构化适配程度。

它不代表：

- 面试通过率
- Offer 概率
- 招聘企业最终评价
- 候选人的绝对能力水平

请结合实际招聘环境与个人情况进行判断。

---

# 隐私与安全

JobFit AI Public Beta 默认采用本地运行 + BYOK 模式。

建议：

- 不要把真实 API Key 写入代码
- 不要把 `.env` 提交到 GitHub
- 不要把真实用户简历、JD 或分析报告提交到仓库
- 不要在公开 Issue 中上传包含个人隐私的完整简历

仓库中的测试数据应使用合成数据或脱敏数据。

---

# 开发与测试

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

代码检查：

```powershell
.\.venv\Scripts\python.exe -m ruff check .
```

依赖检查：

```powershell
.\.venv\Scripts\python.exe -m pip check
```

测试默认不需要真实模型 API 调用。

---

# 当前状态

```text
Product: JobFit AI
Version: v1.1.0-beta.1
Stage: Public Beta
Primary UI: Streamlit
Language: 中文优先
Model access: DeepSeek BYOK
```

当前版本重点验证：

- Resume + JD 分析流程
- 岗位要求与简历证据匹配
- 投递建议
- 简历优化建议
- 面试准备
- 面向真实求职场景的产品可用性

---

# Feedback

JobFit AI 仍在持续迭代。

如果你发现：

- JD 解析不准确
- 简历事实识别错误
- 岗位要求判断存在偏差
- 报告建议不合理
- 页面出现异常
- 某类岗位分析效果明显较差

欢迎通过 GitHub Issues 提交反馈。

提交 Issue 时，请尽量避免直接上传包含姓名、手机号、邮箱等个人信息的完整简历。

---

# License

See [LICENSE](LICENSE).

---

## English Summary

**JobFit AI** is an AI-powered resume and job-fit analysis assistant for students, new graduates, and early-career candidates.

Provide a resume and a target job description, and JobFit AI helps analyze:

- job requirements
- resume evidence
- requirement-to-evidence fit
- application recommendation
- resume improvement opportunities
- capability gaps
- interview preparation

JobFit AI is currently in **Public Beta**.

The system is designed to provide evidence-grounded decision support rather than guarantee hiring outcomes.

Different runs may show small variations because large language models participate in semantic extraction and matching.

JobFit AI should therefore be used as a career decision-support tool, not as a replacement for human judgment.
