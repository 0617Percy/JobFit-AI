"""Cross-platform, side-effect-free knowledge database path resolution."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

from jobfit.errors import ConfigurationError, ErrorCode


def resolve_knowledge_db_path(
    configured_path: str | Path | None = None,
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    cwd: Path | None = None,
) -> Path:
    """Resolve the runtime database path without creating files or directories."""
    environment = os.environ if environ is None else environ
    current_platform = sys.platform if platform_name is None else platform_name
    home_directory = Path.home() if home is None else Path(home)
    working_directory = Path.cwd() if cwd is None else Path(cwd)

    if configured_path is not None:
        raw = str(configured_path).strip()
        if not raw:
            raise ConfigurationError(
                code=ErrorCode.KNOWLEDGE_CONFIG_INVALID,
                user_message="知识库数据库路径配置为空，请检查配置。",
                recoverable=True,
            )
        resolved = Path(raw).expanduser()
        if not resolved.is_absolute():
            resolved = working_directory / resolved
        return resolved.resolve(strict=False)

    if current_platform.startswith("win"):
        local_app_data = environment.get("LOCALAPPDATA")
        base = (
            Path(local_app_data)
            if local_app_data
            else home_directory / "AppData" / "Local"
        )
        return (base / "JobFitAgent" / "knowledge.sqlite3").resolve(strict=False)

    if current_platform == "darwin":
        return (
            home_directory
            / "Library"
            / "Application Support"
            / "JobFitAgent"
            / "knowledge.sqlite3"
        ).resolve(strict=False)

    xdg_data_home = environment.get("XDG_DATA_HOME")
    base = (
        Path(xdg_data_home)
        if xdg_data_home
        else home_directory / ".local" / "share"
    )
    return (base / "jobfit-agent" / "knowledge.sqlite3").resolve(strict=False)


__all__ = ["resolve_knowledge_db_path"]
