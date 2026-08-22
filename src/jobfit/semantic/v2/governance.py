"""Machine-readable governance for the candidate P01-P05 prompt pack."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from pydantic import Field

from jobfit.models.common import NonEmptyStr, StrictModel

GLOBAL_RULES_VERSION = "1.0.0"
PROMPT_PACK_VERSION = "1.0.0"


class PromptLifecycleStatus(StrEnum):
    CANDIDATE = "candidate"


class PromptChangeClass(StrEnum):
    SEMANTIC_ANALYSIS = "C_SEMANTIC_ANALYSIS"
    ADVISORY = "D_ADVISORY"
    PRESENTATION = "E_PRESENTATION"


class KnowledgeTier(StrEnum):
    JOB_EXPLANATION = "K1"
    IMPLICIT = "K2"
    BUILD = "K3"
    INTERVIEW = "K4"


class PromptCriticality(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"


class GlobalRule(StrictModel):
    rule_id: NonEmptyStr = Field(pattern=r"^G(?:0[1-9]|10)$")
    text: NonEmptyStr


class RetryPolicy(StrictModel):
    max_attempts: int = Field(default=3, ge=1, le=3)
    stages: list[NonEmptyStr] = Field(min_length=3, max_length=3)


class PromptManifestEntry(StrictModel):
    prompt_id: NonEmptyStr = Field(pattern=r"^P0[1-8]$")
    prompt_version: NonEmptyStr
    global_rules_version: NonEmptyStr
    prompt_pack_version: NonEmptyStr
    lifecycle_status: PromptLifecycleStatus
    input_schema: NonEmptyStr
    output_schema: NonEmptyStr
    criticality: PromptCriticality
    retry_policy: RetryPolicy
    knowledge_access: bool | list[KnowledgeTier]
    change_class: PromptChangeClass
    filename: NonEmptyStr
    content_hash: NonEmptyStr = Field(pattern=r"^[0-9a-f]{64}$")


class PromptPackManifest(StrictModel):
    prompt_pack_version: NonEmptyStr
    global_rules_version: NonEmptyStr
    lifecycle_status: PromptLifecycleStatus
    prompts: list[PromptManifestEntry] = Field(min_length=8, max_length=8)


def load_global_rules(prompt_root: str | Path) -> tuple[GlobalRule, ...]:
    payload = _load_json(Path(prompt_root) / "global_rules.json")
    version = payload.get("global_rules_version")
    if version != GLOBAL_RULES_VERSION:
        raise ValueError("Global rules version does not match the frozen version.")
    rules = tuple(GlobalRule.model_validate(item) for item in payload.get("rules", []))
    if [item.rule_id for item in rules] != [f"G{index:02d}" for index in range(1, 11)]:
        raise ValueError("Global rules must contain G01 through G10 in order.")
    return rules


def load_prompt_manifest(prompt_root: str | Path) -> PromptPackManifest:
    manifest = PromptPackManifest.model_validate(
        _load_json(Path(prompt_root) / "manifest.json")
    )
    if manifest.prompt_pack_version != PROMPT_PACK_VERSION:
        raise ValueError("Prompt pack version does not match the candidate version.")
    if manifest.global_rules_version != GLOBAL_RULES_VERSION:
        raise ValueError("Prompt manifest uses an unsupported global rules version.")
    if manifest.lifecycle_status is not PromptLifecycleStatus.CANDIDATE:
        raise ValueError("Prompt pack must remain in candidate lifecycle status.")
    if [item.prompt_id for item in manifest.prompts] != [
        f"P{index:02d}" for index in range(1, 9)
    ]:
        raise ValueError("Prompt manifest must contain P01 through P08 in order.")
    return manifest


def validate_prompt_pack(prompt_root: str | Path) -> PromptPackManifest:
    root = Path(prompt_root)
    load_global_rules(root)
    manifest = load_prompt_manifest(root)
    for entry in manifest.prompts:
        path = root / entry.filename
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"Prompt file is unavailable for {entry.prompt_id}.") from exc
        actual_hash = sha256(content).hexdigest()
        if actual_hash != entry.content_hash:
            raise ValueError(f"Prompt content hash mismatch for {entry.prompt_id}.")
        text = content.decode("utf-8")
        if f'task: {entry.filename.removesuffix(".md")}' not in text:
            raise ValueError(f"Prompt task header mismatch for {entry.prompt_id}.")
        if f'version: "{entry.prompt_version}"' not in text:
            raise ValueError(f"Prompt version header mismatch for {entry.prompt_id}.")
    return manifest


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid prompt governance artifact: {path.name}.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Prompt governance artifact must be an object: {path.name}.")
    return value
