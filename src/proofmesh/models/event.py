from datetime import datetime
from typing import Any
from pydantic import Field, field_validator
from proofmesh.models.base import (
    FrozenModel,
    Identifier,
    validate_utc_datetime,
)


class EventRecord(FrozenModel):
    event_id: Identifier
    session_id: Identifier
    source_adapter: str = Field(min_length=1, max_length=64)
    event_type: str = Field(min_length=1, max_length=64)
    occurred_at: datetime
    agent_id: str | None = Field(default=None, max_length=64)
    parent_agent_id: str | None = Field(default=None, max_length=64)
    host_turn_id: str | None = Field(default=None, max_length=128)
    command_signature: str | None = Field(default=None, max_length=512)
    exit_status: int | None = None
    snapshot_before: Identifier | None = None
    snapshot_after: Identifier | None = None
    summary: str = Field(min_length=1, max_length=2000)
    payload_schema_version: int = Field(default=1, ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def check_occurred_at(cls, v: datetime) -> datetime:
        return validate_utc_datetime(v)
