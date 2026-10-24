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


def freeze_value(v: Any) -> Any:
    """Recursively freeze mappings into MappingProxyType and sequences into tuples.
    
    Leaves strings, bytes, numbers, booleans, and None unchanged.
    """
    if isinstance(v, (str, bytes, int, float, bool, type(None))):
        return v
    if isinstance(v, Mapping):
        return MappingProxyType({k: freeze_value(val) for k, val in v.items()})
    if isinstance(v, (list, tuple, Sequence)):
        return tuple(freeze_value(item) for item in v)
    return v


def unfreeze_value(v: Any) -> Any:
    """Recursively convert MappingProxyType to dict and tuples to list for JSON serialization."""
    if isinstance(v, (MappingProxyType, Mapping)):
        return {k: unfreeze_value(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [unfreeze_value(item) for item in v]
    return v


def to_immutable_tuple(v: Any) -> tuple:
    """Coerce sequences and nested collections into deeply immutable tuples."""
    if isinstance(v, (str, bytes)):
        return v
    if isinstance(v, (list, tuple, Sequence)):
        return tuple(freeze_value(item) for item in v)
    return v


def to_immutable_dict(v: Any) -> MappingProxyType:
    """Coerce mappings and nested collections into deeply immutable MappingProxyType."""
    if v is None:
        return MappingProxyType({})
    if isinstance(v, Mapping):
        return freeze_value(v)
    raise ValueError("Must be a mapping/dictionary")


# Immutable dictionary type that serializes cleanly to JSON/dict
ImmutableDict = Annotated[
    MappingProxyType[str, Any],
    PlainSerializer(lambda v: unfreeze_value(v), return_type=dict),
]

# Common constrained types matching TRD §5.6
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
CriterionId = Annotated[str, StringConstraints(pattern=r"^(?:AC-\d{1,4}|[a-z0-9][a-z0-9-]{0,63})$")]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
