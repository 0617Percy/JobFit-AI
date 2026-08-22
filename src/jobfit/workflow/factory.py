"""Composition root for provider-neutral workflow dependencies."""

from __future__ import annotations

import hashlib
import json
import weakref
from pathlib import Path
from typing import Any

from jobfit.config import Settings
from jobfit.errors import KnowledgeDatabaseError
from jobfit.extractors import JobRequirementExtractor, ResumeExtractor
from jobfit.generators import (
    KNOWLEDGE_ADVICE_STRATEGY_VERSION,
    AdviceBundleGenerator,
)
from jobfit.generators.knowledge_reference import KNOWLEDGE_PROMPT_VERSION
from jobfit.knowledge import (
    DefaultKnowledgeRetriever,
    KnowledgeDatabase,
    NoOpKnowledgeRetriever,
    SqliteKnowledgeRepository,
    resolve_knowledge_db_path,
    validate_knowledge_limit,
)
from jobfit.knowledge.protocol import KnowledgeRetriever
from jobfit.llm import LLMClient, LLMSettings, PromptRegistry, build_llm_client
from jobfit.matching import EvidenceMatcher
from jobfit.models import (
    JobProfile,
    KnowledgeContext,
    KnowledgeRetrievalStatus,
    KnowledgeWarning,
    KnowledgeWarningCode,
)
from jobfit.parsers import DocumentParserService
from jobfit.parsers.text import TextDocumentParser
from jobfit.scoring import ScoringEngine
from jobfit.validators import EvidenceValidator
from jobfit.validators.knowledge import (
    KNOWLEDGE_CITATION_VALIDATOR_VERSION,
    KnowledgeCitationValidator,
)
from jobfit.workflow.orchestrator import WorkflowOrchestrator
from jobfit.workflow.state import (
    WorkflowCache,
    WorkflowFingerprintContext,
)

PROMPT_VERSIONS = {
    "extract_resume": "1.0",
    "extract_job": "1.0",
    "match_evidence": "1.0",
    "generate_advice_bundle": "1.2",
}


class _UnavailableKnowledgeRetriever:
    """Return a safe soft-failure without exposing persistence details."""

    def __init__(self, *, retrieval_strategy_version: str) -> None:
        self._strategy_version = retrieval_strategy_version

    def retrieve_for_job(
        self,
        job_profile: JobProfile,
        *,
        limit: int = 12,
    ) -> KnowledgeContext:
        del job_profile
        validate_knowledge_limit(limit)
        return KnowledgeContext(
            status=KnowledgeRetrievalStatus.UNAVAILABLE,
            warnings=[
                KnowledgeWarning(
                    code=KnowledgeWarningCode.DB_UNAVAILABLE,
                    message=(
                        "The reviewed knowledge database is temporarily unavailable."
                    ),
                    recoverable=True,
                )
            ],
            retrieval_strategy_version=self._strategy_version,
        )


class _DatabaseBackedKnowledgeRetriever:
    """Own the database Engine while exposing only the retriever protocol."""

    def __init__(
        self,
        database: KnowledgeDatabase,
        retriever: DefaultKnowledgeRetriever,
    ) -> None:
        self._database = database
        self._retriever = retriever
        self._finalizer = weakref.finalize(self, database.dispose)

    def retrieve_for_job(
        self,
        job_profile: JobProfile,
        *,
        limit: int = 12,
    ) -> KnowledgeContext:
        return self._retriever.retrieve_for_job(job_profile, limit=limit)

    def close(self) -> None:
        self._finalizer()


def _runtime_identity_payload(settings: Settings) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": settings.knowledge_enabled,
        "status": "disabled" if not settings.knowledge_enabled else "unavailable",
        "requested_version": settings.knowledge_version,
        "version": None,
        "content_hash": None,
        "search_mode": settings.knowledge_search_mode.value,
        "retrieval_strategy_version": settings.knowledge_retrieval_strategy_version,
        "requirement_limit": settings.knowledge_requirement_limit,
        "prompt_char_limit": settings.knowledge_prompt_char_limit,
        "knowledge_prompt_version": KNOWLEDGE_PROMPT_VERSION,
        "citation_validator_version": KNOWLEDGE_CITATION_VALIDATOR_VERSION,
        "advice_strategy_version": KNOWLEDGE_ADVICE_STRATEGY_VERSION,
    }
    if not settings.knowledge_enabled:
        return payload

    path = resolve_knowledge_db_path(settings.knowledge_db_path)
    if not path.is_file():
        return payload
    database = KnowledgeDatabase(path)
    try:
        database.ensure_compatible_schema()
        version = SqliteKnowledgeRepository(
            database,
            search_mode=settings.knowledge_search_mode,
        ).get_published_version(settings.knowledge_version)
        if version is not None:
            payload.update(
                status="available",
                version=version.version,
                content_hash=version.content_hash,
            )
    except KnowledgeDatabaseError:
        pass
    finally:
        database.dispose()
    return payload


def build_knowledge_runtime_identity(settings: Settings) -> str:
    """Hash safe runtime facts used to mark reports stale across reruns."""

    encoded = json.dumps(
        _runtime_identity_payload(settings),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_knowledge_retriever(settings: Settings) -> KnowledgeRetriever:
    """Assemble optional knowledge access without creating a database."""

    if not settings.knowledge_enabled:
        return NoOpKnowledgeRetriever(
            retrieval_strategy_version=settings.knowledge_retrieval_strategy_version
        )

    path = resolve_knowledge_db_path(settings.knowledge_db_path)
    if not path.is_file():
        return _UnavailableKnowledgeRetriever(
            retrieval_strategy_version=settings.knowledge_retrieval_strategy_version
        )

    database = KnowledgeDatabase(path)
    try:
        database.ensure_compatible_schema()
        repository = SqliteKnowledgeRepository(
            database,
            search_mode=settings.knowledge_search_mode,
        )
        if repository.get_published_version(settings.knowledge_version) is None:
            database.dispose()
            return _UnavailableKnowledgeRetriever(
                retrieval_strategy_version=(
                    settings.knowledge_retrieval_strategy_version
                )
            )
        retriever = DefaultKnowledgeRetriever(
            repository,
            enabled=True,
            requested_version=settings.knowledge_version,
            search_mode=settings.knowledge_search_mode,
            requirement_limit=settings.knowledge_requirement_limit,
            prompt_char_limit=settings.knowledge_prompt_char_limit,
            retrieval_strategy_version=settings.knowledge_retrieval_strategy_version,
        )
    except KnowledgeDatabaseError:
        database.dispose()
        return _UnavailableKnowledgeRetriever(
            retrieval_strategy_version=settings.knowledge_retrieval_strategy_version
        )
    return _DatabaseBackedKnowledgeRetriever(database, retriever)


def build_workflow_orchestrator(
    settings: Settings,
    *,
    client: LLMClient | None = None,
    cache: WorkflowCache | None = None,
    prompt_root: Path | None = None,
    knowledge_retriever: KnowledgeRetriever | None = None,
) -> WorkflowOrchestrator:
    """Build the workflow without embedding a provider in business modules."""

    resolved_client = client or build_llm_client(settings)
    resolved_prompt_root = prompt_root or Path(__file__).parents[1] / "prompts"
    prompt_registry = PromptRegistry(resolved_prompt_root)
    llm_settings = LLMSettings.from_app_settings(settings)
    advice_generator = AdviceBundleGenerator(
        client=resolved_client,
        prompt_registry=prompt_registry,
        settings=llm_settings,
        prompt_version=PROMPT_VERSIONS["generate_advice_bundle"],
        knowledge_prompt_char_limit=settings.knowledge_prompt_char_limit,
    )
    return WorkflowOrchestrator(
        parser_service=DocumentParserService(settings=settings),
        jd_parser=TextDocumentParser(),
        resume_extractor=ResumeExtractor(
            client=resolved_client,
            prompt_registry=prompt_registry,
            settings=llm_settings,
            prompt_version=PROMPT_VERSIONS["extract_resume"],
            max_characters=settings.max_resume_chars,
        ),
        job_extractor=JobRequirementExtractor(
            client=resolved_client,
            prompt_registry=prompt_registry,
            settings=llm_settings,
            prompt_version=PROMPT_VERSIONS["extract_job"],
            max_characters=settings.max_jd_chars,
        ),
        matcher=EvidenceMatcher(
            client=resolved_client,
            prompt_registry=prompt_registry,
            settings=llm_settings,
            prompt_version=PROMPT_VERSIONS["match_evidence"],
        ),
        evidence_validator=EvidenceValidator(),
        scoring_engine=ScoringEngine(),
        advice_generator=advice_generator,
        knowledge_advice_generator=advice_generator,
        knowledge_citation_validator=KnowledgeCitationValidator(),
        knowledge_retriever=knowledge_retriever,
        fingerprint_context=WorkflowFingerprintContext(
            provider=settings.llm_provider,
            model=settings.llm_model or "mock-model",
            prompt_versions=PROMPT_VERSIONS,
            knowledge_requirement_limit=settings.knowledge_requirement_limit,
            knowledge_prompt_char_limit=settings.knowledge_prompt_char_limit,
            knowledge_retrieval_strategy_version=(
                settings.knowledge_retrieval_strategy_version
            ),
            knowledge_advice_prompt_version=(
                KNOWLEDGE_PROMPT_VERSION
            ),
            knowledge_citation_validator_version=(
                KNOWLEDGE_CITATION_VALIDATOR_VERSION
            ),
            knowledge_advice_strategy_version=KNOWLEDGE_ADVICE_STRATEGY_VERSION,
        ),
        cache=cache,
    )
