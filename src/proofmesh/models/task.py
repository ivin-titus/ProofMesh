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


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class AcceptanceCriterion(FrozenModel):
    criterion_id: CriterionId
    description: str = Field(min_length=1, max_length=1000)
    required_gates: tuple[Identifier, ...] = Field(default_factory=tuple)

    @field_validator("required_gates", mode="before")
    @classmethod
    def convert_required_gates(cls, v: object) -> object:
        return to_immutable_tuple(v)


class ScopePolicy(FrozenModel):
    allow_paths: tuple[str, ...] = Field(default_factory=tuple)
    restricted_paths: tuple[str, ...] = Field(default_factory=tuple)
    max_changed_files: int | None = Field(default=None, ge=1, le=1000)

    @field_validator("allow_paths", "restricted_paths", mode="before")
    @classmethod
    def convert_paths(cls, v: object) -> object:
        return to_immutable_tuple(v)


class TaskRevision(FrozenModel):
    task_id: Identifier
    revision: int = Field(ge=1)
    parent_revision: int | None = Field(default=None, ge=1)
    summary: str = Field(min_length=1, max_length=2000)
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = Field(default_factory=tuple)
    scope: ScopePolicy = Field(default_factory=ScopePolicy)
    required_gates: tuple[Identifier, ...] = Field(default_factory=tuple)
    constraints: tuple[str, ...] = Field(default_factory=tuple)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    approval_status: ApprovalStatus = ApprovalStatus.PROPOSED
    approved_by: str | None = Field(default=None, max_length=128)
    approved_at: datetime | None = None
    contract_digest: Sha256Digest
    raw_markdown: str | None = Field(default=None, max_length=65536)

    @field_validator("acceptance_criteria", "required_gates", "constraints", mode="before")
    @classmethod
    def convert_sequences(cls, v: object) -> object:
        return to_immutable_tuple(v)

    @field_validator("approved_at")
    @classmethod
    def check_approved_at(cls, v: datetime | None) -> datetime | None:
        if v is not None:
            return validate_utc_datetime(v)
        return None
