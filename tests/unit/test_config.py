"""Tests for environment-backed project configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobfit.config import Settings
from jobfit.errors import ConfigurationError, ErrorCode


@pytest.fixture(autouse=True)
def clear_jobfit_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep configuration tests independent from the developer environment."""
    for name in (
        "JOBFIT_APP_ENV",
        "JOBFIT_LLM_PROVIDER",
        "JOBFIT_LLM_MODEL",
        "JOBFIT_LLM_API_KEY",
        "JOBFIT_LLM_BASE_URL",
        "JOBFIT_LLM_TIMEOUT_SECONDS",
        "JOBFIT_LLM_MAX_RETRIES",
        "JOBFIT_MAX_UPLOAD_MB",
        "JOBFIT_MAX_RESUME_CHARS",
        "JOBFIT_MAX_JD_CHARS",
        "JOBFIT_LOG_LEVEL",
        "JOBFIT_DEMO_MODE",
        "JOBFIT_KNOWLEDGE_ENABLED",
        "JOBFIT_KNOWLEDGE_VERSION",
        "JOBFIT_KNOWLEDGE_DB_PATH",
        "JOBFIT_KNOWLEDGE_SEARCH_MODE",
        "JOBFIT_KNOWLEDGE_REQUIREMENT_LIMIT",
        "JOBFIT_KNOWLEDGE_PROMPT_CHAR_LIMIT",
        "JOBFIT_KNOWLEDGE_RETRIEVAL_STRATEGY_VERSION",
        "JOBFIT_ANALYSIS_DB_PATH",
    ):
        monkeypatch.delenv(name, raising=False)


def test_settings_read_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBFIT_APP_ENV", "test")
    monkeypatch.setenv("JOBFIT_LLM_PROVIDER", "mock")
    monkeypatch.setenv("JOBFIT_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("JOBFIT_MAX_UPLOAD_MB", "8")
    monkeypatch.setenv("JOBFIT_MAX_RESUME_CHARS", "42000")
    monkeypatch.setenv("JOBFIT_MAX_JD_CHARS", "25000")
    monkeypatch.setenv("JOBFIT_DEMO_MODE", "true")

    settings = Settings.load(_env_file=None)

    assert settings.app_env == "test"
    assert settings.llm_provider == "mock"
    assert settings.log_level == "DEBUG"
    assert settings.max_upload_mb == 8
    assert settings.max_resume_chars == 42_000
    assert settings.max_jd_chars == 25_000
    assert settings.demo_mode is True


def test_settings_have_architecture_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.max_upload_mb == 10
    assert settings.max_resume_chars == 50_000
    assert settings.max_jd_chars == 30_000
    assert settings.llm_timeout_seconds == 60
    assert settings.llm_max_retries == 2
    assert settings.log_level == "INFO"
    assert settings.knowledge_enabled is True
    assert settings.knowledge_version == "2026.08.1"
    assert settings.knowledge_search_mode.value == "auto"
    assert settings.knowledge_db_path is None
    assert settings.knowledge_requirement_limit == 12
    assert settings.knowledge_prompt_char_limit == 8_000
    assert settings.knowledge_retrieval_strategy_version == "1.0"
    assert settings.analysis_db_path is None


def test_settings_read_analysis_database_path_without_io(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "analysis.sqlite3"
    monkeypatch.setenv("JOBFIT_ANALYSIS_DB_PATH", str(database_path))

    settings = Settings.load(_env_file=None)

    assert settings.analysis_db_path == database_path
    assert not database_path.exists()


def test_settings_read_knowledge_environment_without_io(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "knowledge.sqlite3"
    monkeypatch.setenv("JOBFIT_KNOWLEDGE_ENABLED", "false")
    monkeypatch.setenv("JOBFIT_KNOWLEDGE_VERSION", "2026.08.2")
    monkeypatch.setenv("JOBFIT_KNOWLEDGE_DB_PATH", str(database_path))
    monkeypatch.setenv("JOBFIT_KNOWLEDGE_SEARCH_MODE", "keyword")
    monkeypatch.setenv("JOBFIT_KNOWLEDGE_REQUIREMENT_LIMIT", "8")
    monkeypatch.setenv("JOBFIT_KNOWLEDGE_PROMPT_CHAR_LIMIT", "6000")
    monkeypatch.setenv(
        "JOBFIT_KNOWLEDGE_RETRIEVAL_STRATEGY_VERSION",
        "1.1",
    )

    settings = Settings.load(_env_file=None)

    assert settings.knowledge_enabled is False
    assert settings.knowledge_version == "2026.08.2"
    assert settings.knowledge_db_path == database_path
    assert settings.knowledge_search_mode.value == "keyword"
    assert settings.knowledge_requirement_limit == 8
    assert settings.knowledge_prompt_char_limit == 6_000
    assert settings.knowledge_retrieval_strategy_version == "1.1"
    assert not database_path.exists()


def test_empty_knowledge_database_path_is_none() -> None:
    settings = Settings(
        knowledge_db_path=" ",
        _env_file=None,
    )

    assert settings.knowledge_db_path is None


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("knowledge_version", ""),
        ("knowledge_version", "2026-7-1"),
        ("knowledge_search_mode", "disabled"),
        ("knowledge_search_mode", "semantic"),
        ("knowledge_requirement_limit", 0),
        ("knowledge_requirement_limit", 21),
        ("knowledge_prompt_char_limit", 999),
        ("knowledge_prompt_char_limit", 20_001),
        ("knowledge_retrieval_strategy_version", ""),
    ],
)
def test_settings_reject_invalid_knowledge_configuration(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field_name: invalid_value}, _env_file=None)


def test_provider_mode_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBFIT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("JOBFIT_LLM_MODEL", "test-model")
    monkeypatch.delenv("JOBFIT_LLM_API_KEY", raising=False)
    settings = Settings(_env_file=None)

    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_runtime("provider")

    assert exc_info.value.code is ErrorCode.LLM_CREDENTIALS_MISSING
    assert exc_info.value.recoverable is True


def test_provider_mode_requires_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBFIT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("JOBFIT_LLM_API_KEY", "test-only-secret")
    monkeypatch.delenv("JOBFIT_LLM_MODEL", raising=False)
    settings = Settings(_env_file=None)

    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_runtime("provider")

    assert exc_info.value.code is ErrorCode.CONFIG_INVALID


def test_mock_mode_does_not_require_api_key() -> None:
    settings = Settings(llm_provider="mock", _env_file=None)

    settings.validate_runtime("mock")


def test_api_key_is_hidden_from_settings_repr() -> None:
    settings = Settings(llm_api_key="test-only-secret", _env_file=None)

    assert "test-only-secret" not in repr(settings)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("max_upload_mb", 11),
        ("max_resume_chars", 50_001),
        ("max_jd_chars", 30_001),
        ("llm_timeout_seconds", 0),
        ("llm_max_retries", 3),
    ],
)
def test_settings_reject_values_above_architecture_limits(
    field_name: str,
    invalid_value: int,
) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field_name: invalid_value}, _env_file=None)
