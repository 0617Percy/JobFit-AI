"""Real v2 wiring through a fake DeepSeek transport and durable history."""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import SimpleNamespace

import pytest

from jobfit.config import Settings
from jobfit.demo_v2 import DEMO_JD_TEXT, DEMO_RESUME_TEXT, _build_scripts
from jobfit.llm.deepseek_provider import DeepSeekProvider
from jobfit.parsers.text import TextDocumentParser
from jobfit.runtime_v2 import build_deepseek_runtime
from jobfit.scoring.v2 import SeniorityFacts
from jobfit.semantic.v2 import SemanticLLMTask, SemanticPromptError
from jobfit.workflow.v2 import build_analysis_repository


class _FakeCompletions:
    def __init__(self, outcomes: list[str]) -> None:
        self._outcomes = outcomes
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        canonical_content = self._outcomes.pop(0)
        tools = kwargs["tools"]
        assert isinstance(tools, list) and len(tools) == 1
        function = tools[0]["function"]
        arguments = canonical_content
        if canonical_content.startswith("{"):
            arguments = json.dumps(
                _encode_strict_arguments(
                    json.loads(canonical_content),
                    function["parameters"],
                    function["parameters"],
                ),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="message content is not the structured result",
                        reasoning_content="private reasoning must be discarded",
                        tool_calls=[
                            SimpleNamespace(
                                type="function",
                                function=SimpleNamespace(
                                    name=function["name"],
                                    arguments=arguments,
                                ),
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
            model=kwargs["model"],
        )


class _FakeClient:
    def __init__(self, outcomes: list[str]) -> None:
        self.completions = _FakeCompletions(outcomes)
        self.chat = SimpleNamespace(completions=self.completions)
        self.models = SimpleNamespace(list=lambda: SimpleNamespace(data=[]))


def test_deepseek_runtime_runs_real_p01_to_p08_and_never_persists_secret(tmp_path) -> None:
    parser = TextDocumentParser()
    resume = parser.parse_text(DEMO_RESUME_TEXT)
    jd = parser.parse_text(DEMO_JD_TEXT)
    scripts = _build_scripts(
        resume_document=resume,
        jd_document=jd,
        resume_version_id="deepseek-resume-1",
        jd_snapshot_id="deepseek-jd-1",
    )
    p01_payload = json.loads(scripts[SemanticLLMTask.P01_RESUME_PARSER][0])
    assert all(
        "start_char" not in evidence and "end_char" not in evidence
        for evidence in p01_payload["evidence_items"]
    )
    p02_payload = json.loads(scripts[SemanticLLMTask.P02_JD_PARSER][0])
    assert all(
        "start_char" not in item and "end_char" not in item
        for field_name in (
            "responsibilities",
            "raw_requirements",
            "explicit_constraints",
            "seniority_signals",
        )
        for item in p02_payload[field_name]
    )
    sequence = (
        SemanticLLMTask.P01_RESUME_PARSER,
        SemanticLLMTask.P02_JD_PARSER,
        SemanticLLMTask.P03_REQUIREMENT_CLASSIFIER,
        SemanticLLMTask.P04_EVIDENCE_NORMALIZER,
        SemanticLLMTask.P05_SEMANTIC_MATCHER,
        SemanticLLMTask.P06_ACTIONS,
        SemanticLLMTask.P06_ACTIONS,
        SemanticLLMTask.P07_INTERVIEW,
        SemanticLLMTask.P08_REPORT,
    )
    outcomes = [scripts[task].pop(0) for task in sequence]
    client = _FakeClient(outcomes)
    database_path = tmp_path / "analysis.sqlite3"
    history = build_analysis_repository(
        Settings(_env_file=None, analysis_db_path=database_path),
        repository_root=tmp_path / "synthetic-repository",
    )
    secret = "session-only-deepseek-key"
    runtime = build_deepseek_runtime(
        api_key=secret,
        model="deepseek-v4-flash",
        thinking_enabled=True,
        history=history,
        client=client,
    )

    prepared = runtime.application.prepare_analysis(
        analysis_id="deepseek-analysis-1",
        resume_version_id="deepseek-resume-1",
        jd_snapshot_id="deepseek-jd-1",
        resume_document=resume,
        jd_document=jd,
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )
    completed = runtime.application.finish_analysis(
        runtime.application.begin_analysis(prepared)
    )
    history.dispose()

    assert isinstance(runtime.provider, DeepSeekProvider)
    assert len(client.completions.calls) == 9
    assert all(
        "response_format" not in call
        and "tool_choice" not in call
        and len(call["tools"]) == 1
        and call["tools"][0]["function"]["strict"] is True
        for call in client.completions.calls
    )
    assert [call["tools"][0]["function"]["name"] for call in client.completions.calls] == [
        "jobfit_p01_output",
        "jobfit_p02_output",
        "jobfit_p03_output",
        "jobfit_p04_output",
        "jobfit_p05_output",
        "jobfit_p06_output",
        "jobfit_p06_output",
        "jobfit_p07_output",
        "jobfit_p08_output",
    ]
    p01_evidence = completed.preparation.p01.candidate_evidence[0]
    assert p01_evidence.quote == resume.normalized_text[
        p01_evidence.start_char : p01_evidence.end_char
    ]
    assert completed.advisory_result is not None
    assert completed.advisory_result.report.summary["recommendation"] == "priority"
    assert all(
        record.provider == "deepseek" and record.model == "deepseek-v4-flash"
        for record in (
            *completed.preparation.executions,
            *completed.advisory_result.executions,
        )
    )
    persisted = database_path.read_bytes()
    assert secret.encode() not in persisted
    assert b"private reasoning must be discarded" not in persisted


def test_deepseek_runtime_rejects_deprecated_model_names() -> None:
    client = _FakeClient([])

    for model in ("deepseek-chat", "deepseek-reasoner"):
        try:
            build_deepseek_runtime(
                api_key="session-secret",
                model=model,
                thinking_enabled=False,
                client=client,
            )
        except ValueError as exc:
            assert "supported DeepSeek model" in str(exc)
        else:
            raise AssertionError(f"Deprecated model {model} was accepted.")


@pytest.mark.parametrize(
    ("invalid_content", "expected_code"),
    (
        ("not-json", "STRICT_ARGUMENTS_JSON_INVALID"),
        ('{"unexpected":"shape"}', "STRICT_ARGUMENTS_MISSING_KEY"),
    ),
)
def test_deepseek_runtime_reports_p01_validation_category_without_demo_fallback(
    invalid_content: str,
    expected_code: str,
) -> None:
    parser = TextDocumentParser()
    resume = parser.parse_text(DEMO_RESUME_TEXT)
    jd = parser.parse_text(DEMO_JD_TEXT)
    client = _FakeClient([invalid_content] * 3)
    runtime = build_deepseek_runtime(
        api_key="session-secret",
        model="deepseek-v4-flash",
        thinking_enabled=False,
        client=client,
    )

    with pytest.raises(SemanticPromptError) as exc_info:
        runtime.application.prepare_analysis(
            analysis_id="deepseek-invalid-analysis",
            resume_version_id="deepseek-invalid-resume",
            jd_snapshot_id="deepseek-invalid-jd",
            resume_document=resume,
            jd_document=jd,
            seniority_facts=SeniorityFacts(explicit_entry_scope=True),
        )

    assert exc_info.value.prompt_id == "P01"
    assert exc_info.value.code == expected_code
    assert [attempt.stage for attempt in exc_info.value.attempts] == [
        "normal",
        "targeted_repair",
        "full_retry",
    ]
    assert len(
        {
            json.dumps(call["tools"][0]["function"], sort_keys=True)
            for call in client.completions.calls
        }
    ) == 1
    assert len(client.completions.calls) == 3


def _encode_strict_arguments(
    value: object,
    schema: Mapping[str, object],
    root: Mapping[str, object],
) -> object:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        return _encode_strict_arguments(value, _resolve(reference, root), root)
    description = schema.get("description")
    if description == "Zero items means absent; one item means present.":
        if value is None:
            return []
        items = schema["items"]
        assert isinstance(items, Mapping)
        return [_encode_strict_arguments(value, items, root)]
    if description == "Metadata entries; use an empty array when none exist.":
        assert isinstance(value, Mapping)
        return [
            {
                "key": key,
                "value_json": json.dumps(
                    child, ensure_ascii=False, separators=(",", ":")
                ),
            }
            for key, child in value.items()
        ]
    if schema.get("type") == "object":
        assert isinstance(value, Mapping)
        properties = schema.get("properties", {})
        assert isinstance(properties, Mapping)
        return {
            key: _encode_strict_arguments(child, properties[key], root)
            if isinstance(properties.get(key), Mapping)
            else child
            for key, child in value.items()
        }
    if schema.get("type") == "array":
        assert isinstance(value, list)
        items = schema.get("items")
        if isinstance(items, Mapping):
            return [_encode_strict_arguments(item, items, root) for item in value]
    return value


def _resolve(reference: str, root: Mapping[str, object]) -> Mapping[str, object]:
    current: object = root
    for part in reference.removeprefix("#/").split("/"):
        assert isinstance(current, Mapping)
        current = current[part]
    assert isinstance(current, Mapping)
    return current
