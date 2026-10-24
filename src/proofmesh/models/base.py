from datetime import datetime, timezone
from types import MappingProxyType
from typing import Annotated, Any, Mapping, Sequence
from pydantic import BaseModel, ConfigDict, PlainSerializer, StringConstraints


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
        arbitrary_types_allowed=True,
    )


def validate_utc_datetime(v: datetime) -> datetime:
    """Enforce timezone-awareness and normalize to UTC."""
    if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
        raise ValueError("Timestamp must be timezone-aware")
    return v.astimezone(timezone.utc)


def to_immutable_tuple(v: Any) -> tuple:
    """Coerce sequences into immutable tuples."""
    if isinstance(v, tuple):
        return v
    if isinstance(v, (list, Sequence)) and not isinstance(v, (str, bytes)):
        return tuple(v)
    return v


def to_immutable_dict(v: Any) -> MappingProxyType:
    """Coerce dicts into read-only MappingProxyType."""
    if isinstance(v, MappingProxyType):
        return v
    if isinstance(v, Mapping):
        return MappingProxyType(dict(v))
    raise ValueError("Must be a mapping/dictionary")


# Immutable dictionary type that serializes cleanly to JSON/dict
ImmutableDict = Annotated[
    MappingProxyType[str, Any],
    PlainSerializer(lambda v: dict(v), return_type=dict),
]

# Common constrained types matching TRD §5.6
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
CriterionId = Annotated[str, StringConstraints(pattern=r"^(?:AC-\d{1,4}|[a-z0-9][a-z0-9-]{0,63})$")]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
