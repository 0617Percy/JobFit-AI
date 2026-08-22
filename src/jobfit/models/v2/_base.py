"""Shared configuration for forward-extensible target domain objects."""

from pydantic import ConfigDict

from jobfit.models.common import StrictModel


class ExtensibleDomainModel(StrictModel):
    """Match the frozen structured schema's additional-properties contract."""

    model_config = ConfigDict(extra="allow")


def require_unique(values: list[str], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} values must be unique")
