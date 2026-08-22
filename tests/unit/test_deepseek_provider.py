"""DeepSeek BYOK transport contract without real network access."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from types import SimpleNamespace

import pytest

import jobfit.llm.deepseek_provider as deepseek_module
from jobfit.errors import ErrorCode, LLMError
from jobfit.llm.deepseek_provider import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODELS,
    DeepSeekProvider,
)
from jobfit.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from jobfit.llm.protocol import LLMMessage, LLMSettings, LLMTask


class _FakeCompletions:
    def __init__(self, outcomes: Sequence[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeModels:
    def __init__(self, outcome: object | None = None) -> None:
        self.outcome = outcome or SimpleNamespace(data=[])
        self.call_count = 0

    def list(self) -> object:
        self.call_count += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _FakeClient:
    def __init__(
        self,
        outcomes: Sequence[object],
        *,
        models_outcome: object | None = None,
    ) -> None:
        self.completions = _FakeCompletions(outcomes)
        self.chat = SimpleNamespace(completions=self.completions)
        self.models = _FakeModels(models_outcome)


def _response(
    content: str | None,
    *,
    tool_calls: Sequence[object] | None = None,
    reasoning_content: str = "private chain of thought",
    finish_reason: str = "tool_calls",
) -> object:
    message = SimpleNamespace(
        content=content,
        reasoning_content=reasoning_content,
        tool_calls=tool_calls,
    )
    usage = SimpleNamespace(
        prompt_tokens=11,
        completion_tokens=7,
        total_tokens=18,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=usage,
        model="deepseek-v4-flash",
    )


def _tool_call(
    arguments: str | None,
    *,
    name: str = "jobfit_extract_job_output",
) -> object:
    return SimpleNamespace(
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _generate(
    provider: DeepSeekProvider,
    *,
    model: str = "deepseek-v4-flash",
):
    return provider.generate(
        task=LLMTask.EXTRACT_JOB,
        messages=(
            LLMMessage(role="system", content="Follow the governed prompt."),
            LLMMessage(role="user", content="Synthetic input only."),
        ),
        settings=LLMSettings(model=model, timeout_seconds=9, max_retries=0),
        response_schema={
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        },
    )


def test_deepseek_provider_supports_only_frozen_v4_models() -> None:
    assert DEEPSEEK_MODELS == ("deepseek-v4-flash", "deepseek-v4-pro")
    client = _FakeClient([_response('{"result":"ok"}')])

    with pytest.raises(ValueError, match="supported DeepSeek model"):
        _generate(DeepSeekProvider(api_key="session-secret", client=client), model="deepseek-chat")


@pytest.mark.parametrize("model", DEEPSEEK_MODELS)
def test_deepseek_provider_uses_one_strict_tool_and_thinking_off(model: str) -> None:
    client = _FakeClient(
        [_response("ignored message content", tool_calls=[_tool_call('{"result":"ok"}')])]
    )
    provider = DeepSeekProvider(api_key="session-secret", client=client)

    response = _generate(provider, model=model)

    call = client.completions.calls[0]
    assert call["model"] == model
    assert "response_format" not in call
    assert "tool_choice" not in call
    assert len(call["tools"]) == 1
    function = call["tools"][0]["function"]
    assert function["name"] == "jobfit_extract_job_output"
    assert function["strict"] is True
    assert function["parameters"] == {
        "type": "object",
        "properties": {"result": {"type": "string"}},
        "required": ["result"],
        "additionalProperties": False,
    }
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "temperature" not in call
    assert "reasoning_effort" not in call
    assert call["timeout"] == 9
    assert response.content == '{"result":"ok"}'
    assert response.provider == "deepseek"


def test_deepseek_provider_enables_thinking_with_high_effort_without_temperature() -> None:
    client = _FakeClient([_response(None, tool_calls=[_tool_call('{"result":"ok"}')])])
    provider = DeepSeekProvider(
        api_key="session-secret",
        client=client,
        thinking_enabled=True,
    )

    _generate(provider)

    call = client.completions.calls[0]
    assert call["extra_body"] == {"thinking": {"type": "enabled"}}
    assert call["reasoning_effort"] == "high"
    assert "tool_choice" not in call
    assert "temperature" not in call


def test_deepseek_provider_discards_reasoning_content_and_keeps_usage() -> None:
    client = _FakeClient(
        [
            _response(
                "message content must be ignored",
                tool_calls=[_tool_call('{"result":"ok"}')],
                reasoning_content="do not retain",
            )
        ]
    )

    response = _generate(DeepSeekProvider(api_key="session-secret", client=client))

    assert response.content == '{"result":"ok"}'
    assert "reasoning" not in response.model_dump_json().casefold()
    assert "do not retain" not in response.model_dump_json()
    assert "message content must be ignored" not in response.model_dump_json()
    assert response.usage is not None
    assert response.usage.model_dump() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }


def test_deepseek_provider_captures_normalized_finish_reason_without_reasoning() -> None:
    private_reasoning = "private reasoning must not appear"
    client = _FakeClient(
        [
            _response(
                None,
                tool_calls=[_tool_call('{"result":"partial"}')],
                reasoning_content=private_reasoning,
                finish_reason="length",
            )
        ]
    )

    response = _generate(DeepSeekProvider(api_key="session-secret", client=client))

    assert response.finish_reason == "length"
    assert private_reasoning not in response.model_dump_json()


@pytest.mark.parametrize(
    ("tool_calls", "expected_code"),
    (
        (None, "STRICT_TOOL_CALL_MISSING"),
        ([], "STRICT_TOOL_CALL_MISSING"),
        (
            [_tool_call('{"result":"first"}'), _tool_call('{"result":"second"}')],
            "STRICT_TOOL_CALL_MULTIPLE",
        ),
        (
            [_tool_call('{"result":"ok"}', name="unexpected_function")],
            "STRICT_TOOL_NAME_MISMATCH",
        ),
        ([_tool_call(None)], "STRICT_ARGUMENTS_MISSING"),
        ([_tool_call("not-json")], "STRICT_ARGUMENTS_JSON_INVALID"),
    ),
)
def test_deepseek_provider_fails_closed_on_invalid_strict_tool_response(
    tool_calls: Sequence[object] | None,
    expected_code: str,
) -> None:
    client = _FakeClient(
        [_response('{"result":"message fallback forbidden"}', tool_calls=tool_calls)]
    )

    with pytest.raises(ProviderResponseError, match=expected_code) as exc_info:
        _generate(DeepSeekProvider(api_key="session-secret", client=client))

    assert exc_info.value.__cause__ is None
    assert len(client.completions.calls) == 1


def test_deepseek_provider_maps_strict_schema_rejection_to_safe_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SchemaRejected(Exception):
        status_code = 400

    monkeypatch.setattr(deepseek_module, "APIStatusError", _SchemaRejected)
    client = _FakeClient([_SchemaRejected("private provider response")])

    with pytest.raises(
        ProviderResponseError, match="STRICT_SCHEMA_PROVIDER_REJECTED"
    ) as exc_info:
        _generate(DeepSeekProvider(api_key="session-secret", client=client))

    assert "private provider response" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        (ProviderAuthenticationError("secret detail"), ErrorCode.LLM_AUTH_FAILED),
        (ProviderTimeoutError("network detail"), ErrorCode.LLM_TRANSIENT_ERROR),
        (ProviderRateLimitError("quota detail"), ErrorCode.LLM_TRANSIENT_ERROR),
    ),
)
def test_deepseek_connection_check_maps_provider_errors_safely(
    failure: Exception,
    expected_code: ErrorCode,
) -> None:
    client = _FakeClient([], models_outcome=failure)
    provider = DeepSeekProvider(
        api_key="session-secret", client=client, connection_client=client
    )

    with pytest.raises(LLMError) as exc_info:
        provider.check_connection()

    assert exc_info.value.code is expected_code
    assert "secret detail" not in exc_info.value.user_message
    assert "network detail" not in exc_info.value.user_message
    assert "quota detail" not in exc_info.value.user_message
    assert "session-secret" not in exc_info.value.user_message
    assert client.models.call_count == 1


def test_deepseek_connection_check_uses_models_endpoint() -> None:
    client = _FakeClient([])
    provider = DeepSeekProvider(
        api_key="session-secret", client=client, connection_client=client
    )

    provider.check_connection()

    assert client.models.call_count == 1
    assert client.completions.calls == []


def test_connection_check_routes_models_through_standard_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[SimpleNamespace] = []

    class _RecordingModels:
        def __init__(self, parent: SimpleNamespace) -> None:
            self._parent = parent

        def list(self) -> object:
            self._parent.used = True
            return SimpleNamespace(data=[])

    def fake_openai(**kwargs: object) -> SimpleNamespace:
        client = SimpleNamespace(kwargs=kwargs, used=False)
        client.models = _RecordingModels(client)
        clients.append(client)
        return client

    monkeypatch.setattr("jobfit.llm.deepseek_provider.OpenAI", fake_openai)

    provider = DeepSeekProvider(api_key="session-secret")
    provider.check_connection()

    standard = [c for c in clients if c.kwargs["base_url"] == "https://api.deepseek.com"]
    beta = [c for c in clients if c.kwargs["base_url"] == DEEPSEEK_BASE_URL]
    assert len(standard) == 1 and standard[0].used is True
    assert len(beta) == 1 and beta[0].used is False


def test_deepseek_provider_logs_metadata_without_secret_or_reasoning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="jobfit.llm")
    secret = "session-secret-must-not-appear"
    reasoning = "private reasoning must not appear"
    client = _FakeClient(
        [
            _response(
                None,
                tool_calls=[_tool_call('{"result":"ok"}')],
                reasoning_content=reasoning,
            )
        ]
    )

    _generate(DeepSeekProvider(api_key=secret, client=client))

    assert "provider=deepseek" in caplog.text
    assert "model=deepseek-v4-flash" in caplog.text
    assert secret not in caplog.text
    assert reasoning not in caplog.text
    assert '{"result":"ok"}' not in caplog.text


def test_deepseek_provider_creates_openai_clients_with_frozen_base_urls(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def fake_openai(**kwargs: object) -> _FakeClient:
        captured.append(dict(kwargs))
        return _FakeClient([])

    monkeypatch.setattr("jobfit.llm.deepseek_provider.OpenAI", fake_openai)

    DeepSeekProvider(api_key="session-secret")

    assert [item["base_url"] for item in captured] == [
        DEEPSEEK_BASE_URL,
        "https://api.deepseek.com",
    ]
    assert all(item["api_key"] == "session-secret" for item in captured)
    assert all(item["max_retries"] == 0 for item in captured)
    assert DEEPSEEK_BASE_URL == "https://api.deepseek.com/beta"
