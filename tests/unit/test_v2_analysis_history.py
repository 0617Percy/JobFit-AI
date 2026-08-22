"""B6 append-only in-memory analysis history semantics."""

from __future__ import annotations

from decimal import Decimal

import pytest

from jobfit.models.v2 import (
    AnalysisCore,
    AnalysisInputSnapshot,
    AnalysisReadiness,
    AnalysisStage,
    ArtifactGraph,
    ArtifactRecord,
    Confidence,
    EligibilityStatus,
    LifecycleStatus,
    Recommendation,
    SeniorityAlignment,
    UserClarification,
    ValidityStatus,
    VersionManifest,
)
from jobfit.workflow.v2 import (
    AnalysisHistoryError,
    AnalysisRepository,
    InMemoryAnalysisRepository,
    create_analysis_run,
    fail_stage,
    fork_analysis_run,
    start_stage,
    transition_run,
)


def _core(analysis_id: str, score: str) -> AnalysisCore:
    return AnalysisCore(
        analysis_id=analysis_id,
        resume_version_id="resume-v1" if analysis_id == "AN001" else "resume-v2",
        jd_snapshot_id="jd-v1",
        analysis_readiness=AnalysisReadiness.READY,
        eligibility_status=EligibilityStatus.MET,
        seniority_alignment=SeniorityAlignment.ALIGNED,
        base_fit_score=Decimal(score),
        preferred_bonus=Decimal("0"),
        final_fit_score=Decimal(score),
        confidence=Confidence.HIGH,
        recommendation=(
            Recommendation.SUGGESTED
            if Decimal(score) >= Decimal("70")
            else Recommendation.CHALLENGE
        ),
    )


def _snapshot(analysis_id: str) -> AnalysisInputSnapshot:
    return AnalysisInputSnapshot.freeze(
        analysis_id=analysis_id,
        resume_version_id="resume-v1" if analysis_id == "AN001" else "resume-v2",
        jd_snapshot_id="jd-v1",
        user_clarifications=(
            UserClarification(
                clarification_id=f"clarification-{analysis_id}",
                analysis_id=analysis_id,
                question="Did you own deployment?",
                answer="Yes.",
            ),
        ),
        versions=VersionManifest(
            software_version="1.1.0",
            prompt_pack_version="1.0.0",
            schema_version="2.0.0",
            scoring_rule_version="1.0.0",
            knowledge_version="2026.08.1",
            analysis_engine_version="1.0.0",
        ),
    )


def _completed_run(
    analysis_id: str,
    *,
    score: str,
    parent_analysis_id: str | None = None,
):
    run = create_analysis_run(analysis_id)
    run = transition_run(run, LifecycleStatus.INPUT_READY)
    run = transition_run(run, LifecycleStatus.PARSING)
    run = transition_run(
        run,
        LifecycleStatus.ANALYSIS_READY,
        snapshot=_snapshot(analysis_id),
    )
    run = transition_run(run, LifecycleStatus.ANALYZING)
    run = transition_run(run, LifecycleStatus.REPORT_GENERATING)
    run = transition_run(run, LifecycleStatus.COMPLETED)
    graph = ArtifactGraph(
        analysis_id=analysis_id,
        artifacts=(
            ArtifactRecord(
                artifact_id=f"{analysis_id}-score",
                analysis_id=analysis_id,
                stage="scoring",
                validity=ValidityStatus.VALID,
                content_hash="a" * 64,
            ),
        ),
    )
    return run.model_copy(
        update={
            "parent_analysis_id": parent_analysis_id,
            "reanalysis_reason": (
                "Resume version changed." if parent_analysis_id else None
            ),
            "artifact_graph": graph,
            "analysis_core": _core(analysis_id, score),
        }
    )


def test_in_memory_repository_satisfies_the_domain_protocol() -> None:
    assert isinstance(InMemoryAnalysisRepository(), AnalysisRepository)


def test_completed_analysis_is_append_only_and_cannot_be_overwritten() -> None:
    repository = InMemoryAnalysisRepository()
    original = _completed_run("AN001", score="73")
    repository.append_analysis(original)

    with pytest.raises(AnalysisHistoryError, match="already exists"):
        repository.append_analysis(_completed_run("AN001", score="86"))

    stored = repository.get_analysis("AN001")
    assert stored is not None
    assert stored.analysis_core is not None
    assert stored.analysis_core.final_fit_score == Decimal("73")
    assert not hasattr(repository, "update_completed_analysis")


def test_returned_objects_cannot_mutate_stored_history() -> None:
    repository = InMemoryAnalysisRepository()
    repository.append_analysis(_completed_run("AN001", score="73"))
    fetched = repository.get_analysis("AN001")
    assert fetched is not None and fetched.analysis_core is not None

    fetched.analysis_core.final_fit_score = Decimal("99")

    refetched = repository.get_analysis("AN001")
    assert refetched is not None and refetched.analysis_core is not None
    assert refetched.analysis_core.final_fit_score == Decimal("73")


def test_resume_v2_appends_an002_without_changing_an001_bytes_or_semantics() -> None:
    repository = InMemoryAnalysisRepository()
    original = _completed_run("AN001", score="73")
    repository.append_analysis(original)
    before = repository.get_analysis("AN001").model_dump_json()

    repository.append_analysis(
        _completed_run(
            "AN002",
            score="86",
            parent_analysis_id="AN001",
        )
    )

    after = repository.get_analysis("AN001")
    child = repository.get_analysis("AN002")
    assert after is not None and child is not None
    assert after.model_dump_json() == before
    assert after.input_snapshot.resume_version_id == "resume-v1"
    assert after.analysis_core.final_fit_score == Decimal("73")
    assert child.input_snapshot.resume_version_id == "resume-v2"
    assert child.analysis_core.final_fit_score == Decimal("86")
    assert repository.get_parent("AN002").analysis_id == "AN001"


def test_child_run_requires_an_existing_completed_parent() -> None:
    repository = InMemoryAnalysisRepository()

    with pytest.raises(AnalysisHistoryError, match="parent"):
        repository.append_analysis(
            _completed_run(
                "AN002",
                score="86",
                parent_analysis_id="AN001",
            )
        )


def test_failed_analysis_can_parent_a_new_retry_run_without_overwrite() -> None:
    repository = InMemoryAnalysisRepository()
    parent = create_analysis_run("AN001")
    parent = transition_run(parent, LifecycleStatus.INPUT_READY)
    parent = transition_run(parent, LifecycleStatus.PARSING)
    parent = transition_run(
        parent,
        LifecycleStatus.ANALYSIS_READY,
        snapshot=_snapshot("AN001"),
    )
    parent = transition_run(parent, LifecycleStatus.ANALYZING)
    failed_lifecycle = fail_stage(
        start_stage(parent.lifecycle, AnalysisStage.SCORING),
        AnalysisStage.SCORING,
    )
    parent = parent.model_copy(update={"lifecycle": failed_lifecycle})
    repository.append_analysis(parent)

    child = fork_analysis_run(
        parent,
        target_analysis_id="AN002",
        reason="Retry a failed scoring stage.",
    )
    child = transition_run(
        child,
        LifecycleStatus.ANALYSIS_READY,
        snapshot=_snapshot("AN002"),
    )
    child = transition_run(child, LifecycleStatus.ANALYZING)
    child = transition_run(child, LifecycleStatus.REPORT_GENERATING)
    child = transition_run(child, LifecycleStatus.COMPLETED)

    repository.append_analysis(child)

    assert repository.get_parent("AN002") == repository.get_analysis("AN001")
    assert repository.get_analysis("AN001").lifecycle.status is LifecycleStatus.FAILED


def test_history_listing_is_stable_and_returns_independent_models() -> None:
    repository = InMemoryAnalysisRepository()
    repository.append_analysis(_completed_run("AN001", score="73"))
    repository.append_analysis(
        _completed_run("AN002", score="86", parent_analysis_id="AN001")
    )

    first = repository.list_analysis_versions()
    second = repository.list_analysis_versions()

    assert [item.analysis_id for item in first] == ["AN001", "AN002"]
    assert first == second
    assert first[0] is not second[0]
