"""Runtime knowledge publication and rollback gates in temporary storage."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobfit.config import Settings
from jobfit.knowledge.db import KnowledgeDatabase, initialize_knowledge_schema
from jobfit.knowledge.fts import KnowledgeSearchIndex
from jobfit.knowledge.importer import KnowledgeSeedImporter
from jobfit.knowledge.release import (
    KnowledgeReleaseError,
    atomic_replace_database,
    prepare_candidate_database,
    sha256_file,
)
from jobfit.knowledge.repository import SqliteKnowledgeRepository
from jobfit.knowledge.seed_loader import load_knowledge_seed
from jobfit.knowledge.versioning import KnowledgeVersionPublisher
from jobfit.models import KnowledgeSearchCapabilityStatus, KnowledgeSearchMode
from scripts import publish_runtime_knowledge as runtime_publisher

ROOT = Path(__file__).parents[2]
SEED_ROOT = ROOT / "data" / "knowledge" / "versions" / "2026.08.1"
VERIFY_SCRIPT = ROOT / "scripts" / "verify_runtime_knowledge.py"
PUBLISH_SCRIPT = ROOT / "scripts" / "publish_runtime_knowledge.py"
EXPECTED_HASH = "346542eb0c405643a08ebc4bffdab9b5bce22a1b7227f5ad2b27f12e3d1ef7f4"


def _prepare_pre_release_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    live_exists: bool = True,
    env_exists: bool = True,
) -> dict[str, object]:
    for name in (
        "JOBFIT_KNOWLEDGE_VERSION",
        "JOBFIT_KNOWLEDGE_DB_PATH",
        "JOBFIT_KNOWLEDGE_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    live = tmp_path / "runtime" / "knowledge.sqlite3"
    if live_exists:
        database = KnowledgeDatabase(live)
        try:
            initialize_knowledge_schema(database)
        finally:
            database.dispose()

    env_path = workspace / ".env"
    if env_exists:
        env_path.write_text(
            "\n".join(
                [
                    "JOBFIT_KNOWLEDGE_ENABLED=true",
                    "JOBFIT_KNOWLEDGE_VERSION=2026.07.1",
                    f"JOBFIT_KNOWLEDGE_DB_PATH={live}",
                    "JOBFIT_LLM_PROVIDER=mock",
                    "JOBFIT_LLM_MODEL=mock-model",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    else:
        monkeypatch.setenv("JOBFIT_KNOWLEDGE_ENABLED", "true")
        monkeypatch.setenv("JOBFIT_KNOWLEDGE_DB_PATH", str(live))
        pre_release_settings = Settings(
            app_env="test",
            llm_provider="mock",
            llm_model="mock-model",
            knowledge_enabled=True,
            knowledge_version="2026.07.1",
            knowledge_db_path=live,
            _env_file=None,
        )
        monkeypatch.setattr(
            runtime_publisher,
            "_load_effective_settings",
            lambda _env_path: pre_release_settings,
        )

    return {
        "workspace": workspace,
        "live": live,
        "live_exists": live_exists,
        "database_hash": sha256_file(live) if live_exists else None,
        "env_path": env_path,
        "env_exists": env_exists,
        "env_bytes": env_path.read_bytes() if env_exists else None,
        "result_path": tmp_path / "publication-result.json",
        "backup_root": tmp_path / "release-backups",
    }


def _run_publication(
    state: dict[str, object],
    *,
    require_health: bool = False,
) -> dict[str, object]:
    return runtime_publisher.publish_runtime(
        env_path=Path(state["env_path"]),
        result_path=Path(state["result_path"]),
        backup_root=Path(state["backup_root"]),
        require_streamlit=False,
        require_health=require_health,
        published_at=datetime(2026, 8, 6, 12, 0, tzinfo=UTC),
    )


def _assert_runtime_was_compensated(
    state: dict[str, object],
    result: dict[str, object],
) -> None:
    live = Path(state["live"])
    env_path = Path(state["env_path"])
    assert result["status"] == "failed"
    assert result["compensated"] is True
    assert live.exists() is state["live_exists"]
    if state["env_exists"]:
        assert env_path.read_bytes() == state["env_bytes"]
    else:
        assert not env_path.exists()

    settings = runtime_publisher._load_effective_settings(env_path)
    assert settings.knowledge_version == "2026.07.1"
    backup_dir = Path(str(result["backup_dir"]))
    manifest = json.loads(
        (backup_dir / "publication-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "failed"
    assert manifest["compensated"] is True
    assert (backup_dir / "candidate-verification.json").is_file()
    if state["live_exists"]:
        backup = backup_dir / "knowledge.before.sqlite3"
        assert backup.is_file()
        assert manifest["pre_database_hash"] == state["database_hash"]
        assert sha256_file(live) == sha256_file(backup)

    if live.exists():
        restored = KnowledgeDatabase(live)
        try:
            repository = SqliteKnowledgeRepository(
                restored,
                search_mode=KnowledgeSearchMode.AUTO,
            )
            assert repository.get_version("kbv-2026-08-1") is None
        finally:
            restored.dispose()


def _subprocess_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "JOBFIT_KNOWLEDGE_VERSION",
        "JOBFIT_KNOWLEDGE_DB_PATH",
        "JOBFIT_KNOWLEDGE_ENABLED",
    ):
        environment.pop(name, None)
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(ROOT / "src"), environment.get("PYTHONPATH", "")])
    )
    return environment


def _publish(database_path: Path) -> None:
    database = KnowledgeDatabase(database_path)
    try:
        initialize_knowledge_schema(database)
        bundle = load_knowledge_seed(SEED_ROOT)
        imported = KnowledgeSeedImporter(database).import_seed(bundle)
        KnowledgeVersionPublisher(database).publish(
            imported.version_id,
            published_at=datetime(2026, 8, 5, 12, 0, tzinfo=UTC),
        )
        search_index = KnowledgeSearchIndex(database)
        if search_index.detect() is KnowledgeSearchCapabilityStatus.AVAILABLE:
            report = search_index.rebuild_version(imported.version_id)
            assert report.consistent is True
    finally:
        database.dispose()


def test_shadow_candidate_publishes_verifies_and_replaces_runtime(
    tmp_path: Path,
) -> None:
    live = tmp_path / "knowledge.sqlite3"
    candidate = tmp_path / ".knowledge.sqlite3.candidate"
    result = tmp_path / "verification.json"

    assert prepare_candidate_database(live, candidate) is False
    _publish(candidate)

    completed = subprocess.run(
        [
            sys.executable,
            str(VERIFY_SCRIPT),
            "--database",
            str(candidate),
            "--version",
            "2026.08.1",
            "--expected-hash",
            EXPECTED_HASH,
            "--result",
            str(result),
        ],
        cwd=ROOT,
        env=_subprocess_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["base_knowledge_status"] == "disabled"
    assert payload["enhanced_knowledge_status"] == "available"
    assert all(payload["identity"].values())

    atomic_replace_database(candidate, live)
    database = KnowledgeDatabase(live)
    try:
        repository = SqliteKnowledgeRepository(
            database,
            search_mode=KnowledgeSearchMode.AUTO,
        )
        published = repository.get_published_version("2026.08.1")
        assert published is not None
        assert published.content_hash == EXPECTED_HASH
    finally:
        database.dispose()


def test_publish_transaction_and_guarded_rollback_restore_prior_runtime(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    live = tmp_path / "runtime" / "knowledge.sqlite3"
    database = KnowledgeDatabase(live)
    try:
        initialize_knowledge_schema(database)
    finally:
        database.dispose()
    env_path = workspace / ".env"
    secret = "test-only-secret-must-not-enter-manifest"
    env_path.write_text(
        "\n".join(
            [
                "JOBFIT_KNOWLEDGE_ENABLED=true",
                "JOBFIT_KNOWLEDGE_VERSION=2026.07.1",
                f"JOBFIT_KNOWLEDGE_DB_PATH={live}",
                "JOBFIT_LLM_PROVIDER=mock",
                "JOBFIT_LLM_MODEL=mock-model",
                f"JOBFIT_LLM_API_KEY={secret}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    publish_result_path = tmp_path / "publish-result.json"
    backup_root = tmp_path / "backups"

    published = subprocess.run(
        [
            sys.executable,
            str(PUBLISH_SCRIPT),
            "--env-file",
            str(env_path),
            "--result",
            str(publish_result_path),
            "--backup-root",
            str(backup_root),
            "--skip-streamlit",
            "--skip-health",
        ],
        cwd=workspace,
        env=_subprocess_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert published.returncode == 0, published.stdout + published.stderr
    publish_result = json.loads(publish_result_path.read_text(encoding="utf-8"))
    assert publish_result["status"] == "passed"
    assert publish_result["effective_verification"]["status"] == "passed"
    assert all(publish_result["effective_verification"]["identity"].values())
    assert "JOBFIT_KNOWLEDGE_VERSION=2026.08.1" in env_path.read_text(
        encoding="utf-8"
    )
    manifest_path = Path(publish_result["manifest"])
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert secret not in manifest_text
    manifest = json.loads(manifest_text)
    rollback_entry = Path(manifest["rollback_copy"])
    assert rollback_entry.is_file()
    assert manifest["status"] == "published"
    assert manifest["post_database_hash"]
    assert manifest["post_env_hash"]

    post_env = env_path.read_bytes()
    env_path.write_bytes(post_env + b"# changed after release\n")
    rejected_result_path = tmp_path / "rollback-rejected.json"
    rejected = subprocess.run(
        [
            sys.executable,
            str(rollback_entry),
            "--manifest",
            str(manifest_path),
            "--result",
            str(rejected_result_path),
        ],
        cwd=workspace,
        env=_subprocess_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert rejected.returncode == 1
    rejected_payload = json.loads(rejected_result_path.read_text(encoding="utf-8"))
    assert rejected_payload["status"] == "failed"
    assert "Current .env differs" in rejected_payload["failure"]

    env_path.write_bytes(post_env)
    rollback_result_path = tmp_path / "rollback-result.json"
    rolled_back = subprocess.run(
        [
            sys.executable,
            str(rollback_entry),
            "--manifest",
            str(manifest_path),
            "--result",
            str(rollback_result_path),
        ],
        cwd=workspace,
        env=_subprocess_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert rolled_back.returncode == 0, rolled_back.stdout + rolled_back.stderr
    rollback_result = json.loads(rollback_result_path.read_text(encoding="utf-8"))
    assert rollback_result["status"] == "passed"
    assert rollback_result["effective_version"] == "2026.07.1"
    assert "JOBFIT_KNOWLEDGE_VERSION=2026.07.1" in env_path.read_text(
        encoding="utf-8"
    )
    restored = KnowledgeDatabase(live)
    try:
        repository = SqliteKnowledgeRepository(
            restored,
            search_mode=KnowledgeSearchMode.AUTO,
        )
        assert repository.get_version("kbv-2026-08-1") is None
    finally:
        restored.dispose()


@pytest.mark.parametrize(
    ("failure_point", "live_exists", "env_exists"),
    [
        pytest.param("post_replace_quick_check", False, False, id="quick-check"),
        pytest.param("post_replace_hash", True, True, id="hash"),
    ],
)
def test_publish_compensates_when_atomic_replace_fails_after_live_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
    live_exists: bool,
    env_exists: bool,
) -> None:
    state = _prepare_pre_release_runtime(
        tmp_path,
        monkeypatch,
        live_exists=live_exists,
        env_exists=env_exists,
    )
    original_replace = runtime_publisher.atomic_replace_database
    replacement_calls = 0

    def mutate_then_fail(candidate: Path, live: Path) -> str:
        nonlocal replacement_calls
        replacement_calls += 1
        if replacement_calls == 1:
            os.replace(candidate, live)
            raise KnowledgeReleaseError(f"Injected {failure_point} failure.")
        return original_replace(candidate, live)

    monkeypatch.setattr(
        runtime_publisher,
        "atomic_replace_database",
        mutate_then_fail,
    )

    result = _run_publication(state)

    _assert_runtime_was_compensated(state, result)


def test_publish_preserves_runtime_when_atomic_replace_fails_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _prepare_pre_release_runtime(tmp_path, monkeypatch)

    def fail_before_mutation(candidate: Path, live: Path) -> str:
        raise KnowledgeReleaseError("Injected pre-mutation replacement failure.")

    monkeypatch.setattr(
        runtime_publisher,
        "atomic_replace_database",
        fail_before_mutation,
    )

    result = _run_publication(state)

    live = Path(state["live"])
    env_path = Path(state["env_path"])
    assert result["status"] == "failed"
    assert result["compensated"] is False
    assert sha256_file(live) == state["database_hash"]
    assert env_path.read_bytes() == state["env_bytes"]
    backup_dir = Path(str(result["backup_dir"]))
    manifest = json.loads(
        (backup_dir / "publication-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "failed"
    assert manifest["compensated"] is False
    assert Path(str(result["candidate_database"])).is_file()


def test_publish_compensates_when_runtime_env_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _prepare_pre_release_runtime(tmp_path, monkeypatch)
    env_path = Path(state["env_path"])
    original_write = runtime_publisher.atomic_write_text
    env_write_failed = False

    def fail_target_env_write(path: Path, content: str) -> str:
        nonlocal env_write_failed
        if Path(path) == env_path and not env_write_failed:
            env_write_failed = True
            raise OSError("Injected target .env write failure.")
        return original_write(path, content)

    monkeypatch.setattr(runtime_publisher, "atomic_write_text", fail_target_env_write)

    result = _run_publication(state)

    _assert_runtime_was_compensated(state, result)


@pytest.mark.parametrize(
    "failure_point",
    [
        "effective_verification",
        "health",
        "manifest_write",
        "result_write",
    ],
)
def test_publish_compensates_for_each_remaining_precommit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    state = _prepare_pre_release_runtime(tmp_path, monkeypatch)

    if failure_point == "effective_verification":
        original_verifier = runtime_publisher._run_verifier

        def fail_effective_verification(**kwargs: object) -> dict[str, object]:
            if kwargs["use_effective_config"] is True:
                raise runtime_publisher.PublicationError(
                    "Injected effective verification failure."
                )
            return original_verifier(**kwargs)

        monkeypatch.setattr(runtime_publisher, "_run_verifier", fail_effective_verification)
    elif failure_point == "health":

        def fail_health(**kwargs: object) -> dict[str, object]:
            raise runtime_publisher.PublicationError("Injected health failure.")

        monkeypatch.setattr(runtime_publisher, "_streamlit_health_check", fail_health)
    else:
        original_write_json = runtime_publisher._write_json
        injected = False

        def fail_required_json_write(
            path: Path,
            payload: dict[str, object],
        ) -> None:
            nonlocal injected
            is_target = (
                failure_point == "manifest_write"
                and Path(path).name == "publication-manifest.json"
                and payload.get("status") == "published"
            ) or (
                failure_point == "result_write"
                and Path(path).name == "publication-result.json"
                and payload.get("status") == "passed"
            )
            if is_target and not injected:
                injected = True
                raise OSError(f"Injected {failure_point} failure.")
            original_write_json(path, payload)

        monkeypatch.setattr(runtime_publisher, "_write_json", fail_required_json_write)

    result = _run_publication(
        state,
        require_health=failure_point == "health",
    )

    _assert_runtime_was_compensated(state, result)
