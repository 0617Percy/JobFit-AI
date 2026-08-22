# JobFit Agent v1.1.0 GitHub发布检查表

更新日期：2026-08-05

本清单区分“本地发布准备”“Publisher批准与临时发布验证”“生产运行时发布”和“远程发布”。任何生产数据库、默认版本切换、push、PR、merge、tag或GitHub Release都必须获得对应阶段的明确授权。

## 1. 版本与范围

- [x] `pyproject.toml`项目版本为`1.1.0`
- [x] `jobfit.__version__`为`1.1.0`
- [x] `v1.0.0`稳定tag不移动
- [x] v1.1改动位于`feature/knowledge-base-v1.1`
- [x] 默认知识版本已在Phase 11.10D切换为`2026.08.1`
- [x] Phase 11.10B完成Python 3.12干净环境与双路径验收
- [x] Phase 11.10C完成Publisher批准与临时SQLite发布验证
- [x] Phase 11.10D完成正式运行数据库和本地Release Candidate验收

## 2. 基础产品回归

- [x] TXT、DOCX、文本型PDF和粘贴文本四类输入均有离线E2E
- [x] Evidence只来自当前简历文档
- [x] JD Requirement集合、权重和确定性评分可复算
- [x] 同一成功请求可缓存，下载不重复调用模型
- [x] Markdown和JSON来自同一份已验证Report
- [x] Report Schema 1.0和1.1保持兼容
- [x] Mock模式不需要API Key或网络
- [x] Phase 11.10B完成Streamlit基础模式验收

## 3. 岗位知识回归

- [x] Knowledge enabled覆盖TXT、DOCX、PDF和粘贴文本
- [x] Knowledge disabled保持v1.0基础路径
- [x] enabled与disabled的JD Requirement、Match、Score和Recommendation一致
- [x] Knowledge Requirement不进入评分分母
- [x] `common hard blocker`不触发评分封顶
- [x] 无DB、损坏DB、Schema不兼容和无published版本安全回退
- [x] FTS5与确定性关键词回退已有测试
- [x] no match与ambiguous已有测试
- [x] 伪造、跨版本和越界Citation已有校验
- [x] Prompt Injection Seed在导入前被拒绝
- [x] Session Cache包含知识版本、Hash和策略身份
- [x] 正式Seed的数量、覆盖、审核状态和Canonical Hash有合同测试
- [x] approved正式Seed在临时SQLite完成导入、幂等、publish和immutable验证
- [x] 三个正式岗位画像完成检索隔离与同版本Citation验证
- [x] 正式知识通过Report、Markdown、JSON和Streamlit UI门禁
- [x] Phase 11.10B合成增强模式状态为`available`且不改变分数和推荐

## 4. 正式Seed状态

- [x] 正式Seed版本：`2026.08.1`
- [x] 版本控制Seed状态继续为`draft`
- [x] 岗位方向：AI应用、数据分析、技术战略
- [x] 45条active Requirement均有active Evidence Pattern
- [x] Knowledge Chunk保持0
- [x] Common hard blocker保持0
- [x] 21个来源完成Publisher版权、适用范围和动态URL最终复核
- [x] 182个可审核实体全部由Publisher批准为`approved`
- [x] Approved Canonical Hash：`346542eb0c405643a08ebc4bffdab9b5bce22a1b7227f5ad2b27f12e3d1ef7f4`
- [x] 临时SQLite published版本完成导入、索引、检索、Citation、Report和UI验收
- [x] 默认运行数据库通过影子数据库导入、验证和原子替换并published
- [x] 默认知识版本从`2026.07.1`切换为`2026.08.1`

> 版本控制Seed保持`draft`，182个实体为`approved`。`published`只存在于显式发布后的SQLite运行时生命周期中；正式运行SQLite和本地默认版本已切换到`2026.08.1`，运行数据库和备份不进入Git。

## 5. 测试与质量

- [x] Phase 11.9C-F完整基线：`734 passed`
- [x] Phase 11.10A-F完整测试：`745 passed`
- [x] Phase 11.10B干净Python 3.12环境：745项测试，0失败、0错误、0跳过
- [x] Phase 11.10B Branch Coverage：91.71%
- [x] Phase 11.10B Streamlit健康端点：`ok`
- [x] Phase 11.10C-F完整测试：`750 passed`，Branch Coverage：92%
- [x] Phase 11.10D新增影子发布、备份、补偿和受保护回滚门禁
- [x] Phase 11.10D完整测试：`763 passed`，0失败、0错误、0跳过
- [x] Phase 11.10D Branch Coverage不低于90%
- [x] Ruff通过
- [x] pip check通过
- [x] `git diff --check`通过
- [x] 普通测试通过fixture阻断外部网络
- [x] 本地`.env`不影响测试
- [x] 无仓库SQLite、WAL/SHM、上传或报告残留

Phase 11.10D本地Release Candidate提交只有在正式运行时发布成功、完整pytest、branch coverage不低于90%、Ruff、pip check、有效配置复验和Git门禁全部通过后才能生成。

## 6. 文档

- [x] README已更新为v1.1功能和六个结果标签
- [x] README说明知识不是简历证据且不改变评分
- [x] README说明Seed、SQLite、FTS回退和安全降级
- [x] README说明Seed为`draft/approved`、正式运行SQLite为`published`且二者彼此隔离
- [x] README说明隐私、限制和Publisher边界
- [x] `docs/architecture.md`反映当前生命周期
- [x] Publisher设计、实施计划、审核、决策和运行手册已归档
- [x] 保留历史Spec与Plan
- [x] 截图明确标注为v1.0基础界面
- [ ] v1.1截图更新获得单独授权并完成匿名复核
- [x] Phase 11.10D本地运行时发布记录已生成

## 7. 安全与隐私

- [x] `.env`未被Git跟踪
- [x] SQLite、WAL/SHM未被Git跟踪
- [x] 上传文件和报告目录未被Git跟踪
- [x] 未提交真实简历、手机号、地址或私人邮箱
- [x] 未提交真实API Key、Token、密码或私钥
- [x] 日志不记录完整简历、JD、Prompt或模型完整响应
- [x] 正式Seed安全扫描和引用完整性测试通过
- [x] Git跟踪文件运行时Artifact门禁已加入测试
- [x] Phase 11.10D执行当前文件、暂存文件和运行时Manifest敏感信息门禁
- [x] Phase 11.10D复核提交文件不包含本地绝对路径、运行数据库路径或私人凭据

## 8. 许可证与来源

- [x] 项目代码采用MIT License
- [x] `pypdf`使用BSD-3-Clause且只处理文本层
- [x] 正式来源库存和适用范围文档已建立
- [x] Seed没有直接大段复制来源正文
- [x] Publisher逐来源确认版权、引用方式、动态页面状态和用途边界
- [x] 企业岗位页只保存元数据和原创归纳
- [x] README与本地运行时发布记录列明岗位知识属于参考信息而非招聘保证

## 9. 正式运行时发布

- [x] 发布前有效版本为`2026.07.1`
- [x] 正式数据库位于Git仓库外
- [x] 发布前数据库和`.env`完成外部备份
- [x] SQLite锁、WAL/SHM和`quick_check`门禁通过
- [x] 影子数据库完成approved Seed导入、publish和FTS/关键词回退验证
- [x] 三岗位检索隔离、同版本Citation、Report、Markdown、JSON和Streamlit通过
- [x] 基础与增强路径的Job Profile、Match、Score和Recommendation一致
- [x] 数据库与`.env`完成原子切换
- [x] 不带知识路径/版本临时覆盖的有效配置验证通过
- [x] Streamlit localhost健康端点返回HTTP 200 / `ok`
- [x] 受保护回滚脚本和外部备份集已保留
- [x] 运行数据库、备份、Manifest和结果未进入Git

## 10. Git与远程操作

- [x] GitHub仓库：`0617Percy/jobfit-agent`
- [x] 稳定`main`保持v1.0.0基线
- [x] v1.1功能分支当前不设上游
- [x] 本阶段未push
- [x] 本阶段未创建PR、tag或Release
- [ ] 所有者明确授权push功能分支
- [ ] 所有者明确授权创建PR
- [ ] PR审查和合并策略确定
- [ ] 所有者明确授权创建v1.1.0 tag
- [ ] 所有者明确授权创建GitHub Release

## 11. 当前禁止操作

Phase 11.10D已完成。下列远程或版本发布操作仍未授权：

```text
git push
gh pr create
git merge
git tag v1.1.0
gh release create
移动或重建v1.0.0 tag
```
