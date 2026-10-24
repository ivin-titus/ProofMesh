from datetime import datetime
from enum import StrEnum
from pydantic import Field, field_validator
from proofmesh.models.base import (
    Identifier,
    Sha256Digest,
    StrictModel,
    validate_utc_datetime,
)


class OperatingProfile(StrEnum):
    GUIDED = "guided"
    FLOW = "flow"
    STRICT = "strict"


class IntegrationStatus(StrEnum):
    ENFORCED = "enforced"
    PARTIAL = "partial"
    UNGUARDED = "unguarded"


class SessionState(StrEnum):
    ACTIVE = "ACTIVE"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"
    ACCEPTED = "ACCEPTED"
    BLOCKED = "BLOCKED"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"
    UNKNOWN = "UNKNOWN"
    CLOSED = "CLOSED"


class Session(StrictModel):
    session_id: Identifier
    task_id: Identifier
    contract_revision: int = Field(ge=1)
    repo_root: str = Field(min_length=1, max_length=1000)
    baseline_snapshot_id: Sha256Digest | Identifier
    current_snapshot_id: Sha256Digest | Identifier | None = None
    profile: OperatingProfile = OperatingProfile.FLOW
    policy_digest: Sha256Digest
    integration_status: IntegrationStatus = IntegrationStatus.PARTIAL
    state: SessionState = SessionState.ACTIVE
    started_at: datetime
    ended_at: datetime | None = None

    @field_validator("started_at")
    @classmethod
    def check_started_at(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)

    @field_validator("ended_at")
    @classmethod
    def check_ended_at(cls, v: datetime | None) -> datetime | None:
        if v is not None:
            return validate_utc_datetime(v)
        return None
