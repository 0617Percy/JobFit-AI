"""DeepSeek strict schema property-name preservation regression tests.

Proves _strict_node prunes unsupported JSON-Schema keywords ONLY at
schema-node level and never prunes user/domain property names (or
definition identifiers) that collide with the unsupported-key set.
"""

from __future__ import annotations

import pytest

from jobfit.llm.deepseek_strict import _strict_node

_COLLIDING_NAMES = (
    "title",
    "default",
    "examples",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
)


def test_property_named_title_is_preserved_and_required() -> None:
    schema = {
        "type": "object",
        "title": "Root annotation must be pruned",
        "properties": {
            "title": {
                "type": "string",
                "title": "Per-property annotation must be pruned",
                "default": "unused",
            },
            "name": {"type": "string"},
        },
    }
    result = _strict_node(schema)
    assert "title" in result["properties"]
    assert "title" in result["required"]
    assert result["properties"]["title"] == {"type": "string"}
    assert "title" not in result  # root schema-node annotation pruned


@pytest.mark.parametrize("name", _COLLIDING_NAMES)
def test_colliding_property_names_are_preserved(name: str) -> None:
    schema = {
        "type": "object",
        "properties": {name: {"type": "string"}},
    }
    result = _strict_node(schema)
    assert name in result["properties"]
    assert name in result["required"]


def test_nested_property_named_title_is_preserved() -> None:
    schema = {
        "type": "object",
        "properties": {
            "outer": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
            }
        },
    }
    result = _strict_node(schema)
    assert "title" in result["properties"]["outer"]["properties"]
    assert "title" in result["properties"]["outer"]["required"]


def test_definition_identifier_collision_is_preserved() -> None:
    schema = {
        "type": "object",
        "properties": {"item": {"$ref": "#/$defs/title"}},
        "$defs": {
            "title": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
            }
        },
    }
    result = _strict_node(schema)
    assert "title" in result["$defs"]
    assert result["$defs"]["title"]["required"] == ["a"]


def test_schema_node_annotation_pruning_still_works() -> None:
    schema = {
        "type": "object",
        "title": "A",
        "default": {},
        "examples": [],
        "minLength": 1,
        "maxLength": 99,
        "minItems": 0,
        "maxItems": 9,
        "properties": {"name": {"type": "string"}},
    }
    result = _strict_node(schema)
    for key in ("title", "default", "examples", "minLength", "maxLength", "minItems", "maxItems"):
        assert key not in result
