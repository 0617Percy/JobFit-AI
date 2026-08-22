"""Cross-platform knowledge database path resolution."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from jobfit.errors import ConfigurationError, ErrorCode


def path_module():
    return importlib.import_module("jobfit.knowledge.paths")


def test_windows_default_uses_local_app_data_without_creating_it(tmp_path) -> None:
    expected = tmp_path / "JobFitAgent" / "knowledge.sqlite3"

    result = path_module().resolve_knowledge_db_path(
        platform_name="win32",
        environ={"LOCALAPPDATA": str(tmp_path)},
        home=tmp_path / "home",
        cwd=tmp_path,
    )

    assert result == expected.resolve()
    assert not expected.exists()


def test_windows_falls_back_to_home_local_data(tmp_path) -> None:
    result = path_module().resolve_knowledge_db_path(
        platform_name="win32",
        environ={},
        home=tmp_path / "home",
        cwd=tmp_path,
    )

    assert result == (
        tmp_path / "home" / "AppData" / "Local" / "JobFitAgent" / "knowledge.sqlite3"
    ).resolve()


def test_macos_default_uses_application_support(tmp_path) -> None:
    result = path_module().resolve_knowledge_db_path(
        platform_name="darwin",
        environ={},
        home=tmp_path,
        cwd=tmp_path,
    )

    assert result == (
        tmp_path / "Library" / "Application Support" / "JobFitAgent"
        / "knowledge.sqlite3"
    ).resolve()


def test_linux_uses_xdg_data_home_when_present(tmp_path) -> None:
    result = path_module().resolve_knowledge_db_path(
        platform_name="linux",
        environ={"XDG_DATA_HOME": str(tmp_path / "xdg")},
        home=tmp_path / "home",
        cwd=tmp_path,
    )

    assert result == (
        tmp_path / "xdg" / "jobfit-agent" / "knowledge.sqlite3"
    ).resolve()


def test_linux_falls_back_to_dot_local_share(tmp_path) -> None:
    result = path_module().resolve_knowledge_db_path(
        platform_name="linux",
        environ={},
        home=tmp_path,
        cwd=tmp_path,
    )

    assert result == (
        tmp_path / ".local" / "share" / "jobfit-agent" / "knowledge.sqlite3"
    ).resolve()


def test_explicit_relative_path_is_resolved_from_explicit_cwd(tmp_path) -> None:
    result = path_module().resolve_knowledge_db_path(
        "data/knowledge.sqlite3",
        platform_name="linux",
        environ={},
        home=tmp_path / "home",
        cwd=tmp_path,
    )

    assert result == (tmp_path / "data" / "knowledge.sqlite3").resolve()
    assert not result.exists()


def test_explicit_absolute_path_is_preserved(tmp_path) -> None:
    expected = (tmp_path / "custom.sqlite3").resolve()

    assert (
        path_module().resolve_knowledge_db_path(expected, cwd=tmp_path)
        == expected
    )


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_explicit_path_fails_with_safe_configuration_error(value) -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        path_module().resolve_knowledge_db_path(value)

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_CONFIG_INVALID
    assert "C:\\" not in exc_info.value.user_message
    assert "/" not in exc_info.value.user_message


def test_unknown_platform_uses_linux_compatible_fallback(tmp_path) -> None:
    result = path_module().resolve_knowledge_db_path(
        platform_name="freebsd",
        environ={},
        home=tmp_path,
        cwd=tmp_path,
    )

    assert result == (
        tmp_path / ".local" / "share" / "jobfit-agent" / "knowledge.sqlite3"
    ).resolve()


def test_path_api_returns_path_and_performs_no_io(tmp_path) -> None:
    result = path_module().resolve_knowledge_db_path(
        tmp_path / "missing" / "knowledge.sqlite3",
    )

    assert isinstance(result, Path)
    assert not result.parent.exists()
