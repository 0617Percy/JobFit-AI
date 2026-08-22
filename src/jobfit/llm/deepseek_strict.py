"""Narrow DeepSeek strict-function schema and argument adaptation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from jobfit.llm.exceptions import StrictTransportError

_UNSUPPORTED_SCHEMA_KEYS = {
    "default",
    "examples",
    "maxItems",
    "maxLength",
    "minItems",
    "minLength",
    "title",
}

_MEMBER_NAME_MAPS = frozenset({"properties", "$defs", "$def"})

_FUNCTION_NAMES = {
    "p01_resume_parser": "jobfit_p01_output",
    "p02_jd_parser": "jobfit_p02_output",
    "p03_requirement_classifier": "jobfit_p03_output",
    "p04_evidence_normalizer": "jobfit_p04_output",
    "p05_semantic_matcher": "jobfit_p05_output",
    "p06_actions": "jobfit_p06_output",
    "p07_interview": "jobfit_p07_output",
    "p08_report": "jobfit_p08_output",
}


@dataclass(frozen=True, slots=True)
class DeepSeekStrictContract:
    """One terminal strict-function contract for a DeepSeek request."""

    function_name: str
    parameters: dict[str, Any]
    _canonical_schema: dict[str, Any]

    def decode_arguments(self, arguments: str) -> str:
        """Decode strict transport-only shapes to the canonical JobFit JSON shape."""

        try:
            transport_value = json.loads(arguments)
        except json.JSONDecodeError:
            raise StrictTransportError("STRICT_ARGUMENTS_JSON_INVALID") from None
        try:
            canonical_value = _decode_node(
                transport_value,
                self._canonical_schema,
                self._canonical_schema,
                safe_path="",
            )
        except StrictTransportError:
            raise
        except (KeyError, TypeError, ValueError):
            raise StrictTransportError("STRICT_ARGUMENTS_INVALID") from None
        if not isinstance(canonical_value, dict):
            raise StrictTransportError("STRICT_ARGUMENTS_INVALID")
        return json.dumps(
            canonical_value,
            ensure_ascii=False,
            separators=(",", ":"),
        )


def build_deepseek_strict_contract(
    task: object,
    response_schema: Mapping[str, Any],
) -> DeepSeekStrictContract:
    """Build the observed P01-P08 strict transport subset without domain changes."""

    canonical_schema = deepcopy(dict(response_schema))
    parameters = _strict_node(canonical_schema)
    if not isinstance(parameters, dict):
        raise ValueError("DeepSeek strict response schema must be an object.")
    _prune_unused_defs(parameters)
    parameters = _inline_local_refs(parameters)
    task_value = str(getattr(task, "value", task))
    function_name = _FUNCTION_NAMES.get(task_value, f"jobfit_{task_value}_output")
    return DeepSeekStrictContract(
        function_name=function_name,
        parameters=parameters,
        _canonical_schema=canonical_schema,
    )


def _strict_node(node: object) -> object:
    if isinstance(node, list):
        return [_strict_node(item) for item in node]
    if not isinstance(node, Mapping):
        return node

    if _is_nullable(node):
        non_null = [
            item
            for item in node["anyOf"]
            if not (isinstance(item, Mapping) and item.get("type") == "null")
        ]
        item_schema: object
        if len(non_null) == 1:
            item_schema = _strict_node(non_null[0])
        else:
            item_schema = {"anyOf": [_strict_node(item) for item in non_null]}
        return {
            "type": "array",
            "items": item_schema,
            "description": "Zero items means absent; one item means present.",
        }

    if _is_open_map(node):
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value_json": {
                        "type": "string",
                        "description": "JSON-encoded value for this metadata key.",
                    },
                },
                "required": ["key", "value_json"],
                "additionalProperties": False,
            },
            "description": "Metadata entries; use an empty array when none exist.",
        }

    result: dict[str, Any] = {}
    for key, value in node.items():
        if key in _MEMBER_NAME_MAPS:
            # Member-name maps (properties, $defs, $def) carry USER/domain
            # identifiers that must be preserved verbatim; only the VALUES are
            # transformed as schema nodes. Never prune a member name merely
            # because it collides with an unsupported schema keyword.
            if isinstance(value, Mapping):
                result[key] = {
                    member: _strict_node(child) for member, child in value.items()
                }
            elif isinstance(value, list):
                result[key] = [_strict_node(item) for item in value]
            else:
                result[key] = value
        elif key in _UNSUPPORTED_SCHEMA_KEYS:
            continue
        else:
            result[key] = _strict_node(value)
    properties = result.get("properties")
    if result.get("type") == "object" and isinstance(properties, Mapping):
        result["required"] = list(properties)
        result["additionalProperties"] = False
    return result


def _decode_node(
    value: object,
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    *,
    safe_path: str,
) -> object:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        return _decode_node(
            value,
            _resolve_reference(reference, root),
            root,
            safe_path=safe_path,
        )

    if _is_nullable(schema):
        if not isinstance(value, list) or len(value) > 1:
            raise ValueError("Invalid zero-or-one optional value.")
        if not value:
            return None
        non_null = [
            item
            for item in schema["anyOf"]
            if not (isinstance(item, Mapping) and item.get("type") == "null")
        ]
        if len(non_null) == 1 and isinstance(non_null[0], Mapping):
            return _decode_node(
                value[0],
                non_null[0],
                root,
                safe_path=safe_path,
            )
        return value[0]

    if _is_open_map(schema):
        if not isinstance(value, list):
            raise ValueError("Invalid metadata entry collection.")
        decoded: dict[str, Any] = {}
        for entry in value:
            if not isinstance(entry, Mapping) or set(entry) != {"key", "value_json"}:
                raise ValueError("Invalid metadata entry.")
            key = entry["key"]
            encoded = entry["value_json"]
            if not isinstance(key, str) or not key or not isinstance(encoded, str):
                raise ValueError("Invalid metadata key or value.")
            if key in decoded:
                raise ValueError("Duplicate metadata key.")
            decoded[key] = json.loads(encoded)
        return decoded

    if schema.get("type") == "object" and isinstance(value, Mapping):
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            return dict(value)
        missing_keys = sorted(set(properties) - set(value))
        if missing_keys:
            raise StrictTransportError(
                "STRICT_ARGUMENTS_MISSING_KEY",
                safe_path=_child_path(safe_path, missing_keys[0]),
            )
        extra_keys = sorted(set(value) - set(properties))
        if extra_keys:
            raise StrictTransportError(
                "STRICT_ARGUMENTS_EXTRA_KEY",
                safe_path=_child_path(safe_path, extra_keys[0]),
            )
        return {
            key: _decode_node(
                child,
                properties[key],
                root,
                safe_path=_child_path(safe_path, key),
            )
            if key in properties and isinstance(properties[key], Mapping)
            else child
            for key, child in value.items()
        }

    if schema.get("type") == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            return [
                _decode_node(
                    item,
                    item_schema,
                    root,
                    safe_path=f"{safe_path}[{index}]",
                )
                for index, item in enumerate(value)
            ]
    return value


def _child_path(parent: str, child: str) -> str:
    return f"{parent}.{child}" if parent else child


def _is_nullable(node: Mapping[str, Any]) -> bool:
    alternatives = node.get("anyOf")
    return isinstance(alternatives, list) and any(
        isinstance(item, Mapping) and item.get("type") == "null"
        for item in alternatives
    )


def _is_open_map(node: Mapping[str, Any]) -> bool:
    return (
        node.get("type") == "object"
        and not node.get("properties")
        and isinstance(node.get("additionalProperties"), Mapping)
    )


def _resolve_reference(reference: str, root: Mapping[str, Any]) -> Mapping[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError("Only local schema references are supported.")
    current: object = root
    for part in reference[2:].split("/"):
        if not isinstance(current, Mapping):
            raise ValueError("Invalid schema reference.")
        current = current[part.replace("~1", "/").replace("~0", "~")]
    if not isinstance(current, Mapping):
        raise ValueError("Schema reference must resolve to an object.")
    return current


def _prune_unused_defs(schema: dict[str, Any]) -> None:
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        return
    needed = _referenced_definition_names({k: v for k, v in schema.items() if k != "$defs"})
    pending = list(needed)
    while pending:
        name = pending.pop()
        definition = definitions.get(name)
        if definition is None:
            continue
        for referenced in _referenced_definition_names(definition) - needed:
            needed.add(referenced)
            pending.append(referenced)
    schema["$defs"] = {
        name: definition for name, definition in definitions.items() if name in needed
    }


def _referenced_definition_names(node: object) -> set[str]:
    names: set[str] = set()
    if isinstance(node, Mapping):
        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            names.add(reference.removeprefix("#/$defs/").split("/", 1)[0])
        for value in node.values():
            names.update(_referenced_definition_names(value))
    elif isinstance(node, list):
        for value in node:
            names.update(_referenced_definition_names(value))
    return names


def _inline_local_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively inline local JSON Schema references in a provider schema.

    Resolves only local pointers of the forms ``#/$defs/...`` and
    ``#/$def/...``. External references, unsupported containers, malformed
    or unresolved pointers, sibling keywords on a ``$ref`` node, and
    reference cycles fail closed with a deterministic ``ValueError``. After
    full expansion the now-unused ``$defs``/``$def`` containers are removed,
    leaving a semantically identical schema without local references.
    """

    definitions = schema.get("$defs") or schema.get("$def") or {}
    if not isinstance(definitions, Mapping):
        raise ValueError("STRICT_REF_DEFINITIONS_INVALID")

    def resolve(node: object, stack: tuple[int, ...]) -> object:
        if isinstance(node, list):
            return [resolve(item, stack) for item in node]
        if not isinstance(node, Mapping):
            return node
        reference = node.get("$ref")
        if not isinstance(reference, str):
            return {key: resolve(value, stack) for key, value in node.items()}
        if len(node) != 1:
            raise ValueError("STRICT_REF_SIBLINGS_UNSUPPORTED")
        if not reference.startswith("#/"):
            raise ValueError("STRICT_REF_EXTERNAL")
        parts = reference[2:].split("/")
        if not parts or parts[0] not in ("$defs", "$def"):
            raise ValueError("STRICT_REF_UNSUPPORTED")
        target: object = definitions
        for part in parts[1:]:
            if not isinstance(target, Mapping) or part not in target:
                raise ValueError("STRICT_REF_UNRESOLVED")
            target = target[part.replace("~1", "/").replace("~0", "~")]
        if id(target) in stack:
            raise ValueError("STRICT_REF_CYCLE")
        return resolve(target, stack + (id(target),))

    result = resolve(schema, ())
    if not isinstance(result, Mapping):
        raise ValueError("STRICT_REF_RESULT_INVALID")
    expanded = dict(result)
    expanded.pop("$defs", None)
    expanded.pop("$def", None)
    return expanded


__all__ = ["DeepSeekStrictContract", "build_deepseek_strict_contract"]
