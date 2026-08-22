"""Explicit synchronous SQLite lifecycle for the local knowledge store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from jobfit.errors import ErrorCode, KnowledgeDatabaseError
from jobfit.knowledge.orm import Base
from jobfit.knowledge.schema import (
    KNOWLEDGE_SCHEMA_VERSION,
    KNOWLEDGE_TABLE_NAMES,
)

_DB_UNAVAILABLE_MESSAGE = "岗位知识库暂时不可用，可关闭知识增强后重试。"
_VERSION_MISMATCH_MESSAGE = "岗位知识库版本与当前应用不兼容，请重新初始化知识库。"
_SEARCH_AUXILIARY_PREFIXES = ("knowledge_search_fts",)
_SEARCH_AUXILIARY_TABLES = {"knowledge_search_meta"}


def _core_table_names(names: set[str]) -> set[str]:
    return {
        name
        for name in names
        if name not in _SEARCH_AUXILIARY_TABLES
        and not name.startswith(_SEARCH_AUXILIARY_PREFIXES)
    }


def _database_error(
    *,
    code: ErrorCode = ErrorCode.KNOWLEDGE_DB_UNAVAILABLE,
    message: str = _DB_UNAVAILABLE_MESSAGE,
    cause: Exception | None = None,
) -> KnowledgeDatabaseError:
    return KnowledgeDatabaseError(
        code=code,
        user_message=message,
        recoverable=True,
        cause=cause,
    )


class KnowledgeDatabase:
    """Own a lazily connected Engine and short-lived synchronous Sessions."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5_000) -> None:
        self.path = Path(path).expanduser().resolve(strict=False)
        self._engine = create_engine(
            URL.create("sqlite+pysqlite", database=str(self.path)),
            future=True,
        )
        self._session_factory = sessionmaker(
            bind=self._engine,
            class_=Session,
            expire_on_commit=False,
        )

        @event.listens_for(self._engine, "connect")
        def configure_connection(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
            finally:
                cursor.close()

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise _database_error(cause=exc) from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def ensure_compatible_schema(self) -> None:
        if not self.path.is_file():
            raise _database_error()
        try:
            with self._engine.connect() as connection:
                revision = int(connection.execute(text("PRAGMA user_version")).scalar_one())
                tables = _core_table_names({
                    name
                    for name in inspect(connection).get_table_names()
                    if not name.startswith("sqlite_")
                })
        except SQLAlchemyError as exc:
            raise _database_error(cause=exc) from exc

        if revision != KNOWLEDGE_SCHEMA_VERSION or tables != KNOWLEDGE_TABLE_NAMES:
            raise _database_error(
                code=ErrorCode.KNOWLEDGE_VERSION_MISMATCH,
                message=_VERSION_MISMATCH_MESSAGE,
            )

    def schema_version(self) -> int:
        self.ensure_compatible_schema()
        return KNOWLEDGE_SCHEMA_VERSION

    def dispose(self) -> None:
        self._engine.dispose()


def initialize_knowledge_schema(database: KnowledgeDatabase) -> None:
    """Create schema revision 1 only for a genuinely empty SQLite database."""
    try:
        database.path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _database_error(cause=exc) from exc

    try:
        with database._engine.begin() as connection:
            revision = int(connection.execute(text("PRAGMA user_version")).scalar_one())
            tables = _core_table_names({
                name
                for name in inspect(connection).get_table_names()
                if not name.startswith("sqlite_")
            })

            if revision > KNOWLEDGE_SCHEMA_VERSION:
                raise _database_error(
                    code=ErrorCode.KNOWLEDGE_VERSION_MISMATCH,
                    message=_VERSION_MISMATCH_MESSAGE,
                )
            if revision < KNOWLEDGE_SCHEMA_VERSION and tables:
                raise _database_error(
                    code=ErrorCode.KNOWLEDGE_VERSION_MISMATCH,
                    message=_VERSION_MISMATCH_MESSAGE,
                )
            if revision == KNOWLEDGE_SCHEMA_VERSION:
                if tables != KNOWLEDGE_TABLE_NAMES:
                    raise _database_error(
                        code=ErrorCode.KNOWLEDGE_VERSION_MISMATCH,
                        message=_VERSION_MISMATCH_MESSAGE,
                    )
                return

            Base.metadata.create_all(connection)
            connection.execute(
                text(f"PRAGMA user_version = {KNOWLEDGE_SCHEMA_VERSION}")
            )
    except KnowledgeDatabaseError:
        raise
    except SQLAlchemyError as exc:
        raise _database_error(cause=exc) from exc


__all__ = ["KnowledgeDatabase", "initialize_knowledge_schema"]
