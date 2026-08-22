"""B6 analysis-history repository boundary and process-local adapter."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Protocol, runtime_checkable

from pydantic import ConfigDict, model_validator

from jobfit.models import DocumentContent
from jobfit.models.common import NonEmptyStr, StrictModel
from jobfit.models.v2 import AnalysisRun, LifecycleStatus, UserClarification


class AnalysisHistoryError(ValueError):
    """An append would overwrite or break analysis lineage."""


class PersistedAnalysis(StrictModel):
    """Minimum restart-safe record kept behind the B6 repository boundary."""

    model_config = ConfigDict(frozen=True)

    run: AnalysisRun
    resume_version_id: NonEmptyStr
    jd_snapshot_id: NonEmptyStr
    resume_document: DocumentContent | None = None
    jd_document: DocumentContent | None = None
    user_clarifications: tuple[UserClarification, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self) -> PersistedAnalysis:
        snapshot = self.run.input_snapshot
        if snapshot is not None and (
            snapshot.resume_version_id != self.resume_version_id
            or snapshot.jd_snapshot_id != self.jd_snapshot_id
        ):
            raise ValueError("Persisted input identities differ from the frozen snapshot.")
        if any(
            item.analysis_id != self.run.analysis_id
            for item in self.user_clarifications
        ):
            raise ValueError("Persisted clarification belongs to another analysis.")
        return self

    @classmethod
    def from_documents(
        cls,
        *,
        run: AnalysisRun,
        resume_version_id: str,
        jd_snapshot_id: str,
        resume_document: DocumentContent,
        jd_document: DocumentContent,
        user_clarifications: tuple[UserClarification, ...] = (),
    ) -> PersistedAnalysis:
        return cls(
            run=run,
            resume_version_id=resume_version_id,
            jd_snapshot_id=jd_snapshot_id,
            resume_document=_sanitize_document(resume_document),
            jd_document=_sanitize_document(jd_document),
            user_clarifications=user_clarifications,
        )


@runtime_checkable
class AnalysisRepository(Protocol):
    def save_working_analysis(self, record: PersistedAnalysis) -> None: ...

    def append_analysis(self, run: AnalysisRun) -> None: ...

    def get_analysis(self, analysis_id: str) -> AnalysisRun | None: ...

    def get_persisted_analysis(self, analysis_id: str) -> PersistedAnalysis | None: ...

    def list_analyses(self) -> tuple[AnalysisRun, ...]: ...

    def list_analysis_versions(self) -> tuple[AnalysisRun, ...]: ...

    def get_parent(self, analysis_id: str) -> AnalysisRun | None: ...

    def delete_analysis_chain(self, analysis_id: str) -> int: ...

    def delete_all_analysis_data(self) -> int: ...

    def dispose(self) -> None: ...


class InMemoryAnalysisRepository:
    """Process-local proof adapter; it performs no durable user-data writes."""

    def __init__(self) -> None:
        self._records: dict[str, bytes] = {}
        self._order: list[str] = []

    def save_working_analysis(self, record: PersistedAnalysis) -> None:
        if _is_terminal(record.run):
            raise AnalysisHistoryError("Working analysis cannot be terminal.")
        existing = self.get_persisted_analysis(record.run.analysis_id)
        if existing is not None:
            if _is_terminal(existing.run):
                raise AnalysisHistoryError("Completed analysis history is immutable.")
            _validate_working_replacement(existing, record)
        else:
            self._validate_parent(record.run)
            self._order.append(record.run.analysis_id)
        self._records[record.run.analysis_id] = record.model_dump_json().encode("utf-8")

    def append_analysis(self, run: AnalysisRun) -> None:
        if not _is_terminal(run):
            raise AnalysisHistoryError("Only terminal analysis runs enter history.")
        existing = self.get_persisted_analysis(run.analysis_id)
        if existing is not None:
            if _is_terminal(existing.run):
                raise AnalysisHistoryError(
                    f"Analysis {run.analysis_id!r} already exists and cannot be overwritten."
                )
            replacement = existing.model_copy(update={"run": run})
            replacement = PersistedAnalysis.model_validate(
                replacement.model_dump(mode="python")
            )
            _validate_working_replacement(existing, replacement)
        else:
            self._validate_parent(run)
            replacement = _record_from_terminal_run(run)
            self._order.append(run.analysis_id)
        self._records[run.analysis_id] = replacement.model_dump_json().encode("utf-8")

    def get_analysis(self, analysis_id: str) -> AnalysisRun | None:
        record = self.get_persisted_analysis(analysis_id)
        return None if record is None else record.run

    def get_persisted_analysis(self, analysis_id: str) -> PersistedAnalysis | None:
        payload = self._records.get(analysis_id)
        return None if payload is None else PersistedAnalysis.model_validate_json(payload)

    def list_analyses(self) -> tuple[AnalysisRun, ...]:
        return tuple(self.get_persisted_analysis(item).run for item in self._order)

    def list_analysis_versions(self) -> tuple[AnalysisRun, ...]:
        return tuple(
            record.run
            for analysis_id in self._order
            if (record := self.get_persisted_analysis(analysis_id)) is not None
            and _is_terminal(record.run)
        )

    def get_parent(self, analysis_id: str) -> AnalysisRun | None:
        run = self.get_analysis(analysis_id)
        if run is None or run.parent_analysis_id is None:
            return None
        return self.get_analysis(run.parent_analysis_id)

    def delete_analysis_chain(self, analysis_id: str) -> int:
        if analysis_id not in self._records:
            return 0
        targets = _descendant_ids(self.list_analyses(), analysis_id)
        for target in targets:
            self._records.pop(target, None)
        self._order = [item for item in self._order if item not in targets]
        return len(targets)

    def delete_all_analysis_data(self) -> int:
        count = len(self._records)
        self._records.clear()
        self._order.clear()
        return count

    def dispose(self) -> None:
        """Mirror the durable adapter lifecycle without owning resources."""

    def _validate_parent(self, run: AnalysisRun) -> None:
        if run.parent_analysis_id is None:
            return
        parent = self.get_analysis(run.parent_analysis_id)
        if parent is None:
            raise AnalysisHistoryError("Analysis parent does not exist.")
        if not _is_terminal(parent):
            raise AnalysisHistoryError("Analysis parent must be terminal.")


def _sanitize_document(document: DocumentContent) -> DocumentContent:
    filename = document.original_filename
    if filename is not None:
        filename = PurePosixPath(filename.replace("\\", "/")).name
    safe_metadata = {
        key: value
        for key, value in document.metadata.items()
        if not any(token in key.casefold() for token in ("path", "directory"))
    }
    payload = document.model_dump(mode="python")
    payload.update(
        {
            "original_filename": filename,
            "source": None,
            "metadata": safe_metadata,
            "warnings": [],
        }
    )
    return DocumentContent.model_validate(payload)


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


def _validate_working_replacement(
    existing: PersistedAnalysis,
    replacement: PersistedAnalysis,
) -> None:
    if existing.run.parent_analysis_id != replacement.run.parent_analysis_id:
        raise AnalysisHistoryError("Analysis lineage cannot be changed in place.")
    if (
        existing.resume_version_id != replacement.resume_version_id
        or existing.jd_snapshot_id != replacement.jd_snapshot_id
        or existing.resume_document != replacement.resume_document
        or existing.jd_document != replacement.jd_document
    ):
        raise AnalysisHistoryError("Analysis source identity cannot be changed in place.")
    if (
        existing.run.input_snapshot is not None
        and existing.run.input_snapshot != replacement.run.input_snapshot
    ):
        raise AnalysisHistoryError("Frozen analysis input snapshot is immutable.")


def _descendant_ids(runs: tuple[AnalysisRun, ...], root_id: str) -> set[str]:
    targets = {root_id}
    changed = True
    while changed:
        changed = False
        for run in runs:
            if run.parent_analysis_id in targets and run.analysis_id not in targets:
                targets.add(run.analysis_id)
                changed = True
    return targets


def _is_terminal(run: AnalysisRun) -> bool:
    return run.lifecycle.status in {LifecycleStatus.COMPLETED, LifecycleStatus.FAILED}
