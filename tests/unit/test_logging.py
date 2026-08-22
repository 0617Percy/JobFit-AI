"""Tests for safe, centralized logging."""

from __future__ import annotations

import io
import logging

from jobfit.logging_config import configure_logging, log_event


def make_stream_handler(stream: io.StringIO) -> logging.StreamHandler:
    handler = logging.StreamHandler(stream)
    return handler


def test_configure_logging_is_idempotent() -> None:
    first_stream = io.StringIO()
    second_stream = io.StringIO()

    configure_logging("INFO", handlers=[make_stream_handler(first_stream)])
    configure_logging("DEBUG", handlers=[make_stream_handler(second_stream)])

    logger = logging.getLogger("jobfit")
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1


def test_default_logging_uses_console_only() -> None:
    configure_logging("INFO")

    handlers = logging.getLogger("jobfit").handlers
    assert len(handlers) == 1
    assert type(handlers[0]) is logging.StreamHandler


def test_sensitive_values_are_redacted() -> None:
    stream = io.StringIO()
    configure_logging("INFO", handlers=[make_stream_handler(stream)])
    logger = logging.getLogger("jobfit.security")
    synthetic_phone = "138" + "0000" + "0000"

    logger.info(
        "email=student@example.com phone=%s "
        "Authorization: Bearer bearer-secret api_key=test-only-secret",
        synthetic_phone,
    )

    output = stream.getvalue()
    assert "student@example.com" not in output
    assert synthetic_phone not in output
    assert "bearer-secret" not in output
    assert "test-only-secret" not in output
    assert output.count("[REDACTED]") >= 4


def test_log_event_keeps_only_allowlisted_metadata() -> None:
    stream = io.StringIO()
    configure_logging("INFO", handlers=[make_stream_handler(stream)])
    logger = logging.getLogger("jobfit.workflow")

    log_event(
        logger,
        "stage_finished",
        request_id="req-123",
        stage="VALIDATING_INPUT",
        status="ok",
        elapsed_ms=12,
        resume_text="private resume body",
        person_name="Private Person",
    )

    output = stream.getvalue()
    assert "stage_finished" in output
    assert "req-123" in output
    assert "VALIDATING_INPUT" in output
    assert "elapsed_ms=12" in output
    assert "private resume body" not in output
    assert "Private Person" not in output
    assert "resume_text" not in output
    assert "person_name" not in output
