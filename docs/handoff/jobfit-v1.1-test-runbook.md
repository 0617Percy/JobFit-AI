# JobFit Agent v1.1 测试与运行手册

## 1. 环境基线

| 组件 | 当前交接环境 |
| --- | --- |
| Python | 3.12.13；项目支持 `>=3.11,<3.13` |
| pip | 25.0.1 |
| Streamlit | 1.60.0 |
| SQLAlchemy | 2.0.51 |
| Pydantic | 2.13.4 |
| pypdf | 6.14.2 |

不要把本机解释器绝对路径、用户目录或 `.env` 内容写入日志、报告或提交。

### Windows 建立环境

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### macOS / Linux 建立环境

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e ".[dev]"
```

普通测试使用 Mock/Fake，不需要 `.env` 或 API Key。

## 2. 测试命令

以下命令均从 `<project-root>` 执行。

### 单模块示例

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_orchestrator.py
```

### Knowledge 全套

```powershell
.\.venv\Scripts\python.exe -m pytest tests/knowledge
```

### Workflow

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/unit/test_orchestrator.py `
  tests/unit/test_workflow_state.py `
  tests/unit/test_workflow_knowledge_factory.py `
  tests/integration/test_mock_workflow.py
```

### Reporting 与导出

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/unit/test_analysis_report_knowledge.py `
  tests/unit/test_knowledge_reporting.py `
  tests/unit/test_knowledge_report_validator.py `
  tests/unit/test_markdown_reporting.py `
  tests/unit/test_json_reporting.py `
  tests/integration/test_report_assembly.py `
  tests/integration/test_report_exports.py
```

### Streamlit/UI 无浏览器测试

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/integration/test_streamlit_smoke.py `
  tests/integration/test_streamlit_interactions.py `
  tests/integration/test_streamlit_knowledge.py `
  tests/unit/test_streamlit_stale_identity.py
```

### 全部测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

### Ruff

```powershell
.\.venv\Scripts\ruff.exe check .
```

### 依赖完整性

```powershell
.\.venv\Scripts\python.exe -m pip check
```

### Git 空白错误

```powershell
git diff --check
```

### Streamlit headless 健康检查

终端 1：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.headless true
```

终端 2：

```powershell
Invoke-WebRequest http://127.0.0.1:8501/_stcore/health -UseBasicParsing
```

确认响应成功后回到终端 1 按 `Ctrl+C`。不要把服务留在后台。

## 3. 当前验收基线

- 当前测试总数：730。
- 当前已知基线：730 passed、0 failed。
- Ruff：通过。
- pip check：通过。
- 网络：`tests/conftest.py` 的 autouse fixture 拦截普通测试的 socket 连接；只有显式 `live_api` marker 才可例外，本 runbook 不运行该 marker。
- SQLite：所有知识测试使用 pytest 临时目录；完成后仓库内应无 `.sqlite3`、`.db`、`.sqlite`、WAL 或 SHM。
- dotenv 隔离：autouse fixture 临时将 `Settings.model_config["env_file"]` 设为 `None`；配置单测还显式传入 `_env_file=None`。测试不得读取、打印或修改开发者本地 `.env`。
- Mock：默认演示不需要数据库、API Key 或网络，基础路径保持四次固定模型调用。

交接提交后的最终测试结果以仓库外 handoff manifest 为准。

## 4. Seed 专项验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/knowledge/test_official_seed_contract.py
.\.venv\Scripts\python.exe -m pytest tests/knowledge/test_seed_loader.py tests/knowledge/test_seed_validation.py
```

正式知识变更还必须验证：

- strict JSON 与重复 key；
- stable ID、枚举和引用；
- canonical content hash；
- 临时 SQLite draft 导入和幂等性；
- pending 内容发布必须被拒绝；
- 仓库无 SQLite 残留。

## 5. 推荐验证顺序

1. 运行用户指定的最小专项测试。
2. 专项通过后运行完整 pytest。
3. 运行 Ruff。
4. 运行 pip check。
5. 运行 `git diff --check`。
6. 检查 `git status --short` 和 `git diff --stat`。
7. 只有用户明确要求且 UI 被修改时才运行一次 headless Streamlit 健康检查。

未经用户明确要求，不运行 coverage、浏览器自动化、真实模型、网络研究、干净克隆或新环境重建。

## 6. 失败反馈格式

后续 Codex 遇到失败时只返回以下内容，不自动修复：

```text
执行命令：<exact command>
退出码：<integer>
失败测试名：<test node id；多个时逐行列出>
第一段关键错误：<first relevant error block>
最后一段关键错误：<last relevant error block>
git diff --stat：<exact output or empty>
git status --short：<exact output or clean>
```

约束：

- 不猜测修复方案并直接改代码。
- 不重复运行失败命令，除非用户要求或首次失败明显属于瞬时执行环境问题。
- 不输出 API Key、`.env`、完整用户输入、完整 Prompt、数据库路径或底层凭据。
- 未经授权不提交；即使授权提交也不 push。

## 7. 后续 Codex 操作基线

后续 Codex 只接收明确补丁或完整文件，核对目标 HEAD，按原样转存或应用，运行指定测试并反馈结果。Codex 不再自主设计、开发、重构、修复、调整知识内容或批准发布。
