"""Strict offline loading, validation, and canonical hashing for seed packages."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from jobfit.errors import ErrorCode, KnowledgeSeedError
from jobfit.knowledge.seed_models import (
    SEED_SCHEMA_VERSION,
    KnowledgeSeedBundle,
)

MAX_SEED_FILE_BYTES = 2 * 1024 * 1024
SEED_FILES = (
    "knowledge_base_version.json",
    "job_families.json",
    "role_profiles.json",
    "competency_dimensions.json",
    "role_requirements.json",
    "evidence_patterns.json",
    "knowledge_sources.json",
    "knowledge_chunks.json",
    "interview_questions.json",
    "source_role_links.json",
)

_FILE_TO_FIELD = {filename: filename.removesuffix(".json") for filename in SEED_FILES}
_SAFE_SEED_MESSAGE = "Knowledge seed validation failed."
_UNSAFE_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]:[\\/](?:Users|Documents and Settings)[\\/]"),
    re.compile(r"(?i)(?:^|[\s\"'])/(?:Users|home)/[^/\s]+/"),
    re.compile(r"(?i)(?:sk-|ghp_|github_pat_|AKIA)[A-Za-z0-9_-]{8,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    re.compile(r"(?i)<\s*/?\s*(?:script|iframe|object)\b"),
    re.compile(
        r"(?i)<\s*/?\s*(?:html|body|div|span|p|a|img|br|table|tr|td|"
        r"ul|ol|li|h[1-6]|style|link|meta|form|input|button)\b"
    ),
    re.compile(r"(?i)\b(?:ignore|disregard)\s+(?:all\s+)?previous\s+instructions\b"),
    re.compile(r"(?:忽略|无视).{0,12}(?:以上|此前|之前).{0,8}指令"),
    re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"),
)


class _DuplicateKey(ValueError):
    pass


def _seed_error(
    code: ErrorCode,
    *,
    cause: Exception | None = None,
    recoverable: bool = False,
) -> KnowledgeSeedError:
    return KnowledgeSeedError(
        code=code,
        user_message=_SAFE_SEED_MESSAGE,
        recoverable=recoverable,
        cause=cause,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _decode_json(data: bytes) -> Any:
    if len(data) > MAX_SEED_FILE_BYTES:
        raise _seed_error(ErrorCode.KNOWLEDGE_SEED_TOO_LARGE)
    try:
        text = data.decode("utf-8-sig")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant: {value}")
            ),
        )
    except _DuplicateKey as exc:
        raise _seed_error(
            ErrorCode.KNOWLEDGE_SEED_DUPLICATE_KEY,
            cause=exc,
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _seed_error(
            ErrorCode.KNOWLEDGE_SEED_FILE_INVALID,
            cause=exc,
        ) from exc


def parse_knowledge_seed_bytes(data: bytes) -> KnowledgeSeedBundle:
    """Parse a strict aggregate JSON bundle without filesystem access."""
    value = _decode_json(data)
    try:
        return validate_knowledge_seed(KnowledgeSeedBundle.model_validate(value))
    except KnowledgeSeedError:
        raise
    except ValidationError as exc:
        raise _seed_error(
            ErrorCode.KNOWLEDGE_SEED_SCHEMA_INVALID,
            cause=exc,
        ) from exc


def _read_json_file(path: Path) -> Any:
    try:
        if path.is_symlink() or not path.is_file():
            raise _seed_error(ErrorCode.KNOWLEDGE_SEED_FILE_INVALID)
        return _decode_json(path.read_bytes())
    except KnowledgeSeedError:
        raise
    except OSError as exc:
        raise _seed_error(
            ErrorCode.KNOWLEDGE_SEED_FILE_INVALID,
            cause=exc,
        ) from exc


def _validate_manifest(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"schema_version", "files"}:
        raise _seed_error(ErrorCode.KNOWLEDGE_SEED_SCHEMA_INVALID)
    if value["schema_version"] != SEED_SCHEMA_VERSION:
        raise _seed_error(ErrorCode.KNOWLEDGE_SEED_SCHEMA_INVALID)
    if value["files"] != list(SEED_FILES):
        raise _seed_error(ErrorCode.KNOWLEDGE_SEED_FILE_INVALID)
    for filename in value["files"]:
        candidate = Path(filename)
        if (
            candidate.is_absolute()
            or candidate.name != filename
            or ".." in candidate.parts
            or "\\" in filename
        ):
            raise _seed_error(ErrorCode.KNOWLEDGE_SEED_FILE_INVALID)


def load_knowledge_seed(source: str | Path) -> KnowledgeSeedBundle:
    """Load one local, manifest-whitelisted, multi-file JSON package."""
    if isinstance(source, str) and re.match(r"(?i)^https?://", source):
        raise _seed_error(ErrorCode.KNOWLEDGE_SEED_FILE_INVALID)
    package = Path(source)
    try:
        if not package.is_dir():
            raise _seed_error(ErrorCode.KNOWLEDGE_SEED_FILE_INVALID)
        manifest = _read_json_file(package / "manifest.json")
        _validate_manifest(manifest)
        actual_files = {item.name for item in package.iterdir() if item.is_file()}
    except KnowledgeSeedError:
        raise
    except OSError as exc:
        raise _seed_error(
            ErrorCode.KNOWLEDGE_SEED_FILE_INVALID,
            cause=exc,
        ) from exc
    expected_files = {"manifest.json", *SEED_FILES}
    if actual_files != expected_files:
        raise _seed_error(ErrorCode.KNOWLEDGE_SEED_FILE_INVALID)

    payload: dict[str, Any] = {"schema_version": SEED_SCHEMA_VERSION}
    for filename in SEED_FILES:
        payload[_FILE_TO_FIELD[filename]] = _read_json_file(package / filename)
    try:
        bundle = KnowledgeSeedBundle.model_validate(payload)
    except ValidationError as exc:
        raise _seed_error(
            ErrorCode.KNOWLEDGE_SEED_SCHEMA_INVALID,
            cause=exc,
        ) from exc
    return validate_knowledge_seed(bundle)


def _assert_references(
    values: set[str],
    known: set[str],
) -> None:
    if not values <= known:
        raise _seed_error(ErrorCode.KNOWLEDGE_SEED_REFERENCE_INVALID)


def _iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def validate_knowledge_seed(bundle: KnowledgeSeedBundle) -> KnowledgeSeedBundle:
    """Fail closed on cross-reference, integrity, and content safety errors."""
    dumped = bundle.model_dump(mode="json")
    if any(pattern.search(text) for text in _iter_strings(dumped) for pattern in _UNSAFE_PATTERNS):
        raise _seed_error(ErrorCode.KNOWLEDGE_SEED_CONTENT_UNSAFE)

    version_id = bundle.knowledge_base_version.id
    versioned = (
        *bundle.job_families,
        *bundle.role_profiles,
        *bundle.competency_dimensions,
        *bundle.role_requirements,
        *bundle.evidence_patterns,
        *bundle.knowledge_chunks,
        *bundle.interview_questions,
        *bundle.source_role_links,
    )
    if any(item.knowledge_version_id != version_id for item in versioned):
        raise _seed_error(ErrorCode.KNOWLEDGE_SEED_REFERENCE_INVALID)

    families = {item.id for item in bundle.job_families}
    roles = {item.id for item in bundle.role_profiles}
    dimensions = {item.id for item in bundle.competency_dimensions}
    requirements = {item.id for item in bundle.role_requirements}
    sources = {item.id for item in bundle.knowledge_sources}
    unique_groups = (
        [item.code for item in bundle.job_families],
        [item.code for item in bundle.role_profiles],
        [item.code for item in bundle.competency_dimensions],
        [item.checksum for item in bundle.knowledge_sources],
        [(item.role_profile_id, item.title.casefold()) for item in bundle.role_requirements],
    )
    if any(len(values) != len(set(values)) for values in unique_groups):
        raise _seed_error(ErrorCode.KNOWLEDGE_SEED_REFERENCE_INVALID)

    _assert_references(
        {item.job_family_id for item in bundle.role_profiles},
        families,
    )
    _assert_references(
        {item.role_profile_id for item in bundle.role_requirements},
        roles,
    )
    _assert_references(
        {item.competency_dimension_id for item in bundle.role_requirements},
        dimensions,
    )
    _assert_references(
        {item.source_id for item in bundle.role_requirements},
        sources,
    )
    _assert_references(
        {item.role_requirement_id for item in bundle.evidence_patterns},
        requirements,
    )
    _assert_references(
        {item.source_id for item in bundle.evidence_patterns},
        sources,
    )
    _assert_references(
        {item.source_id for item in bundle.knowledge_chunks},
        sources,
    )
    _assert_references(
        {
            item.role_profile_id
            for item in bundle.knowledge_chunks
            if item.role_profile_id is not None
        },
        roles,
    )
    _assert_references(
        {item.role_profile_id for item in bundle.interview_questions},
        roles,
    )
    _assert_references(
        {item.competency_dimension_id for item in bundle.interview_questions},
        dimensions,
    )
    _assert_references(
        {item.source_id for item in bundle.interview_questions},
        sources,
    )
    _assert_references(
        {item.source_id for item in bundle.source_role_links},
        sources,
    )
    _assert_references(
        {item.role_profile_id for item in bundle.source_role_links},
        roles,
    )
    links = {(item.source_id, item.role_profile_id) for item in bundle.source_role_links}
    requirement_roles = {item.id: item.role_profile_id for item in bundle.role_requirements}
    required_links = {(item.source_id, item.role_profile_id) for item in bundle.role_requirements}
    required_links.update(
        (
            item.source_id,
            requirement_roles[item.role_requirement_id],
        )
        for item in bundle.evidence_patterns
    )
    required_links.update(
        (item.source_id, item.role_profile_id) for item in bundle.interview_questions
    )
    required_links.update(
        (item.source_id, item.role_profile_id)
        for item in bundle.knowledge_chunks
        if item.role_profile_id is not None
    )
    if not required_links <= links:
        raise _seed_error(ErrorCode.KNOWLEDGE_SEED_REFERENCE_INVALID)
    used_sources = {
        item.source_id
        for collection in (
            bundle.role_requirements,
            bundle.evidence_patterns,
            bundle.knowledge_chunks,
            bundle.interview_questions,
            bundle.source_role_links,
        )
        for item in collection
    }
    if sources != used_sources:
        raise _seed_error(ErrorCode.KNOWLEDGE_SEED_REFERENCE_INVALID)

    for chunk in bundle.knowledge_chunks:
        expected_hash = hashlib.sha256(chunk.chunk_text.encode()).hexdigest()
        if chunk.content_hash != expected_hash:
            raise _seed_error(ErrorCode.KNOWLEDGE_SEED_HASH_MISMATCH)
        if (
            chunk.start_offset is not None
            and chunk.end_offset is not None
            and chunk.end_offset - chunk.start_offset != len(chunk.chunk_text)
        ):
            raise _seed_error(ErrorCode.KNOWLEDGE_SEED_REFERENCE_INVALID)
    return bundle


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def canonical_seed_bytes(bundle: KnowledgeSeedBundle) -> bytes:
    """Return platform-independent business content bytes for hashing."""
    validated = validate_knowledge_seed(bundle)
    dumped = validated.model_dump(mode="json")
    version = dict(dumped["knowledge_base_version"])
    version.pop("status", None)
    values: dict[str, Any] = {
        "knowledge_base_version.json": version,
        **{
            filename: dumped[field_name]
            for filename, field_name in _FILE_TO_FIELD.items()
            if filename != "knowledge_base_version.json"
        },
    }
    manifest = {
        "schema_version": SEED_SCHEMA_VERSION,
        "files": list(SEED_FILES),
    }
    fragments = [b"manifest.json\n", _canonical_json(manifest), b"\n"]
    for filename in SEED_FILES:
        fragments.extend(
            (
                filename.encode(),
                b"\n",
                _canonical_json(values[filename]),
                b"\n",
            )
        )
    return b"".join(fragments)


def calculate_seed_content_hash(bundle: KnowledgeSeedBundle) -> str:
    return hashlib.sha256(canonical_seed_bytes(bundle)).hexdigest()


__all__ = [
    "MAX_SEED_FILE_BYTES",
    "SEED_FILES",
    "calculate_seed_content_hash",
    "canonical_seed_bytes",
    "load_knowledge_seed",
    "parse_knowledge_seed_bytes",
    "validate_knowledge_seed",
]
