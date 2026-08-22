"""Frozen enumerations for the target JobFit domain contract."""

from enum import StrEnum


class EvidenceSourceOrigin(StrEnum):
    RESUME = "resume"
    USER_CLARIFICATION = "user_clarification"
    PORTFOLIO = "portfolio"
    EXTERNAL_VERIFICATION = "external_verification"


class PersonalContribution(StrEnum):
    CLEAR = "clear"
    PARTIAL = "partial"
    UNCLEAR = "unclear"
    NOT_APPLICABLE = "not_applicable"


class ClarityLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class EvidenceLevel(StrEnum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class CandidateStatus(StrEnum):
    STUDENT = "student"
    FRESH_GRADUATE = "fresh_graduate"
    EARLY_CAREER = "early_career"
    UNKNOWN = "unknown"


class ParseCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class RequirementType(StrEnum):
    HARD = "hard"
    CORE = "core"
    SUPPORTING = "supporting"
    PREFERRED = "preferred"
    IMPLICIT = "implicit"


class RequirementExplicitness(StrEnum):
    EXPLICIT = "explicit"
    IMPLICIT = "implicit"


class RequirementSource(StrEnum):
    JD = "jd"
    KNOWLEDGE = "knowledge"


class CriticalStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANDIDATE = "candidate"
    NOT_CRITICAL = "not_critical"


class JobFamily(StrEnum):
    AI_APPLICATION = "ai_application"
    DATA_ANALYTICS = "data_analytics"
    TECHNOLOGY_STRATEGY = "technology_strategy"
    OTHER = "other"
    UNKNOWN = "unknown"


class KnowledgeCoverage(StrEnum):
    ENHANCED = "enhanced"
    BASE_ONLY = "base_only"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class Relevance(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SupportType(StrEnum):
    DIRECT = "direct"
    TRANSFERABLE = "transferable"
    CONTEXTUAL = "contextual"


class MatchCoverage(StrEnum):
    FULL = "full"
    SUBSTANTIAL = "substantial"
    PARTIAL = "partial"
    WEAK = "weak"
    NONE = "none"


class EvidenceStatus(StrEnum):
    PRESENT = "present"
    WEAK = "weak"
    MISSING = "missing"
    CONFLICT = "conflict"


class AbilityStatus(StrEnum):
    CONFIRMED = "confirmed"
    CONFIRMED_GAP = "confirmed_gap"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class AnalysisReadiness(StrEnum):
    READY = "ready"
    READY_WITH_GAPS = "ready_with_gaps"
    CLARIFICATION_RECOMMENDED = "clarification_recommended"
    CLARIFICATION_REQUIRED = "clarification_required"
    REVIEW_REQUIRED = "review_required"


class ClarificationQuestionType(StrEnum):
    HARD_ELIGIBILITY = "hard_eligibility"
    ROLE_SENIORITY = "role_seniority"
    CRITICAL_EVIDENCE = "critical_evidence"
    SCORE_BAND = "score_band"
    CONFIDENCE = "confidence"
    EVIDENCE_OWNERSHIP = "evidence_ownership"


class ClarificationQuestionStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    SKIPPED = "skipped"
    UNABLE_TO_CONFIRM = "unable_to_confirm"


class ClarificationAnswerStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    SKIPPED = "skipped"
    UNABLE_TO_CONFIRM = "unable_to_confirm"


class ClarificationAnswerType(StrEnum):
    BOOLEAN = "boolean"
    ENUM = "enum"
    NUMBER_RANGE = "number_range"
    SHORT_FACT = "short_fact"
    MULTI_SELECT = "multi_select"


class ClarificationCoreImpact(StrEnum):
    ELIGIBILITY = "eligibility"
    HARD_PENDING = "hard_pending"
    SENIORITY = "seniority"
    CRITICAL_STATUS = "critical_status"
    SCORE_BAND = "score_band"
    CONFIDENCE = "confidence"
    RECOMMENDATION = "recommendation"


class ClarificationResolutionStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    FORCED_CONTINUE = "forced_continue"
    REVIEW_REQUIRED = "review_required"


class ClarificationConflictType(StrEnum):
    SOURCE_CONFLICT = "source_conflict"
    TARGET_MISMATCH = "target_mismatch"
    CONTRADICTORY_REANSWER = "contradictory_reanswer"
    MULTIPLE_CLARIFICATIONS = "multiple_clarifications"


class EligibilityStatus(StrEnum):
    MET = "met"
    PENDING = "pending"
    BLOCKED = "blocked"


class SeniorityAlignment(StrEnum):
    ALIGNED = "aligned"
    BORDERLINE = "borderline"
    MISALIGNED = "misaligned"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Recommendation(StrEnum):
    PRIORITY = "priority"
    SUGGESTED = "suggested"
    CHALLENGE = "challenge"
    NOT_RECOMMENDED = "not_recommended"


class ReasonCode(StrEnum):
    HIGH_FIT_SCORE = "HIGH_FIT_SCORE"
    MEDIUM_FIT_SCORE = "MEDIUM_FIT_SCORE"
    LOW_FIT_SCORE = "LOW_FIT_SCORE"
    HARD_BLOCKER = "HARD_BLOCKER"
    HARD_PENDING = "HARD_PENDING"
    CRITICAL_GAP_ONE = "CRITICAL_GAP_ONE"
    CRITICAL_GAP_MULTIPLE = "CRITICAL_GAP_MULTIPLE"
    CORE_COVERAGE_STRONG = "CORE_COVERAGE_STRONG"
    CORE_COVERAGE_WEAK = "CORE_COVERAGE_WEAK"
    STRONG_TRANSFERABLE_EVIDENCE = "STRONG_TRANSFERABLE_EVIDENCE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    SENIORITY_MISMATCH = "SENIORITY_MISMATCH"
    SENIORITY_BORDERLINE = "SENIORITY_BORDERLINE"
    FORCED_CONTINUE = "FORCED_CONTINUE"
    CLARIFICATION_RECOMMENDED = "CLARIFICATION_RECOMMENDED"


class ActionType(StrEnum):
    REWRITE = "rewrite"
    RECOVER = "recover"
    BUILD = "build"


class Priority(StrEnum):
    P0 = "p0"
    P1 = "p1"
    P2 = "p2"


class Effort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceVisibility(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Transferability(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ActionTiming(StrEnum):
    BEFORE_APPLY = "before_apply"
    PARALLEL_WITH_APPLICATIONS = "parallel_with_applications"
    LONG_TERM = "long_term"


class InterviewQuestionType(StrEnum):
    RESUME_DEEP_DIVE = "resume_deep_dive"
    ROLE_CAPABILITY = "role_capability"
    GAP_RISK = "gap_risk"
    BEHAVIORAL = "behavioral"


class Reliability(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CitationUsage(StrEnum):
    JOB_EXPLANATION = "job_explanation"
    IMPLICIT_REQUIREMENT = "implicit_requirement"
    BUILD_RECOMMENDATION = "build_recommendation"
    INTERVIEW_PREPARATION = "interview_preparation"


class LifecycleStatus(StrEnum):
    DRAFT = "draft"
    INPUT_READY = "input_ready"
    PARSING = "parsing"
    REVIEW_REQUIRED = "review_required"
    ANALYSIS_READY = "analysis_ready"
    ANALYZING = "analyzing"
    REPORT_GENERATING = "report_generating"
    COMPLETED = "completed"
    NEEDS_REANALYSIS = "needs_reanalysis"
    FAILED = "failed"


class TaskStatus(StrEnum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ValidityStatus(StrEnum):
    VALID = "valid"
    STALE = "stale"
    INVALID = "invalid"


class RecomputeFrom(StrEnum):
    NONE = "none"
    RESUME_PARSE = "resume_parse"
    JD_PARSE = "jd_parse"
    EVIDENCE = "evidence"
    READINESS = "readiness"
    MATCHING = "matching"
    ELIGIBILITY = "eligibility"
    SCORING = "scoring"
    RECOMMENDATION = "recommendation"
    ACTIONS = "actions"
    INTERVIEW = "interview"
    REPORT = "report"


class AnalysisStage(StrEnum):
    RESUME_PARSE = "resume_parse"
    JD_PARSE = "jd_parse"
    REQUIREMENT_CLASSIFICATION = "requirement_classification"
    EVIDENCE = "evidence"
    READINESS = "readiness"
    MATCHING = "matching"
    ELIGIBILITY = "eligibility"
    SCORING = "scoring"
    RECOMMENDATION = "recommendation"
    ACTIONS = "actions"
    INTERVIEW = "interview"
    REPORT = "report"


class AnalysisChangeType(StrEnum):
    UI_OR_NOTE_ONLY = "UI_OR_NOTE_ONLY"
    NEW_RESUME = "NEW_RESUME"
    RESUME_TEXT_CHANGED = "RESUME_TEXT_CHANGED"
    USER_CONFIRMED_EXPERIENCE = "USER_CONFIRMED_EXPERIENCE"
    HARD_CLARIFICATION_CHANGED = "HARD_CLARIFICATION_CHANGED"
    NEW_JD = "NEW_JD"
    JD_SEMANTIC_CHANGED = "JD_SEMANTIC_CHANGED"
    KNOWLEDGE_VERSION_CHANGED = "KNOWLEDGE_VERSION_CHANGED"
    SCORING_RULE_VERSION_CHANGED = "SCORING_RULE_VERSION_CHANGED"
    PROMPT_P01_CHANGED = "PROMPT_P01_CHANGED"
    PROMPT_P02_CHANGED = "PROMPT_P02_CHANGED"
    PROMPT_P03_CHANGED = "PROMPT_P03_CHANGED"
    PROMPT_P04_CHANGED = "PROMPT_P04_CHANGED"
    PROMPT_P05_CHANGED = "PROMPT_P05_CHANGED"
    PROMPT_P06_CHANGED = "PROMPT_P06_CHANGED"
    PROMPT_P07_CHANGED = "PROMPT_P07_CHANGED"
    PROMPT_P08_CHANGED = "PROMPT_P08_CHANGED"
    SCHEMA_VERSION_CHANGED = "SCHEMA_VERSION_CHANGED"
    ANALYSIS_ENGINE_VERSION_CHANGED = "ANALYSIS_ENGINE_VERSION_CHANGED"


class ChangeSemanticScope(StrEnum):
    UI_ONLY = "ui_only"
    INPUT_SEMANTIC = "input_semantic"
    EVIDENCE_FACT = "evidence_fact"
    ELIGIBILITY_ONLY = "eligibility_only"
    KNOWLEDGE_ADVISORY = "knowledge_advisory"
    SCORING_ONLY = "scoring_only"
    PROMPT_SEMANTIC = "prompt_semantic"
    PRESENTATION_ONLY = "presentation_only"
    DOMAIN_SEMANTIC = "domain_semantic"
    DECISION_ENGINE = "decision_engine"
    UNKNOWN = "unknown"


class FailureImpactLevel(StrEnum):
    NORMAL = "F0"
    PARTIAL_ENHANCEMENT = "F1"
    BASE_ANALYSIS = "F2"
    DECISION_UNSAFE = "F3"


class FailureCategory(StrEnum):
    INPUT = "input_error"
    PARSING = "parsing_error"
    EVIDENCE_LOGIC = "evidence_logic_error"
    MODEL = "model_error"
    KNOWLEDGE = "knowledge_error"
    SYSTEM_PERSISTENCE = "system_persistence_error"
