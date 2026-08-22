"""Offline tests for LLM protocols, providers, retries, and prompt management."""

from __future__ import annotations

import logging
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import Field, SecretStr, ValidationError

from jobfit.config import Settings
from jobfit.errors import ErrorCode, JobFitError
from jobfit.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from jobfit.llm.mock_adapter import MockLLMClient, MockLLMProvider
from jobfit.llm.openai_adapter import OpenAIAdapter
from jobfit.llm.prompt_registry import PromptRegistry
from jobfit.llm.protocol import (
    LLMMessage,
    LLMResponse,
    LLMSettings,
    LLMTask,
    TokenUsage,
)
from jobfit.llm.provider import build_llm_client
from jobfit.llm.structured_runner import StructuredRunner
from jobfit.logging_config import configure_logging
from jobfit.models import JobExtractionDraft, StrictModel


class ExamplePayload(StrictModel):
    name: str = Field(min_length=1)
    count: int = Field(ge=0)


VALID_EXAMPLE_JSON = '{"name":"offline result","count":2}'


@pytest.fixture
def prompt_root() -> Path:
    return Path(__file__).parents[2] / "src" / "jobfit" / "prompts"


@pytest.fixture
def llm_fixture_dir() -> Path:
    return Path(__file__).parents[1] / "fixtures" / "llm_responses"


@pytest.fixture
def call_settings() -> LLMSettings:
    return LLMSettings(
        model="mock-model",
        timeout_seconds=2,
        max_retries=1,
        temperature=0,
        request_id="request-llm-test",
        prompt_version="1.0",
    )


def messages_with_private_content() -> list[LLMMessage]:
    return [
        LLMMessage(role="system", content="Return only JSON."),
        LLMMessage(
            role="user",
            content="Private resume email: candidate@example.com",
        ),
    ]


def test_mock_client_returns_validated_model(
    llm_fixture_dir: Path,
    call_settings: LLMSettings,
) -> None:
    client = MockLLMClient.from_directory(llm_fixture_dir)

    result = client.generate_structured(
        task=LLMTask.EXTRACT_JOB,
        response_model=JobExtractionDraft,
        messages=[],
        settings=call_settings,
    )

    assert isinstance(result, JobExtractionDraft)
    assert result.title == "AI应用开发实习生"


def test_mock_client_rejects_invalid_fixture(
    tmp_path: Path,
    call_settings: LLMSettings,
) -> None:
    (tmp_path / "extract_job.json").write_text(
        '{"unexpected": true}',
        encoding="utf-8",
    )
    client = MockLLMClient.from_directory(tmp_path)

    with pytest.raises(JobFitError) as exc_info:
        client.generate_structured(
            task=LLMTask.EXTRACT_JOB,
            response_model=JobExtractionDraft,
            messages=[],
            settings=call_settings.model_copy(update={"max_retries": 0}),
        )

    assert exc_info.value.code is ErrorCode.LLM_SCHEMA_INVALID


def test_mock_client_reports_missing_fixture(
    tmp_path: Path,
    call_settings: LLMSettings,
) -> None:
    client = MockLLMClient.from_directory(tmp_path)

    with pytest.raises(JobFitError) as exc_info:
        client.generate_structured(
            task=LLMTask.EXTRACT_JOB,
            response_model=JobExtractionDraft,
            messages=[],
            settings=call_settings,
        )

    assert exc_info.value.code is ErrorCode.MOCK_FIXTURE_MISSING


def test_mock_provider_can_simulate_error(call_settings: LLMSettings) -> None:
    provider = MockLLMProvider({LLMTask.EXTRACT_JOB: [ProviderAuthenticationError("invalid key")]})

    with pytest.raises(JobFitError) as exc_info:
        StructuredRunner(provider).run(
            task=LLMTask.EXTRACT_JOB,
            response_model=ExamplePayload,
            messages=[],
            settings=call_settings,
        )

    assert exc_info.value.code is ErrorCode.LLM_AUTH_FAILED
    assert provider.call_count == 1


def test_provider_factory_switches_to_mock(
    llm_fixture_dir: Path,
) -> None:
    settings = Settings(app_env="test", llm_provider="mock")

    client = build_llm_client(
        settings,
        mock_fixture_dir=llm_fixture_dir,
    )

    assert isinstance(client, MockLLMClient)


def test_provider_factory_switches_to_openai_with_injected_client() -> None:
    fake_client = FakeOpenAIClient([ExamplePayload(name="ok", count=1)])
    settings = Settings(
        app_env="test",
        llm_provider="openai",
        llm_model="configured-model",
        llm_api_key=SecretStr("test-placeholder-key"),
    )

    client = build_llm_client(settings, openai_client=fake_client)

    assert isinstance(client, OpenAIAdapter)


def test_runner_returns_validated_schema(call_settings: LLMSettings) -> None:
    provider = MockLLMProvider({LLMTask.EXTRACT_JOB: [VALID_EXAMPLE_JSON]})

    result = StructuredRunner(provider).run(
        task=LLMTask.EXTRACT_JOB,
        response_model=ExamplePayload,
        messages=[],
        settings=call_settings,
    )

    assert result == ExamplePayload(name="offline result", count=2)


def test_runner_repairs_invalid_json_once(
    call_settings: LLMSettings,
) -> None:
    provider = MockLLMProvider(
        {
            LLMTask.EXTRACT_JOB: [
                '{"name":',
                VALID_EXAMPLE_JSON,
            ]
        }
    )

    result = StructuredRunner(provider).run(
        task=LLMTask.EXTRACT_JOB,
        response_model=ExamplePayload,
        messages=[],
        settings=call_settings,
    )

    assert result.name == "offline result"
    assert provider.call_count == 2
    assert "invalid_output" in provider.calls[1].messages[-1].content


def test_runner_repairs_schema_error_once(
    call_settings: LLMSettings,
) -> None:
    provider = MockLLMProvider(
        {
            LLMTask.EXTRACT_JOB: [
                '{"name":"missing count"}',
                VALID_EXAMPLE_JSON,
            ]
        }
    )

    result = StructuredRunner(provider).run(
        task=LLMTask.EXTRACT_JOB,
        response_model=ExamplePayload,
        messages=[],
        settings=call_settings,
    )

    assert result.count == 2
    repair_message = provider.calls[1].messages[-1].content
    assert '"type":"missing"' in repair_message
    assert "Traceback" not in repair_message


def test_runner_stops_after_repair_and_one_full_retry(
    call_settings: LLMSettings,
) -> None:
    provider = MockLLMProvider(
        {
            LLMTask.EXTRACT_JOB: [
                '{"wrong":1}',
                '{"wrong":2}',
                '{"wrong":3}',
            ]
        }
    )

    with pytest.raises(JobFitError) as exc_info:
        StructuredRunner(provider).run(
            task=LLMTask.EXTRACT_JOB,
            response_model=ExamplePayload,
            messages=[],
            settings=call_settings.model_copy(update={"max_retries": 0}),
        )

    assert exc_info.value.code is ErrorCode.LLM_SCHEMA_INVALID
    assert provider.call_count == 3


@pytest.mark.parametrize(
    "error",
    [
        ProviderTimeoutError("timeout"),
        ProviderRateLimitError("rate limited"),
    ],
)
def test_retryable_provider_errors_are_retried(
    error: Exception,
    call_settings: LLMSettings,
) -> None:
    provider = MockLLMProvider({LLMTask.EXTRACT_JOB: [error, VALID_EXAMPLE_JSON]})

    result = StructuredRunner(provider).run(
        task=LLMTask.EXTRACT_JOB,
        response_model=ExamplePayload,
        messages=[],
        settings=call_settings,
    )

    assert result.name == "offline result"
    assert provider.call_count == 2


def test_retry_exhaustion_returns_safe_transient_error(
    call_settings: LLMSettings,
) -> None:
    provider = MockLLMProvider(
        {
            LLMTask.EXTRACT_JOB: [
                ProviderTimeoutError("private timeout detail"),
                ProviderTimeoutError("private timeout detail"),
            ]
        }
    )

    with pytest.raises(JobFitError) as exc_info:
        StructuredRunner(provider).run(
            task=LLMTask.EXTRACT_JOB,
            response_model=ExamplePayload,
            messages=[],
            settings=call_settings,
        )

    assert exc_info.value.code is ErrorCode.LLM_TRANSIENT_ERROR
    assert "private timeout detail" not in str(exc_info.value)
    assert provider.call_count == 2


def test_prompt_registry_loads_all_versioned_prompts(prompt_root: Path) -> None:
    registry = PromptRegistry(prompt_root)

    for task in LLMTask:
        template = registry.load(task.value, "1.0")
        combined = f"{template.system_text}\n{template.user_template}"
        assert template.task_name == task.value
        assert template.version == "1.0"
        assert "输入边界" in combined
        assert "不得新增" in combined
        assert "start_char" in combined
        assert "end_char" in combined
        assert "unknown" in combined
        assert "仅输出 JSON" in combined


def test_prompt_registry_rejects_unknown_version(prompt_root: Path) -> None:
    with pytest.raises(JobFitError) as exc_info:
        PromptRegistry(prompt_root).load("extract_job", "9.9")

    assert exc_info.value.code is ErrorCode.PROMPT_NOT_FOUND


def test_prompt_registry_rejects_header_mismatch(tmp_path: Path) -> None:
    (tmp_path / "extract_job.md").write_text(
        "\n".join(
            [
                "---",
                "task: extract_resume",
                'version: "1.0"',
                "---",
                "## System",
                "system",
                "## User",
                "user",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(JobFitError) as exc_info:
        PromptRegistry(tmp_path).load("extract_job", "1.0")

    assert exc_info.value.code is ErrorCode.PROMPT_NOT_FOUND


class FakeResponses:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(
            output_parsed=outcome,
            output_text=(
                outcome.model_dump_json() if isinstance(outcome, StrictModel) else str(outcome)
            ),
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=4,
                total_tokens=14,
            ),
        )


class FakeOpenAIClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.responses = FakeResponses(outcomes)


def test_openai_adapter_uses_structured_parse_without_network() -> None:
    fake_client = FakeOpenAIClient([ExamplePayload(name="parsed", count=3)])
    adapter = OpenAIAdapter(fake_client)
    settings = LLMSettings(
        model="configured-model",
        timeout_seconds=12,
        max_retries=0,
        temperature=0,
    )

    result = adapter.generate_structured(
        task=LLMTask.EXTRACT_JOB,
        response_model=ExamplePayload,
        messages=messages_with_private_content(),
        settings=settings,
    )

    assert result == ExamplePayload(name="parsed", count=3)
    call = fake_client.responses.calls[0]
    assert call["model"] == "configured-model"
    assert call["text_format"] is ExamplePayload
    assert call["timeout"] == 12
    assert call["store"] is False


def test_openai_adapter_retries_timeout() -> None:
    fake_client = FakeOpenAIClient(
        [
            ProviderTimeoutError("timeout"),
            ExamplePayload(name="parsed", count=3),
        ]
    )
    adapter = OpenAIAdapter(fake_client)

    result = adapter.generate_structured(
        task=LLMTask.EXTRACT_JOB,
        response_model=ExamplePayload,
        messages=[],
        settings=LLMSettings(
            model="configured-model",
            timeout_seconds=2,
            max_retries=1,
        ),
    )

    assert result.name == "parsed"
    assert len(fake_client.responses.calls) == 2


def test_openai_adapter_repairs_schema_once() -> None:
    fake_client = FakeOpenAIClient(
        [
            {"name": "missing count"},
            ExamplePayload(name="repaired", count=4),
        ]
    )
    adapter = OpenAIAdapter(fake_client)

    result = adapter.generate_structured(
        task=LLMTask.EXTRACT_JOB,
        response_model=ExamplePayload,
        messages=[LLMMessage(role="user", content="source-bound input")],
        settings=LLMSettings(
            model="configured-model",
            timeout_seconds=2,
            max_retries=0,
        ),
    )

    assert result == ExamplePayload(name="repaired", count=4)
    assert len(fake_client.responses.calls) == 2
    repair_input = fake_client.responses.calls[1]["input"]
    assert "invalid_output" in repair_input[-1]["content"]


def test_openai_adapter_does_not_retry_authentication_error() -> None:
    fake_client = FakeOpenAIClient([ProviderAuthenticationError("do not expose key detail")])
    adapter = OpenAIAdapter(fake_client)

    with pytest.raises(JobFitError) as exc_info:
        adapter.generate_structured(
            task=LLMTask.EXTRACT_JOB,
            response_model=ExamplePayload,
            messages=[],
            settings=LLMSettings(
                model="configured-model",
                timeout_seconds=2,
                max_retries=2,
            ),
        )

    assert exc_info.value.code is ErrorCode.LLM_AUTH_FAILED
    assert len(fake_client.responses.calls) == 1


def test_openai_adapter_does_not_retry_sdk_schema_error() -> None:
    try:
        ExamplePayload.model_validate({"name": "missing count"})
    except ValidationError as validation_error:
        sdk_schema_error = validation_error
    fake_client = FakeOpenAIClient([sdk_schema_error])
    adapter = OpenAIAdapter(fake_client)

    with pytest.raises(JobFitError) as exc_info:
        adapter.generate_structured(
            task=LLMTask.EXTRACT_JOB,
            response_model=ExamplePayload,
            messages=[],
            settings=LLMSettings(
                model="configured-model",
                timeout_seconds=2,
                max_retries=2,
            ),
        )

    assert exc_info.value.code is ErrorCode.LLM_SCHEMA_INVALID
    assert len(fake_client.responses.calls) == 1


def test_call_logging_contains_metrics_but_not_content(
    call_settings: LLMSettings,
) -> None:
    stream = StringIO()
    configure_logging(
        "INFO",
        handlers=[logging.StreamHandler(stream)],
    )
    provider = MockLLMProvider(
        {
            LLMTask.EXTRACT_JOB: [
                LLMResponse(
                    content=VALID_EXAMPLE_JSON,
                    provider="mock",
                    model="mock-model",
                    usage=TokenUsage(
                        input_tokens=10,
                        output_tokens=4,
                        total_tokens=14,
                    ),
                )
            ]
        }
    )

    StructuredRunner(provider).run(
        task=LLMTask.EXTRACT_JOB,
        response_model=ExamplePayload,
        messages=messages_with_private_content(),
        settings=call_settings,
    )
    logged = stream.getvalue()

    assert "request_id=request-llm-test" in logged
    assert "provider=mock" in logged
    assert "model=mock-model" in logged
    assert "prompt_version=1.0" in logged
    assert "input_char_count=" in logged
    assert "output_char_count=" in logged
    assert "elapsed_ms=" in logged
    assert "token_usage=14" in logged
    assert "candidate@example.com" not in logged
    assert VALID_EXAMPLE_JSON not in logged
