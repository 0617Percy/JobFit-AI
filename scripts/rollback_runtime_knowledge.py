#!/usr/bin/env python3
"""Guarded rollback for one completed runtime knowledge publication."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _bootstrap_repo_root() -> Path:
    default = Path(__file__).resolve().parents[1]
    try:
        index = sys.argv.index("--manifest")
        manifest_path = Path(sys.argv[index + 1]).expanduser().resolve(strict=True)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        configured = Path(str(payload.get("repo_root", ""))).expanduser()
        if (configured / "src" / "jobfit").is_dir():
            return configured.resolve(strict=True)
    except (ValueError, IndexError, OSError, json.JSONDecodeError):
        pass
    return default


ROOT = _bootstrap_repo_root()
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jobfit.config import Settings  # noqa: E402
from jobfit.knowledge.paths import resolve_knowledge_db_path  # noqa: E402
from jobfit.knowledge.release import (  # noqa: E402
    assert_sqlite_exclusive_access,
    atomic_replace_database,
    atomic_write_bytes,
    atomic_write_text,
    copy_verified_sqlite,
    replace_env_assignment,
    sha256_file,
)


class RollbackError(RuntimeError):
    """Raised when rollback cannot prove that the release state is unchanged."""


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _restore_database(
    *,
    live_database: Path,
    live_existed: bool,
    database_backup: Path | None,
) -> tuple[str, str | None]:
    assert_sqlite_exclusive_access(live_database)
    if not live_existed:
        live_database.unlink(missing_ok=True)
        return "removed", None
    if database_backup is None or not database_backup.is_file():
        raise RollbackError("Pre-release database backup is unavailable.")
    candidate = live_database.with_name(
        f".{live_database.name}.rollback-{os.getpid()}.sqlite3"
    )
    candidate.unlink(missing_ok=True)
    copy_verified_sqlite(database_backup, candidate)
    digest = atomic_replace_database(candidate, live_database)
    return "restored", digest


def rollback_runtime(
    *,
    manifest_path: Path,
    result_path: Path | None = None,
) -> dict[str, Any]:
    if "JOBFIT_KNOWLEDGE_VERSION" in os.environ:
        raise RollbackError(
            "Remove the process-level JOBFIT_KNOWLEDGE_VERSION override before rollback."
        )
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "1.0" or manifest.get("status") != "published":
        raise RollbackError("Manifest is not a completed supported publication.")

    backup_dir = manifest_path.parent
    result_path = result_path or (backup_dir / "rollback-result.json")
    live_database = Path(manifest["live_database"]).resolve(strict=False)
    env_path = Path(manifest["env_path"]).resolve(strict=False)
    post_db_hash = manifest.get("post_database_hash")
    post_env_hash = manifest.get("post_env_hash")
    if not live_database.is_file() or sha256_file(live_database) != post_db_hash:
        raise RollbackError("Current runtime database differs from the published state.")
    if not env_path.is_file() or sha256_file(env_path) != post_env_hash:
        raise RollbackError("Current .env differs from the published state.")

    pre_db_existed = bool(manifest["live_database_existed"])
    database_backup = (
        Path(manifest["database_backup"]).resolve(strict=True)
        if manifest.get("database_backup")
        else None
    )
    pre_env_backup = (
        Path(manifest["env_backup"]).resolve(strict=True)
        if manifest.get("env_backup")
        else None
    )
    previous_version = str(manifest["previous_version"])

    post_snapshot = backup_dir / "rollback-post.sqlite3"
    post_env_snapshot = backup_dir / "rollback-post.env"
    post_snapshot.unlink(missing_ok=True)
    post_env_snapshot.unlink(missing_ok=True)
    copy_verified_sqlite(live_database, post_snapshot)
    atomic_write_bytes(post_env_snapshot, env_path.read_bytes())

    mutated = False
    compensated = False
    try:
        database_state, restored_db_hash = _restore_database(
            live_database=live_database,
            live_existed=pre_db_existed,
            database_backup=database_backup,
        )
        mutated = True
        if pre_env_backup is not None:
            try:
                previous_env_text = pre_env_backup.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise RollbackError("Pre-release .env backup is not valid UTF-8.") from exc
        else:
            previous_env_text = ""
        rollback_env = replace_env_assignment(
            previous_env_text,
            "JOBFIT_KNOWLEDGE_VERSION",
            previous_version,
        )
        restored_env_hash = atomic_write_text(env_path, rollback_env)

        settings = Settings.load(_env_file=env_path)
        resolved_database = resolve_knowledge_db_path(
            settings.knowledge_db_path,
            cwd=env_path.parent,
        )
        if settings.knowledge_version != previous_version:
            raise RollbackError("Rollback did not restore the previous effective version.")
        if resolved_database != live_database:
            raise RollbackError("Rollback changed the effective database path.")
        if pre_db_existed and restored_db_hash != sha256_file(database_backup):
            raise RollbackError("Restored database does not match the backup file.")
        if not pre_db_existed and live_database.exists():
            raise RollbackError("Rollback did not remove the newly created database.")

        result = {
            "status": "passed",
            "rolled_back_at": datetime.now(UTC).isoformat(),
            "manifest": str(manifest_path),
            "database_state": database_state,
            "database_hash": restored_db_hash,
            "env_hash": restored_env_hash,
            "effective_version": settings.knowledge_version,
            "compensated": False,
        }
    except Exception as exc:
        compensation_failure = None
        if mutated:
            try:
                compensation_candidate = live_database.with_name(
                    f".{live_database.name}.rollback-compensation-{os.getpid()}.sqlite3"
                )
                compensation_candidate.unlink(missing_ok=True)
                copy_verified_sqlite(post_snapshot, compensation_candidate)
                atomic_replace_database(compensation_candidate, live_database)
                atomic_write_bytes(env_path, post_env_snapshot.read_bytes())
                compensated = True
            except Exception as compensation_exc:
                compensation_failure = (
                    f"{type(compensation_exc).__name__}: {compensation_exc}"
                )
        result = {
            "status": "failed",
            "failure": f"{type(exc).__name__}: {exc}",
            "manifest": str(manifest_path),
            "compensated": compensated,
            "compensation_failure": compensation_failure,
        }
    _write_json(result_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    try:
        result = rollback_runtime(
            manifest_path=args.manifest,
            result_path=args.result,
        )
    except Exception as exc:
        result = {
            "status": "failed",
            "failure": f"{type(exc).__name__}: {exc}",
        }
        result_path = args.result or args.manifest.parent / "rollback-result.json"
        _write_json(result_path, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
