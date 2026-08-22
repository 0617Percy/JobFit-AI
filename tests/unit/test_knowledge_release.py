"""Safety primitives for local runtime knowledge publication."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from jobfit.knowledge.db import KnowledgeDatabase
from jobfit.knowledge.release import (
    KnowledgeReleaseError,
    assert_sqlite_exclusive_access,
    atomic_replace_database,
    atomic_write_bytes,
    atomic_write_text,
    backup_sqlite_database,
    copy_verified_sqlite,
    prepare_candidate_database,
    replace_env_assignment,
    sha256_file,
)


def _create_sqlite(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(value) VALUES (?)", (value,))
        connection.commit()


def _read_value(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return str(connection.execute("SELECT value FROM sample").fetchone()[0])


def test_replace_env_assignment_replaces_only_target_and_preserves_newline() -> None:
    original = "JOBFIT_LLM_MODEL=test-model\r\nexport JOBFIT_KNOWLEDGE_VERSION=2026.07.1\r\n"

    updated = replace_env_assignment(
        original,
        "JOBFIT_KNOWLEDGE_VERSION",
        "2026.08.1",
    )

    assert updated == (
        "JOBFIT_LLM_MODEL=test-model\r\n"
        "JOBFIT_KNOWLEDGE_VERSION=2026.08.1\r\n"
    )


def test_replace_env_assignment_appends_missing_key_without_losing_content() -> None:
    updated = replace_env_assignment(
        "JOBFIT_LLM_PROVIDER=mock",
        "JOBFIT_KNOWLEDGE_VERSION",
        "2026.08.1",
    )

    assert updated == (
        "JOBFIT_LLM_PROVIDER=mock\n"
        "JOBFIT_KNOWLEDGE_VERSION=2026.08.1\n"
    )


def test_replace_env_assignment_rejects_duplicate_active_assignments() -> None:
    content = (
        "JOBFIT_KNOWLEDGE_VERSION=2026.07.1\n"
        "JOBFIT_KNOWLEDGE_VERSION=2026.08.1\n"
    )

    with pytest.raises(KnowledgeReleaseError, match="multiple active assignments"):
        replace_env_assignment(content, "JOBFIT_KNOWLEDGE_VERSION", "2026.08.1")


def test_atomic_write_text_replaces_file_and_returns_hash(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text("before\n", encoding="utf-8")

    digest = atomic_write_text(target, "after\n")

    assert target.read_text(encoding="utf-8") == "after\n"
    assert digest == sha256_file(target)
    assert not list(tmp_path.glob("*.tmp"))



def test_atomic_write_bytes_preserves_exact_content(tmp_path: Path) -> None:
    target = tmp_path / "state.bin"

    digest = atomic_write_bytes(target, b"\x00before\r\nafter\xff")

    assert target.read_bytes() == b"\x00before\r\nafter\xff"
    assert digest == sha256_file(target)


def test_copy_verified_sqlite_preserves_file_hash(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "copy.sqlite3"
    _create_sqlite(source, "copy")

    digest = copy_verified_sqlite(source, destination)

    assert _read_value(destination) == "copy"
    assert digest == sha256_file(source) == sha256_file(destination)

def test_backup_sqlite_database_is_consistent_and_does_not_change_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "live.sqlite3"
    backup = tmp_path / "backup" / "knowledge.sqlite3"
    _create_sqlite(source, "before")
    source_hash = sha256_file(source)

    backup_sqlite_database(source, backup)

    assert _read_value(backup) == "before"
    assert sha256_file(source) == source_hash


def test_prepare_candidate_database_copies_existing_live_database(tmp_path: Path) -> None:
    live = tmp_path / "live.sqlite3"
    candidate = tmp_path / "candidate.sqlite3"
    _create_sqlite(live, "live")

    live_existed = prepare_candidate_database(live, candidate)

    assert live_existed is True
    assert _read_value(candidate) == "live"
    assert _read_value(live) == "live"


def test_prepare_candidate_database_initializes_schema_when_live_is_missing(
    tmp_path: Path,
) -> None:
    live = tmp_path / "missing.sqlite3"
    candidate = tmp_path / "candidate.sqlite3"

    live_existed = prepare_candidate_database(live, candidate)

    database = KnowledgeDatabase(candidate)
    try:
        assert live_existed is False
        database.ensure_compatible_schema()
    finally:
        database.dispose()


def test_assert_sqlite_exclusive_access_rejects_active_lock(tmp_path: Path) -> None:
    database = tmp_path / "locked.sqlite3"
    _create_sqlite(database, "locked")
    connection = sqlite3.connect(database, isolation_level=None)
    connection.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(KnowledgeReleaseError, match="exclusive access"):
            assert_sqlite_exclusive_access(database)
    finally:
        connection.execute("ROLLBACK")
        connection.close()


def test_atomic_replace_database_replaces_live_with_candidate(tmp_path: Path) -> None:
    live = tmp_path / "knowledge.sqlite3"
    candidate = tmp_path / ".knowledge.sqlite3.candidate"
    _create_sqlite(live, "old")
    _create_sqlite(candidate, "new")

    atomic_replace_database(candidate, live)

    assert _read_value(live) == "new"
    assert not candidate.exists()
