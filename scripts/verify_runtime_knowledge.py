#!/usr/bin/env python3
"""Verify one published runtime knowledge database without network access."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jobfit.config import Settings  # noqa: E402
from jobfit.demo import (  # noqa: E402
    DEMO_COMPANY_NAME,
    DEMO_JOB_TEXT,
    DEMO_RESUME_TEXT,
    DemoRuntime,
    _build_scripts,
)
from jobfit.knowledge.db import KnowledgeDatabase  # noqa: E402
from jobfit.knowledge.fts import KnowledgeSearchIndex  # noqa: E402
from jobfit.knowledge.paths import resolve_knowledge_db_path  # noqa: E402
from jobfit.knowledge.repository import SqliteKnowledgeRepository  # noqa: E402
from jobfit.knowledge.retriever import DefaultKnowledgeRetriever  # noqa: E402
from jobfit.llm import LLMTask, MockLLMClient, MockLLMProvider  # noqa: E402
from jobfit.models import (  # noqa: E402
    AnalysisRequest,
    HardConditionKind,
    Importance,
    JobProfile,
    JobRequirement,
    JobRequirementCollection,
    KnowledgeRetrievalStatus,
    KnowledgeSearchMode,
    LanguageCode,
    RequirementCategory,
    RequirementType,
)
from jobfit.reporting import render_json, render_markdown  # noqa: E402
from jobfit.workflow.factory import (  # noqa: E402
    build_knowledge_retriever,
    build_workflow_orchestrator,
)

ROLE_CASES = (
    (
        "AI应用实习生",
        "人工智能应用、Python、LLM API、Agent工作流与评估",
        "rp-ai-application-intern",
        "kr-ai-",
    ),
    (
        "数据分析实习生",
        "数据分析、SQL、指标、可视化、Dashboard与业务洞察",
        "rp-data-analyst-intern",
        "kr-da-",
    ),
    (
        "技术战略实习生",
        "技术战略、竞争情报、技术趋势、情景分析与路线图",
        "rp-technology-strategy-intern",
        "kr-ts-",
    ),
)


class VerificationError(RuntimeError):
    pass


def _job_profile(title: str, summary: str) -> JobProfile:
    requirement_text = summary.split("、", maxsplit=1)[0]
    return JobProfile(
        job_id=f"runtime-{title}",
        title=title,
        language=LanguageCode.ZH,
        jd_text=summary,
        summary=summary,
        keywords=[part for part in summary.replace("与", "、").split("、") if part],
        requirements=JobRequirementCollection(
            items=[
                JobRequirement(
                    requirement_id=f"req-{title}",
                    requirement_text=requirement_text,
                    source_text=requirement_text,
                    source_start_char=0,
                    source_end_char=len(requirement_text),
                    requirement_type=RequirementType.RESPONSIBILITY,
                    category=RequirementCategory.DOMAIN_BUSINESS,
                    importance=Importance.MEDIUM,
                    mandatory=False,
                    hard_condition_kind=HardConditionKind.NONE,
                    normalized_key=f"key-{title}",
                    priority_factor=Decimal("0"),
                    weight=Decimal("0"),
                )
            ],
            source_coverage_ratio=Decimal("1"),
        ),
    )


def _analysis_settings(
    *,
    database: Path,
    version: str,
    enabled: bool,
) -> Settings:
    return Settings(
        app_env="test",
        llm_provider="mock",
        llm_model="mock-model",
        llm_api_key=None,
        demo_mode=True,
        knowledge_enabled=enabled,
        knowledge_version=version,
        knowledge_db_path=database,
        _env_file=None,
    )


def _formal_demo_scripts(citation_id: str | None):
    scripts = _build_scripts()
    job_payload = json.loads(scripts[LLMTask.EXTRACT_JOB][0])
    job_payload["title"] = "AI应用实习生"
    scripts[LLMTask.EXTRACT_JOB] = [
        json.dumps(job_payload, ensure_ascii=False, separators=(",", ":"))
    ]
    if citation_id is not None:
        advice_payload = json.loads(scripts[LLMTask.GENERATE_ADVICE_BUNDLE][0])
        advice_payload["knowledge_citation_uses"] = [
            {
                "citation_id": citation_id,
                "target_type": "recommendation",
                "target_index": 0,
                "purpose": "role_requirement_context",
            }
        ]
        scripts[LLMTask.GENERATE_ADVICE_BUNDLE] = [
            json.dumps(advice_payload, ensure_ascii=False, separators=(",", ":"))
        ]
    return scripts


def _demo_citation_id(settings: Settings) -> str | None:
    if not settings.knowledge_enabled:
        return None
    database = KnowledgeDatabase(resolve_knowledge_db_path(settings.knowledge_db_path))
    try:
        repository = SqliteKnowledgeRepository(
            database,
            search_mode=settings.knowledge_search_mode,
        )
        context = DefaultKnowledgeRetriever(
            repository,
            requested_version=settings.knowledge_version,
            search_mode=settings.knowledge_search_mode,
        ).retrieve_for_job(
            _job_profile(
                "AI应用实习生",
                "人工智能应用、Python、LLM API、Agent工作流与评估",
            )
        )
        if context.status is not KnowledgeRetrievalStatus.AVAILABLE or not context.citations:
            raise VerificationError("Formal demo Citation is unavailable.")
        return context.citations[0].citation_id
    finally:
        database.dispose()


def _demo_runtime(settings: Settings) -> DemoRuntime:
    provider = MockLLMProvider(_formal_demo_scripts(_demo_citation_id(settings)))
    retriever = build_knowledge_retriever(settings)
    return DemoRuntime(
        orchestrator=build_workflow_orchestrator(
            settings,
            client=MockLLMClient(provider),
            knowledge_retriever=retriever,
        ),
        provider=provider,
    )


def _run_demo(settings: Settings, request_id: str):
    runtime = _demo_runtime(settings)
    result = runtime.orchestrator.run(
        AnalysisRequest(
            request_id=request_id,
            pasted_resume_text=DEMO_RESUME_TEXT,
            job_description_text=DEMO_JOB_TEXT,
            job_title="AI应用实习生",
            company_name=DEMO_COMPANY_NAME,
            llm_mode="mock",
        ),
        selected_source="text",
    )
    if not result.success or result.report is None:
        raise VerificationError("Deterministic demo workflow did not complete.")
    if runtime.provider.call_count != 4:
        raise VerificationError("Deterministic demo model call count changed.")
    return result


@contextmanager
def _temporary_environment(updates: dict[str, str | None]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _visible(app) -> str:
    values: list[str] = []
    for collection in (
        app.markdown,
        app.caption,
        app.info,
        app.warning,
        app.success,
        app.subheader,
        app.text,
    ):
        values.extend(str(item.value) for item in collection)
    values.extend(str(item.value) for item in app.metric)
    return "\n".join(values)


def _streamlit_acceptance(
    *,
    database: Path,
    version: str,
    use_effective_config: bool,
) -> dict[str, object]:
    from streamlit.testing.v1 import AppTest

    updates = {
        "JOBFIT_LLM_PROVIDER": "mock",
        "JOBFIT_LLM_MODEL": "mock-model",
        "JOBFIT_LLM_API_KEY": None,
        "JOBFIT_DEMO_MODE": "true",
    }
    if not use_effective_config:
        updates.update(
            {
                "JOBFIT_KNOWLEDGE_ENABLED": "true",
                "JOBFIT_KNOWLEDGE_VERSION": version,
                "JOBFIT_KNOWLEDGE_DB_PATH": str(database),
            }
        )
    with _temporary_environment(updates):
        settings = (
            Settings.load()
            if use_effective_config
            else _analysis_settings(database=database, version=version, enabled=True)
        )
        app = AppTest.from_file(ROOT / "app.py", default_timeout=30).run()
        app.button(key="load_demo").click().run()
        app.text_input(key="job_title").input("AI应用实习生").run()
        app.session_state["demo_runtime"] = _demo_runtime(settings)
        app.button(key="analyze").click().run(timeout=30)
    if app.exception:
        raise VerificationError("Streamlit AppTest reported an exception.")
    report = app.session_state["analysis_report"]
    if report is None or report.knowledge is None:
        raise VerificationError("Streamlit report did not contain knowledge state.")
    if report.knowledge.status is not KnowledgeRetrievalStatus.AVAILABLE:
        raise VerificationError("Streamlit formal knowledge was not available.")
    visible = _visible(app)
    if version not in visible or "岗位知识参考" not in [tab.label for tab in app.tabs]:
        raise VerificationError("Streamlit did not render the published version.")
    if len(report.knowledge.citations) < 1:
        raise VerificationError("Streamlit report has no validated knowledge Citation.")
    if [button.label for button in app.download_button] != ["下载 Markdown", "下载 JSON"]:
        raise VerificationError("Streamlit downloads are incomplete.")
    return {
        "status": report.knowledge.status.value,
        "citations": len(report.knowledge.citations),
        "downloads": len(app.download_button),
    }


def verify(
    *,
    database: Path,
    version: str,
    expected_hash: str,
    require_streamlit: bool,
    use_effective_config: bool,
) -> dict[str, object]:
    database = database.expanduser().resolve(strict=False)
    if use_effective_config:
        settings = Settings.load()
        resolved = resolve_knowledge_db_path(settings.knowledge_db_path)
        if settings.knowledge_version != version:
            raise VerificationError("Effective knowledge version is not the target version.")
        if not settings.knowledge_enabled:
            raise VerificationError("Effective knowledge feature is disabled.")
        if resolved != database:
            raise VerificationError("Effective runtime database path does not match.")

    knowledge_database = KnowledgeDatabase(database)
    try:
        knowledge_database.ensure_compatible_schema()
        search_index = KnowledgeSearchIndex(knowledge_database)
        repository = SqliteKnowledgeRepository(
            knowledge_database,
            search_mode=KnowledgeSearchMode.AUTO,
            search_index=search_index,
        )
        published = repository.get_published_version(version)
        if published is None:
            raise VerificationError("Published knowledge version is unavailable.")
        if published.content_hash != expected_hash:
            raise VerificationError("Published knowledge Hash does not match approval.")
        roles: dict[str, object] = {}
        for title, summary, role_id, requirement_prefix in ROLE_CASES:
            context = DefaultKnowledgeRetriever(
                repository,
                requested_version=version,
                search_mode=KnowledgeSearchMode.AUTO,
            ).retrieve_for_job(_job_profile(title, summary))
            if context.status is not KnowledgeRetrievalStatus.AVAILABLE:
                raise VerificationError(f"Knowledge unavailable for role: {title}")
            if len(context.inferred_role_profiles) != 1:
                raise VerificationError(f"Role inference is not isolated: {title}")
            if context.inferred_role_profiles[0].role_profile_id != role_id:
                raise VerificationError(f"Unexpected role profile: {title}")
            if not context.requirements or any(
                item.role_profile_id != role_id
                or not item.knowledge_requirement_id.startswith(requirement_prefix)
                for item in context.requirements
            ):
                raise VerificationError(f"Cross-role requirement contamination: {title}")
            if not context.citations or any(
                not repository.citation_exists(citation, version_id=published.id)
                for citation in context.citations
            ):
                raise VerificationError(f"Invalid Citation for role: {title}")
            roles[role_id] = {
                "requirements": len(context.requirements),
                "citations": len(context.citations),
            }
    finally:
        knowledge_database.dispose()

    if use_effective_config:
        effective = Settings.load().model_copy(
            update={
                "app_env": "test",
                "llm_provider": "mock",
                "llm_model": "mock-model",
                "llm_api_key": None,
                "demo_mode": True,
            }
        )
        enhanced_settings = effective
        base_settings = effective.model_copy(update={"knowledge_enabled": False})
    else:
        base_settings = _analysis_settings(
            database=database,
            version=version,
            enabled=False,
        )
        enhanced_settings = _analysis_settings(
            database=database,
            version=version,
            enabled=True,
        )

    base = _run_demo(base_settings, "runtime-base")
    enhanced = _run_demo(enhanced_settings, "runtime-enhanced")
    base_report = base.report
    enhanced_report = enhanced.report
    assert base_report is not None and enhanced_report is not None
    if base_report.knowledge is None or (
        base_report.knowledge.status is not KnowledgeRetrievalStatus.DISABLED
    ):
        raise VerificationError("Base mode did not report disabled knowledge.")
    if enhanced_report.knowledge is None or (
        enhanced_report.knowledge.status is not KnowledgeRetrievalStatus.AVAILABLE
    ):
        raise VerificationError("Enhanced mode did not report available knowledge.")
    if not enhanced_report.knowledge.citations:
        raise VerificationError("Enhanced report has no Citation.")

    identities = {
        "job_profile": base_report.job_profile == enhanced_report.job_profile,
        "matches": base_report.matches == enhanced_report.matches,
        "score": base_report.score_summary == enhanced_report.score_summary,
        "recommendation": base_report.recommendation == enhanced_report.recommendation,
    }
    if not all(identities.values()):
        raise VerificationError("Knowledge changed evidence, score or recommendation.")
    markdown = render_markdown(enhanced_report)
    json_text = render_json(enhanced_report)
    payload = json.loads(json_text)
    if "岗位知识参考" not in markdown or payload["knowledge"]["status"] != "available":
        raise VerificationError("Formal knowledge did not reach Report exports.")

    streamlit_result = None
    if require_streamlit:
        streamlit_result = _streamlit_acceptance(
            database=database,
            version=version,
            use_effective_config=use_effective_config,
        )

    return {
        "status": "passed",
        "database": str(database),
        "version": version,
        "content_hash": expected_hash,
        "roles": roles,
        "search_capability": "auto",
        "base_knowledge_status": base_report.knowledge.status.value,
        "enhanced_knowledge_status": enhanced_report.knowledge.status.value,
        "enhanced_citations": len(enhanced_report.knowledge.citations),
        "final_score": str(enhanced_report.score_summary.final_score),
        "recommendation": enhanced_report.recommendation.level.value,
        "identity": identities,
        "streamlit": streamlit_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-hash", required=True)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--require-streamlit", action="store_true")
    parser.add_argument("--use-effective-config", action="store_true")
    args = parser.parse_args()
    try:
        result = verify(
            database=args.database,
            version=args.version,
            expected_hash=args.expected_hash,
            require_streamlit=args.require_streamlit,
            use_effective_config=args.use_effective_config,
        )
    except Exception as exc:
        result = {
            "status": "failed",
            "failure": f"{type(exc).__name__}: {exc}",
        }
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False))
        return 1
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
