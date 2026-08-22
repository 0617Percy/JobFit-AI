"""Contract tests for the JobFit Agent domain models."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from jobfit.models import (
    AdviceBundleDraft,
    AnalysisReport,
    ApplicationRecommendation,
    DimensionScore,
    DocumentContent,
    DocumentSourceKind,
    EducationItem,
    EvidenceItem,
    EvidenceKind,
    EvidenceRegistry,
    EvidenceSourceType,
    GapItem,
    GapRemediability,
    HardConditionKind,
    Importance,
    InterviewQuestion,
    JobProfile,
    JobRequirement,
    JobRequirementCollection,
    JobRequirementDraft,
    LanguageCode,
    MatchScoreSummary,
    MatchStatus,
    RecommendationLevel,
    RequirementCategory,
    RequirementMatch,
    RequirementMatchDraft,
    RequirementType,
    ResumeProfile,
    RewriteSuggestion,
    StrengthItem,
    TextSegment,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)


def make_segment() -> TextSegment:
    return TextSegment(
        segment_id="seg-001",
        start_char=0,
        end_char=6,
        text="Python",
    )


def make_evidence(
    *,
    evidence_id: str = "ev-001",
    evidence_kind: EvidenceKind = EvidenceKind.DIRECT,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        document_id="doc-001",
        segment_id="seg-001",
        source_type=EvidenceSourceType.RESUME,
        source_reference="seg-001",
        quote="Python",
        start_char=0,
        end_char=6,
        evidence_kind=evidence_kind,
        confidence=Decimal("0.95"),
    )


def make_requirement() -> JobRequirement:
    return JobRequirement(
        requirement_id="req-001",
        requirement_text="熟悉 Python",
        source_text="熟悉 Python",
        source_start_char=0,
        source_end_char=9,
        requirement_type=RequirementType.MUST_HAVE,
        category=RequirementCategory.TECHNICAL_SKILL,
        importance=Importance.HIGH,
        mandatory=True,
        hard_condition_kind=HardConditionKind.NONE,
        normalized_key="python",
        priority_factor=Decimal("4"),
        weight=Decimal("100"),
    )


def make_job_profile() -> JobProfile:
    requirement = make_requirement()
    return JobProfile(
        job_id="job-001",
        title="AI 应用开发实习生",
        company="示例科技",
        language=LanguageCode.ZH,
        jd_text="熟悉 Python",
        summary="面向初级候选人的 AI 应用岗位",
        requirements=JobRequirementCollection(
            items=[requirement],
            source_coverage_ratio=Decimal("1"),
        ),
        keywords=["Python"],
    )


def make_resume_profile() -> ResumeProfile:
    return ResumeProfile(
        resume_id="resume-001",
        document_id="doc-001",
        language=LanguageCode.ZH,
        education=[
            EducationItem(
                education_id="edu-001",
                institution="示例大学",
                degree="本科",
                major="计算机科学",
                raw_text="示例大学 计算机科学 本科",
                evidence_ids=["ev-001"],
            )
        ],
        extraction_warnings=[],
    )


def make_match() -> RequirementMatch:
    return RequirementMatch(
        requirement_id="req-001",
        match_status=MatchStatus.MATCHED,
        match_score=Decimal("1"),
        evidence_items=[make_evidence()],
        reasoning="简历中存在直接使用 Python 的证据。",
        confidence=Decimal("0.95"),
        improvement_suggestion="补充项目规模和职责边界。",
    )


def make_score_summary() -> MatchScoreSummary:
    return MatchScoreSummary(
        dimension_scores=[
            DimensionScore(
                category=RequirementCategory.TECHNICAL_SKILL,
                base_points=Decimal("25"),
                effective_points=Decimal("25"),
                earned_points=Decimal("25"),
                active=True,
                requirement_ids=["req-001"],
                coverage_ratio=Decimal("1"),
            )
        ],
        raw_score=Decimal("100"),
        score_cap=Decimal("100"),
        final_score=Decimal("100"),
        mandatory_coverage_ratio=Decimal("1"),
        strong_evidence_coverage_ratio=Decimal("1"),
        confirmed_hard_blockers=[],
        unverified_hard_blockers=[],
        recommendation_level=RecommendationLevel.PRIORITY_APPLY,
    )


def make_interview_questions() -> list[InterviewQuestion]:
    return [
        InterviewQuestion(
            question_id=f"question-{index}",
            question=f"请介绍第 {index} 个相关项目。",
            intent="验证项目经验",
            answer_framework=["背景", "行动", "结果"],
            resume_evidence_ids=["ev-001"],
            requirement_ids=["req-001"],
            emphasis=["个人贡献"],
            risks_to_avoid=["不要夸大职责"],
        )
        for index in range(1, 6)
    ]


def make_report() -> AnalysisReport:
    return AnalysisReport(
        schema_version="1.0",
        report_id="report-001",
        generated_at=datetime(2026, 7, 23, 10, 30, tzinfo=UTC),
        job_profile=make_job_profile(),
        resume_profile=make_resume_profile(),
        matches=[make_match()],
        score_summary=make_score_summary(),
        strengths=[
            StrengthItem(
                title="Python 项目证据明确",
                summary="项目经历能够直接支持岗位技术要求。",
                requirement_ids=["req-001"],
                evidence_ids=["ev-001"],
                why_it_matters="该能力是岗位的高权重要求。",
            )
        ],
        gaps=[
            GapItem(
                title="工程规模未体现",
                summary="简历尚未证明生产环境经验。",
                requirement_ids=["req-001"],
                remediability=GapRemediability.EVIDENCE_NEEDED,
                risk_level=Importance.MEDIUM,
                recommended_action="如有真实经历，补充项目规模和部署证据。",
                user_confirmation_needed=True,
            )
        ],
        recommendation=ApplicationRecommendation(
            level=RecommendationLevel.PRIORITY_APPLY,
            reasoning=["核心技能存在直接证据"],
            blocking_requirement_ids=[],
            before_applying_actions=["补充项目规模"],
        ),
        rewrite_suggestions=[
            RewriteSuggestion(
                suggestion_id="rewrite-001",
                original_text="使用 Python 处理数据。",
                rewritten_text="使用 Python 完成项目数据处理与实验分析。",
                reason="突出已有动作，不新增结果。",
                requirement_ids=["req-001"],
                evidence_ids=["ev-001"],
                introduced_claims=[],
                user_confirmation_needed=[],
            )
        ],
        interview_questions=make_interview_questions(),
        limitations=[],
        validation=ValidationResult(
            valid=True,
            issues=[],
            checked_rules=["report_consistency"],
        ),
    )


def test_document_content_computes_text_length_and_serializes_metadata() -> None:
    document = DocumentContent(
        document_id="doc-001",
        source_kind=DocumentSourceKind.PASTED_TEXT,
        source="manual_input",
        raw_text="Python",
        normalized_text="Python",
        language=LanguageCode.ZH,
        segments=[make_segment()],
        content_sha256="a" * 64,
        metadata={"input_mode": "paste"},
    )

    assert document.text_length == 6
    assert document.model_dump()["text_length"] == 6
    assert document.model_dump()["metadata"] == {"input_mode": "paste"}


def test_text_segment_rejects_invalid_offsets_and_exposes_index_aliases() -> None:
    segment = make_segment()

    assert segment.start_index == segment.start_char == 0
    assert segment.end_index == segment.end_char == 6

    with pytest.raises(ValidationError):
        TextSegment(
            segment_id="seg-invalid",
            start_char=2,
            end_char=5,
            text="Python",
        )


def test_strict_models_forbid_unknown_fields_and_validate_assignment() -> None:
    with pytest.raises(ValidationError, match="extra"):
        TextSegment(
            segment_id="seg-001",
            start_char=0,
            end_char=6,
            text="Python",
            unexpected=True,
        )

    segment = make_segment()
    with pytest.raises(ValidationError):
        segment.end_char = -1


def test_required_fields_and_enum_values_are_validated() -> None:
    with pytest.raises(ValidationError, match="document_id"):
        DocumentContent(
            source_kind=DocumentSourceKind.TXT,
            raw_text="text",
            normalized_text="text",
            content_sha256="b" * 64,
        )

    with pytest.raises(ValidationError, match="requirement_type"):
        JobRequirementDraft(
            requirement_text="熟悉 Python",
            source_text="熟悉 Python",
            source_start_char=0,
            source_end_char=9,
            requirement_type="technical_skill",
            category=RequirementCategory.TECHNICAL_SKILL,
            importance=Importance.HIGH,
            mandatory=True,
            normalized_key="python",
        )


def test_evidence_registry_preserves_order_and_rejects_bad_references() -> None:
    first = make_evidence()
    second = make_evidence(evidence_id="ev-002")
    registry = EvidenceRegistry([first, second])

    assert registry.require_many(["ev-002", "ev-001"]) == [second, first]
    assert registry.ids == ("ev-001", "ev-002")

    with pytest.raises(ValueError, match="Duplicate evidence_id"):
        EvidenceRegistry([first, first])

    with pytest.raises(KeyError, match="ev-missing"):
        registry.require_many(["ev-missing"])


def test_evidence_item_validates_quote_range_and_confidence() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            evidence_id="ev-invalid",
            document_id="doc-001",
            segment_id="seg-001",
            source_type=EvidenceSourceType.RESUME,
            source_reference="seg-001",
            quote="Python",
            start_char=0,
            end_char=5,
            evidence_kind=EvidenceKind.DIRECT,
            confidence=Decimal("1.1"),
        )

    evidence = make_evidence()
    assert evidence.text == evidence.quote


def test_resume_profile_validates_nested_experience_evidence() -> None:
    profile = make_resume_profile()

    assert profile.education[0].raw_text == "示例大学 计算机科学 本科"
    assert profile.education[0].evidence_ids == ["ev-001"]

    with pytest.raises(ValidationError, match="evidence_ids"):
        EducationItem(
            education_id="edu-invalid",
            institution="示例大学",
            raw_text="示例大学",
            evidence_ids=[],
        )


def test_job_requirement_enforces_implicit_and_hard_condition_rules() -> None:
    with pytest.raises(ValidationError, match="Implicit requirements"):
        JobRequirementDraft(
            requirement_text="能够快速学习",
            source_text="我们重视快速学习",
            source_start_char=0,
            source_end_char=8,
            requirement_type=RequirementType.IMPLICIT,
            category=RequirementCategory.COMMUNICATION_KEYWORD,
            importance=Importance.HIGH,
            mandatory=True,
            normalized_key="learning_agility",
        )

    with pytest.raises(ValidationError, match="Hard conditions"):
        JobRequirementDraft(
            requirement_text="需要硕士学历",
            source_text="需要硕士学历",
            source_start_char=0,
            source_end_char=6,
            requirement_type=RequirementType.MUST_HAVE,
            category=RequirementCategory.ELIGIBILITY,
            importance=Importance.MEDIUM,
            mandatory=True,
            hard_condition_kind=HardConditionKind.DEGREE_LEVEL,
            normalized_key="degree_level",
        )


def test_job_requirement_collection_rejects_duplicate_ids() -> None:
    requirement = make_requirement()

    with pytest.raises(ValidationError, match="Duplicate requirement_id"):
        JobRequirementCollection(
            items=[requirement, requirement],
            source_coverage_ratio=Decimal("1"),
        )


def test_requirement_match_requires_status_appropriate_evidence() -> None:
    base = {
        "requirement_id": "req-001",
        "match_score": Decimal("1"),
        "reasoning": "测试理由",
        "confidence": Decimal("0.9"),
        "improvement_suggestion": "补充有效证据。",
    }

    with pytest.raises(ValidationError, match="direct evidence"):
        RequirementMatch(
            **base,
            match_status=MatchStatus.MATCHED,
            evidence_items=[
                make_evidence(evidence_kind=EvidenceKind.CONTEXTUAL)
            ],
        )

    with pytest.raises(ValidationError, match="at least one evidence"):
        RequirementMatch(
            **base,
            match_status=MatchStatus.PARTIAL_MATCH,
            evidence_items=[],
        )

    with pytest.raises(ValidationError, match="missing_evidence_note"):
        RequirementMatch(
            **{**base, "match_score": Decimal("0")},
            match_status=MatchStatus.UNKNOWN,
            evidence_items=[],
        )


def test_score_models_enforce_numeric_bounds() -> None:
    with pytest.raises(ValidationError):
        DimensionScore(
            category=RequirementCategory.TECHNICAL_SKILL,
            base_points=Decimal("25"),
            effective_points=Decimal("25"),
            earned_points=Decimal("30"),
            active=True,
            requirement_ids=["req-001"],
            coverage_ratio=Decimal("1"),
        )

    with pytest.raises(ValidationError, match="mandatory_coverage_ratio"):
        MatchScoreSummary(
            dimension_scores=[],
            raw_score=Decimal("50"),
            score_cap=Decimal("100"),
            final_score=Decimal("50"),
            mandatory_coverage_ratio=Decimal("1.1"),
            strong_evidence_coverage_ratio=Decimal("0.5"),
            confirmed_hard_blockers=[],
            unverified_hard_blockers=[],
            recommendation_level=RecommendationLevel.TRY_APPLY,
        )


def test_validation_result_must_agree_with_error_issues() -> None:
    issue = ValidationIssue(
        code="missing_evidence",
        severity=ValidationSeverity.ERROR,
        message="匹配项缺少证据。",
        object_ref="matches.0",
    )

    with pytest.raises(ValidationError, match="valid"):
        ValidationResult(
            valid=True,
            issues=[issue],
            checked_rules=["evidence_grounding"],
        )


def test_analysis_report_validates_cardinality_and_aware_timestamp() -> None:
    payload = make_report().model_dump()
    payload["interview_questions"] = make_interview_questions()[:4]

    with pytest.raises(ValidationError, match="interview_questions"):
        AnalysisReport.model_validate(payload)

    payload = make_report().model_dump()
    payload["generated_at"] = datetime(2026, 7, 23, 10, 30)

    with pytest.raises(ValidationError, match="generated_at"):
        AnalysisReport.model_validate(payload)


def test_analysis_report_json_round_trip_is_stable() -> None:
    report = make_report()

    raw_json = report.model_dump_json()
    payload = json.loads(raw_json)
    restored = AnalysisReport.model_validate_json(raw_json)

    assert payload["schema_version"] == "1.0"
    assert payload["score_summary"]["final_score"] == "100"
    assert restored == report


def test_report_schema_excludes_upload_bytes_and_secrets() -> None:
    schema_text = json.dumps(AnalysisReport.model_json_schema()).lower()

    assert "api_key" not in schema_text
    assert "uploaded_document_input" not in schema_text
    assert "content_sha256" not in schema_text


def test_job_profile_keeps_original_jd_text() -> None:
    profile = make_job_profile()

    assert profile.jd_text == "熟悉 Python"
    assert profile.requirements.items[0].weight == Decimal("100")


def test_llm_drafts_exclude_deterministic_fields() -> None:
    assert "priority_factor" not in JobRequirementDraft.model_fields
    assert "weight" not in JobRequirementDraft.model_fields
    assert "match_score" not in RequirementMatchDraft.model_fields
    assert "level" not in AdviceBundleDraft.model_fields


def test_resume_profile_rejects_duplicate_item_ids() -> None:
    education = make_resume_profile().education[0]

    with pytest.raises(ValidationError, match="unique"):
        ResumeProfile(
            resume_id="resume-duplicate",
            document_id="doc-001",
            language=LanguageCode.ZH,
            education=[education, education],
        )


def test_analysis_report_is_frozen() -> None:
    report = make_report()

    with pytest.raises(ValidationError, match="frozen"):
        report.limitations = ["changed after final assembly"]
