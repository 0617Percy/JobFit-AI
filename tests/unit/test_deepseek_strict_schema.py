"""DeepSeek strict-schema compatibility for all P01-P08 output contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from jobfit.demo_v2 import DEMO_JD_TEXT, DEMO_RESUME_TEXT, _build_scripts
from jobfit.errors import LLMError
from jobfit.llm.deepseek_strict import build_deepseek_strict_contract
from jobfit.llm.exceptions import ProviderResponseError, StrictTransportError
from jobfit.llm.retry import RetryExecutor
from jobfit.parsers.text import TextDocumentParser
from jobfit.semantic.v2.advisory_contracts import P06BuildOutput, P06CandidateOutput
from jobfit.semantic.v2.executor import SemanticLLMTask
from jobfit.semantic.v2.stage_contracts import PROMPT_OUTPUT_MODELS

_TASKS = {
    "P01": SemanticLLMTask.P01_RESUME_PARSER,
    "P02": SemanticLLMTask.P02_JD_PARSER,
    "P03": SemanticLLMTask.P03_REQUIREMENT_CLASSIFIER,
    "P04": SemanticLLMTask.P04_EVIDENCE_NORMALIZER,
    "P05": SemanticLLMTask.P05_SEMANTIC_MATCHER,
    "P06": SemanticLLMTask.P06_ACTIONS,
    "P07": SemanticLLMTask.P07_INTERVIEW,
    "P08": SemanticLLMTask.P08_REPORT,
}
_UNSUPPORTED = {"minLength", "maxLength", "minItems", "maxItems", "default"}


@pytest.mark.parametrize("prompt_id", tuple(PROMPT_OUTPUT_MODELS))
def test_all_p01_p08_provider_schemas_are_deepseek_strict_compatible(
    prompt_id: str,
) -> None:
    model = PROMPT_OUTPUT_MODELS[prompt_id]
    contract = build_deepseek_strict_contract(
        _TASKS[prompt_id], model.model_json_schema()
    )

    assert contract.function_name == f"jobfit_{prompt_id.casefold()}_output"
    _assert_strict_schema(contract.parameters)


@pytest.mark.parametrize("prompt_id", tuple(PROMPT_OUTPUT_MODELS))
def test_all_p01_p08_valid_strict_arguments_reach_canonical_dto_validation(
    prompt_id: str,
) -> None:
    scripts = _demo_scripts()
    task = _TASKS[prompt_id]
    model = PROMPT_OUTPUT_MODELS[prompt_id]
    if prompt_id == "P06":
        # P06 provider transport is mode-specific now; round-trip a synthetic
        # canonical P06ActionOutput through the canonical DTO contract.
        canonical: dict[str, object] = {
            "actions": [
                {
                    "action_id": "action-rewrite",
                    "action_type": "rewrite",
                    "priority": "p0",
                    "related_requirement_ids": ["req-core"],
                    "related_evidence_ids": [],
                    "supported_by_evidence_ids": [],
                    "source_clarification_ids": [],
                    "knowledge_citation_ids": [],
                    "title": "Clarify the existing evidence",
                    "why_it_matters": "The evidence is already grounded.",
                    "recommended_action": "Built a Python API.",
                    "completion_criteria": "The wording stays traceable.",
                    "effort": "low",
                    "time_to_complete": "30 minutes",
                    "timing": "before_apply",
                    "introduced_claims": [],
                }
            ],
            "warnings": [],
        }
    else:
        canonical = json.loads(scripts[task][0])
    schema = model.model_json_schema()
    contract = build_deepseek_strict_contract(task, schema)
    arguments = _encode_transport(canonical, schema, schema)

    decoded = contract.decode_arguments(json.dumps(arguments, ensure_ascii=False))

    assert model.model_validate_json(decoded).model_dump(mode="json") == canonical


def test_p06_mode_provider_schemas_are_deepseek_strict_compatible() -> None:
    for model in (P06CandidateOutput, P06BuildOutput):
        contract = build_deepseek_strict_contract(
            SemanticLLMTask.P06_ACTIONS, model.model_json_schema()
        )
        assert contract.function_name == "jobfit_p06_output"
        _assert_strict_schema(contract.parameters)


def test_p06_build_strict_contract_excludes_system_owned_fields() -> None:
    contract = build_deepseek_strict_contract(
        SemanticLLMTask.P06_ACTIONS, P06BuildOutput.model_json_schema()
    )
    item_properties = contract.parameters["properties"]["actions"]["items"][
        "properties"
    ]
    for field in (
        "action_id",
        "action_type",
        "related_evidence_ids",
        "supported_by_evidence_ids",
        "source_clarification_ids",
        "future_only",
    ):
        assert field not in item_properties


def test_p06_candidate_and_build_demo_scripts_round_trip_through_strict_contract() -> None:
    scripts = _demo_scripts()
    for index, model in enumerate((P06CandidateOutput, P06BuildOutput)):
        canonical = json.loads(scripts[SemanticLLMTask.P06_ACTIONS][index])
        schema = model.model_json_schema()
        contract = build_deepseek_strict_contract(
            SemanticLLMTask.P06_ACTIONS, schema
        )
        transport = _encode_transport(canonical, schema, schema)

        decoded = contract.decode_arguments(json.dumps(transport, ensure_ascii=False))

        assert model.model_validate_json(decoded).model_dump(mode="json") == canonical


def test_p08_knowledge_off_empty_citations_round_trip_through_strict_contract() -> None:
    model = PROMPT_OUTPUT_MODELS["P08"]
    schema = model.model_json_schema()
    contract = build_deepseek_strict_contract(_TASKS["P08"], schema)
    canonical: dict[str, object] = {
        "job_explanations": [
            {
                "text": f"Explicit role explanation {index + 1}.",
                "knowledge_citation_ids": [],
            }
            for index in range(12)
        ],
        "implicit_explanations": [],
        "application_strategy_notes": ["Follow the frozen recommendation."],
        "boundary_notes": ["Missing evidence does not prove missing ability."],
        "warnings": [],
    }
    transport = _encode_transport(canonical, schema, schema)

    decoded = contract.decode_arguments(json.dumps(transport, ensure_ascii=False))

    assert model.model_validate_json(decoded).model_dump(mode="json") == canonical


def test_optional_string_transport_preserves_absent_and_present_values() -> None:
    model = PROMPT_OUTPUT_MODELS["P02"]
    schema = model.model_json_schema()
    contract = build_deepseek_strict_contract(_TASKS["P02"], schema)
    canonical = json.loads(_demo_scripts()[_TASKS["P02"]][0])
    transport = _encode_transport(canonical, schema, schema)

    assert transport["company"] == []
    absent = json.loads(contract.decode_arguments(json.dumps(transport)))
    assert absent["company"] is None

    transport["company"] = ["Synthetic Company"]
    present = json.loads(contract.decode_arguments(json.dumps(transport)))
    assert present["company"] == "Synthetic Company"


def test_optional_transport_rejects_more_than_one_value() -> None:
    model = PROMPT_OUTPUT_MODELS["P02"]
    schema = model.model_json_schema()
    contract = build_deepseek_strict_contract(_TASKS["P02"], schema)
    canonical = json.loads(_demo_scripts()[_TASKS["P02"]][0])
    transport = _encode_transport(canonical, schema, schema)
    transport["company"] = ["First", "Second"]

    with pytest.raises(StrictTransportError, match="STRICT_ARGUMENTS_INVALID"):
        contract.decode_arguments(json.dumps(transport))


def test_strict_transport_identifies_missing_root_key_without_values() -> None:
    contract, transport = _p07_contract_and_transport()
    transport.pop("warnings")

    with pytest.raises(StrictTransportError) as exc_info:
        contract.decode_arguments(json.dumps(transport))

    assert exc_info.value.code == "STRICT_ARGUMENTS_MISSING_KEY"
    assert exc_info.value.safe_path == "warnings"


def test_strict_transport_identifies_extra_root_key_without_values() -> None:
    contract, transport = _p07_contract_and_transport()
    transport["unexpected"] = "private value must not enter diagnostics"

    with pytest.raises(StrictTransportError) as exc_info:
        contract.decode_arguments(json.dumps(transport))

    assert exc_info.value.code == "STRICT_ARGUMENTS_EXTRA_KEY"
    assert exc_info.value.safe_path == "unexpected"
    assert "private value" not in str(exc_info.value)


def test_strict_transport_identifies_missing_nested_p07_key() -> None:
    contract, transport = _p07_contract_and_transport()
    transport["questions"][0].pop("related_action_ids")

    with pytest.raises(StrictTransportError) as exc_info:
        contract.decode_arguments(json.dumps(transport))

    assert exc_info.value.code == "STRICT_ARGUMENTS_MISSING_KEY"
    assert exc_info.value.safe_path == "questions[0].related_action_ids"


def test_strict_transport_identifies_extra_nested_p07_key() -> None:
    contract, transport = _p07_contract_and_transport()
    transport["questions"][0]["unexpected"] = "private value"

    with pytest.raises(StrictTransportError) as exc_info:
        contract.decode_arguments(json.dumps(transport))

    assert exc_info.value.code == "STRICT_ARGUMENTS_EXTRA_KEY"
    assert exc_info.value.safe_path == "questions[0].unexpected"
    assert "private value" not in str(exc_info.value)


def test_strict_transport_distinguishes_malformed_json_without_content() -> None:
    contract, _ = _p07_contract_and_transport()

    with pytest.raises(StrictTransportError) as exc_info:
        contract.decode_arguments('{"questions": [private content')

    assert exc_info.value.code == "STRICT_ARGUMENTS_JSON_INVALID"
    assert exc_info.value.safe_path == "transport"
    assert "private content" not in str(exc_info.value)


def test_p01_metadata_map_round_trips_without_semantic_sentinels() -> None:
    model = PROMPT_OUTPUT_MODELS["P01"]
    schema = model.model_json_schema()
    contract = build_deepseek_strict_contract(_TASKS["P01"], schema)
    canonical = json.loads(_demo_scripts()[_TASKS["P01"]][0])
    transport = _encode_transport(canonical, schema, schema)

    assert transport["projects"][0]["details"] == [
        {
            "key": "source",
            "value_json": json.dumps(
                canonical["projects"][0]["details"]["source"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
    ]
    decoded = json.loads(contract.decode_arguments(json.dumps(transport)))
    assert decoded["projects"][0]["details"] == canonical["projects"][0]["details"]


def test_provider_schema_rejection_stays_non_retryable_at_transport_layer() -> None:
    calls = 0

    def rejected() -> None:
        nonlocal calls
        calls += 1
        raise ProviderResponseError("STRICT_SCHEMA_PROVIDER_REJECTED")

    with pytest.raises(LLMError) as exc_info:
        RetryExecutor().run(rejected, max_retries=2)

    assert calls == 1
    assert "STRICT_SCHEMA_PROVIDER_REJECTED" not in str(exc_info.value)


def _demo_scripts() -> dict[SemanticLLMTask, list[str]]:
    parser = TextDocumentParser()
    return _build_scripts(
        resume_document=parser.parse_text(DEMO_RESUME_TEXT),
        jd_document=parser.parse_text(DEMO_JD_TEXT),
        resume_version_id="strict-resume-1",
        jd_snapshot_id="strict-jd-1",
    )


def _p07_contract_and_transport() -> tuple[object, dict[str, object]]:
    model = PROMPT_OUTPUT_MODELS["P07"]
    schema = model.model_json_schema()
    contract = build_deepseek_strict_contract(_TASKS["P07"], schema)
    canonical = json.loads(_demo_scripts()[_TASKS["P07"]][0])
    transport = _encode_transport(canonical, schema, schema)
    assert isinstance(transport, dict)
    return contract, transport


def _assert_strict_schema(node: object) -> None:
    if isinstance(node, list):
        for child in node:
            _assert_strict_schema(child)
        return
    if not isinstance(node, Mapping):
        return
    assert not (_UNSUPPORTED & set(node))
    assert node.get("type") != "null"
    if node.get("type") == "object":
        properties = node.get("properties", {})
        assert node.get("additionalProperties") is False
        assert node.get("required") == list(properties)
    for child in node.values():
        _assert_strict_schema(child)


def _encode_transport(
    value: object,
    schema: Mapping[str, object],
    root: Mapping[str, object],
) -> object:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        return _encode_transport(value, _resolve(reference, root), root)
    alternatives = schema.get("anyOf")
    if isinstance(alternatives, list) and any(
        isinstance(item, Mapping) and item.get("type") == "null"
        for item in alternatives
    ):
        if value is None:
            return []
        non_null = [
            item
            for item in alternatives
            if not (isinstance(item, Mapping) and item.get("type") == "null")
        ]
        item_schema = non_null[0] if len(non_null) == 1 else {}
        return [
            _encode_transport(value, item_schema, root)
            if isinstance(item_schema, Mapping)
            else value
        ]
    if (
        schema.get("type") == "object"
        and not schema.get("properties")
        and isinstance(schema.get("additionalProperties"), Mapping)
    ):
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
            key: _encode_transport(child, properties[key], root)
            if isinstance(properties.get(key), Mapping)
            else child
            for key, child in value.items()
        }
    if schema.get("type") == "array":
        assert isinstance(value, list)
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            return [_encode_transport(item, item_schema, root) for item in value]
    return value


def _resolve(reference: str, root: Mapping[str, object]) -> Mapping[str, object]:
    current: object = root
    for part in reference.removeprefix("#/").split("/"):
        assert isinstance(current, Mapping)
        current = current[part]
    assert isinstance(current, Mapping)
    return current
