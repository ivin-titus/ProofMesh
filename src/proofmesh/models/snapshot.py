from datetime import datetime
from pydantic import Field, field_validator
from proofmesh.models.base import (
    FrozenModel,
    Sha256Digest,
    to_immutable_tuple,
    validate_utc_datetime,
)


class FileFingerprint(FrozenModel):
    """Deterministic fingerprint for a file in the repository."""

    path: str = Field(min_length=1, max_length=1000)
    sha256: Sha256Digest
    size_bytes: int = Field(ge=0)
    is_tracked: bool = True


class RepoSnapshot(FrozenModel):
    """Deterministic repository snapshot capturing code state and Git baseline."""

    snapshot_id: Sha256Digest
    repo_root: str = Field(min_length=1, max_length=1000)
    git_commit: str | None = Field(default=None, max_length=64)
    git_dirty: bool = False
    files: tuple[FileFingerprint, ...] = Field(default_factory=tuple)
    captured_at: datetime

    @field_validator("files", mode="before")
    @classmethod
    def convert_files(cls, v: object) -> object:
        return to_immutable_tuple(v)

    @field_validator("captured_at")
    @classmethod
    def check_captured_at(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    def get_file(self, path: str) -> FileFingerprint | None:
        """Find fingerprint for a specific relative path."""
        for f in self.files:
            if f.path == path:
                return f
        return None

    @property
    def file_paths(self) -> set[str]:
        """Set of all relative file paths in this snapshot."""
        return {f.path for f in self.files}
