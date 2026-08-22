"""D2.18 P06 semantic-strength detector regression contract.

The old detector treated every novel English lexical token as a new
tool/technology claim, so benign paraphrasing and language-preserving
translation were hard-blocked. These tests pin the repaired contract:

- benign paraphrasing (ZH / EN / mixed translation) passes;
- every unsupported factual-strengthening family stays a hard block;
- language change alone never produces a claim;
- the new-tool guard is shape-based, deterministic, and reuses
  authoritative structured capability data where provided.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jobfit.generators.rewrite import (
    _detect_new_claims,
    _detected_strength_families,
)

CRITICAL_FAMILIES = frozenset(
    {
        "RESPONSIBILITY_ESCALATION",
        "RESULT_INVENTION",
        "DEPLOYMENT_ESCALATION",
        "QUALITY_ESCALATION",
        "USER_IMPACT_ESCALATION",
        "COMPLETION_ESCALATION",
    }
)


def _claims(
    source: str,
    rewritten: str,
    allowed_terms: tuple[str, ...] = (),
) -> list[str]:
    item = SimpleNamespace(original_text=source, rewritten_text=rewritten)
    return _detect_new_claims(
        item,
        evidence_text=source,
        allowed_terms=allowed_terms,
    )


def _families(
    source: str,
    rewritten: str,
    allowed_terms: tuple[str, ...] = (),
) -> frozenset[str]:
    item = SimpleNamespace(original_text=source, rewritten_text=rewritten)
    return _detected_strength_families(
        item,
        evidence_text=source,
        allowed_terms=allowed_terms,
    )


BENIGN_PARAPHRASE_PAIRS: list[tuple[str, str, str]] = [
    (
        "zh-paraphrase-mandated",
        "参与数据分析项目，使用 Python 清洗数据。",
        "参与项目数据分析，并使用 Python 完成数据清洗工作。",
    ),
    (
        "zh-bullet-clarity",
        "使用Python完成数据处理",
        "使用 Python 完成数据处理，清晰呈现技术行动。",
    ),
    (
        "zh-ownership-family-present",
        "主导数据清洗工作。",
        "在项目中主导了数据清洗任务。",
    ),
    (
        "zh-report-word-swap",
        "用 SQL 查询数据并生成报表。",
        "通过 SQL 完成数据查询和报表输出。",
    ),
    (
        "zh-quality-family-present",
        "优化了数据入库脚本。",
        "对入库脚本进行了优化调整。",
    ),
    (
        "zh-course-paraphrase",
        "课程项目：学习机器学习模型。",
        "课程里做了一个机器学习的小项目，学习模型知识。",
    ),
    (
        "en-paraphrase-mandated",
        "Used SQL to query data and create reports.",
        "Queried data with SQL and prepared reporting outputs.",
    ),
    (
        "en-word-reorder",
        "Used Python for data analysis.",
        "Worked with Python on data analysis tasks.",
    ),
    (
        "en-api-confirm",
        "Built a Python API and validated JSON output.",
        "Built the Python API and confirmed that its JSON output was valid.",
    ),
    (
        "en-tests-synonym",
        "Wrote unit tests for the service.",
        "Authored test suites covering the service code.",
    ),
    (
        "en-participate-synonym",
        "Participated in model development.",
        "Took part in the development of the model.",
    ),
    (
        "en-pandas-clean",
        "Cleaned and processed raw data with pandas.",
        "Prepared raw datasets through cleaning and transformation steps using pandas.",
    ),
    (
        "en-dashboard-synonym",
        "Designed the dashboard layout.",
        "Created the visual structure of the dashboard.",
    ),
    (
        "zh-to-en-mandated",
        "使用 Python 进行数据分析和清洗。",
        "Performed data analysis and cleaning using Python.",
    ),
    (
        "en-to-zh-mandated",
        "Used Python for data analysis.",
        "使用 Python 完成数据分析工作。",
    ),
    (
        "en-many-novel-words-mandated",
        "Used Python for data analysis and reporting.",
        "Analyzed datasets with Python and generated well-organized report summaries.",
    ),
    (
        "zh-to-en-sql-familiar",
        "熟悉SQL，做过报表。",
        "Familiar with SQL and experienced in preparing reports.",
    ),
    (
        "en-to-zh-react",
        "Built the dashboard with React.",
        "用 React 搭建了数据看板。",
    ),
    (
        "zh-to-en-scraper",
        "用 Python 写爬虫脚本。",
        "Developed a web scraping script in Python.",
    ),
    (
        "en-to-zh-deployment-family-present",
        "Deployed the service to production.",
        "服务已经部署到生产环境。",
    ),
    (
        "en-to-zh-ownership-family-present",
        "Led the design review meetings.",
        "主持设计评审会议。",
    ),
    (
        "en-to-zh-result-family-present",
        "Improved model accuracy through tuning.",
        "通过调参提升了模型准确率。",
    ),
    (
        "tool-supported-in-source",
        "Used Python and SQL for analysis.",
        "Analyzed data with Python and SQL tooling.",
    ),
    (
        "sentence-start-verb",
        "Used Python for analysis.",
        "Performed analysis with Python across the project.",
    ),
]

TRUE_STRENGTHENING_PAIRS: list[tuple[str, str, str, str]] = [
    (
        "responsibility-en-mandated",
        "Participated in model development.",
        "Led model development independently.",
        "RESPONSIBILITY_ESCALATION",
    ),
    (
        "responsibility-zh",
        "参与数据处理工作。",
        "独立负责数据处理全流程。",
        "RESPONSIBILITY_ESCALATION",
    ),
    (
        "responsibility-en-managed",
        "Assisted with the migration.",
        "Managed the migration end to end.",
        "RESPONSIBILITY_ESCALATION",
    ),
    (
        "result-en-mandated",
        "Performed data analysis.",
        "Improved operational efficiency by 30%.",
        "RESULT_INVENTION",
    ),
    (
        "result-zh",
        "开发数据处理脚本。",
        "处理效率提升30%。",
        "RESULT_INVENTION",
    ),
    (
        "result-en-increased",
        "Ran the campaign.",
        "Increased signups and achieved record growth.",
        "RESULT_INVENTION",
    ),
    (
        "deployment-en-mandated",
        "Built a project prototype.",
        "Deployed the system to production.",
        "DEPLOYMENT_ESCALATION",
    ),
    (
        "deployment-zh",
        "开发了数据处理脚本。",
        "脚本已上线生产环境。",
        "DEPLOYMENT_ESCALATION",
    ),
    (
        "quality-en-mandated",
        "Developed a data-processing script.",
        "Developed a robust, high-performance and reliable data-processing system.",
        "QUALITY_ESCALATION",
    ),
    (
        "quality-zh-mandated",
        "开发数据处理脚本。",
        "开发高性能、稳定可靠的数据处理系统。",
        "QUALITY_ESCALATION",
    ),
    (
        "quality-en-optimized",
        "Wrote a dashboard script.",
        "Wrote an optimized, scalable dashboard service.",
        "QUALITY_ESCALATION",
    ),
    (
        "user-impact-en-mandated",
        "Built an analysis tool.",
        "Built an analysis tool adopted by enterprise customers.",
        "USER_IMPACT_ESCALATION",
    ),
    (
        "user-impact-zh",
        "整理销售数据。",
        "为多家公司客户提供数据分析支持。",
        "USER_IMPACT_ESCALATION",
    ),
    (
        "completion-en",
        "Worked on the pipeline.",
        "Completed and delivered the pipeline on schedule.",
        "COMPLETION_ESCALATION",
    ),
    (
        "completion-zh",
        "进行系统测试。",
        "已完成全部系统测试并交付。",
        "COMPLETION_ESCALATION",
    ),
    (
        "new-tool-capitalized-mandated",
        "Used Python for analysis.",
        "Used Python and Tableau for analysis.",
        "NEW_TOOL_OR_TECHNOLOGY",
    ),
    (
        "new-tool-acronym",
        "Used Python for analysis.",
        "Used Python and SQL for analysis.",
        "NEW_TOOL_OR_TECHNOLOGY",
    ),
    (
        "new-tool-camelcase",
        "Used Python for analysis.",
        "Used Python and PyTorch for analysis.",
        "NEW_TOOL_OR_TECHNOLOGY",
    ),
    (
        "new-tool-punctuated",
        "Used Python for analysis.",
        "Used Python and C++ for analysis.",
        "NEW_TOOL_OR_TECHNOLOGY",
    ),
    (
        "new-tool-digit",
        "Used Python for analysis.",
        "Used Python and K8s for analysis.",
        "NEW_TOOL_OR_TECHNOLOGY",
    ),
    (
        "new-tool-acronym-sentence-start",
        "Used Python for analysis.",
        "SQL dashboards were added for analysis.",
        "NEW_TOOL_OR_TECHNOLOGY",
    ),
    (
        "ability-en",
        "Used data tools.",
        "Proficient in data tooling.",
        "ABILITY_ESCALATION",
    ),
]


@pytest.mark.parametrize(
    ("source", "rewritten"),
    [
        (
            "参与数据分析项目，使用 Python 清洗数据。",
            "参与项目数据分析，并使用 Python 完成数据清洗工作。",
        ),
        (
            "Used SQL to query data and create reports.",
            "Queried data with SQL and prepared reporting outputs.",
        ),
        ("使用 Python 进行数据分析和清洗。", "Performed data analysis and cleaning using Python."),
        ("Used Python for data analysis.", "使用 Python 完成数据分析工作。"),
        (
            "Used Python for data analysis and reporting.",
            "Analyzed datasets with Python and generated well-organized report summaries.",
        ),
    ],
    ids=["zh-paraphrase", "en-paraphrase", "zh-to-en", "en-to-zh", "many-novel-words"],
)
def test_mandated_benign_cases_pass(source: str, rewritten: str) -> None:
    assert _claims(source, rewritten) == []
    assert _families(source, rewritten) == frozenset()


@pytest.mark.parametrize(
    ("source", "rewritten", "family"),
    [
        (
            "Used Python for analysis.",
            "Used Python and Tableau for analysis.",
            "NEW_TOOL_OR_TECHNOLOGY",
        ),
        (
            "Participated in model development.",
            "Led model development independently.",
            "RESPONSIBILITY_ESCALATION",
        ),
        (
            "Performed data analysis.",
            "Improved operational efficiency by 30%.",
            "RESULT_INVENTION",
        ),
        (
            "Built a project prototype.",
            "Deployed the system to production.",
            "DEPLOYMENT_ESCALATION",
        ),
        (
            "Developed a data-processing script.",
            "Developed a robust, high-performance and reliable data-processing system.",
            "QUALITY_ESCALATION",
        ),
        (
            "开发数据处理脚本。",
            "开发高性能、稳定可靠的数据处理系统。",
            "QUALITY_ESCALATION",
        ),
        (
            "Built an analysis tool.",
            "Built an analysis tool adopted by enterprise customers.",
            "USER_IMPACT_ESCALATION",
        ),
    ],
    ids=[
        "new-tool",
        "responsibility",
        "result",
        "deployment",
        "quality-en",
        "quality-zh",
        "customer-impact",
    ],
)
def test_mandated_true_positive_cases_block(
    source: str,
    rewritten: str,
    family: str,
) -> None:
    assert _claims(source, rewritten)
    assert family in _families(source, rewritten)


def test_benign_paraphrase_regression_set_has_zero_false_positives() -> None:
    flagged = [
        name for name, source, rewritten in BENIGN_PARAPHRASE_PAIRS if _claims(source, rewritten)
    ]
    assert flagged == []
    rate = len(flagged) / len(BENIGN_PARAPHRASE_PAIRS)
    assert rate <= 0.05
    assert len(BENIGN_PARAPHRASE_PAIRS) >= 20


def test_true_strengthening_regression_set_has_full_recall() -> None:
    undetected = [
        name
        for name, source, rewritten, family in TRUE_STRENGTHENING_PAIRS
        if family not in _families(source, rewritten)
    ]
    assert undetected == []
    rate = 1 - len(undetected) / len(TRUE_STRENGTHENING_PAIRS)
    assert rate == 1.0
    assert len(TRUE_STRENGTHENING_PAIRS) >= 15


def test_every_critical_family_has_minimum_regression_coverage() -> None:
    for family in CRITICAL_FAMILIES:
        count = sum(1 for _, _, _, expected in TRUE_STRENGTHENING_PAIRS if expected == family)
        assert count >= 2, family


def test_critical_families_never_emit_other_family_only_claims() -> None:
    """A critical strengthening pair must be detected as its own family."""
    for name, source, rewritten, family in TRUE_STRENGTHENING_PAIRS:
        if family not in CRITICAL_FAMILIES:
            continue
        assert family in _families(source, rewritten), name


@pytest.mark.parametrize(
    ("source", "rewritten"),
    [
        (
            "Used Python for analysis.",
            "Used Python and SQL for analysis.",
        ),
        (
            "Used Python for analysis.",
            "Used Python and PyTorch for analysis.",
        ),
        (
            "Used Python for analysis.",
            "Used Python and Tableau for analysis.",
        ),
        (
            "Used Python for analysis.",
            "Used Python and C++ for analysis.",
        ),
        (
            "Used Python for analysis.",
            "Used Python and K8s for analysis.",
        ),
    ],
    ids=["acronym", "camelcase", "capitalized-product", "punctuated", "digit"],
)
def test_new_tool_guard_covers_naming_styles(source: str, rewritten: str) -> None:
    assert "NEW_TOOL_OR_TECHNOLOGY" in _families(source, rewritten)


def test_new_tool_guard_allows_tool_supported_by_structured_capabilities() -> None:
    # Tableau is absent from the raw evidence text but present in the
    # authoritative normalized capabilities (P04 output), so the rewrite
    # must not be treated as an unsupported new tool.
    assert (
        _families(
            "Built dashboards for the team.",
            "Built Tableau dashboards for the team.",
            allowed_terms=("Tableau",),
        )
        == frozenset()
    )
    # Without the structured allowance the same rewrite is a hard block.
    assert "NEW_TOOL_OR_TECHNOLOGY" in _families(
        "Built dashboards for the team.",
        "Built Tableau dashboards for the team.",
    )


def test_sentence_start_capitalized_word_is_not_a_new_tool() -> None:
    assert (
        _families(
            "Used SQL to query data and create reports.",
            "Queried data with SQL and prepared reporting outputs.",
        )
        == frozenset()
    )


def test_claim_text_is_token_free_and_stable_per_family() -> None:
    claims = _claims(
        "Performed data analysis.",
        "Led the analysis and improved efficiency by 30% with Tableau.",
    )
    assert "职责强化" in claims
    assert "新增结果或量化主张" in claims
    assert "新增数字或量化结果" in claims
    assert "新增技术或工具" in claims
    # Offending tokens must never leak into claim diagnostics.
    assert all("Tableau" not in claim for claim in claims)
    assert all("Led" not in claim for claim in claims)
    assert all("30%" not in claim for claim in claims)
