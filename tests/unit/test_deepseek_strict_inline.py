"""DeepSeek strict local-ref inliner: unit, fail-closed, and preservation tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

import pytest

from jobfit.demo_v2 import DEMO_JD_TEXT, DEMO_RESUME_TEXT, _build_scripts
from jobfit.llm.deepseek_strict import (
    _inline_local_refs,
    build_deepseek_strict_contract,
)
from jobfit.parsers.text import TextDocumentParser
from jobfit.semantic.v2.executor import SemanticLLMTask
from jobfit.semantic.v2.stage_contracts import PROMPT_OUTPUT_MODELS

_WRAPPER = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Zero items means absent; one item means present.",
}

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


def _count_refs(node: object) -> int:
    total = 0
    if isinstance(node, Mapping):
        if "$ref" in node:
            total += 1
        for value in node.values():
            total += _count_refs(value)
    elif isinstance(node, list):
        for item in node:
            total += _count_refs(item)
    return total


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _schema_with_ref(container: str, reference: str) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"item": {"$ref": reference}},
        "required": ["item"],
        "additionalProperties": False,
        container: {
            "Item": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            }
        },
    }


# ---------------- A. inliner unit tests ----------------


def test_inline_simple_local_ref_defs() -> None:
    schema = _schema_with_ref("$defs", "#/$defs/Item")
    result = _inline_local_refs(schema)
    assert _count_refs(result) == 0
    assert "$defs" not in result and "$def" not in result
    assert result["properties"]["item"] == schema["$defs"]["Item"]
    assert result["required"] == ["item"]


def test_inline_simple_local_ref_def() -> None:
    schema = _schema_with_ref("$def", "#/$def/Item")
    result = _inline_local_refs(schema)
    assert _count_refs(result) == 0
    assert "$defs" not in result and "$def" not in result
    assert result["properties"]["item"] == schema["$def"]["Item"]


def test_inline_nested_refs() -> None:
    schema = {
        "type": "object",
        "properties": {"outer": {"$ref": "#/$defs/Outer"}},
        "required": ["outer"],
        "additionalProperties": False,
        "$defs": {
            "Outer": {
                "type": "object",
                "properties": {"inner": {"$ref": "#/$defs/Inner"}},
                "required": ["inner"],
                "additionalProperties": False,
            },
            "Inner": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        },
    }
    result = _inline_local_refs(schema)
    assert _count_refs(result) == 0
    assert result["properties"]["outer"]["properties"]["inner"] == schema["$defs"]["Inner"]


def test_inline_multiple_refs_to_same_def() -> None:
    schema = {
        "type": "object",
        "properties": {
            "first": {"$ref": "#/$defs/Item"},
            "second": {"$ref": "#/$defs/Item"},
        },
        "required": ["first", "second"],
        "additionalProperties": False,
        "$defs": {
            "Item": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            }
        },
    }
    result = _inline_local_refs(schema)
    assert _count_refs(result) == 0
    assert result["properties"]["first"] == result["properties"]["second"]
    assert result["properties"]["first"] == schema["$defs"]["Item"]


def test_inline_no_ref_input_preserved() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }
    assert _inline_local_refs(schema) == schema


def test_inline_unresolved_ref_fails_closed() -> None:
    schema = _schema_with_ref("$defs", "#/$defs/Missing")
    with pytest.raises(ValueError, match="STRICT_REF_UNRESOLVED"):
        _inline_local_refs(schema)


def test_inline_external_ref_fails_closed() -> None:
    schema = {
        "type": "object",
        "properties": {"item": {"$ref": "https://example.com/schema.json#/$defs/Item"}},
        "required": ["item"],
        "additionalProperties": False,
    }
    with pytest.raises(ValueError, match="STRICT_REF_EXTERNAL"):
        _inline_local_refs(schema)


def test_inline_malformed_pointer_fails_closed() -> None:
    schema = {
        "type": "object",
        "properties": {"item": {"$ref": "#/definitions/Item"}},
        "required": ["item"],
        "additionalProperties": False,
        "$defs": {"Item": {"type": "object"}},
    }
    with pytest.raises(ValueError, match="STRICT_REF_UNSUPPORTED"):
        _inline_local_refs(schema)


def test_inline_cycle_fails_closed() -> None:
    schema = {
        "type": "object",
        "properties": {"node": {"$ref": "#/$defs/Node"}},
        "required": ["node"],
        "additionalProperties": False,
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {"next": {"$ref": "#/$defs/Node"}},
                "required": ["next"],
                "additionalProperties": False,
            }
        },
    }
    with pytest.raises(ValueError, match="STRICT_REF_CYCLE"):
        _inline_local_refs(schema)


def test_inline_ref_with_siblings_fails_closed() -> None:
    schema = {
        "type": "object",
        "properties": {
            "item": {
                "$ref": "#/$defs/Item",
                "description": "sibling annotation",
            }
        },
        "required": ["item"],
        "additionalProperties": False,
        "$defs": {
            "Item": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            }
        },
    }
    with pytest.raises(ValueError, match="STRICT_REF_SIBLINGS_UNSUPPORTED"):
        _inline_local_refs(schema)


# ---------------- B. semantic preservation ----------------


@pytest.fixture
def preservation_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "profile": {"$ref": "#/$defs/Profile"},
            "status": {"$ref": "#/$defs/Status"},
        },
        "required": ["profile", "status"],
        "additionalProperties": False,
        "$defs": {
            "Profile": {
                "type": "object",
                "properties": {"name": _WRAPPER, "level": _WRAPPER},
                "required": ["name", "level"],
                "additionalProperties": False,
            },
            "Status": {"type": "string", "enum": ["active", "inactive"]},
        },
    }


_PRESERVATION_FIXTURES = [
    ({"profile": {"name": ["X"], "level": []}, "status": "active"}, 0),
    ({"profile": {"name": ["X"]}, "status": "active"}, 1),  # missing required
    (
        {
            "profile": {"name": ["X"], "level": [], "extra": ["y"]},
            "status": "active",
        },
        1,  # additional property
    ),
    ({"profile": {"name": "X", "level": []}, "status": "active"}, 1),  # wrong wrapper type
    ({"profile": {"name": ["X"], "level": []}, "status": "bogus"}, 1),  # invalid enum
]


@pytest.mark.parametrize("instance,expected_errors", _PRESERVATION_FIXTURES)
def test_semantic_preservation_original_vs_inlined(
    preservation_schema: dict[str, object],
    instance: object,
    expected_errors: int,
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator
    inlined = _inline_local_refs(preservation_schema)

    def signature(schema: object) -> list[tuple[str, str]]:
        errors = sorted(
            validator(schema).iter_errors(instance),
            key=lambda e: (tuple(str(p) for p in e.absolute_path), e.validator),
        )
        return [(str(list(e.absolute_path)), e.validator) for e in errors]

    original_sig = signature(preservation_schema)
    inlined_sig = signature(inlined)
    assert original_sig == inlined_sig
    assert (len(original_sig) > 0) == (expected_errors > 0)


# ---------------- C. production contract tests ----------------


def test_p01_provider_schema_has_zero_refs_and_expected_hash() -> None:
    contract = build_deepseek_strict_contract(
        _TASKS["P01"], PROMPT_OUTPUT_MODELS["P01"].model_json_schema()
    )
    assert _count_refs(contract.parameters) == 0
    assert "$defs" not in contract.parameters and "$def" not in contract.parameters
    assert _canonical_hash(contract.parameters) == (
        "e3645cd0aa349ac77ee56337f64a78d57ce1c86435ada860261fb7bf3334ed65"
    )


def test_p01_canonical_schema_unchanged() -> None:
    model = PROMPT_OUTPUT_MODELS["P01"]
    schema = model.model_json_schema()
    contract = build_deepseek_strict_contract(_TASKS["P01"], schema)
    assert contract._canonical_schema == schema
    assert "$defs" in contract._canonical_schema


def test_p01_inlined_round_trip_and_canonical_validation() -> None:
    scripts = _demo_scripts()
    task = _TASKS["P01"]
    model = PROMPT_OUTPUT_MODELS["P01"]
    schema = model.model_json_schema()
    canonical = json.loads(scripts[task][0])
    contract = build_deepseek_strict_contract(task, schema)
    assert _count_refs(contract.parameters) == 0

    transport = _encode_transport(canonical, schema, schema)
    decoded = contract.decode_arguments(json.dumps(transport, ensure_ascii=False))

    assert model.model_validate_json(decoded).model_dump(mode="json") == canonical


def test_p01_metadata_adapter_restores_canonical() -> None:
    scripts = _demo_scripts()
    task = _TASKS["P01"]
    model = PROMPT_OUTPUT_MODELS["P01"]
    schema = model.model_json_schema()
    canonical = json.loads(scripts[task][0])
    contract = build_deepseek_strict_contract(task, schema)

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


# ---------------- D. P01-P08 provider-schema audit ----------------


@pytest.mark.parametrize("prompt_id", tuple(PROMPT_OUTPUT_MODELS))
def test_all_p01_p08_provider_schemas_have_zero_refs(prompt_id: str) -> None:
    model = PROMPT_OUTPUT_MODELS[prompt_id]
    schema = model.model_json_schema()
    contract = build_deepseek_strict_contract(_TASKS[prompt_id], schema)
    assert _count_refs(contract.parameters) == 0
    assert "$defs" not in contract.parameters and "$def" not in contract.parameters
    assert contract._canonical_schema == schema


# ---------------- helpers ----------------


def _demo_scripts() -> dict[SemanticLLMTask, list[str]]:
    parser = TextDocumentParser()
    return _build_scripts(
        resume_document=parser.parse_text(DEMO_RESUME_TEXT),
        jd_document=parser.parse_text(DEMO_JD_TEXT),
        resume_version_id="strict-resume-1",
        jd_snapshot_id="strict-jd-1",
    )


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
