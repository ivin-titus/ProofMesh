from enum import StrEnum
from pydantic import Field, field_validator
from proofmesh.models.base import FrozenModel, Sha256Digest, to_immutable_tuple


class ScopeChangeType(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class PathChange(FrozenModel):
    """Represents a detected change to a single path."""

    path: str = Field(min_length=1, max_length=1000)
    change_type: ScopeChangeType
    old_sha256: Sha256Digest | None = None
    new_sha256: Sha256Digest | None = None


class ScopeFinding(FrozenModel):
    """Policy finding for an individual changed path."""

    path: str = Field(min_length=1, max_length=1000)
    allowed: bool
    restricted: bool
    reason: str = Field(min_length=1, max_length=500)


class ScopeAnalysisResult(FrozenModel):
    """Result of comparing current repository snapshot against baseline under ScopePolicy."""

    baseline_snapshot_id: Sha256Digest
    current_snapshot_id: Sha256Digest
    changes: tuple[PathChange, ...] = Field(default_factory=tuple)
    findings: tuple[ScopeFinding, ...] = Field(default_factory=tuple)
    total_changed_files: int = Field(default=0, ge=0)
    exceeded_file_limit: bool = False
    has_violations: bool = False

    @field_validator("changes", "findings", mode="before")
    @classmethod
    def convert_sequences(cls, v: object) -> object:
        return to_immutable_tuple(v)
