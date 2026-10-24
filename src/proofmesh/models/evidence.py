from datetime import datetime
from enum import StrEnum
from pydantic import Field, field_validator
from proofmesh.models.base import (
    CriterionId,
    FrozenModel,
    Identifier,
    Sha256Digest,
    to_immutable_tuple,
    validate_utc_datetime,
)


class EvidenceStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"


class EvidenceRecord(FrozenModel):
    evidence_id: Identifier
    session_id: Identifier
    contract_revision: int = Field(ge=1)
    gate_id: Identifier
    acceptance_criteria: tuple[CriterionId, ...] = Field(default_factory=tuple)
    provider_name: str = Field(min_length=1, max_length=128)
    provider_version: str = Field(min_length=1, max_length=64)
    config_digest: Sha256Digest
    started_at: datetime
    ended_at: datetime
    duration_ms: int = Field(ge=0)
    snapshot_before: Sha256Digest | Identifier
    snapshot_after: Sha256Digest | Identifier
    status: EvidenceStatus
    exit_code: int | None = None
    summary: str = Field(min_length=1, max_length=5000)
    invalidation_reason: str | None = Field(default=None, max_length=1000)

    @field_validator("acceptance_criteria", mode="before")
    @classmethod
    def convert_criteria(cls, v: object) -> object:
        return to_immutable_tuple(v)

    @field_validator("started_at")
    @classmethod
    def check_started_at(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    @field_validator("ended_at")
    @classmethod
    def check_ended_at(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)
