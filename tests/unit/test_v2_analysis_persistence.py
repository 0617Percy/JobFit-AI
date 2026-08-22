"""Durable v2 analysis-history persistence at the approved V1 boundary."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from jobfit.config import Settings
from jobfit.models.v2 import (
    AnalysisCore,
    AnalysisInputSnapshot,
    AnalysisReadiness,
    Failure,
    FailureImpactLevel,
    JobFitReport,
    LifecycleStatus,
    Recommendation,
    SeniorityAlignment,
    UserClarification,
    VersionManifest,
)
from jobfit.models.v2.enums import Confidence, EligibilityStatus
from jobfit.parsers.text import TextDocumentParser
from jobfit.workflow.v2 import (
    ANALYSIS_SCHEMA_VERSION,
    AnalysisDatabase,
    AnalysisPersistenceError,
    AnalysisRepository,
    PersistedAnalysis,
    SQLiteAnalysisRepository,
    build_analysis_repository,
    create_analysis_run,
    initialize_analysis_schema,
    resolve_analysis_db_path,
    transition_run,
)


def _versions() -> VersionManifest:
    return VersionManifest(
        software_version="1.1.0",
        prompt_pack_version="1.0.0",
        schema_version="2.0.0",
        scoring_rule_version="1.0.0",
        knowledge_version="2026.08.1",
        analysis_engine_version="1.0.0",
    )


def _ready_run(
    analysis_id: str,
    *,
    parent_analysis_id: str | None = None,
):
    clarification = UserClarification(
        clarification_id=f"clarification-{analysis_id}",
        analysis_id=analysis_id,
        question="Did you own deployment?",
        answer="Yes.",
    )
    snapshot = AnalysisInputSnapshot.freeze(
        analysis_id=analysis_id,
        resume_version_id=f"resume-{analysis_id}",
        jd_snapshot_id="jd-1",
        user_clarifications=(clarification,),
        versions=_versions(),
    )
    run = create_analysis_run(analysis_id)
    run = transition_run(run, LifecycleStatus.INPUT_READY)
    run = transition_run(run, LifecycleStatus.PARSING)
    run = transition_run(run, LifecycleStatus.ANALYSIS_READY, snapshot=snapshot)
    lifecycle = run.lifecycle.model_copy(
        update={"last_successful_stage": "matching"}
    )
    return run.model_copy(
        update={
            "parent_analysis_id": parent_analysis_id,
            "reanalysis_reason": "Inputs updated." if parent_analysis_id else None,
            "lifecycle": lifecycle,
        }
    )


def _completed_run(
    analysis_id: str,
    *,
    score: str = "73",
    parent_analysis_id: str | None = None,
):
    run = _ready_run(analysis_id, parent_analysis_id=parent_analysis_id)
    run = transition_run(run, LifecycleStatus.ANALYZING)
    run = transition_run(run, LifecycleStatus.REPORT_GENERATING)
    run = transition_run(run, LifecycleStatus.COMPLETED)
    core = AnalysisCore(
        analysis_id=analysis_id,
        resume_version_id=f"resume-{analysis_id}",
        jd_snapshot_id="jd-1",
        analysis_readiness=AnalysisReadiness.READY,
        eligibility_status=EligibilityStatus.MET,
        seniority_alignment=SeniorityAlignment.ALIGNED,
        base_fit_score=Decimal(score),
        preferred_bonus=Decimal("0"),
        final_fit_score=Decimal(score),
        confidence=Confidence.HIGH,
        recommendation=Recommendation.SUGGESTED,
    )
    report = JobFitReport(
        report_id=f"report-{analysis_id}",
        analysis_id=analysis_id,
        summary={"score": score},
        build_recommendations=[
            {"action_id": f"action-{analysis_id}", "title": "Clarify evidence"}
        ],
        application_strategy={"recommendation": "suggested"},
        interview_preparation=[
            {"question_id": f"question-{analysis_id}", "question": "Explain it."}
        ],
    )
    return run.model_copy(update={"analysis_core": core, "report": report})


def _record(run) -> PersistedAnalysis:
    resume = TextDocumentParser().parse_text("Synthetic resume evidence.")
    resume = resume.model_copy(
        update={
            "original_filename": r"C:\private\candidate\resume.txt",
            "source": r"C:\private\candidate\resume.txt",
            "metadata": {"local_path": r"C:\private\candidate\resume.txt"},
            "warnings": [r"Read from C:\private\candidate\resume.txt"],
        }
    )
    jd = TextDocumentParser().parse_text("Synthetic role description.")
    clarification = UserClarification(
        clarification_id=f"clarification-{run.analysis_id}",
        analysis_id=run.analysis_id,
        question="Did you own deployment?",
        answer="Yes.",
    )
    return PersistedAnalysis.from_documents(
        run=run,
        resume_version_id=f"resume-{run.analysis_id}",
        jd_snapshot_id="jd-1",
        resume_document=resume,
        jd_document=jd,
        user_clarifications=(clarification,),
    )


def _repository(path: Path) -> tuple[AnalysisDatabase, SQLiteAnalysisRepository]:
    database = AnalysisDatabase(path)
    initialize_analysis_schema(database)
    return database, SQLiteAnalysisRepository(database)


def test_schema_bootstrap_is_explicit_idempotent_and_reopens(tmp_path: Path) -> None:
    path = tmp_path / "analysis.sqlite3"
    database = AnalysisDatabase(path)

    assert not path.exists()
    initialize_analysis_schema(database)
    initialize_analysis_schema(database)
    assert database.schema_version() == ANALYSIS_SCHEMA_VERSION == 1
    database.dispose()

    reopened = AnalysisDatabase(path)
    assert reopened.schema_version() == 1
    reopened.dispose()


def test_completed_analysis_round_trip_preserves_versions_sources_and_report(
    tmp_path: Path,
) -> None:
    path = tmp_path / "analysis.sqlite3"
    database, repository = _repository(path)
    ready = _ready_run("AN001")
    repository.save_working_analysis(_record(ready))
    completed = _completed_run("AN001")
    repository.append_analysis(completed)
    database.dispose()

    reopened_database = AnalysisDatabase(path)
    reopened = SQLiteAnalysisRepository(reopened_database)
    stored = reopened.get_persisted_analysis("AN001")

    assert stored is not None
    assert stored.run == completed
    assert stored.run.input_snapshot is not None
    assert (
        stored.run.input_snapshot.versions.model_dump()
        == _versions().model_dump()
    )
    assert stored.run.report is not None
    assert stored.run.report.build_recommendations[0]["action_id"] == "action-AN001"
    assert stored.run.report.interview_preparation[0]["question_id"] == "question-AN001"
    assert stored.resume_document is not None
    assert stored.resume_document.raw_text == "Synthetic resume evidence."
    serialized = stored.model_dump_json()
    assert "C:\\private" not in serialized
    assert "resume.txt" in serialized
    reopened_database.dispose()


def test_completed_history_is_immutable_and_reanalysis_appends(tmp_path: Path) -> None:
    database, repository = _repository(tmp_path / "analysis.sqlite3")
    repository.save_working_analysis(_record(_ready_run("AN001")))
    original = _completed_run("AN001", score="73")
    repository.append_analysis(original)

    with pytest.raises(AnalysisPersistenceError, match="immutable"):
        repository.append_analysis(_completed_run("AN001", score="86"))
    with pytest.raises(AnalysisPersistenceError, match="immutable"):
        repository.save_working_analysis(_record(_ready_run("AN001")))

    repository.save_working_analysis(
        _record(_ready_run("AN002", parent_analysis_id="AN001"))
    )
    repository.append_analysis(
        _completed_run("AN002", score="86", parent_analysis_id="AN001")
    )

    assert [item.analysis_id for item in repository.list_analysis_versions()] == [
        "AN001",
        "AN002",
    ]
    assert repository.get_analysis("AN001") == original
    assert repository.get_parent("AN002") == original
    database.dispose()


def test_frozen_input_snapshot_cannot_change_during_working_updates(
    tmp_path: Path,
) -> None:
    database, repository = _repository(tmp_path / "analysis.sqlite3")
    record = _record(_ready_run("AN001"))
    repository.save_working_analysis(record)
    assert record.run.input_snapshot is not None
    changed_snapshot = record.run.input_snapshot.model_copy(
        update={"user_clarifications": ()}
    )
    changed_run = record.run.model_copy(update={"input_snapshot": changed_snapshot})
    changed_record = record.model_copy(update={"run": changed_run})

    with pytest.raises(AnalysisPersistenceError, match="snapshot is immutable"):
        repository.save_working_analysis(changed_record)
    database.dispose()


def test_restart_recovers_working_lifecycle_and_last_successful_stage(
    tmp_path: Path,
) -> None:
    path = tmp_path / "analysis.sqlite3"
    database, repository = _repository(path)
    run = _ready_run("AN001").model_copy(
        update={
            "failures": (
                Failure(
                    failure_id="failure-AN001",
                    failure_stage="matching",
                    failure_code="SYNTHETIC_RECOVERABLE",
                    impact_level=FailureImpactLevel.NORMAL,
                    retryable=True,
                    user_action_required=False,
                    last_successful_stage="matching",
                    technical_message="Synthetic internal marker.",
                    user_message="A recoverable synthetic issue occurred.",
                ),
            )
        }
    )
    repository.save_working_analysis(_record(run))
    database.dispose()

    reopened_database = AnalysisDatabase(path)
    reopened = SQLiteAnalysisRepository(reopened_database)
    restored = reopened.get_analysis("AN001")

    assert restored is not None
    assert restored.lifecycle.status is LifecycleStatus.ANALYSIS_READY
    assert restored.lifecycle.last_successful_stage == "matching"
    assert restored.input_snapshot == run.input_snapshot
    assert restored.failures == run.failures
    assert [item.analysis_id for item in reopened.list_analyses()] == ["AN001"]
    assert reopened.list_analysis_versions() == ()
    reopened_database.dispose()


def test_explicit_chain_and_all_deletion_hard_delete_only_candidate_data(
    tmp_path: Path,
) -> None:
    knowledge_path = tmp_path / "knowledge.sqlite3"
    knowledge_path.write_bytes(b"knowledge-runtime-sentinel")
    app_path = tmp_path / "analysis.sqlite3"
    database, repository = _repository(app_path)

    repository.save_working_analysis(_record(_ready_run("AN001")))
    repository.append_analysis(_completed_run("AN001"))
    repository.save_working_analysis(
        _record(_ready_run("AN002", parent_analysis_id="AN001"))
    )
    repository.append_analysis(
        _completed_run("AN002", parent_analysis_id="AN001")
    )

    assert repository.delete_analysis_chain("AN001") == 2
    assert repository.get_analysis("AN001") is None
    assert repository.get_analysis("AN002") is None
    assert knowledge_path.read_bytes() == b"knowledge-runtime-sentinel"

    repository.save_working_analysis(_record(_ready_run("AN003")))
    assert repository.delete_all_analysis_data() == 1
    assert repository.list_analyses() == ()
    assert knowledge_path.read_bytes() == b"knowledge-runtime-sentinel"
    database.dispose()
    assert b"Synthetic resume evidence." not in app_path.read_bytes()


def test_analysis_path_is_external_configurable_and_separate_from_knowledge(
    tmp_path: Path,
) -> None:
    windows = resolve_analysis_db_path(
        platform_name="win32",
        environ={"LOCALAPPDATA": str(tmp_path / "local")},
        home=tmp_path / "home",
    )
    linux = resolve_analysis_db_path(
        platform_name="linux",
        environ={"XDG_DATA_HOME": str(tmp_path / "xdg")},
        home=tmp_path / "home",
    )
    macos = resolve_analysis_db_path(
        platform_name="darwin",
        environ={},
        home=tmp_path / "home",
    )

    assert windows.name == linux.name == macos.name == "analysis.sqlite3"
    assert "JobFitAgent" in windows.parts
    assert "jobfit-agent" in linux.parts
    assert "Application Support" in macos.parts
    assert not windows.exists()
    assert not linux.exists()
    assert not macos.exists()

    with pytest.raises(AnalysisPersistenceError, match="absolute"):
        resolve_analysis_db_path("relative/analysis.sqlite3")

    app_path = tmp_path / "app" / "analysis.sqlite3"
    knowledge_path = tmp_path / "knowledge" / "knowledge.sqlite3"
    settings = Settings(analysis_db_path=app_path, _env_file=None)
    repository = build_analysis_repository(
        settings,
        repository_root=tmp_path / "repository",
        knowledge_db_path=knowledge_path,
    )
    assert isinstance(repository, AnalysisRepository)
    assert isinstance(repository, SQLiteAnalysisRepository)
    assert app_path.exists()
    assert not knowledge_path.exists()
    repository.dispose()


def test_analysis_database_rejects_repository_and_knowledge_paths(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    inside_repository = repository_root / "analysis.sqlite3"
    knowledge_path = tmp_path / "knowledge.sqlite3"

    with pytest.raises(AnalysisPersistenceError, match="repository"):
        build_analysis_repository(
            Settings(analysis_db_path=inside_repository, _env_file=None),
            repository_root=repository_root,
            knowledge_db_path=knowledge_path,
        )
    assert not inside_repository.exists()

    with pytest.raises(AnalysisPersistenceError, match="knowledge"):
        build_analysis_repository(
            Settings(analysis_db_path=knowledge_path, _env_file=None),
            repository_root=repository_root,
            knowledge_db_path=knowledge_path,
        )
    assert not knowledge_path.exists()


def test_unknown_future_schema_fails_closed_without_leaking_path(tmp_path: Path) -> None:
    path = tmp_path / "private-user-name" / "analysis.sqlite3"
    path.parent.mkdir()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 2")

    database = AnalysisDatabase(path)
    with pytest.raises(AnalysisPersistenceError) as exc_info:
        database.ensure_compatible_schema()

    assert "schema" in str(exc_info.value).lower()
    assert str(path) not in str(exc_info.value)
    database.dispose()
