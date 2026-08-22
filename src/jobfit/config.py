"""Environment-backed settings for JobFit Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Self

from pydantic import (
    AnyHttpUrl,
    Field,
    SecretStr,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from jobfit.errors import ConfigurationError, ErrorCode
from jobfit.models.knowledge import KnowledgeSearchMode

RuntimeMode = Literal["provider", "mock"]


class Settings(BaseSettings):
    """Validated application settings loaded from JOBFIT-prefixed variables."""

    model_config = SettingsConfigDict(
        env_prefix="JOBFIT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"

    llm_provider: Literal["openai", "mock"] = "openai"
    llm_model: str = ""
    llm_api_key: SecretStr | None = None
    llm_base_url: AnyHttpUrl | None = None
    llm_timeout_seconds: int = Field(default=60, ge=1, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=2)

    max_upload_mb: int = Field(default=10, ge=1, le=10)
    max_resume_chars: int = Field(default=50_000, ge=1, le=50_000)
    max_jd_chars: int = Field(default=30_000, ge=1, le=30_000)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    demo_mode: bool = False

    knowledge_enabled: bool = True
    knowledge_version: str = Field(
        default="2026.08.1",
        pattern=r"^\d{4}\.\d{2}\.\d+$",
    )
    knowledge_db_path: Path | None = None
    knowledge_search_mode: KnowledgeSearchMode = KnowledgeSearchMode.AUTO
    knowledge_requirement_limit: int = Field(default=12, ge=1, le=20)
    knowledge_prompt_char_limit: int = Field(default=8_000, ge=1_000, le=20_000)
    knowledge_retrieval_strategy_version: str = Field(
        default="1.0",
        pattern=r"^\d+\.\d+$",
    )
    analysis_db_path: Path | None = None

    @field_validator("llm_model", mode="before")
    @classmethod
    def normalize_model_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("llm_base_url", mode="before")
    @classmethod
    def empty_base_url_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("knowledge_db_path", mode="before")
    @classmethod
    def empty_knowledge_db_path_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("analysis_db_path", mode="before")
    @classmethod
    def empty_analysis_db_path_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "knowledge_version",
        "knowledge_retrieval_strategy_version",
        mode="before",
    )
    @classmethod
    def strip_knowledge_versions(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @classmethod
    def load(cls, **overrides: Any) -> Self:
        """Load settings from the environment with optional explicit overrides."""
        return cls(**overrides)

    def validate_runtime(self, mode: RuntimeMode) -> None:
        """Validate credentials only when a real provider will be called."""
        if mode == "mock":
            return

        if self.llm_provider == "mock":
            raise ConfigurationError(
                code=ErrorCode.LLM_PROVIDER_UNSUPPORTED,
                user_message="生产分析模式不能使用 Mock 模型供应商。",
                recoverable=True,
            )

        if not self.llm_model:
            raise ConfigurationError(
                code=ErrorCode.CONFIG_INVALID,
                user_message="生产分析模式缺少 JOBFIT_LLM_MODEL 配置。",
                recoverable=True,
            )

        secret = self.llm_api_key.get_secret_value().strip() if self.llm_api_key else ""
        if not secret:
            raise ConfigurationError(
                code=ErrorCode.LLM_CREDENTIALS_MISSING,
                user_message="生产分析模式缺少 JOBFIT_LLM_API_KEY 配置。",
                recoverable=True,
            )
