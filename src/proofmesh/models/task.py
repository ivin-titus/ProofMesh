from datetime import datetime
from enum import StrEnum
from pydantic import Field, field_validator
from proofmesh.models.base import (
    CriterionId,
    FrozenModel,
    Identifier,
    Sha256Digest,
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
    required_gates: list[Identifier] = Field(default_factory=list, max_length=20)


class ScopePolicy(FrozenModel):
    allow_paths: list[str] = Field(default_factory=list, max_length=100)
    restricted_paths: list[str] = Field(default_factory=list, max_length=100)
    max_changed_files: int | None = Field(default=None, ge=1, le=1000)


class TaskRevision(FrozenModel):
    task_id: Identifier
    revision: int = Field(ge=1)
    summary: str = Field(min_length=1, max_length=2000)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list, max_length=50)
    scope: ScopePolicy = Field(default_factory=ScopePolicy)
    required_gates: list[Identifier] = Field(default_factory=list, max_length=20)
    constraints: list[str] = Field(default_factory=list, max_length=50)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    approval_status: ApprovalStatus = ApprovalStatus.PROPOSED
    approved_by: str | None = Field(default=None, max_length=128)
    approved_at: datetime | None = None
    contract_digest: Sha256Digest

    @field_validator("approved_at")
    @classmethod
    def check_approved_at(cls, v: datetime | None) -> datetime | None:
        if v is not None:
            return validate_utc_datetime(v)
        return None
