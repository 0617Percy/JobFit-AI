"""Local-only safety primitives for runtime knowledge publication."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from jobfit.knowledge.db import KnowledgeDatabase, initialize_knowledge_schema

_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class KnowledgeReleaseError(RuntimeError):
    """Raised when a local publication safety gate cannot be satisfied."""


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of one existing file."""
    resolved = Path(path)
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quick_check(path: Path) -> None:
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=0)) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
    except sqlite3.Error as exc:
        raise KnowledgeReleaseError(
            f"SQLite quick_check failed for {path.name}."
        ) from exc
    if result != ("ok",):
        raise KnowledgeReleaseError(
            f"SQLite quick_check did not return ok for {path.name}."
        )


def _sidecar_paths(path: Path) -> tuple[Path, Path]:
    return (
        path.with_name(f"{path.name}-wal"),
        path.with_name(f"{path.name}-shm"),
    )


def assert_no_sqlite_sidecars(path: str | Path) -> None:
    """Reject WAL/SHM sidecars before an atomic runtime replacement."""
    resolved = Path(path)
    present = [item.name for item in _sidecar_paths(resolved) if item.exists()]
    if present:
        raise KnowledgeReleaseError(
            "SQLite sidecar files are present; stop the application and retry: "
            + ", ".join(sorted(present))
        )


def assert_sqlite_exclusive_access(path: str | Path) -> None:
    """Prove that an existing SQLite file is healthy and not actively locked."""
    resolved = Path(path)
    if not resolved.exists():
        return
    if not resolved.is_file():
        raise KnowledgeReleaseError("Runtime database path is not a file.")
    assert_no_sqlite_sidecars(resolved)
    try:
        connection = sqlite3.connect(resolved, timeout=0, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout = 0")
            connection.execute("BEGIN EXCLUSIVE")
            result = connection.execute("PRAGMA quick_check").fetchone()
            connection.execute("ROLLBACK")
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise KnowledgeReleaseError(
            "Could not obtain exclusive access to the runtime SQLite database."
        ) from exc
    if result != ("ok",):
        raise KnowledgeReleaseError("Runtime SQLite quick_check did not return ok.")


def backup_sqlite_database(source: str | Path, destination: str | Path) -> str:
    """Create a consistent SQLite Backup API snapshot and return its hash."""
    source_path = Path(source).expanduser().resolve(strict=False)
    destination_path = Path(destination).expanduser().resolve(strict=False)
    if not source_path.is_file():
        raise KnowledgeReleaseError("Source SQLite database does not exist.")
    if destination_path.exists():
        raise KnowledgeReleaseError("SQLite backup destination already exists.")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    _quick_check(source_path)
    try:
        source_uri = f"{source_path.as_uri()}?mode=ro"
        with (
            closing(sqlite3.connect(source_uri, uri=True, timeout=5)) as source_connection,
            closing(sqlite3.connect(destination_path, timeout=5)) as destination_connection,
        ):
            source_connection.backup(destination_connection)
            destination_connection.commit()
    except sqlite3.Error as exc:
        destination_path.unlink(missing_ok=True)
        raise KnowledgeReleaseError("SQLite backup failed.") from exc
    _quick_check(destination_path)
    return sha256_file(destination_path)


def copy_verified_sqlite(source: str | Path, destination: str | Path) -> str:
    """Copy one closed SQLite file byte-for-byte after integrity checks."""
    source_path = Path(source).expanduser().resolve(strict=False)
    destination_path = Path(destination).expanduser().resolve(strict=False)
    if not source_path.is_file():
        raise KnowledgeReleaseError("SQLite copy source does not exist.")
    if destination_path.exists():
        raise KnowledgeReleaseError("SQLite copy destination already exists.")
    assert_no_sqlite_sidecars(source_path)
    _quick_check(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source_path, destination_path)
    except OSError as exc:
        destination_path.unlink(missing_ok=True)
        raise KnowledgeReleaseError("SQLite copy failed.") from exc
    _quick_check(destination_path)
    return sha256_file(destination_path)


def prepare_candidate_database(
    live_database: str | Path,
    candidate_database: str | Path,
) -> bool:
    """Copy the live database or initialize an empty compatible candidate."""
    live_path = Path(live_database).expanduser().resolve(strict=False)
    candidate_path = Path(candidate_database).expanduser().resolve(strict=False)
    if candidate_path.exists():
        raise KnowledgeReleaseError("Candidate SQLite database already exists.")
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    if live_path.exists():
        assert_sqlite_exclusive_access(live_path)
        backup_sqlite_database(live_path, candidate_path)
        return True
    database = KnowledgeDatabase(candidate_path)
    try:
        initialize_knowledge_schema(database)
        database.ensure_compatible_schema()
    finally:
        database.dispose()
    return False


def atomic_replace_database(candidate: str | Path, live: str | Path) -> str:
    """Atomically replace the live database with a verified same-filesystem candidate."""
    candidate_path = Path(candidate).expanduser().resolve(strict=False)
    live_path = Path(live).expanduser().resolve(strict=False)
    if not candidate_path.is_file():
        raise KnowledgeReleaseError("Candidate SQLite database does not exist.")
    if candidate_path.parent != live_path.parent:
        raise KnowledgeReleaseError(
            "Candidate and live SQLite databases must share one directory."
        )
    _quick_check(candidate_path)
    assert_no_sqlite_sidecars(candidate_path)
    if live_path.exists():
        assert_sqlite_exclusive_access(live_path)
    live_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(candidate_path, live_path)
    except OSError as exc:
        raise KnowledgeReleaseError("Atomic SQLite replacement failed.") from exc
    _quick_check(live_path)
    return sha256_file(live_path)


def replace_env_assignment(content: str, key: str, value: str) -> str:
    """Replace one active dotenv assignment or append it without exposing peers."""
    if not _ENV_KEY.fullmatch(key):
        raise KnowledgeReleaseError("Invalid environment variable name.")
    if "\n" in value or "\r" in value:
        raise KnowledgeReleaseError("Environment variable value must be one line.")
    lines = content.splitlines(keepends=True)
    pattern = re.compile(
        rf"^\s*(?:export\s+)?{re.escape(key)}\s*=",
        re.IGNORECASE,
    )
    matches = [index for index, line in enumerate(lines) if pattern.match(line)]
    if len(matches) > 1:
        raise KnowledgeReleaseError(
            f"Found multiple active assignments for {key}."
        )
    if matches:
        index = matches[0]
        old_line = lines[index]
        newline = "\r\n" if old_line.endswith("\r\n") else "\n" if old_line.endswith("\n") else ""
        lines[index] = f"{key}={value}{newline}"
        return "".join(lines)

    if not content:
        return f"{key}={value}\n"
    newline = "\r\n" if "\r\n" in content else "\n"
    prefix = content if content.endswith(("\n", "\r")) else content + newline
    return f"{prefix}{key}={value}{newline}"


def atomic_write_bytes(path: str | Path, content: bytes) -> str:
    """Atomically write bytes in the target directory and return the file hash."""
    target = Path(path).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return sha256_file(target)


def atomic_write_text(path: str | Path, content: str) -> str:
    """Atomically write UTF-8 text in the target directory and return its hash."""
    return atomic_write_bytes(path, content.encode("utf-8"))


__all__ = [
    "KnowledgeReleaseError",
    "assert_no_sqlite_sidecars",
    "assert_sqlite_exclusive_access",
    "atomic_replace_database",
    "atomic_write_bytes",
    "atomic_write_text",
    "backup_sqlite_database",
    "copy_verified_sqlite",
    "prepare_candidate_database",
    "replace_env_assignment",
    "sha256_file",
]
