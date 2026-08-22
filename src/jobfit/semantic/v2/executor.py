"""Bounded candidate-prompt executor with safe repair and trace metadata."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from jobfit.llm.exceptions import StrictTransportError
from jobfit.llm.prompt_registry import PromptRegistry
from jobfit.llm.protocol import LLMMessage, LLMProvider, LLMSettings
from jobfit.llm.retry import RetryExecutor
from jobfit.semantic.v2.contracts import (
    PromptAttemptRecord,
    PromptExecutionRecord,
    PromptValidationRecord,
    SemanticPromptResult,
)
from jobfit.semantic.v2.governance import (
    GlobalRule,
    KnowledgeTier,
    PromptManifestEntry,
    load_global_rules,
    validate_prompt_pack,
)
from jobfit.semantic.v2.severity import (
    SemanticValidationIssue,
    SemanticValidationSeverity,
    validation_issue,
)

T = TypeVar("T", bound=BaseModel)
Validator = Callable[[T], None]
QualityValidator = Callable[[T], Sequence[SemanticValidationIssue]]
OutputIdGetter = Callable[[T], Sequence[str]]

class SemanticLLMTask(StrEnum):
    P01_RESUME_PARSER = "p01_resume_parser"
    P02_JD_PARSER = "p02_jd_parser"
    P03_REQUIREMENT_CLASSIFIER = "p03_requirement_classifier"
    P04_EVIDENCE_NORMALIZER = "p04_evidence_normalizer"
    P05_SEMANTIC_MATCHER = "p05_semantic_matcher"
    P06_ACTIONS = "p06_actions"
    P07_INTERVIEW = "p07_interview"
    P08_REPORT = "p08_report"


_TASK_BY_PROMPT = {
    "P01": SemanticLLMTask.P01_RESUME_PARSER,
    "P02": SemanticLLMTask.P02_JD_PARSER,
    "P03": SemanticLLMTask.P03_REQUIREMENT_CLASSIFIER,
    "P04": SemanticLLMTask.P04_EVIDENCE_NORMALIZER,
    "P05": SemanticLLMTask.P05_SEMANTIC_MATCHER,
    "P06": SemanticLLMTask.P06_ACTIONS,
    "P07": SemanticLLMTask.P07_INTERVIEW,
    "P08": SemanticLLMTask.P08_REPORT,
}
_KNOWLEDGE_KEYS = {
    "knowledge",
    "knowledge_context",
    "knowledge_citation",
    "knowledge_citations",
    "citation",
    "citations",
}
_INJECTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "forget previous",
    "system prompt",
    "developer message",
    "output score",
    "override instructions",
    "change the recommendation",
    "recommendation to priority",
    "把recommendation",
)
_SAFE_VALIDATION_CATEGORY_BY_MESSAGE = {
    "Evidence end offset must exceed start offset.": (
        "EVIDENCE_OFFSET_ORDER_INVALID"
    ),
    "Evidence offsets must match the exact quote length.": (
        "EVIDENCE_QUOTE_LENGTH_MISMATCH"
    ),
}
_SAFE_MODEL_VALIDATOR_CATEGORY_BY_MESSAGE = {
    "P03 requirement local IDs must be unique.": "P03_REQUIREMENT_ID_DUPLICATE",
    "P03 normalized capabilities must be unique.": (
        "P03_REQUIREMENT_NORMALIZATION_DUPLICATE"
    ),
    "P04 normalized capabilities must be unique.": (
        "P04_NORMALIZED_CAPABILITY_DUPLICATE"
    ),
    "P05 matched evidence IDs must be unique.": "P05_MATCH_EVIDENCE_ID_DUPLICATE",
    "P06 action IDs must be unique.": "P06_ACTION_ID_DUPLICATE",
    "P07 question IDs must be unique.": "P07_QUESTION_ID_DUPLICATE",
    "P08 explanation citation IDs must be unique.": (
        "P08_EXPLANATION_CITATION_ID_DUPLICATE"
    ),
    "P08 implicit requirement explanations must be unique.": (
        "P08_IMPLICIT_EXPLANATION_DUPLICATE"
    ),
}


class SemanticPromptError(ValueError):
    """Safe fail-closed error at the candidate semantic boundary."""

    def __init__(
        self,
        prompt_id: str,
        code: str,
        *,
        attempts: Sequence[PromptAttemptRecord] = (),
    ) -> None:
        self.prompt_id = prompt_id
        self.code = code
        self.attempts = tuple(attempts)
        super().__init__(f"{prompt_id} semantic execution failed: {code}")


class SemanticValidationIssueError(ValueError):
    """Safe structured validation failure without source or model content."""

    def __init__(
        self,
        code: str,
        *,
        validation_paths: Sequence[str],
        validation_categories: Sequence[str],
        validation_severities: Sequence[SemanticValidationSeverity] = (),
    ) -> None:
        paths = tuple(validation_paths)
        categories = tuple(validation_categories)
        if not paths or len(paths) != len(categories):
            raise ValueError("Safe validation issues require matching path/category data.")
        severities = tuple(validation_severities)
        if severities and len(severities) != len(paths):
            raise ValueError("Safe validation issues require matching severity data.")
        self.code = code
        self.validation_paths = paths
        self.validation_categories = categories
        self.validation_severities = severities
        super().__init__(code)


class SemanticPromptExecutor:
    """Execute one governed semantic prompt in at most three model calls."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        prompt_root: str | Path,
        settings: LLMSettings,
    ) -> None:
        self._provider = provider
        self._prompt_root = Path(prompt_root)
        self._settings = settings
        try:
            self._manifest = validate_prompt_pack(self._prompt_root)
            self._rules = load_global_rules(self._prompt_root)
        except ValueError as exc:
            raise SemanticPromptError(
                "PIPELINE", "PROMPT_PACK_VALIDATION_FAILED"
            ) from exc
        self._registry = PromptRegistry(self._prompt_root)
        self._transport = RetryExecutor()

    def execute_prompt(
        self,
        *,
        prompt_id: str,
        input_payload: BaseModel | Mapping[str, Any],
        input_object_ids: Sequence[str],
        response_model: type[T],
        business_validator: Validator[T] | None = None,
        cross_object_validator: Validator[T] | None = None,
        quality_validator: QualityValidator[T] | None = None,
        output_id_getter: OutputIdGetter[T] | None = None,
        knowledge_scope: Sequence[KnowledgeTier] = (),
    ) -> SemanticPromptResult[T]:
        entry = self._entry(prompt_id)
        normalized_input = (
            input_payload.model_dump(mode="json")
            if isinstance(input_payload, BaseModel)
            else dict(input_payload)
        )
        requested_scope = tuple(dict.fromkeys(knowledge_scope))
        allowed_scope = _allowed_knowledge_scope(entry)
        if any(scope not in allowed_scope for scope in requested_scope):
            raise SemanticPromptError(prompt_id, "knowledge access is forbidden")
        if _contains_forbidden_knowledge(normalized_input) and not requested_scope:
            raise SemanticPromptError(prompt_id, "knowledge access is forbidden")
        warnings = (
            ("EMBEDDED_INSTRUCTION_IGNORED",)
            if _contains_embedded_instruction(normalized_input)
            else ()
        )
        messages = self._messages(entry, normalized_input)
        attempts: list[PromptAttemptRecord] = []
        output: T | None = None
        quality_issues: tuple[SemanticValidationIssue, ...] = ()
        stages = entry.retry_policy.stages

        for attempt_number, stage in enumerate(stages, start=1):
            syntax_valid = False
            schema_valid = False
            business_valid = False
            cross_object_valid = False
            error_code: str | None = None
            validation_paths: tuple[str, ...] = ()
            validation_types: tuple[str, ...] = ()
            validation_categories: tuple[str, ...] = ()
            validation_issues: tuple[SemanticValidationIssue, ...] = ()
            response = None
            try:
                response = self._transport.run(
                    lambda messages=messages: self._provider.generate(
                        task=_TASK_BY_PROMPT[prompt_id],
                        messages=messages,
                        settings=self._settings.model_copy(
                            update={"prompt_version": entry.prompt_version}
                        ),
                        response_schema=response_model.model_json_schema(),
                    ),
                    max_retries=0,
                )
                json.loads(response.content)
                syntax_valid = True
                candidate = response_model.model_validate_json(response.content)
                schema_valid = True
                if business_validator is not None:
                    business_validator(candidate)
                business_valid = True
                if cross_object_validator is not None:
                    cross_object_validator(candidate)
                cross_object_valid = True
                if quality_validator is not None:
                    quality_issues = tuple(quality_validator(candidate))
                    if any(
                        issue.severity
                        is not SemanticValidationSeverity.QUALITY_WARNING
                        for issue in quality_issues
                    ):
                        raise SemanticPromptError(
                            prompt_id,
                            "QUALITY_VALIDATOR_SEVERITY_INVALID",
                            attempts=attempts,
                        )
                output = candidate
            except StrictTransportError as exc:
                error_code = exc.code
                validation_paths = (exc.safe_path,)
                validation_types = ("transport_error",)
                validation_categories = (exc.code,)
                validation_issues = (
                    validation_issue(
                        stage=prompt_id,
                        category=exc.code,
                        safe_path=exc.safe_path,
                    ),
                )
            except json.JSONDecodeError:
                error_code = "INVALID_JSON"
                validation_paths = ("root",)
                validation_types = ("json_invalid",)
                validation_categories = ("INVALID_JSON",)
                validation_issues = (
                    validation_issue(
                        stage=prompt_id,
                        category="INVALID_JSON",
                        safe_path="root",
                    ),
                )
            except ValidationError as exc:
                error_code = (
                    "SCHEMA_INVALID"
                    if not schema_valid
                    else (
                        "BUSINESS_VALIDATION_FAILED"
                        if not business_valid
                        else "CROSS_OBJECT_VALIDATION_FAILED"
                    )
                )
                (
                    validation_paths,
                    validation_types,
                    validation_categories,
                ) = _safe_validation_details(exc, prompt_id=prompt_id)
                validation_issues = tuple(
                    validation_issue(
                        stage=prompt_id,
                        category=category,
                        safe_path=path,
                    )
                    for path, category in zip(
                        validation_paths,
                        validation_categories,
                        strict=True,
                    )
                )
            except SemanticValidationIssueError as exc:
                error_code = exc.code
                validation_paths = exc.validation_paths
                validation_types = ("value_error",) * len(validation_paths)
                validation_categories = exc.validation_categories
                validation_issues = tuple(
                    SemanticValidationIssue(
                        stage=prompt_id,
                        category=category,
                        severity=(
                            exc.validation_severities[index]
                            if exc.validation_severities
                            else validation_issue(
                                stage=prompt_id,
                                category=category,
                                safe_path=path,
                            ).severity
                        ),
                        safe_path=path,
                    )
                    for index, (path, category) in enumerate(
                        zip(
                            validation_paths,
                            validation_categories,
                            strict=True,
                        )
                    )
                )
            except SemanticPromptError:
                raise
            except (KeyError, TypeError, ValueError):
                error_code = (
                    "BUSINESS_VALIDATION_FAILED"
                    if not business_valid
                    else "CROSS_OBJECT_VALIDATION_FAILED"
                )

            attempts.append(
                PromptAttemptRecord(
                    attempt=attempt_number,
                    stage=stage,
                    syntax_valid=syntax_valid,
                    schema_valid=schema_valid,
                    business_valid=business_valid,
                    cross_object_valid=cross_object_valid,
                    error_code=error_code,
                    validation_error_count=len(validation_paths),
                    validation_paths=validation_paths,
                    validation_types=validation_types,
                    validation_categories=validation_categories,
                    validation_issues=validation_issues,
                    finish_reason=(
                        response.finish_reason if response is not None else "other"
                    ),
                    output_char_count=(
                        len(response.content) if response is not None else 0
                    ),
                    token_usage=response.usage if response is not None else None,
                    output_truncation_suspected=(
                        response is not None and response.finish_reason == "length"
                    ),
                )
            )
            if output is not None:
                break
            if attempt_number < len(stages):
                next_stage = stages[attempt_number]
                messages = (
                    self._full_retry_messages(entry, normalized_input)
                    if next_stage == "full_retry"
                    else self._repair_messages(
                        entry,
                        normalized_input,
                        error_code,
                        validation_paths,
                        validation_categories,
                    )
                )

        if output is None:
            raise SemanticPromptError(
                prompt_id,
                attempts[-1].error_code or "INVALID_OUTPUT",
                attempts=attempts,
            )

        output_ids = tuple(output_id_getter(output)) if output_id_getter else ()
        safe_warnings = tuple(
            dict.fromkeys(
                [*warnings, *(issue.category for issue in quality_issues)]
            )
        )
        return SemanticPromptResult(
            output=output,
            record=PromptExecutionRecord(
                prompt_id=prompt_id,
                prompt_version=entry.prompt_version,
                global_rules_version=entry.global_rules_version,
                prompt_pack_version=entry.prompt_pack_version,
                attempt_count=len(attempts),
                attempts=tuple(attempts),
                input_object_ids=tuple(input_object_ids),
                output_object_ids=output_ids,
                warnings=safe_warnings,
                validation_issues=quality_issues,
                validation=PromptValidationRecord(
                    syntax_valid=True,
                    schema_valid=True,
                    business_valid=True,
                    cross_object_valid=True,
                ),
                provider=self._provider.provider_name,
                model=self._settings.model,
            ),
        )

    def _entry(self, prompt_id: str) -> PromptManifestEntry:
        for entry in self._manifest.prompts:
            if entry.prompt_id == prompt_id:
                return entry
        raise SemanticPromptError(prompt_id, "UNKNOWN_PROMPT")

    def _messages(
        self,
        entry: PromptManifestEntry,
        input_payload: Mapping[str, Any],
    ) -> tuple[LLMMessage, LLMMessage]:
        template = self._registry.load(
            entry.filename.removesuffix(".md"), entry.prompt_version
        )
        global_text = _format_global_rules(self._rules)
        token = "{semantic_input_json}"
        if token not in template.user_template:
            raise SemanticPromptError(entry.prompt_id, "PROMPT_INPUT_TOKEN_MISSING")
        payload = json.dumps(input_payload, ensure_ascii=False, separators=(",", ":"))
        return (
            LLMMessage(
                role="system",
                content=f"{template.system_text}\n\n{global_text}",
            ),
            LLMMessage(
                role="user",
                content=template.user_template.replace(token, payload),
            ),
        )

    def _repair_messages(
        self,
        entry: PromptManifestEntry,
        input_payload: Mapping[str, Any],
        error_code: str | None,
        validation_paths: Sequence[str],
        validation_categories: Sequence[str],
    ) -> tuple[LLMMessage, LLMMessage, LLMMessage]:
        original = self._messages(entry, input_payload)
        instruction = (
            "Repair the reported schema, source-boundary, or reference errors, "
            "but return one complete corrected JSON object that conforms exactly "
            "to the declared response schema. Do not return only the invalid field "
            "or sub-object. Do not return repair metadata or validation annotations. "
            "Do not add facts or decision fields."
        )
        if error_code and error_code.startswith("STRICT_"):
            instruction += (
                " Return the complete result by calling the single provided function."
            )
        if any(
            category
            in {"EVIDENCE_QUOTE_NOT_FOUND", "EVIDENCE_QUOTE_AMBIGUOUS"}
            for category in validation_categories
        ):
            instruction += (
                " For quote anchoring issues, copy an exact verbatim quote from "
                "the supplied resume source and make it uniquely identifiable "
                "within its referenced segment. Do not return start_char or end_char."
            )
        if "JD_SOURCE_TEXT_AMBIGUOUS" in validation_categories:
            instruction += (
                " For JD source-text ambiguity, copy a slightly longer exact "
                "verbatim span with enough surrounding context until it is unique "
                "within its referenced segment."
            )
        if "JD_SOURCE_TEXT_NOT_FOUND" in validation_categories:
            instruction += (
                " For JD source-text not found, copy exact verbatim text from the "
                "referenced segment; do not paraphrase."
            )
        if "INVALID_ACTION_TYPE" in validation_categories:
            instruction += (
                " For P06 action-type validation, candidate_grounded permits only "
                "rewrite or recover, while future_build permits only build."
            )
        if "P03_CLASSIFICATION_INCOMPLETE" in validation_categories:
            instruction += (
                " Reconcile every requirement's raw_requirement_ids against "
                "the supplied raw_requirements in the complete replacement "
                "object: every supplied raw requirement object_id must appear "
                "exactly once. Do not omit, duplicate, invent, rename, or "
                "replace raw requirement IDs. When grouping several raw "
                "requirements into one normalized requirement, keep all of "
                "their supplied object_ids in that requirement's "
                "raw_requirement_ids. Return the complete corrected object."
            )
        if "P03_REQUIREMENT_NORMALIZATION_DUPLICATE" in validation_categories:
            instruction += (
                " Rebuild the complete replacement object: identify "
                "requirements whose normalized_capability is case-insensitively "
                "equal and merge them into exactly one Requirement, aggregating "
                "all of their raw_requirement_ids without omission. Keep every "
                "other Requirement unchanged. Do not return a patch fragment."
            )
        if "SEMANTIC_STRENGTH_INCREASE" in validation_categories:
            instruction += (
                " Re-check every action_type=\"rewrite\" in the complete "
                "replacement object. For each Rewrite, recommended_action must "
                "not increase factual strength beyond its cited Resume evidence: "
                "it must be resume-ready replacement wording, not advice about "
                "rewriting, and must not add unsupported ownership, scope, "
                "tools, metrics, results, deployment, users, quality, or "
                "ability. Omit any Rewrite that cannot be made safe, and "
                "return the complete corrected object."
            )
        if "REWRITE_TRACEABILITY_MISSING" in validation_categories:
            instruction += (
                " A Rewrite must reference at least one existing supported Resume "
                "evidence through supported_by_evidence_ids."
            )
        if (
            entry.prompt_id == "P06"
            and "UNKNOWN_REQUIREMENT_REFERENCE" in validation_categories
        ):
            instruction += (
                " For P06 requirement traceability, copy every "
                "related_requirement_ids value verbatim from "
                "requirement_reference_catalog. Never invent, normalize, shorten, "
                "transform, or infer an ID. Return the complete corrected object."
            )
        if (
            entry.prompt_id == "P06"
            and "UNKNOWN_EVIDENCE_REFERENCE" in validation_categories
        ):
            instruction += (
                " For P06 evidence traceability, copy every related_evidence_ids "
                "and supported_by_evidence_ids value verbatim from "
                "evidence_reference_catalog. Respect eligible_for_rewrite and "
                "eligible_for_recover; never invent, normalize, shorten, transform, "
                "or infer an ID. Return the complete corrected object."
            )
        if (
            entry.prompt_id == "P06"
            and "RECOVER_TRACEABILITY_MISSING" in validation_categories
        ):
            instruction += (
                " For each Recover, supported_by_evidence_ids must contain at least "
                "one ID copied verbatim from an evidence_reference_catalog item "
                "whose eligible_for_recover is true. When that item has "
                "source_origin user_clarification, also copy its source_record_id "
                "verbatim into source_clarification_ids and use only IDs present in "
                "clarification_reference_catalog. If no eligible support exists, "
                "omit the Recover. Return the complete corrected object."
            )
        if (
            entry.prompt_id == "P06"
            and "BUILD_TRACEABILITY_MISSING" in validation_categories
        ):
            instruction += (
                " For P06 Build traceability, use the supplied validation_issues "
                "path to identify the failed Build action and its "
                "completion_criteria field. Rewrite that field so it names an "
                "observable future artifact that must exist and be reviewable or "
                "verifiable when the future-only work is complete, such as a "
                "report, document, notebook, script, test, dashboard, table, "
                "repository, README, notes, record, or analysis output. A feeling, "
                "intention, activity, or broad skill improvement alone is invalid. "
                "Do not cite existing Evidence as if the future work already "
                "happened, and do not invent candidate facts. Return one complete "
                "corrected JSON object, not a field patch."
            )
        if "KNOWLEDGE_SCOPE_VIOLATION" in validation_categories:
            instruction += (
                " Use only Knowledge Citation IDs that are eligible for the current "
                "stage's knowledge scope according to the supplied citation metadata "
                "(usage, knowledge version, role family). Remove any citation that "
                "does not meet this scope. Do not invent replacement citation IDs."
            )
        if "INVENTED_HARD_CONCERN_REFERENCE" in validation_categories:
            instruction += (
                " hard_concern_requirement_ids may contain only requirement IDs "
                "supplied as authoritative hard blockers or hard-pending "
                "requirements. If that authoritative set is empty, return an empty "
                "list."
            )
        if entry.prompt_id == "P07" and any(
            category
            in {
                "UNKNOWN_REQUIREMENT_REFERENCE",
                "UNKNOWN_EVIDENCE_REFERENCE",
                "UNKNOWN_ACTION_REFERENCE",
                "INVENTED_CRITICAL_GAP_REFERENCE",
                "INVENTED_HARD_CONCERN_REFERENCE",
                "KNOWLEDGE_SCOPE_VIOLATION",
            }
            for category in validation_categories
        ):
            instruction += (
                " For P07 traceability, copy related_requirement_ids, "
                "related_evidence_ids, related_action_ids, "
                "critical_gap_requirement_ids, hard_concern_requirement_ids, "
                "and knowledge_citation_ids verbatim only from their authoritative "
                "sets in the supplied input. Never invent, normalize, shorten, "
                "transform, or infer an ID."
            )
        if (
            entry.prompt_id == "P07"
            and "CANDIDATE_FACT_FABRICATION" in validation_categories
        ):
            instruction += (
                " For P07 candidate facts, keep resume_deep_dive wording neutral: "
                "ask the candidate to explain or walk through the experience traced "
                "by related_evidence_ids without asserting a past action, quantity, "
                "team size, responsibility, outcome, tool, ownership, or achievement. "
                "For other question types, use hypothetical wording. Do not script "
                "a personal answer in preparation points; coach what to cover."
            )
        if any(
            category
            in {
                "P05_MATCH_COUNT_INVALID",
                "P05_MATCH_ID_DUPLICATE",
                "P05_MISSING_EVIDENCE_RELATION_INVALID",
                "P05_MISSING_EVIDENCE_COVERAGE_INVALID",
                "P05_MISSING_EVIDENCE_ABILITY_INVALID",
                "P05_PRESENT_EVIDENCE_RELATION_REQUIRED",
                "FORBIDDEN_ABILITY_GAP_AUTHORITY",
            }
            for category in validation_categories
        ):
            instruction += (
                " Rebuild the complete matches object according to the legal "
                "state machine: every supplied requirement appears exactly "
                "once; evidence_status missing requires matched_evidence "
                "empty, coverage none, and ability_status unknown; present, "
                "weak, or conflict evidence requires at least one "
                "matched_evidence entry referencing supplied evidence IDs; "
                "never use confirmed_gap as ability_status. Do not return a "
                "patch fragment."
            )
        return (
            *original,
            LLMMessage(
                role="user",
                content=json.dumps(
                    {
                        "instruction": instruction,
                        "error_code": error_code or "INVALID_OUTPUT",
                        "validation_issues": [
                            {"path": path, "category": category}
                            for path, category in zip(
                                validation_paths,
                                validation_categories,
                                strict=True,
                            )
                        ],
                    },
                    separators=(",", ":"),
                ),
            ),
        )

    def _full_retry_messages(
        self,
        entry: PromptManifestEntry,
        input_payload: Mapping[str, Any],
    ) -> tuple[LLMMessage, LLMMessage, LLMMessage]:
        return (
            *self._messages(entry, input_payload),
            LLMMessage(
                role="user",
                content=(
                    "Start over from the original task. The previous response failed "
                    "validation. Return one complete replacement JSON object that "
                    "conforms exactly to the declared response schema. Do not return "
                    "repair metadata, validation annotations, or wrapper fields."
                ),
            ),
        )


def _format_global_rules(rules: Sequence[GlobalRule]) -> str:
    return "Global rules:\n" + "\n".join(
        f"{rule.rule_id}: {rule.text}" for rule in rules
    )


def _safe_validation_details(
    error: ValidationError,
    *,
    prompt_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    paths: list[str] = []
    error_types: list[str] = []
    categories: list[str] = []
    for item in error.errors(
        include_input=False,
        include_context=True,
        include_url=False,
    ):
        error_type = str(item.get("type", "validation_error"))
        paths.append(_format_validation_path(item.get("loc", ())))
        error_types.append(error_type)
        categories.append(
            _safe_validation_category(item, error_type, prompt_id=prompt_id)
        )
    return tuple(paths), tuple(error_types), tuple(categories)


def _safe_validation_category(
    item: Mapping[str, Any],
    error_type: str,
    *,
    prompt_id: str,
) -> str:
    location = tuple(str(part).casefold() for part in item.get("loc", ()))
    authoritative_fields = {
        "ability_status",
        "confidence",
        "critical",
        "eligibility",
        "evidence_level",
        "hard_blocker",
        "recommendation",
        "score",
        "seniority",
    }
    if error_type == "extra_forbidden" and (
        prompt_id == "P08" or any(part in authoritative_fields for part in location)
    ):
        return "FORBIDDEN_AUTHORITATIVE_FIELD"
    context = item.get("ctx")
    if not isinstance(context, Mapping):
        return error_type
    message = str(context.get("error", ""))
    static_message = message.split(" Value error, ", 1)[-1]
    return _SAFE_VALIDATION_CATEGORY_BY_MESSAGE.get(
        static_message,
        _SAFE_MODEL_VALIDATOR_CATEGORY_BY_MESSAGE.get(static_message, error_type),
    )


def _format_validation_path(location: Sequence[object]) -> str:
    result = ""
    for part in location:
        if isinstance(part, int):
            result += f"[{part}]"
        elif result:
            result += f".{part}"
        else:
            result = str(part)
    return result or "root"


def _contains_forbidden_knowledge(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).casefold() in _KNOWLEDGE_KEYS
            or _contains_forbidden_knowledge(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_knowledge(child) for child in value)
    return False


def _allowed_knowledge_scope(entry: PromptManifestEntry) -> tuple[KnowledgeTier, ...]:
    access = entry.knowledge_access
    if access is False:
        return ()
    if access is True:
        return tuple(KnowledgeTier)
    return tuple(access)


def _contains_embedded_instruction(value: object) -> bool:
    if isinstance(value, str):
        folded = value.casefold()
        return any(marker in folded for marker in _INJECTION_MARKERS)
    if isinstance(value, Mapping):
        return any(_contains_embedded_instruction(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_embedded_instruction(child) for child in value)
    return False
