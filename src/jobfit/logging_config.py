"""Centralized logging with defensive sensitive-data redaction."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Final

_REDACTED: Final = "[REDACTED]"

_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;]+)"),
        rf"\1{_REDACTED}",
    ),
    (
        re.compile(r"(?i)\b(api[_-]?key|token|password)\s*[:=]\s*([^\s,;]+)"),
        rf"\1={_REDACTED}",
    ),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), _REDACTED),
    (
        re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        _REDACTED,
    ),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), _REDACTED),
)

_ALLOWED_METADATA: Final[frozenset[str]] = frozenset(
    {
        "request_id",
        "stage",
        "elapsed_ms",
        "error_code",
        "status",
        "provider",
        "model",
        "prompt_version",
        "token_usage",
        "char_count",
        "input_char_count",
        "output_char_count",
        "file_type",
        "content_hash_prefix",
    }
)

_LOG_FORMAT: Final = (
    "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s"
)


def _redact(value: str) -> str:
    redacted = value
    for pattern, replacement in _PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


class SensitiveDataFilter(logging.Filter):
    """Redact common credentials and personal contact values from records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", "-")
        record.msg = _redact(record.getMessage())
        record.args = ()
        return True


class SensitiveFormatter(logging.Formatter):
    """Apply a final redaction pass, including formatted exception text."""

    def format(self, record: logging.LogRecord) -> str:
        return _redact(super().format(record))


def configure_logging(
    level: str,
    *,
    handlers: Iterable[logging.Handler] | None = None,
) -> None:
    """Configure the ``jobfit`` logger without creating duplicate handlers."""
    normalized_level = level.upper()
    numeric_level = logging.getLevelNamesMapping().get(normalized_level)
    if numeric_level is None:
        raise ValueError(f"Unsupported log level: {level}")

    logger = logging.getLogger("jobfit")
    logger.handlers.clear()
    logger.setLevel(numeric_level)
    logger.propagate = False

    selected_handlers = list(handlers) if handlers is not None else [logging.StreamHandler()]
    formatter = SensitiveFormatter(_LOG_FORMAT)
    for handler in selected_handlers:
        handler.setLevel(numeric_level)
        handler.addFilter(SensitiveDataFilter())
        handler.setFormatter(formatter)
        logger.addHandler(handler)


def log_event(
    logger: logging.Logger,
    event: str,
    **metadata: object,
) -> None:
    """Log an event using only an explicit, privacy-safe metadata allowlist."""
    safe_metadata = {
        key: value for key, value in metadata.items() if key in _ALLOWED_METADATA
    }
    details = " ".join(f"{key}={safe_metadata[key]}" for key in sorted(safe_metadata))
    message = f"event={event}" if not details else f"event={event} {details}"
    logger.info(
        message,
        extra={"request_id": str(safe_metadata.get("request_id", "-"))},
    )
