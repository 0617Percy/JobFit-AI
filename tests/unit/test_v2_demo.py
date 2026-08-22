"""Deterministic offline runtime for the side-by-side v2 RC application."""

from jobfit.demo_v2 import DEMO_JD_TEXT, DEMO_RESUME_TEXT, build_demo_runtime
from jobfit.models.v2 import JobFamily, LifecycleStatus
from jobfit.parsers.text import TextDocumentParser
from jobfit.scoring.v2 import SeniorityFacts


def test_demo_runtime_runs_p01_to_p08_without_network_or_api_key() -> None:
    parser = TextDocumentParser()
    resume = parser.parse_text(DEMO_RESUME_TEXT)
    jd = parser.parse_text(DEMO_JD_TEXT)
    runtime = build_demo_runtime(resume_document=resume, jd_document=jd)

    prepared = runtime.application.prepare_analysis(
        analysis_id="demo-analysis-1",
        resume_version_id="demo-resume-1",
        jd_snapshot_id="demo-jd-1",
        resume_document=resume,
        jd_document=jd,
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )
    completed = runtime.application.finish_analysis(
        runtime.application.begin_analysis(prepared)
    )

    assert runtime.provider.call_count == 9
    assert completed.run.lifecycle.status is LifecycleStatus.COMPLETED
    assert completed.advisory_result is not None
    assert completed.advisory_result.report.summary["recommendation"] == "priority"
    assert len(type(completed.advisory_result.report).model_fields) == 14
    assert len(completed.advisory_result.report.build_recommendations) <= 3


def test_demo_runtime_uses_role_specific_synthetic_capability() -> None:
    parser = TextDocumentParser()
    scenarios = (
        (
            "Data Analytics Intern\nBuild business dashboards.\nSQL analysis is required.",
            JobFamily.DATA_ANALYTICS,
            "SQL business analysis",
        ),
        (
            "Technology Strategy Intern\nBuild research briefs.\nTechnology research is required.",
            JobFamily.TECHNOLOGY_STRATEGY,
            "technology research and structured analysis",
        ),
    )

    for jd_text, family, capability in scenarios:
        resume = parser.parse_text(DEMO_RESUME_TEXT)
        jd = parser.parse_text(jd_text)
        runtime = build_demo_runtime(resume_document=resume, jd_document=jd)
        prepared = runtime.application.prepare_analysis(
            analysis_id=f"demo-{family.value}",
            resume_version_id="demo-resume-1",
            jd_snapshot_id="demo-jd-1",
            resume_document=resume,
            jd_document=jd,
            seniority_facts=SeniorityFacts(explicit_entry_scope=True),
        )

        assert prepared.job_profile.job_family is family
        assert prepared.requirements[0].normalized_capability == capability

        completed = runtime.application.finish_analysis(
            runtime.application.begin_analysis(prepared)
        )
        assert completed.advisory_result is not None
        action_text = " ".join(
            str(item.recommended_action)
            for item in completed.advisory_result.bundle.actions
        ).casefold()
        question_text = " ".join(
            item.question
            for item in completed.advisory_result.bundle.interview_questions
        ).casefold()
        expected_term = {
            JobFamily.DATA_ANALYTICS: "sql",
            JobFamily.TECHNOLOGY_STRATEGY: "research",
        }[family]
        assert expected_term in action_text
        assert expected_term in question_text


def test_demo_actions_and_interview_are_ready_for_human_execution() -> None:
    parser = TextDocumentParser()
    resume = parser.parse_text(DEMO_RESUME_TEXT)
    jd = parser.parse_text(DEMO_JD_TEXT)
    runtime = build_demo_runtime(resume_document=resume, jd_document=jd)
    prepared = runtime.application.prepare_analysis(
        analysis_id="demo-action-quality",
        resume_version_id="demo-resume-1",
        jd_snapshot_id="demo-jd-1",
        resume_document=resume,
        jd_document=jd,
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )

    completed = runtime.application.finish_analysis(
        runtime.application.begin_analysis(prepared)
    )

    assert completed.advisory_result is not None
    assert all(
        item.time_to_complete
        for item in completed.advisory_result.bundle.actions
    )
    assert all(
        len(item.preparation_points) >= 3
        for item in completed.advisory_result.bundle.interview_questions
    )
