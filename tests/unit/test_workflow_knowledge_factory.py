"""Safe application assembly for optional runtime knowledge retrieval."""

from __future__ import annotations

from jobfit.config import Settings
from jobfit.models import KnowledgeRetrievalStatus, KnowledgeSearchMode
from jobfit.workflow.factory import (
    build_knowledge_retriever,
    build_knowledge_runtime_identity,
)

pytest_plugins = ("tests.knowledge.conftest",)


def _settings(**overrides: object) -> Settings:
    values = {
        "_env_file": None,
        "app_env": "test",
        "llm_provider": "mock",
        "llm_model": "mock-model",
        "knowledge_enabled": True,
        "knowledge_version": "2026.07.1",
        "knowledge_search_mode": KnowledgeSearchMode.KEYWORD,
    }
    values.update(overrides)
    return Settings(**values)


def test_disabled_factory_never_creates_configured_database(
    tmp_path,
    report_case,
) -> None:
    path = tmp_path / "missing" / "knowledge.sqlite3"
    settings = _settings(
        knowledge_enabled=False,
        knowledge_db_path=path,
    )

    retriever = build_knowledge_retriever(settings)
    context = retriever.retrieve_for_job(report_case.job)

    assert context.status is KnowledgeRetrievalStatus.DISABLED
    assert not path.exists()


def test_missing_database_returns_safe_unavailable_context_without_creation(
    tmp_path,
    report_case,
) -> None:
    path = tmp_path / "missing" / "knowledge.sqlite3"

    retriever = build_knowledge_retriever(
        _settings(knowledge_db_path=path)
    )
    context = retriever.retrieve_for_job(report_case.job)

    assert context.status is KnowledgeRetrievalStatus.UNAVAILABLE
    assert context.warnings[0].recoverable is True
    assert str(path) not in context.warnings[0].message
    assert "SELECT" not in context.warnings[0].message
    assert not path.exists()


def test_existing_compatible_database_builds_live_retriever(
    seeded_database,
    report_case,
) -> None:
    retriever = build_knowledge_retriever(
        _settings(knowledge_db_path=seeded_database.path)
    )

    context = retriever.retrieve_for_job(report_case.job)

    assert context.status is not KnowledgeRetrievalStatus.UNAVAILABLE
    close = getattr(retriever, "close", None)
    assert callable(close)
    close()


def test_runtime_identity_tracks_knowledge_content_not_database_path(
    seeded_database,
    tmp_path,
) -> None:
    first = _settings(knowledge_db_path=seeded_database.path)
    baseline = build_knowledge_runtime_identity(first)

    from jobfit.knowledge import KnowledgeDatabase, initialize_knowledge_schema
    from jobfit.knowledge.orm import KnowledgeBaseVersionRecord

    other = KnowledgeDatabase(tmp_path / "copy.sqlite3")
    initialize_knowledge_schema(other)
    with seeded_database._session_scope() as source, other._session_scope() as target:
        row = source.get(KnowledgeBaseVersionRecord, "kbv-2026-07-1")
        assert row is not None
        target.add(
            KnowledgeBaseVersionRecord(
                id=row.id,
                version=row.version,
                name=row.name,
                description=row.description,
                status=row.status,
                published_at=row.published_at,
                created_at=row.created_at,
                content_hash=row.content_hash,
            )
        )
    try:
        same_content = build_knowledge_runtime_identity(
            _settings(knowledge_db_path=other.path)
        )
        with other._session_scope() as session:
            row = session.get(KnowledgeBaseVersionRecord, "kbv-2026-07-1")
            assert row is not None
            row.content_hash = "f" * 64
        changed_content = build_knowledge_runtime_identity(
            _settings(knowledge_db_path=other.path)
        )
    finally:
        other.dispose()

    assert baseline == same_content
    assert baseline != changed_content


def test_runtime_identity_tracks_configuration_without_secrets(tmp_path) -> None:
    missing = tmp_path / "not-created.sqlite3"
    baseline = build_knowledge_runtime_identity(
        _settings(knowledge_db_path=missing)
    )
    changed = build_knowledge_runtime_identity(
        _settings(
            knowledge_db_path=missing,
            knowledge_retrieval_strategy_version="1.1",
        )
    )

    assert baseline != changed
    assert str(missing) not in baseline
    assert "mock-model" not in baseline
    assert not missing.exists()


def test_runtime_identity_tracks_requested_version_and_local_rule_versions(
    tmp_path,
    monkeypatch,
) -> None:
    import jobfit.workflow.factory as factory

    missing = tmp_path / "not-created.sqlite3"
    baseline = build_knowledge_runtime_identity(
        _settings(knowledge_db_path=missing)
    )
    requested_version_changed = build_knowledge_runtime_identity(
        _settings(
            knowledge_db_path=missing,
            knowledge_version="2026.07.2",
        )
    )
    monkeypatch.setattr(factory, "KNOWLEDGE_PROMPT_VERSION", "1.1")
    prompt_changed = build_knowledge_runtime_identity(
        _settings(knowledge_db_path=missing)
    )
    monkeypatch.setattr(factory, "KNOWLEDGE_CITATION_VALIDATOR_VERSION", "1.1")
    validator_changed = build_knowledge_runtime_identity(
        _settings(knowledge_db_path=missing)
    )

    assert baseline != requested_version_changed
    assert baseline != prompt_changed
    assert prompt_changed != validator_changed
