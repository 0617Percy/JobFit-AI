"""Source-grounded resume extraction and deterministic model assembly."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from jobfit.errors import ErrorCode, SchemaValidationError
from jobfit.extractors.common import (
    build_prompt_messages,
    require_text_limit,
    settings_for_prompt,
    stable_id,
)
from jobfit.extractors.validators import grounding_error, validate_resume_fact
from jobfit.llm import LLMClient, LLMSettings, LLMTask, PromptRegistry
from jobfit.models import (
    AchievementItem,
    BasicInfo,
    CertificateItem,
    DocumentContent,
    EducationItem,
    EvidenceCandidate,
    EvidenceItem,
    EvidenceKind,
    EvidenceRegistry,
    EvidenceSourceType,
    ExperienceItem,
    LanguageItem,
    ProjectItem,
    ResumeBullet,
    ResumeExtractionDraft,
    ResumeFact,
    ResumeFactDraft,
    ResumeProfile,
    SkillItem,
    SkillType,
)

_ALLOWED_FIELDS: dict[str, set[str]] = {
    "basic_info": {"name", "email", "phone", "location", "target_title"},
    "education": {
        "institution",
        "degree",
        "major",
        "start_date",
        "end_date",
        "coursework",
        "gpa_text",
    },
    "experience": {"organization", "role", "start_date", "end_date", "bullets"},
    "project": {
        "name",
        "role",
        "start_date",
        "end_date",
        "technologies",
        "bullets",
    },
    "skill": {"name", "skill_type", "proficiency_text"},
    "achievement": {"name", "issuer", "date", "result_text"},
    "certificate": {"name", "issuer", "date"},
    "language": {"language", "proficiency_text"},
    "additional_information": {"text"},
}


class ResumeExtractor:
    """Convert a document into a validated profile plus resolvable evidence."""

    def __init__(
        self,
        *,
        client: LLMClient,
        prompt_registry: PromptRegistry,
        settings: LLMSettings,
        prompt_version: str = "1.0",
        max_characters: int = 50_000,
    ) -> None:
        self._client = client
        self._prompt_registry = prompt_registry
        self._settings = settings
        self._prompt_version = prompt_version
        self._max_characters = max_characters

    def extract(
        self,
        document: DocumentContent,
    ) -> tuple[ResumeProfile, EvidenceRegistry]:
        require_text_limit(
            document,
            max_characters=self._max_characters,
            label="简历",
        )
        template = self._prompt_registry.load(
            LLMTask.EXTRACT_RESUME.value,
            self._prompt_version,
        )
        draft = self._client.generate_structured(
            task=LLMTask.EXTRACT_RESUME,
            response_model=ResumeExtractionDraft,
            messages=build_prompt_messages(
                template,
                placeholder="resume_text",
                source_text=document.normalized_text,
            ),
            settings=settings_for_prompt(self._settings, template),
        )
        return self._assemble(document, draft)

    def _assemble(
        self,
        document: DocumentContent,
        draft: ResumeExtractionDraft,
    ) -> tuple[ResumeProfile, EvidenceRegistry]:
        draft_facts = [
            *draft.facts,
            *self._ground_basic_info(document, draft.basic_info),
        ]
        facts = sorted(
            draft_facts,
            key=lambda fact: (
                min(item.start_char for item in fact.evidence_candidates),
                fact.fact_type.casefold(),
                fact.raw_text,
            ),
        )
        for fact in facts:
            self._validate_fact_schema(fact)
            validate_resume_fact(document, fact)

        evidence_registry, fact_evidence = self._build_evidence(document, facts)
        try:
            profile = self._build_profile(
                document,
                draft,
                facts,
                fact_evidence,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise SchemaValidationError(
                code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                user_message="简历结构化结果无法映射到领域模型。",
                recoverable=True,
                cause=exc,
            ) from exc

        for evidence_ids in self._all_evidence_ids(profile):
            evidence_registry.require_many(evidence_ids)
        return profile, evidence_registry

    @staticmethod
    def _ground_basic_info(
        document: DocumentContent,
        basic_info: Mapping[str, Any],
    ) -> list[ResumeFactDraft]:
        unexpected = set(basic_info) - _ALLOWED_FIELDS["basic_info"]
        if unexpected:
            raise grounding_error("基本信息包含未定义的结构化字段。")
        facts: list[ResumeFactDraft] = []
        for key, value in basic_info.items():
            if value is None:
                continue
            if not isinstance(value, str):
                raise grounding_error("基本信息字段必须是原文字符串或空值。")
            start_char = document.normalized_text.find(value)
            if start_char < 0:
                raise grounding_error("基本信息无法在简历原文中定位。")
            facts.append(
                ResumeFactDraft(
                    fact_type="basic_info",
                    raw_text=value,
                    structured_fields={key: value},
                    evidence_candidates=[
                        EvidenceCandidate(
                            quote=value,
                            start_char=start_char,
                            end_char=start_char + len(value),
                            evidence_kind=EvidenceKind.DIRECT,
                            confidence=Decimal("1"),
                        )
                    ],
                )
            )
        return facts

    @staticmethod
    def _validate_fact_schema(fact: ResumeFactDraft) -> None:
        fact_type = fact.fact_type.casefold()
        allowed = _ALLOWED_FIELDS.get(fact_type)
        if allowed is None:
            raise grounding_error("简历事实类型不受支持。")
        unexpected = set(fact.structured_fields) - allowed
        if unexpected:
            raise grounding_error("简历事实包含未定义的结构化字段。")

    @staticmethod
    def _build_evidence(
        document: DocumentContent,
        facts: list[ResumeFactDraft],
    ) -> tuple[EvidenceRegistry, dict[int, list[str]]]:
        unique: dict[tuple[int, int, str], tuple[Any, Any]] = {}
        for fact in facts:
            for candidate in fact.evidence_candidates:
                segment = next(
                    segment
                    for segment in document.segments
                    if segment.start_char <= candidate.start_char
                    and candidate.end_char <= segment.end_char
                )
                key = (
                    candidate.start_char,
                    candidate.end_char,
                    candidate.evidence_kind.value,
                )
                unique.setdefault(key, (candidate, segment))

        items: list[EvidenceItem] = []
        key_to_id: dict[tuple[int, int, str], str] = {}
        for key in sorted(unique):
            candidate, segment = unique[key]
            evidence_id = stable_id(
                "ev",
                document.document_id,
                candidate.start_char,
                candidate.end_char,
                candidate.evidence_kind.value,
            )
            key_to_id[key] = evidence_id
            items.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    document_id=document.document_id,
                    segment_id=segment.segment_id,
                    source_type=EvidenceSourceType.RESUME,
                    source_reference=segment.segment_id,
                    quote=candidate.quote,
                    start_char=candidate.start_char,
                    end_char=candidate.end_char,
                    page_number=segment.page_number,
                    evidence_kind=candidate.evidence_kind,
                    confidence=candidate.confidence,
                )
            )

        fact_evidence: dict[int, list[str]] = {}
        for position, fact in enumerate(facts):
            ids = []
            for candidate in fact.evidence_candidates:
                key = (
                    candidate.start_char,
                    candidate.end_char,
                    candidate.evidence_kind.value,
                )
                evidence_id = key_to_id[key]
                if evidence_id not in ids:
                    ids.append(evidence_id)
            fact_evidence[position] = ids
        return EvidenceRegistry(items), fact_evidence

    def _build_profile(
        self,
        document: DocumentContent,
        draft: ResumeExtractionDraft,
        facts: list[ResumeFactDraft],
        fact_evidence: dict[int, list[str]],
    ) -> ResumeProfile:
        basic_fields: dict[str, Any] = {}
        basic_evidence: list[str] = []
        education: list[EducationItem] = []
        experiences: list[ExperienceItem] = []
        projects: list[ProjectItem] = []
        skills: list[SkillItem] = []
        achievements: list[AchievementItem] = []
        certificates: list[CertificateItem] = []
        languages: list[LanguageItem] = []
        additional: list[ResumeFact] = []

        for position, fact in enumerate(facts):
            fact_type = fact.fact_type.casefold()
            fields = dict(fact.structured_fields)
            evidence_ids = fact_evidence[position]
            identity = stable_id(
                fact_type,
                document.document_id,
                fact.raw_text,
                *evidence_ids,
            )
            if fact_type == "basic_info":
                for key, value in fields.items():
                    if value is not None:
                        if key in basic_fields and basic_fields[key] != value:
                            raise grounding_error("基本信息存在相互冲突的提取结果。")
                        basic_fields[key] = value
                basic_evidence.extend(
                    item for item in evidence_ids if item not in basic_evidence
                )
            elif fact_type == "education":
                education.append(
                    EducationItem(
                        education_id=identity,
                        raw_text=fact.raw_text,
                        evidence_ids=evidence_ids,
                        **fields,
                    )
                )
            elif fact_type == "experience":
                bullet_values = fields.pop("bullets", [])
                experiences.append(
                    ExperienceItem(
                        experience_id=identity,
                        raw_text=fact.raw_text,
                        evidence_ids=evidence_ids,
                        bullets=self._build_bullets(
                            identity,
                            bullet_values,
                            evidence_ids,
                        ),
                        **fields,
                    )
                )
            elif fact_type == "project":
                bullet_values = fields.pop("bullets", [])
                projects.append(
                    ProjectItem(
                        project_id=identity,
                        raw_text=fact.raw_text,
                        evidence_ids=evidence_ids,
                        bullets=self._build_bullets(
                            identity,
                            bullet_values,
                            evidence_ids,
                        ),
                        **fields,
                    )
                )
            elif fact_type == "skill":
                fields.setdefault("skill_type", SkillType.OTHER)
                skills.append(
                    SkillItem(
                        skill_id=identity,
                        evidence_ids=evidence_ids,
                        **fields,
                    )
                )
            elif fact_type == "achievement":
                achievements.append(
                    AchievementItem(
                        achievement_id=identity,
                        evidence_ids=evidence_ids,
                        **fields,
                    )
                )
            elif fact_type == "certificate":
                certificates.append(
                    CertificateItem(
                        certificate_id=identity,
                        evidence_ids=evidence_ids,
                        **fields,
                    )
                )
            elif fact_type == "language":
                languages.append(
                    LanguageItem(
                        language_id=identity,
                        evidence_ids=evidence_ids,
                        **fields,
                    )
                )
            else:
                additional.append(
                    ResumeFact(
                        fact_id=identity,
                        fact_type=fact.fact_type,
                        text=str(fields.get("text") or fact.raw_text),
                        evidence_ids=evidence_ids,
                    )
                )

        return ResumeProfile(
            resume_id=stable_id("resume", document.document_id),
            document_id=document.document_id,
            language=draft.language,
            basic_info=BasicInfo(
                **basic_fields,
                evidence_ids=basic_evidence,
            ),
            education=education,
            experiences=experiences,
            projects=projects,
            skills=skills,
            achievements=achievements,
            certificates=certificates,
            languages=languages,
            additional_information=additional,
            extraction_warnings=draft.extraction_warnings,
        )

    @staticmethod
    def _build_bullets(
        parent_id: str,
        values: Any,
        evidence_ids: list[str],
    ) -> list[ResumeBullet]:
        if not isinstance(values, list):
            raise TypeError("bullets must be a list")
        bullets: list[ResumeBullet] = []
        for index, value in enumerate(values, start=1):
            if isinstance(value, str):
                payload: Mapping[str, Any] = {"text": value}
            elif isinstance(value, Mapping):
                payload = value
            else:
                raise TypeError("bullet entries must be strings or objects")
            bullets.append(
                ResumeBullet(
                    bullet_id=stable_id("bullet", parent_id, index, payload.get("text")),
                    evidence_ids=evidence_ids,
                    **payload,
                )
            )
        return bullets

    @staticmethod
    def _all_evidence_ids(profile: ResumeProfile) -> list[list[str]]:
        return [
            profile.basic_info.evidence_ids,
            *(item.evidence_ids for item in profile.education),
            *(item.evidence_ids for item in profile.experiences),
            *(bullet.evidence_ids for item in profile.experiences for bullet in item.bullets),
            *(item.evidence_ids for item in profile.projects),
            *(bullet.evidence_ids for item in profile.projects for bullet in item.bullets),
            *(item.evidence_ids for item in profile.skills),
            *(item.evidence_ids for item in profile.achievements),
            *(item.evidence_ids for item in profile.certificates),
            *(item.evidence_ids for item in profile.languages),
            *(item.evidence_ids for item in profile.additional_information),
        ]
