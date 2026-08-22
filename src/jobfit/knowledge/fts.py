"""Optional, rebuildable SQLite FTS5 candidate index."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from pydantic import ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from jobfit.errors import ErrorCode, KnowledgeDatabaseError
from jobfit.knowledge.db import KnowledgeDatabase
from jobfit.knowledge.normalization import (
    build_fts_match_expression,
    normalize_query_terms,
)
from jobfit.models.common import StrictModel
from jobfit.models.knowledge import (
    KnowledgeSearchBackend,
    KnowledgeSearchCapabilities,
    KnowledgeSearchCapabilityStatus,
    KnowledgeSearchMode,
)

KNOWLEDGE_SEARCH_INDEX_VERSION = "1"
MAX_FTS_CANDIDATES = 100
_FTS_TABLE = "knowledge_search_fts"
_META_TABLE = "knowledge_search_meta"
_SAFE_SEARCH_MESSAGE = "Knowledge search is temporarily unavailable."


class SearchIndexCounts(StrictModel):
    model_config = ConfigDict(frozen=True)

    role_profiles: int = Field(ge=0)
    role_requirements: int = Field(ge=0)
    knowledge_chunks: int = Field(ge=0)
    interview_questions: int = Field(ge=0)


class SearchIndexReport(StrictModel):
    model_config = ConfigDict(frozen=True)

    version_id: str
    index_version: str = KNOWLEDGE_SEARCH_INDEX_VERSION
    counts: SearchIndexCounts
    consistent: bool


@dataclass(frozen=True, slots=True)
class FtsCandidate:
    entity_type: str
    entity_id: str
    role_profile_id: str | None


def _search_error(
    code: ErrorCode,
    *,
    cause: Exception | None = None,
) -> KnowledgeDatabaseError:
    return KnowledgeDatabaseError(
        code=code,
        user_message=_SAFE_SEARCH_MESSAGE,
        recoverable=True,
        cause=cause,
    )


def detect_fts5_capability(
    *,
    connection: sqlite3.Connection | None = None,
    probe: Callable[[], None] | None = None,
) -> KnowledgeSearchCapabilityStatus:
    """Probe FTS5 by creating and removing one temporary in-memory table."""
    if probe is not None:
        try:
            probe()
        except sqlite3.OperationalError as exc:
            if "fts5" in str(exc).casefold():
                return KnowledgeSearchCapabilityStatus.UNAVAILABLE
            return KnowledgeSearchCapabilityStatus.PROBE_FAILED
        except Exception:
            return KnowledgeSearchCapabilityStatus.PROBE_FAILED
        return KnowledgeSearchCapabilityStatus.AVAILABLE

    owns_connection = connection is None
    candidate = connection or sqlite3.connect(":memory:")
    try:
        candidate.execute(
            "CREATE VIRTUAL TABLE temp.jobfit_fts_probe USING fts5(content)"
        )
        candidate.execute("DROP TABLE temp.jobfit_fts_probe")
        return KnowledgeSearchCapabilityStatus.AVAILABLE
    except sqlite3.OperationalError as exc:
        with suppress(sqlite3.Error):
            candidate.execute("DROP TABLE IF EXISTS temp.jobfit_fts_probe")
        if "fts5" in str(exc).casefold():
            return KnowledgeSearchCapabilityStatus.UNAVAILABLE
        return KnowledgeSearchCapabilityStatus.PROBE_FAILED
    except sqlite3.Error:
        return KnowledgeSearchCapabilityStatus.PROBE_FAILED
    finally:
        if owns_connection:
            candidate.close()


def _json_strings(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        values = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise _search_error(
            ErrorCode.KNOWLEDGE_SEARCH_INDEX_INVALID,
            cause=exc,
        ) from exc
    if not isinstance(values, list) or any(
        not isinstance(value, str) for value in values
    ):
        raise _search_error(ErrorCode.KNOWLEDGE_SEARCH_INDEX_INVALID)
    return tuple(values)


def _searchable_text(*values: str | None, collections: Sequence[str] = ()) -> str:
    text_values = tuple(value for value in values if value)
    return " ".join(normalize_query_terms((*text_values, *collections)))


class KnowledgeSearchIndex:
    """Manage an optional derivative index without changing core schema facts."""

    def __init__(
        self,
        database: KnowledgeDatabase,
        *,
        capability_override: KnowledgeSearchCapabilityStatus | None = None,
    ) -> None:
        self._database = database
        self._capability_override = capability_override
        self._capability: KnowledgeSearchCapabilityStatus | None = None

    def detect(self) -> KnowledgeSearchCapabilityStatus:
        if self._capability is None:
            self._capability = (
                self._capability_override or detect_fts5_capability()
            )
        return self._capability

    def capabilities(
        self,
        mode: KnowledgeSearchMode,
        *,
        enabled: bool = True,
    ) -> KnowledgeSearchCapabilities:
        if not enabled:
            return KnowledgeSearchCapabilities()
        if mode is KnowledgeSearchMode.KEYWORD:
            return KnowledgeSearchCapabilities(
                mode=KnowledgeSearchBackend.KEYWORD_FALLBACK,
                status=KnowledgeSearchCapabilityStatus.AVAILABLE,
                keyword_fallback_available=True,
            )
        status = self.detect()
        if status is KnowledgeSearchCapabilityStatus.AVAILABLE:
            return KnowledgeSearchCapabilities(
                mode=KnowledgeSearchBackend.FTS5,
                fts5_available=True,
                status=status,
                keyword_fallback_available=True,
                search_index_version=KNOWLEDGE_SEARCH_INDEX_VERSION,
            )
        if mode is KnowledgeSearchMode.AUTO:
            return KnowledgeSearchCapabilities(
                mode=KnowledgeSearchBackend.KEYWORD_FALLBACK,
                status=status,
                keyword_fallback_available=True,
            )
        return KnowledgeSearchCapabilities(
            mode=KnowledgeSearchBackend.DISABLED,
            status=status,
            keyword_fallback_available=True,
        )

    def create_if_supported(self) -> bool:
        if self.detect() is not KnowledgeSearchCapabilityStatus.AVAILABLE:
            return False
        self._database.ensure_compatible_schema()
        try:
            with self._database._engine.begin() as connection:
                connection.exec_driver_sql(
                    f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS {_FTS_TABLE} USING fts5(
                        entity_type UNINDEXED,
                        entity_id UNINDEXED,
                        knowledge_version_id UNINDEXED,
                        role_profile_id UNINDEXED,
                        job_family_code UNINDEXED,
                        source_id UNINDEXED,
                        search_text,
                        tokenize='unicode61'
                    )
                    """
                )
                connection.exec_driver_sql(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_META_TABLE} (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    text(
                        f"""
                        INSERT INTO {_META_TABLE}(key, value)
                        VALUES ('index_version', :version)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value
                        """
                    ),
                    {"version": KNOWLEDGE_SEARCH_INDEX_VERSION},
                )
        except SQLAlchemyError as exc:
            raise _search_error(
                ErrorCode.KNOWLEDGE_SEARCH_FAILED,
                cause=exc,
            ) from exc
        return True

    def has_index_objects(self) -> bool:
        if not self._database.path.is_file():
            return False
        try:
            with self._database._engine.connect() as connection:
                return bool(
                    connection.execute(
                        text(
                            """
                            SELECT 1 FROM sqlite_master
                            WHERE name = :name AND type = 'table'
                            """
                        ),
                        {"name": _FTS_TABLE},
                    ).first()
                )
        except SQLAlchemyError:
            return False

    def rebuild_version(self, version_id: str) -> SearchIndexReport:
        if not self.create_if_supported():
            raise _search_error(ErrorCode.KNOWLEDGE_SEARCH_UNAVAILABLE)
        try:
            rows = self._index_rows(version_id)
            if rows is None:
                raise _search_error(ErrorCode.KNOWLEDGE_SEARCH_UNAVAILABLE)
            with self._database._engine.begin() as connection:
                connection.execute(
                    text(
                        f"DELETE FROM {_FTS_TABLE} "
                        "WHERE knowledge_version_id = :version_id"
                    ),
                    {"version_id": version_id},
                )
                for row in rows:
                    connection.execute(
                        text(
                            f"""
                            INSERT INTO {_FTS_TABLE}(
                                entity_type,
                                entity_id,
                                knowledge_version_id,
                                role_profile_id,
                                job_family_code,
                                source_id,
                                search_text
                            ) VALUES (
                                :entity_type,
                                :entity_id,
                                :knowledge_version_id,
                                :role_profile_id,
                                :job_family_code,
                                :source_id,
                                :search_text
                            )
                            """
                        ),
                        row,
                    )
            return self.verify_version(version_id)
        except KnowledgeDatabaseError:
            raise
        except SQLAlchemyError as exc:
            raise _search_error(
                ErrorCode.KNOWLEDGE_SEARCH_FAILED,
                cause=exc,
            ) from exc

    def _index_rows(self, version_id: str) -> list[dict[str, Any]] | None:
        with self._database._session_scope() as session:
            published = session.execute(
                text(
                    """
                    SELECT 1 FROM knowledge_base_versions
                    WHERE id = :version_id AND status = 'published'
                    """
                ),
                {"version_id": version_id},
            ).first()
            if published is None:
                return None
            rows: list[dict[str, Any]] = []
            role_rows = session.execute(
                text(
                    """
                    SELECT rp.id, rp.code, rp.name, rp.aliases_json,
                           rp.keywords_json, rp.description, jf.code
                    FROM role_profiles rp
                    JOIN job_families jf ON jf.id = rp.job_family_id
                    WHERE rp.knowledge_version_id = :version_id
                      AND rp.review_status = 'approved'
                      AND rp.is_active = 1
                      AND jf.is_active = 1
                    ORDER BY rp.id
                    """
                ),
                {"version_id": version_id},
            )
            for role_id, code, name, aliases, keywords, description, family in role_rows:
                rows.append(
                    self._row(
                        "role_profile",
                        role_id,
                        version_id,
                        role_id,
                        family,
                        None,
                        code,
                        name,
                        description,
                        collections=(*_json_strings(aliases), *_json_strings(keywords)),
                    )
                )

            requirement_rows = session.execute(
                text(
                    """
                    SELECT rr.id, rr.role_profile_id, jf.code, rr.source_id, rr.title,
                           rr.description, rr.keywords_json,
                           rr.expected_evidence_json, rr.weak_evidence_json,
                           rr.negative_signals_json
                    FROM role_requirements rr
                    JOIN role_profiles rp ON rp.id = rr.role_profile_id
                    JOIN job_families jf ON jf.id = rp.job_family_id
                    JOIN competency_dimensions cd
                      ON cd.id = rr.competency_dimension_id
                    JOIN knowledge_sources ks ON ks.id = rr.source_id
                    WHERE rr.knowledge_version_id = :version_id
                      AND rr.review_status = 'approved'
                      AND rr.is_active = 1
                      AND rp.review_status = 'approved'
                      AND rp.is_active = 1
                      AND jf.is_active = 1
                      AND cd.review_status = 'approved'
                      AND cd.is_active = 1
                      AND ks.review_status = 'approved'
                    ORDER BY rr.id
                    """
                ),
                {"version_id": version_id},
            )
            for values in requirement_rows:
                (
                    item_id,
                    role_id,
                    family,
                    source_id,
                    title,
                    description,
                    keywords,
                    expected,
                    weak,
                    negative,
                ) = values
                rows.append(
                    self._row(
                        "role_requirement",
                        item_id,
                        version_id,
                        role_id,
                        family,
                        source_id,
                        title,
                        description,
                        collections=(
                            *_json_strings(keywords),
                            *_json_strings(expected),
                            *_json_strings(weak),
                            *_json_strings(negative),
                        ),
                    )
                )

            chunk_rows = session.execute(
                text(
                    """
                    SELECT kc.id, kc.role_profile_id, jf.code, kc.source_id, kc.section,
                           kc.chunk_text, kc.keywords_json
                    FROM knowledge_chunks kc
                    JOIN knowledge_sources ks ON ks.id = kc.source_id
                    LEFT JOIN role_profiles rp ON rp.id = kc.role_profile_id
                    LEFT JOIN job_families jf ON jf.id = rp.job_family_id
                    WHERE kc.knowledge_version_id = :version_id
                      AND kc.review_status = 'approved'
                      AND ks.review_status = 'approved'
                      AND (
                        kc.role_profile_id IS NULL OR (
                          rp.review_status = 'approved'
                          AND rp.is_active = 1
                          AND jf.is_active = 1
                        )
                      )
                    ORDER BY kc.id
                    """
                ),
                {"version_id": version_id},
            )
            for (
                item_id,
                role_id,
                family,
                source_id,
                section,
                chunk_text,
                keywords,
            ) in chunk_rows:
                rows.append(
                    self._row(
                        "knowledge_chunk",
                        item_id,
                        version_id,
                        role_id,
                        family,
                        source_id,
                        section,
                        chunk_text,
                        collections=_json_strings(keywords),
                    )
                )

            question_rows = session.execute(
                text(
                    """
                    SELECT iq.id, iq.role_profile_id, jf.code, iq.source_id, iq.question,
                           iq.expected_points_json, iq.follow_up_questions_json
                    FROM interview_questions iq
                    JOIN role_profiles rp ON rp.id = iq.role_profile_id
                    JOIN job_families jf ON jf.id = rp.job_family_id
                    JOIN competency_dimensions cd
                      ON cd.id = iq.competency_dimension_id
                    JOIN knowledge_sources ks ON ks.id = iq.source_id
                    WHERE iq.knowledge_version_id = :version_id
                      AND iq.review_status = 'approved'
                      AND iq.is_active = 1
                      AND rp.review_status = 'approved'
                      AND rp.is_active = 1
                      AND jf.is_active = 1
                      AND cd.review_status = 'approved'
                      AND cd.is_active = 1
                      AND ks.review_status = 'approved'
                    ORDER BY iq.id
                    """
                ),
                {"version_id": version_id},
            )
            for (
                item_id,
                role_id,
                family,
                source_id,
                question,
                expected,
                follow_up,
            ) in question_rows:
                rows.append(
                    self._row(
                        "interview_question",
                        item_id,
                        version_id,
                        role_id,
                        family,
                        source_id,
                        question,
                        collections=(
                            *_json_strings(expected),
                            *_json_strings(follow_up),
                        ),
                    )
                )
            return rows

    @staticmethod
    def _row(
        entity_type: str,
        entity_id: str,
        version_id: str,
        role_profile_id: str | None,
        job_family_code: str | None,
        source_id: str | None,
        *values: str | None,
        collections: Sequence[str] = (),
    ) -> dict[str, Any]:
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "knowledge_version_id": version_id,
            "role_profile_id": role_profile_id,
            "job_family_code": job_family_code,
            "source_id": source_id,
            "search_text": _searchable_text(*values, collections=collections),
        }

    def remove_version(self, version_id: str) -> None:
        if not self.has_index_objects():
            return
        try:
            with self._database._engine.begin() as connection:
                connection.execute(
                    text(
                        f"DELETE FROM {_FTS_TABLE} "
                        "WHERE knowledge_version_id = :version_id"
                    ),
                    {"version_id": version_id},
                )
        except SQLAlchemyError as exc:
            raise _search_error(
                ErrorCode.KNOWLEDGE_SEARCH_FAILED,
                cause=exc,
            ) from exc

    def verify_version(self, version_id: str) -> SearchIndexReport:
        empty = SearchIndexCounts(
            role_profiles=0,
            role_requirements=0,
            knowledge_chunks=0,
            interview_questions=0,
        )
        if not self.has_index_objects():
            return SearchIndexReport(
                version_id=version_id,
                counts=empty,
                consistent=False,
            )
        try:
            expected_rows = self._index_rows(version_id)
            if expected_rows is None:
                return SearchIndexReport(
                    version_id=version_id,
                    counts=empty,
                    consistent=False,
                )
            expected = self._counts(expected_rows)
            with self._database._engine.connect() as connection:
                indexed_rows = connection.execute(
                    text(
                        f"""
                        SELECT entity_type, entity_id
                        FROM {_FTS_TABLE}
                        WHERE knowledge_version_id = :version_id
                        ORDER BY entity_type, entity_id
                        """
                    ),
                    {"version_id": version_id},
                ).all()
                meta = connection.execute(
                    text(
                        f"SELECT value FROM {_META_TABLE} "
                        "WHERE key = 'index_version'"
                    )
                ).scalar_one_or_none()
            indexed_dicts = [
                {"entity_type": entity_type, "entity_id": entity_id}
                for entity_type, entity_id in indexed_rows
            ]
            actual = self._counts(indexed_dicts)
            expected_identities = {
                (row["entity_type"], row["entity_id"])
                for row in expected_rows
            }
            actual_identities = {
                (entity_type, entity_id)
                for entity_type, entity_id in indexed_rows
            }
            return SearchIndexReport(
                version_id=version_id,
                counts=actual,
                consistent=actual == expected
                and actual_identities == expected_identities
                and meta == KNOWLEDGE_SEARCH_INDEX_VERSION,
            )
        except KnowledgeDatabaseError:
            raise
        except SQLAlchemyError as exc:
            raise _search_error(
                ErrorCode.KNOWLEDGE_SEARCH_FAILED,
                cause=exc,
            ) from exc

    @staticmethod
    def _counts(rows: Sequence[dict[str, Any]]) -> SearchIndexCounts:
        return SearchIndexCounts(
            role_profiles=sum(
                row["entity_type"] == "role_profile" for row in rows
            ),
            role_requirements=sum(
                row["entity_type"] == "role_requirement" for row in rows
            ),
            knowledge_chunks=sum(
                row["entity_type"] == "knowledge_chunk" for row in rows
            ),
            interview_questions=sum(
                row["entity_type"] == "interview_question" for row in rows
            ),
        )

    def search_candidates(
        self,
        *,
        version_id: str,
        entity_types: Sequence[str],
        tokens: Sequence[str],
        role_profile_ids: Sequence[str] = (),
        job_family_codes: Sequence[str] = (),
        source_ids: Sequence[str] = (),
        limit: int,
    ) -> list[FtsCandidate]:
        if not self.has_index_objects() or not tokens:
            return []
        safe_limit = min(max(int(limit), 1), MAX_FTS_CANDIDATES)
        expression = build_fts_match_expression(tokens)
        entity_placeholders = ", ".join("?" for _ in entity_types)
        role_clause = ""
        parameters: list[Any] = [
            expression,
            version_id,
            *entity_types,
        ]
        if role_profile_ids:
            role_placeholders = ", ".join("?" for _ in role_profile_ids)
            role_clause = f" AND role_profile_id IN ({role_placeholders})"
            parameters.extend(role_profile_ids)
        if job_family_codes:
            family_placeholders = ", ".join("?" for _ in job_family_codes)
            role_clause += (
                f" AND job_family_code IN ({family_placeholders})"
            )
            parameters.extend(job_family_codes)
        if source_ids:
            source_placeholders = ", ".join("?" for _ in source_ids)
            role_clause += f" AND source_id IN ({source_placeholders})"
            parameters.extend(source_ids)
        parameters.append(safe_limit)
        sql = (
            f"SELECT entity_type, entity_id, role_profile_id "
            f"FROM {_FTS_TABLE} "
            f"WHERE {_FTS_TABLE} MATCH ? "
            f"AND knowledge_version_id = ? "
            f"AND entity_type IN ({entity_placeholders})"
            f"{role_clause} "
            f"ORDER BY entity_type, entity_id LIMIT ?"
        )
        try:
            with self._database._engine.connect() as connection:
                rows = connection.exec_driver_sql(sql, tuple(parameters)).all()
            return [
                FtsCandidate(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    role_profile_id=role_profile_id,
                )
                for entity_type, entity_id, role_profile_id in rows
            ]
        except SQLAlchemyError as exc:
            raise _search_error(
                ErrorCode.KNOWLEDGE_SEARCH_FAILED,
                cause=exc,
            ) from exc


__all__ = [
    "KNOWLEDGE_SEARCH_INDEX_VERSION",
    "MAX_FTS_CANDIDATES",
    "FtsCandidate",
    "KnowledgeSearchIndex",
    "SearchIndexCounts",
    "SearchIndexReport",
    "detect_fts5_capability",
]
