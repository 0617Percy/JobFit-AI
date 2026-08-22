"""Restart-safe v2 RC history without network or the knowledge database."""

from __future__ import annotations

from pathlib import Path

from jobfit.demo_v2 import DEMO_JD_TEXT, DEMO_RESUME_TEXT, build_demo_runtime
from jobfit.parsers.text import TextDocumentParser
from jobfit.scoring.v2 import SeniorityFacts
from jobfit.workflow.v2 import (
    AnalysisDatabase,
    SQLiteAnalysisRepository,
    initialize_analysis_schema,
)


def test_v2_application_recovers_completed_report_after_repository_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "analysis.sqlite3"
    database = AnalysisDatabase(path)
    initialize_analysis_schema(database)
    repository = SQLiteAnalysisRepository(database)
    resume_document = TextDocumentParser().parse_text(DEMO_RESUME_TEXT)
    jd_document = TextDocumentParser().parse_text(DEMO_JD_TEXT)
    runtime = build_demo_runtime(
        resume_document=resume_document,
        jd_document=jd_document,
        history=repository,
    )

    session = runtime.application.prepare_analysis(
        analysis_id="analysis-durable-1",
        resume_version_id="demo-resume-1",
        jd_snapshot_id="demo-jd-1",
        resume_document=resume_document,
        jd_document=jd_document,
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )
    assert repository.get_analysis("analysis-durable-1") == session.run

    session = runtime.application.begin_analysis(session)
    session = runtime.application.finish_analysis(session)
    expected_report = session.run.report
    expected_core = session.run.analysis_core
    database.dispose()

    reopened_database = AnalysisDatabase(path)
    reopened = SQLiteAnalysisRepository(reopened_database)
    restored = reopened.get_analysis("analysis-durable-1")

    assert restored is not None
    assert restored.report == expected_report
    assert restored.analysis_core == expected_core
    assert restored.input_snapshot is not None
    assert restored.input_snapshot.versions.knowledge_version == "2026.08.1"
    assert reopened.get_persisted_analysis("analysis-durable-1") is not None
    assert len(reopened.list_analysis_versions()) == 1
    reopened_database.dispose()
