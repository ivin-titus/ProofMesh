from datetime import datetime
from enum import StrEnum
from pydantic import Field, field_validator
from proofmesh.models.base import (
    FrozenModel,
    Identifier,
    validate_utc_datetime,
)


class VerdictOutcome(StrEnum):
    ALLOW = "ALLOW"
    WARN = "WARN"
    BLOCK = "BLOCK"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    UNKNOWN = "UNKNOWN"


class EnforcementLevel(StrEnum):
    ENFORCED = "enforced"
    PARTIAL = "partial"
    UNGUARDED = "unguarded"


class VerdictRecord(FrozenModel):
    verdict_id: Identifier
    session_id: Identifier
    contract_revision: int = Field(ge=1)
    snapshot_id: Identifier
    verdict: VerdictOutcome
    enforcement_level: EnforcementLevel
    reasons: list[str] = Field(default_factory=list, max_length=100)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def check_evaluated_at(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)
