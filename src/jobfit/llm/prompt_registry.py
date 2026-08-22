"""Versioned Markdown prompt registry with no YAML dependency."""

from __future__ import annotations

import re
from pathlib import Path

from jobfit.errors import ConfigurationError, ErrorCode
from jobfit.llm.protocol import PromptTemplate

_TASK_LINE = re.compile(r"^task:\s*([a-z0-9_]+)\s*$")
_VERSION_LINE = re.compile(r'^version:\s*"([^"]+)"\s*$')


class PromptRegistry:
    def __init__(self, prompt_root: str | Path) -> None:
        self._prompt_root = Path(prompt_root)

    def load(self, task_name: str, version: str) -> PromptTemplate:
        paths = (
            self._prompt_root / f"{task_name}.md",
            self._prompt_root / "archive" / f"{task_name}.{version}.md",
        )
        last_error: Exception | None = None
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                last_error = exc
                continue
            template = self._parse(text, task_name, version)
            if template is not None:
                return template
        raise self._not_found(task_name, version, last_error)

    @staticmethod
    def _parse(
        text: str,
        task_name: str,
        version: str,
    ) -> PromptTemplate | None:
        lines = text.splitlines()
        if len(lines) < 8 or lines[0] != "---" or lines[3] != "---":
            return None
        task_match = _TASK_LINE.fullmatch(lines[1])
        version_match = _VERSION_LINE.fullmatch(lines[2])
        if (
            task_match is None
            or version_match is None
            or task_match.group(1) != task_name
            or version_match.group(1) != version
        ):
            return None

        body = "\n".join(lines[4:]).strip()
        system_marker = "## System"
        user_marker = "## User"
        if not body.startswith(system_marker) or user_marker not in body:
            return None
        system_block, user_block = body.split(user_marker, maxsplit=1)
        system_text = system_block.removeprefix(system_marker).strip()
        user_template = user_block.strip()
        if not system_text or not user_template:
            return None
        return PromptTemplate(
            task_name=task_name,
            version=version,
            system_text=system_text,
            user_template=user_template,
        )

    @staticmethod
    def _not_found(
        task_name: str,
        version: str,
        cause: Exception | None = None,
    ) -> ConfigurationError:
        return ConfigurationError(
            code=ErrorCode.PROMPT_NOT_FOUND,
            user_message=f"未找到Prompt：{task_name} v{version}。",
            recoverable=False,
            cause=cause,
        )
