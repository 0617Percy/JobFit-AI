"""Four-layer semantic validation and cross-object isolation tests."""

from __future__ import annotations

from jobfit.models import Importance
from jobfit.models.v2 import (
    AbilityStatus,
    CandidateProfile,
    CandidateStatus,
    CriticalStatus,
    Evidence,
    EvidenceLevel,
    EvidenceSourceOrigin,
    EvidenceStatus,
    JobFamily,
    JobProfile,
    KnowledgeCoverage,
    MatchCoverage,
    MatchedEvidence,
    ParseCompleteness,
    PersonalContribution,
    Relevance,
    Requirement,
    RequirementExplicitness,
    RequirementMatch,
    RequirementSource,
    RequirementType,
    ResumeProfile,
    SupportType,
)
from jobfit.semantic.v2.contracts import (
    PromptExecutionRecord,
    PromptValidationRecord,
)
from jobfit.semantic.v2.validation import SemanticPipelineValidator


def _record(prompt_id: str) -> PromptExecutionRecord:
    return PromptExecutionRecord(
        prompt_id=prompt_id,
        prompt_version="1.0.0",
        global_rules_version="1.0.0",
        prompt_pack_version="1.0.0-candidate",
        attempt_count=1,
        attempts=(),
        input_object_ids=("analysis-1",),
        output_object_ids=(),
        validation=PromptValidationRecord(
            syntax_valid=True,
            schema_valid=True,
            business_valid=True,
            cross_object_valid=True,
        ),
        provider="mock",
        model="semantic-mock",
    )


def _objects() -> tuple[
    ResumeProfile,
    list[Evidence],
    JobProfile,
    list[Requirement],
    list[RequirementMatch],
]:
    resume = ResumeProfile(
        resume_version_id="resume-version-1",
        candidate_profile=CandidateProfile(current_status=CandidateStatus.STUDENT),
        education=[{"label": "Synthetic degree"}],
        projects=[{"label": "Synthetic project", "evidence_ids": ["evidence-1"]}],
        evidence_ids=["evidence-1"],
        parse_completeness=ParseCompleteness.COMPLETE,
    )
    evidence = Evidence(
        evidence_id="evidence-1",
        resume_version_id="resume-version-1",
        source_origin=EvidenceSourceOrigin.RESUME,
        source_type="project",
        source_text="Built a tested API.",
        personal_contribution=PersonalContribution.CLEAR,
        evidence_level=EvidenceLevel.L1,
        document_id="doc-resume-1",
        segment_id="segment-resume-1",
        start_char=0,
        end_char=19,
    )
    requirement = Requirement(
        requirement_id="requirement-1",
        jd_snapshot_id="jd-snapshot-1",
        raw_requirement_ids=["raw-requirement-1"],
        raw_text="Python is required.",
        normalized_capability="Python",
        requirement_type=RequirementType.CORE,
        importance=Importance.HIGH,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
        critical_status=CriticalStatus.NOT_CRITICAL,
    )
    job = JobProfile(
        jd_snapshot_id="jd-snapshot-1",
        job_title="Synthetic role",
        job_family=JobFamily.AI_APPLICATION,
        knowledge_coverage=KnowledgeCoverage.BASE_ONLY,
        raw_requirement_ids=["raw-requirement-1"],
        requirement_ids=["requirement-1"],
    )
    match = RequirementMatch(
        match_id="match-1",
        requirement_id="requirement-1",
        matched_evidence=[
            MatchedEvidence(
                evidence_id="evidence-1",
                relevance=Relevance.HIGH,
                support_type=SupportType.DIRECT,
            )
        ],
        coverage=MatchCoverage.FULL,
        evidence_status=EvidenceStatus.PRESENT,
        ability_status=AbilityStatus.CONFIRMED,
    )
    return resume, [evidence], job, [requirement], [match]


def test_four_validation_layers_pass_for_consistent_semantic_objects() -> None:
    resume, evidence, job, requirements, matches = _objects()

    result = SemanticPipelineValidator().validate(
        analysis_id="analysis-1",
        resume_profile=resume,
        evidence=evidence,
        job_profile=job,
        requirements=requirements,
        matches=matches,
        execution_records=tuple(_record(f"P0{index}") for index in range(1, 6)),
    )

    assert result.valid is True
    assert result.syntax_valid is True
    assert result.schema_valid is True
    assert result.business_valid is True
    assert result.cross_object_valid is True
    assert result.issue_codes == ()


def test_cross_object_layer_rejects_wrong_resume_and_jd_versions() -> None:
    resume, evidence, job, requirements, matches = _objects()
    evidence[0] = evidence[0].model_copy(update={"resume_version_id": "resume-other"})
    requirements[0] = requirements[0].model_copy(update={"jd_snapshot_id": "jd-other"})

    result = SemanticPipelineValidator().validate(
        analysis_id="analysis-1",
        resume_profile=resume,
        evidence=evidence,
        job_profile=job,
        requirements=requirements,
        matches=matches,
        execution_records=tuple(_record(f"P0{index}") for index in range(1, 6)),
    )

    assert result.valid is False
    assert result.cross_object_valid is False
    assert "EVIDENCE_RESUME_VERSION_MISMATCH" in result.issue_codes
    assert "REQUIREMENT_JD_VERSION_MISMATCH" in result.issue_codes


def test_cross_object_layer_rejects_dangling_match_evidence() -> None:
    resume, evidence, job, requirements, matches = _objects()
    matches[0] = matches[0].model_copy(
        update={
            "matched_evidence": [
                MatchedEvidence(
                    evidence_id="evidence-other",
                    relevance=Relevance.HIGH,
                    support_type=SupportType.DIRECT,
                )
            ]
        }
    )

    result = SemanticPipelineValidator().validate(
        analysis_id="analysis-1",
        resume_profile=resume,
        evidence=evidence,
        job_profile=job,
        requirements=requirements,
        matches=matches,
        execution_records=tuple(_record(f"P0{index}") for index in range(1, 6)),
    )

    assert result.valid is False
    assert result.issue_codes == ("DANGLING_MATCH_EVIDENCE_REFERENCE",)


def test_execution_layer_requires_exact_p01_to_p05_trace() -> None:
    resume, evidence, job, requirements, matches = _objects()

    result = SemanticPipelineValidator().validate(
        analysis_id="analysis-1",
        resume_profile=resume,
        evidence=evidence,
        job_profile=job,
        requirements=requirements,
        matches=matches,
        execution_records=(_record("P01"), _record("P02")),
    )

    assert result.valid is False
    assert result.business_valid is False
    assert result.issue_codes == ("PROMPT_TRACE_INCOMPLETE",)
