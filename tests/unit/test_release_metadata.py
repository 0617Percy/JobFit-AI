"""Repository-level v1.1 release metadata and artifact gates."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import jobfit

ROOT = Path(__file__).parents[2]


def test_package_versions_are_consistent_for_v1_1() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == "1.1.0"
    assert jobfit.__version__ == "1.1.0"


def test_git_tracks_no_runtime_database_or_private_input_artifacts() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    tracked = {
        item.decode("utf-8")
        for item in completed.stdout.split(b"\0")
        if item
    }
    forbidden_suffixes = (
        ".sqlite",
        ".sqlite3",
        ".db",
        ".db-wal",
        ".db-shm",
    )
    forbidden_names = {".env"}

    assert not {
        path
        for path in tracked
        if path.endswith(forbidden_suffixes)
        or Path(path).name in forbidden_names
        or path.startswith("reports/")
        or path.startswith("uploads/")
    }
