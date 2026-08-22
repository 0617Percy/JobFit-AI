"""Explicit SQLite lifecycle, schema revision, and transaction tests."""

from __future__ import annotations

import importlib
import sqlite3

import pytest

from jobfit.errors import ErrorCode, JobFitError

EXPECTED_TABLES = {
    "knowledge_base_versions",
    "job_families",
    "role_profiles",
    "competency_dimensions",
    "role_requirements",
    "evidence_patterns",
    "knowledge_sources",
    "knowledge_chunks",
    "interview_questions",
    "source_role_links",
}


def db_module():
    return importlib.import_module("jobfit.knowledge.db")


def test_importing_database_module_does_not_create_database(tmp_path) -> None:
    path = tmp_path / "knowledge.sqlite3"

    importlib.import_module("jobfit.knowledge.db")

    assert not path.exists()


def test_initialization_creates_parent_and_exact_ten_domain_tables(tmp_path) -> None:
    module = db_module()
    path = tmp_path / "nested" / "knowledge.sqlite3"
    database = module.KnowledgeDatabase(path)

    module.initialize_knowledge_schema(database)

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert tables == EXPECTED_TABLES
    assert user_version == 1
    database.dispose()


def test_initialization_is_idempotent(knowledge_database) -> None:
    module = db_module()

    module.initialize_knowledge_schema(knowledge_database)
    module.initialize_knowledge_schema(knowledge_database)

    assert knowledge_database.schema_version() == 1


def test_engine_connections_enable_foreign_keys_and_busy_timeout(
    knowledge_database,
) -> None:
    text = importlib.import_module("sqlalchemy").text

    with knowledge_database._session_scope() as session:
        foreign_keys = session.execute(text("PRAGMA foreign_keys")).scalar_one()
        busy_timeout = session.execute(text("PRAGMA busy_timeout")).scalar_one()

    assert foreign_keys == 1
    assert busy_timeout >= 1_000


def test_session_scope_commits_and_closes(knowledge_database, knowledge_modules) -> None:
    orm = knowledge_modules["orm"]
    now = importlib.import_module("datetime").datetime.now(
        importlib.import_module("datetime").UTC
    )
    with knowledge_database._session_scope() as session:
        session.add(
            orm.KnowledgeBaseVersionRecord(
                id="kbv-draft",
                version="2026.08.1",
                name="Draft",
                description="",
                status="draft",
                published_at=None,
                created_at=now,
                content_hash="d" * 64,
            )
        )

    with knowledge_database._session_scope() as session:
        count = session.query(orm.KnowledgeBaseVersionRecord).count()
    assert count == 1


def test_session_scope_rolls_back_on_error(knowledge_database, knowledge_modules) -> None:
    orm = knowledge_modules["orm"]
    now = importlib.import_module("datetime").datetime.now(
        importlib.import_module("datetime").UTC
    )

    with (
        pytest.raises(RuntimeError, match="stop transaction"),
        knowledge_database._session_scope() as session,
    ):
        session.add(
            orm.KnowledgeBaseVersionRecord(
                id="kbv-rollback",
                version="2026.08.2",
                name="Rollback",
                description="",
                status="draft",
                published_at=None,
                created_at=now,
                content_hash="e" * 64,
            )
        )
        raise RuntimeError("stop transaction")

    with knowledge_database._session_scope() as session:
        assert session.query(orm.KnowledgeBaseVersionRecord).count() == 0


def test_higher_schema_version_fails_closed_without_path_leak(tmp_path) -> None:
    module = db_module()
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 2")

    with pytest.raises(JobFitError) as exc_info:
        module.initialize_knowledge_schema(module.KnowledgeDatabase(path))

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_VERSION_MISMATCH
    assert str(path) not in exc_info.value.user_message


def test_lower_nonempty_schema_is_not_silently_upgraded(tmp_path) -> None:
    module = db_module()
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE legacy_table (id TEXT PRIMARY KEY)")
        connection.execute("PRAGMA user_version = 0")

    with pytest.raises(JobFitError) as exc_info:
        module.initialize_knowledge_schema(module.KnowledgeDatabase(path))

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_VERSION_MISMATCH


def test_missing_database_check_does_not_create_file(tmp_path) -> None:
    module = db_module()
    path = tmp_path / "missing.sqlite3"
    database = module.KnowledgeDatabase(path)

    with pytest.raises(JobFitError) as exc_info:
        database.ensure_compatible_schema()

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_DB_UNAVAILABLE
    assert not path.exists()
    database.dispose()


def test_corrupt_database_is_reported_safely(tmp_path) -> None:
    module = db_module()
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"not a sqlite database")
    database = module.KnowledgeDatabase(path)

    with pytest.raises(JobFitError) as exc_info:
        database.ensure_compatible_schema()

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_DB_UNAVAILABLE
    assert str(path) not in exc_info.value.user_message
    assert "sqlite" not in exc_info.value.user_message.lower()
    database.dispose()
