"""Minimal SQLite persistence for single-instance v2 analysis history."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import NullPool

from jobfit.config import Settings
from jobfit.knowledge.paths import resolve_knowledge_db_path
from jobfit.models.v2 import AnalysisRun, LifecycleStatus
from jobfit.workflow.v2.history import (
    AnalysisHistoryError,
    PersistedAnalysis,
)

ANALYSIS_SCHEMA_VERSION = 1
_ANALYSIS_TABLE_NAMES = {"analysis_records"}
_TERMINAL_STATUSES = {LifecycleStatus.COMPLETED, LifecycleStatus.FAILED}


class AnalysisPersistenceError(RuntimeError):
    """Safe fail-closed application persistence error."""


class _Base(DeclarativeBase):
    pass


class _AnalysisRecordRow(_Base):
    __tablename__ = "analysis_records"

    row_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    parent_analysis_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("analysis_records.analysis_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    lifecycle_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    is_terminal: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    record_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class AnalysisDatabase:
    """Own a lazy SQLAlchemy Engine for one external analysis SQLite file."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5_000) -> None:
        self.path = Path(path).expanduser().resolve(strict=False)
        self._engine = create_engine(
            URL.create("sqlite+pysqlite", database=str(self.path)),
            future=True,
            poolclass=NullPool,
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
                cursor.execute("PRAGMA secure_delete = ON")
            finally:
                cursor.close()

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except AnalysisPersistenceError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise _safe_error("Analysis database transaction failed.") from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def ensure_compatible_schema(self) -> None:
        if not self.path.is_file():
            raise _safe_error("Analysis database is unavailable.")
        try:
            with self._engine.connect() as connection:
                revision = int(connection.execute(text("PRAGMA user_version")).scalar_one())
                tables = _table_names(connection)
        except SQLAlchemyError as exc:
            raise _safe_error("Analysis database is unavailable.") from exc
        if revision != ANALYSIS_SCHEMA_VERSION or tables != _ANALYSIS_TABLE_NAMES:
            raise _safe_error("Analysis database schema is not supported.")

    def schema_version(self) -> int:
        self.ensure_compatible_schema()
        return ANALYSIS_SCHEMA_VERSION

    def dispose(self) -> None:
        self._engine.dispose()


def initialize_analysis_schema(database: AnalysisDatabase) -> None:
    """Create schema version 1 only for an empty analysis database."""
    try:
        database.path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _safe_error("Analysis database directory cannot be created.") from exc

    try:
        with database._engine.begin() as connection:
            revision = int(connection.execute(text("PRAGMA user_version")).scalar_one())
            tables = _table_names(connection)
            if revision > ANALYSIS_SCHEMA_VERSION:
                raise _safe_error("Analysis database schema is newer than this application.")
            if revision < ANALYSIS_SCHEMA_VERSION and tables:
                raise _safe_error("Analysis database schema migration is required.")
            if revision == ANALYSIS_SCHEMA_VERSION:
                if tables != _ANALYSIS_TABLE_NAMES:
                    raise _safe_error("Analysis database schema is incomplete.")
                return
            _Base.metadata.create_all(connection)
            connection.execute(text(f"PRAGMA user_version = {ANALYSIS_SCHEMA_VERSION}"))
    except AnalysisPersistenceError:
        raise
    except SQLAlchemyError as exc:
        raise _safe_error("Analysis database initialization failed.") from exc


class SQLiteAnalysisRepository:
    """Durable B6 adapter with immutable terminal rows and explicit deletion."""

    def __init__(self, database: AnalysisDatabase) -> None:
        database.ensure_compatible_schema()
        self._database = database

    def save_working_analysis(self, record: PersistedAnalysis) -> None:
        if _is_terminal(record.run):
            raise AnalysisPersistenceError("Working analysis cannot be terminal.")
        with self._database.session_scope() as session:
            row = self._row(session, record.run.analysis_id)
            if row is None:
                self._require_terminal_parent(session, record.run)
                session.add(_row_from_record(record))
                return
            existing = _decode_record(row.record_json)
            if row.is_terminal:
                raise AnalysisPersistenceError("Completed analysis history is immutable.")
            _validate_replacement(existing, record)
            _assign_record(row, record)

    def append_analysis(self, run: AnalysisRun) -> None:
        if not _is_terminal(run):
            raise AnalysisHistoryError("Only terminal analysis runs enter history.")
        with self._database.session_scope() as session:
            row = self._row(session, run.analysis_id)
            if row is None:
                self._require_terminal_parent(session, run)
                session.add(_row_from_record(_record_from_terminal_run(run)))
                return
            if row.is_terminal:
                raise AnalysisPersistenceError("Completed analysis history is immutable.")
            existing = _decode_record(row.record_json)
            replacement = PersistedAnalysis.model_validate(
                existing.model_copy(update={"run": run}).model_dump(mode="python")
            )
            _validate_replacement(existing, replacement)
            _assign_record(row, replacement)

    def get_analysis(self, analysis_id: str) -> AnalysisRun | None:
        record = self.get_persisted_analysis(analysis_id)
        return None if record is None else record.run

    def get_persisted_analysis(self, analysis_id: str) -> PersistedAnalysis | None:
        with self._database.session_scope() as session:
            row = self._row(session, analysis_id)
            return None if row is None else _decode_record(row.record_json)

    def list_analyses(self) -> tuple[AnalysisRun, ...]:
        return tuple(record.run for record in self._list_records(terminal_only=False))

    def list_analysis_versions(self) -> tuple[AnalysisRun, ...]:
        return tuple(record.run for record in self._list_records(terminal_only=True))

    def get_parent(self, analysis_id: str) -> AnalysisRun | None:
        run = self.get_analysis(analysis_id)
        if run is None or run.parent_analysis_id is None:
            return None
        return self.get_analysis(run.parent_analysis_id)

    def delete_analysis_chain(self, analysis_id: str) -> int:
        with self._database.session_scope() as session:
            rows = self._all_rows(session)
            if analysis_id not in {row.analysis_id for row in rows}:
                return 0
            targets = _descendant_ids(rows, analysis_id)
            for row in reversed(rows):
                if row.analysis_id in targets:
                    session.delete(row)
                    session.flush()
            return len(targets)

    def delete_all_analysis_data(self) -> int:
        with self._database.session_scope() as session:
            rows = self._all_rows(session)
            for row in reversed(rows):
                session.delete(row)
                session.flush()
            return len(rows)

    def dispose(self) -> None:
        self._database.dispose()

    def _list_records(self, *, terminal_only: bool) -> tuple[PersistedAnalysis, ...]:
        with self._database.session_scope() as session:
            statement = select(_AnalysisRecordRow).order_by(_AnalysisRecordRow.row_id)
            if terminal_only:
                statement = statement.where(_AnalysisRecordRow.is_terminal.is_(True))
            rows = tuple(session.scalars(statement))
            return tuple(_decode_record(row.record_json) for row in rows)

    @staticmethod
    def _row(session: Session, analysis_id: str) -> _AnalysisRecordRow | None:
        return session.scalar(
            select(_AnalysisRecordRow).where(
                _AnalysisRecordRow.analysis_id == analysis_id
            )
        )

    @staticmethod
    def _all_rows(session: Session) -> tuple[_AnalysisRecordRow, ...]:
        return tuple(
            session.scalars(
                select(_AnalysisRecordRow).order_by(_AnalysisRecordRow.row_id)
            )
        )

    def _require_terminal_parent(self, session: Session, run: AnalysisRun) -> None:
        if run.parent_analysis_id is None:
            return
        parent = self._row(session, run.parent_analysis_id)
        if parent is None:
            raise AnalysisPersistenceError("Analysis parent does not exist.")
        if not parent.is_terminal:
            raise AnalysisPersistenceError("Analysis parent must be terminal.")


def resolve_analysis_db_path(
    configured_path: str | Path | None = None,
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve an external application-data path without creating anything."""
    environment = os.environ if environ is None else environ
    current_platform = sys.platform if platform_name is None else platform_name
    home_directory = Path.home() if home is None else Path(home)
    if configured_path is not None:
        raw = str(configured_path).strip()
        candidate = Path(raw).expanduser()
        if not raw or not candidate.is_absolute():
            raise AnalysisPersistenceError("Analysis database path must be absolute.")
        return candidate.resolve(strict=False)
    if current_platform.startswith("win"):
        base = Path(
            environment.get("LOCALAPPDATA", home_directory / "AppData" / "Local")
        )
        return (base / "JobFitAgent" / "analysis.sqlite3").resolve(strict=False)
    if current_platform == "darwin":
        return (
            home_directory
            / "Library"
            / "Application Support"
            / "JobFitAgent"
            / "analysis.sqlite3"
        ).resolve(strict=False)
    base = Path(environment.get("XDG_DATA_HOME", home_directory / ".local" / "share"))
    return (base / "jobfit-agent" / "analysis.sqlite3").resolve(strict=False)


def build_analysis_repository(
    settings: Settings,
    *,
    repository_root: str | Path,
    knowledge_db_path: str | Path | None = None,
) -> SQLiteAnalysisRepository:
    """Build the v2 durable adapter after enforcing DB separation and location."""
    path = resolve_analysis_db_path(settings.analysis_db_path)
    root = Path(repository_root).resolve(strict=False)
    if path == root or root in path.parents:
        raise AnalysisPersistenceError("Analysis database cannot be inside the repository.")
    knowledge_path = (
        Path(knowledge_db_path).expanduser().resolve(strict=False)
        if knowledge_db_path is not None
        else resolve_knowledge_db_path(settings.knowledge_db_path)
    )
    if path == knowledge_path:
        raise AnalysisPersistenceError("Analysis database must differ from knowledge database.")
    database = AnalysisDatabase(path)
    initialize_analysis_schema(database)
    return SQLiteAnalysisRepository(database)


def _row_from_record(record: PersistedAnalysis) -> _AnalysisRecordRow:
    return _AnalysisRecordRow(
        analysis_id=record.run.analysis_id,
        parent_analysis_id=record.run.parent_analysis_id,
        lifecycle_status=record.run.lifecycle.status.value,
        is_terminal=_is_terminal(record.run),
        record_json=record.model_dump_json(),
    )


def _assign_record(row: _AnalysisRecordRow, record: PersistedAnalysis) -> None:
    row.parent_analysis_id = record.run.parent_analysis_id
    row.lifecycle_status = record.run.lifecycle.status.value
    row.is_terminal = _is_terminal(record.run)
    row.record_json = record.model_dump_json()
    row.updated_at = datetime.now(UTC)


def _record_from_terminal_run(run: AnalysisRun) -> PersistedAnalysis:
    snapshot = run.input_snapshot
    return PersistedAnalysis(
        run=run,
        resume_version_id=(
            snapshot.resume_version_id if snapshot is not None else run.analysis_id
        ),
        jd_snapshot_id=(
            snapshot.jd_snapshot_id if snapshot is not None else run.analysis_id
        ),
    )


def _decode_record(payload: str) -> PersistedAnalysis:
    try:
        return PersistedAnalysis.model_validate_json(payload)
    except (ValidationError, ValueError) as exc:
        raise _safe_error("Stored analysis data failed validation.") from exc


def _validate_replacement(
    existing: PersistedAnalysis,
    replacement: PersistedAnalysis,
) -> None:
    if existing.run.parent_analysis_id != replacement.run.parent_analysis_id:
        raise AnalysisPersistenceError("Analysis lineage cannot change in place.")
    if (
        existing.resume_version_id != replacement.resume_version_id
        or existing.jd_snapshot_id != replacement.jd_snapshot_id
        or existing.resume_document != replacement.resume_document
        or existing.jd_document != replacement.jd_document
    ):
        raise AnalysisPersistenceError("Analysis source identity cannot change in place.")
    if (
        existing.run.input_snapshot is not None
        and existing.run.input_snapshot != replacement.run.input_snapshot
    ):
        raise AnalysisPersistenceError("Frozen analysis input snapshot is immutable.")


def _descendant_ids(
    rows: tuple[_AnalysisRecordRow, ...],
    root_id: str,
) -> set[str]:
    targets = {root_id}
    changed = True
    while changed:
        changed = False
        for row in rows:
            if row.parent_analysis_id in targets and row.analysis_id not in targets:
                targets.add(row.analysis_id)
                changed = True
    return targets


def _table_names(connection) -> set[str]:
    return {
        name
        for name in inspect(connection).get_table_names()
        if not name.startswith("sqlite_")
    }


def _is_terminal(run: AnalysisRun) -> bool:
    return run.lifecycle.status in _TERMINAL_STATUSES


def _safe_error(message: str) -> AnalysisPersistenceError:
    return AnalysisPersistenceError(message)


__all__ = [
    "ANALYSIS_SCHEMA_VERSION",
    "AnalysisDatabase",
    "AnalysisPersistenceError",
    "SQLiteAnalysisRepository",
    "build_analysis_repository",
    "initialize_analysis_schema",
    "resolve_analysis_db_path",
]
