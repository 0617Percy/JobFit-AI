#!/usr/bin/env python3
"""Publish approved formal knowledge through a verified shadow SQLite database."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jobfit.config import Settings  # noqa: E402
from jobfit.knowledge.db import KnowledgeDatabase  # noqa: E402
from jobfit.knowledge.fts import KnowledgeSearchIndex  # noqa: E402
from jobfit.knowledge.importer import KnowledgeSeedImporter  # noqa: E402
from jobfit.knowledge.paths import resolve_knowledge_db_path  # noqa: E402
from jobfit.knowledge.release import (  # noqa: E402
    assert_no_sqlite_sidecars,
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
from jobfit.knowledge.repository import SqliteKnowledgeRepository  # noqa: E402
from jobfit.knowledge.seed_loader import (  # noqa: E402
    calculate_seed_content_hash,
    load_knowledge_seed,
)
from jobfit.knowledge.versioning import KnowledgeVersionPublisher  # noqa: E402
from jobfit.models import (  # noqa: E402
    KnowledgeSearchCapabilityStatus,
    KnowledgeSearchMode,
    KnowledgeVersionStatus,
)

TARGET_VERSION = "2026.08.1"
PREVIOUS_VERSION = "2026.07.1"
EXPECTED_HASH = "346542eb0c405643a08ebc4bffdab9b5bce22a1b7227f5ad2b27f12e3d1ef7f4"
SEED_ROOT = ROOT / "data" / "knowledge" / "versions" / TARGET_VERSION
VERIFY_SCRIPT = ROOT / "scripts" / "verify_runtime_knowledge.py"
ROLLBACK_SCRIPT = ROOT / "scripts" / "rollback_runtime_knowledge.py"


class PublicationError(RuntimeError):
    """Raised when a runtime publication gate fails."""


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except UnicodeDecodeError as exc:
        raise PublicationError("The local .env file is not valid UTF-8.") from exc


def _assert_no_process_version_override() -> None:
    if "JOBFIT_KNOWLEDGE_VERSION" in os.environ:
        raise PublicationError(
            "Remove the process-level JOBFIT_KNOWLEDGE_VERSION override before publication."
        )


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _load_effective_settings(env_path: Path) -> Settings:
    return Settings.load(_env_file=env_path)


def _publish_candidate(
    candidate: Path,
    *,
    published_at: datetime,
) -> dict[str, Any]:
    bundle = load_knowledge_seed(SEED_ROOT)
    seed_hash = calculate_seed_content_hash(bundle)
    if seed_hash != EXPECTED_HASH:
        raise PublicationError("Approved Seed Canonical Hash does not match.")

    database = KnowledgeDatabase(candidate)
    try:
        database.ensure_compatible_schema()
        repository = SqliteKnowledgeRepository(
            database,
            search_mode=KnowledgeSearchMode.AUTO,
        )
        version_id = bundle.knowledge_base_version.id
        existing = repository.get_version(version_id)
        imported = None
        published_now = False
        if existing is None:
            imported = KnowledgeSeedImporter(database).import_seed(bundle)
            KnowledgeVersionPublisher(database).publish(
                imported.version_id,
                published_at=published_at,
            )
            published_now = True
        elif existing.content_hash != EXPECTED_HASH:
            raise PublicationError("Candidate contains a conflicting target version.")
        elif existing.status is KnowledgeVersionStatus.DRAFT:
            imported = KnowledgeSeedImporter(database).import_seed(bundle)
            if not imported.idempotent:
                raise PublicationError("Existing target draft was not idempotent.")
            KnowledgeVersionPublisher(database).publish(
                existing.id,
                published_at=published_at,
            )
            published_now = True
        elif existing.status is not KnowledgeVersionStatus.PUBLISHED:
            raise PublicationError("Target version is not publishable in candidate database.")

        published = repository.get_published_version(TARGET_VERSION)
        if published is None or published.content_hash != EXPECTED_HASH:
            raise PublicationError("Candidate did not expose the approved published version.")

        search_index = KnowledgeSearchIndex(database)
        capability = search_index.detect()
        rebuilt = False
        if capability is KnowledgeSearchCapabilityStatus.AVAILABLE:
            report = search_index.rebuild_version(published.id)
            if not report.consistent:
                raise PublicationError("Candidate FTS index is inconsistent.")
            rebuilt = True
        return {
            "version_id": published.id,
            "version": published.version,
            "content_hash": published.content_hash,
            "status": published.status.value,
            "published_now": published_now,
            "import_created": None if imported is None else imported.created,
            "import_idempotent": None if imported is None else imported.idempotent,
            "search_capability": capability.value,
            "search_index_rebuilt": rebuilt,
        }
    finally:
        database.dispose()


def _run_verifier(
    *,
    database: Path,
    result_path: Path,
    require_streamlit: bool,
    use_effective_config: bool,
    cwd: Path,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(VERIFY_SCRIPT),
        "--database",
        str(database),
        "--version",
        TARGET_VERSION,
        "--expected-hash",
        EXPECTED_HASH,
        "--result",
        str(result_path),
    ]
    if require_streamlit:
        command.append("--require-streamlit")
    if use_effective_config:
        command.append("--use-effective-config")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(SRC), environment.get("PYTHONPATH", "")])
    )
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.returncode != 0:
        raise PublicationError(
            "Runtime knowledge verifier failed: "
            + (completed.stdout + completed.stderr)[-4000:]
        )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if payload.get("status") != "passed":
        raise PublicationError("Runtime knowledge verifier did not return passed.")
    return payload


def _reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _streamlit_health_check(*, cwd: Path, log_path: Path) -> dict[str, Any]:
    port = _reserve_local_port()
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(ROOT / "app.py"),
        "--server.headless=true",
        f"--server.port={port}",
        "--browser.gatherUsageStats=false",
    ]
    environment = os.environ.copy()
    environment.update(
        {
            "JOBFIT_LLM_PROVIDER": "mock",
            "JOBFIT_LLM_MODEL": "mock-model",
            "JOBFIT_DEMO_MODE": "true",
        }
    )
    started = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.monotonic() + 45
            last_error: Exception | None = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise PublicationError("Streamlit exited before health acceptance.")
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/_stcore/health",
                        timeout=2,
                    ) as response:
                        body = response.read().decode("utf-8", errors="replace").strip()
                        if response.status == 200 and body.lower() == "ok":
                            return {
                                "status": "ok",
                                "http_status": response.status,
                                "port": port,
                                "duration_seconds": round(time.monotonic() - started, 3),
                            }
                except Exception as exc:  # local startup polling
                    last_error = exc
                time.sleep(0.5)
            raise PublicationError(
                "Streamlit health endpoint did not become ready."
                + (" " + str(last_error) if last_error else "")
            )
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def _restore_previous_runtime(
    *,
    live_database: Path,
    live_existed: bool,
    database_backup: Path | None,
    env_path: Path,
    env_existed: bool,
    previous_env_bytes: bytes | None,
) -> dict[str, Any]:
    if live_database.exists():
        assert_sqlite_exclusive_access(live_database)
    if live_existed:
        if database_backup is None or not database_backup.is_file():
            raise PublicationError("Database backup is unavailable for compensation.")
        restore_candidate = live_database.with_name(
            f".{live_database.name}.compensation-{os.getpid()}.sqlite3"
        )
        restore_candidate.unlink(missing_ok=True)
        copy_verified_sqlite(database_backup, restore_candidate)
        database_hash = atomic_replace_database(restore_candidate, live_database)
        database_state = "restored"
    else:
        live_database.unlink(missing_ok=True)
        database_hash = None
        database_state = "removed"

    if env_existed:
        if previous_env_bytes is None:
            raise PublicationError("The pre-release .env snapshot is unavailable.")
        env_hash = atomic_write_bytes(env_path, previous_env_bytes)
    else:
        env_path.unlink(missing_ok=True)
        env_hash = None
    settings = _load_effective_settings(env_path)
    resolved = resolve_knowledge_db_path(
        settings.knowledge_db_path,
        cwd=env_path.parent,
    )
    if settings.knowledge_version != PREVIOUS_VERSION or resolved != live_database:
        raise PublicationError("Compensation did not restore the previous runtime identity.")
    return {
        "database_state": database_state,
        "database_hash": database_hash,
        "env_hash": env_hash,
        "effective_version": settings.knowledge_version,
    }


def _runtime_matches_previous_state(
    *,
    live_database: Path,
    live_existed: bool,
    pre_database_hash: str | None,
    env_path: Path,
    env_existed: bool,
    previous_env_bytes: bytes | None,
) -> bool:
    try:
        database_matches = (
            live_database.is_file()
            and pre_database_hash is not None
            and sha256_file(live_database) == pre_database_hash
            if live_existed
            else not live_database.exists()
        )
        env_matches = (
            env_path.is_file()
            and previous_env_bytes is not None
            and env_path.read_bytes() == previous_env_bytes
            if env_existed
            else not env_path.exists()
        )
    except OSError:
        return False
    return database_matches and env_matches


def publish_runtime(
    *,
    env_path: Path,
    result_path: Path,
    backup_root: Path | None = None,
    require_streamlit: bool = True,
    require_health: bool = True,
    published_at: datetime | None = None,
) -> dict[str, Any]:
    """Execute the complete shadow publication transaction."""
    _assert_no_process_version_override()
    env_path = env_path.expanduser().resolve(strict=False)
    workspace = env_path.parent
    settings = _load_effective_settings(env_path)
    if not settings.knowledge_enabled:
        raise PublicationError("Knowledge must be enabled before publication.")
    if settings.knowledge_version != PREVIOUS_VERSION:
        raise PublicationError("Effective pre-release knowledge version is not 2026.07.1.")
    live_database = resolve_knowledge_db_path(
        settings.knowledge_db_path,
        cwd=workspace,
    )
    if _is_inside(live_database, ROOT.resolve()):
        raise PublicationError("Runtime SQLite database must be outside the Git repository.")

    timestamp = (published_at or datetime.now(UTC)).astimezone(UTC)
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    backup_parent = (
        backup_root.expanduser().resolve(strict=False)
        if backup_root is not None
        else live_database.parent / "release-backups"
    )
    backup_dir = backup_parent / f"{stamp}-{TARGET_VERSION}"
    if backup_dir.exists():
        raise PublicationError("Release backup directory already exists.")
    backup_dir.mkdir(parents=True, exist_ok=False)

    env_existed = env_path.is_file()
    previous_env_text = _read_utf8(env_path)
    previous_env_bytes = env_path.read_bytes() if env_existed else None
    env_backup = backup_dir / "dotenv.before"
    if env_existed:
        assert previous_env_bytes is not None
        atomic_write_bytes(env_backup, previous_env_bytes)
        with suppress(OSError):
            env_backup.chmod(0o600)

    live_existed = live_database.is_file()
    database_backup = backup_dir / "knowledge.before.sqlite3" if live_existed else None
    pre_db_hash = None
    if live_existed:
        assert_sqlite_exclusive_access(live_database)
        assert database_backup is not None
        backup_sqlite_database(live_database, database_backup)
        pre_db_hash = sha256_file(live_database)

    candidate = live_database.with_name(
        f".{live_database.name}.{TARGET_VERSION}.{stamp}.{os.getpid()}.candidate"
    )
    candidate.unlink(missing_ok=True)
    manifest_path = backup_dir / "publication-manifest.json"
    candidate_verification_path = backup_dir / "candidate-verification.json"
    effective_verification_path = backup_dir / "effective-verification.json"
    health_log_path = backup_dir / "streamlit-health.log"
    result_backup_path = backup_dir / "publication-result.json"

    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "prepared",
        "created_at": timestamp.isoformat(),
        "repo_root": str(ROOT.resolve()),
        "workspace": str(workspace),
        "live_database": str(live_database),
        "live_database_existed": live_existed,
        "database_backup": None if database_backup is None else str(database_backup),
        "pre_database_hash": pre_db_hash,
        "env_path": str(env_path),
        "env_existed": env_existed,
        "env_backup": str(env_backup) if env_existed else None,
        "pre_env_hash": sha256_file(env_path) if env_existed else None,
        "previous_version": PREVIOUS_VERSION,
        "target_version": TARGET_VERSION,
        "approved_hash": EXPECTED_HASH,
        "candidate_database": str(candidate),
        "post_database_hash": None,
        "post_env_hash": None,
        "rollback_script": str(ROLLBACK_SCRIPT.resolve()),
    }
    _write_json(manifest_path, manifest)

    compensation_guard_armed = False
    transaction_committed = False
    compensated = False
    compensation: dict[str, Any] | None = None
    try:
        prepare_candidate_database(live_database, candidate)
        candidate_state = _publish_candidate(candidate, published_at=timestamp)
        assert_no_sqlite_sidecars(candidate)
        candidate_verification = _run_verifier(
            database=candidate,
            result_path=candidate_verification_path,
            require_streamlit=require_streamlit,
            use_effective_config=False,
            cwd=workspace,
        )

        target_env_text = replace_env_assignment(
            previous_env_text,
            "JOBFIT_KNOWLEDGE_VERSION",
            TARGET_VERSION,
        )
        assert_sqlite_exclusive_access(candidate)
        if live_database.exists():
            assert_sqlite_exclusive_access(live_database)
        compensation_guard_armed = True
        post_database_hash = atomic_replace_database(candidate, live_database)
        post_env_hash = atomic_write_text(env_path, target_env_text)

        effective_settings = _load_effective_settings(env_path)
        effective_database = resolve_knowledge_db_path(
            effective_settings.knowledge_db_path,
            cwd=workspace,
        )
        if (
            effective_settings.knowledge_version != TARGET_VERSION
            or not effective_settings.knowledge_enabled
            or effective_database != live_database
        ):
            raise PublicationError("Effective runtime identity did not switch to target.")

        effective_verification = _run_verifier(
            database=live_database,
            result_path=effective_verification_path,
            require_streamlit=require_streamlit,
            use_effective_config=True,
            cwd=workspace,
        )
        health = (
            _streamlit_health_check(cwd=workspace, log_path=health_log_path)
            if require_health
            else {"status": "not_requested"}
        )

        rollback_copy = backup_dir / "rollback_runtime_knowledge.py"
        atomic_write_bytes(rollback_copy, ROLLBACK_SCRIPT.read_bytes())
        rollback_ps1 = backup_dir / "rollback.ps1"
        rollback_command = (
            f'& "{sys.executable}" "{rollback_copy}" '
            f'--manifest "{manifest_path}"\nexit $LASTEXITCODE\n'
        )
        atomic_write_text(rollback_ps1, rollback_command)

        manifest.update(
            {
                "status": "published",
                "candidate_database": None,
                "candidate_state": candidate_state,
                "candidate_verification": str(candidate_verification_path),
                "effective_verification": str(effective_verification_path),
                "post_database_hash": post_database_hash,
                "post_env_hash": post_env_hash,
                "streamlit_health": health,
                "rollback_copy": str(rollback_copy),
                "rollback_command_file": str(rollback_ps1),
                "completed_at": datetime.now(UTC).isoformat(),
            }
        )
        _write_json(manifest_path, manifest)
        result = {
            "status": "passed",
            "target_version": TARGET_VERSION,
            "approved_hash": EXPECTED_HASH,
            "live_database": str(live_database),
            "backup_dir": str(backup_dir),
            "manifest": str(manifest_path),
            "database_hash": post_database_hash,
            "env_hash": post_env_hash,
            "candidate": candidate_state,
            "candidate_verification": candidate_verification,
            "effective_verification": effective_verification,
            "streamlit_health": health,
            "compensated": False,
        }
        _write_json(result_backup_path, result)
        _write_json(result_path, result)
        transaction_committed = True
    except Exception as exc:
        if compensation_guard_armed and not transaction_committed:
            if _runtime_matches_previous_state(
                live_database=live_database,
                live_existed=live_existed,
                pre_database_hash=pre_db_hash,
                env_path=env_path,
                env_existed=env_existed,
                previous_env_bytes=previous_env_bytes,
            ):
                compensation = {
                    "status": "not_required",
                    "reason": "runtime_unchanged",
                }
            else:
                try:
                    compensation = _restore_previous_runtime(
                        live_database=live_database,
                        live_existed=live_existed,
                        database_backup=database_backup,
                        env_path=env_path,
                        env_existed=env_existed,
                        previous_env_bytes=previous_env_bytes,
                    )
                    compensated = True
                except Exception as compensation_exc:
                    compensation = {
                        "status": "failed",
                        "failure": (
                            f"{type(compensation_exc).__name__}: {compensation_exc}"
                        ),
                    }
        manifest.update(
            {
                "status": "failed",
                "failure": f"{type(exc).__name__}: {exc}",
                "compensated": compensated,
                "compensation": compensation,
                "failed_at": datetime.now(UTC).isoformat(),
            }
        )
        _write_json(manifest_path, manifest)
        result = {
            "status": "failed",
            "failure": f"{type(exc).__name__}: {exc}",
            "backup_dir": str(backup_dir),
            "manifest": str(manifest_path),
            "candidate_database": str(candidate) if candidate.exists() else None,
            "compensated": compensated,
            "compensation": compensation,
        }
        _write_json(result_backup_path, result)
        _write_json(result_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--skip-streamlit", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-health", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        result = publish_runtime(
            env_path=args.env_file,
            result_path=args.result,
            backup_root=args.backup_root,
            require_streamlit=not args.skip_streamlit,
            require_health=not args.skip_health,
        )
    except Exception as exc:
        result = {
            "status": "failed",
            "failure": f"{type(exc).__name__}: {exc}",
        }
        _write_json(args.result, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
