from datetime import datetime, timezone
from typing import Annotated
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator


class StrictModel(BaseModel):
    """Base class for all domain models enforcing strict validation and runtime safety."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        validate_default=True,
        revalidate_instances="always",
        str_max_length=10_000,
    )


class FrozenModel(StrictModel):
    """Immutable model for value objects, approved revisions, evidence records, and verdicts."""

    model_config = ConfigDict(
        frozen=True,
    )


def validate_utc_datetime(v: datetime) -> datetime:
    """Enforce timezone-awareness and normalize to UTC."""
    if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
        raise ValueError("Timestamp must be timezone-aware")
    return v.astimezone(timezone.utc)


# Common constrained types
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")]
CriterionId = Annotated[str, StringConstraints(pattern=r"^(?:AC-)?[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
