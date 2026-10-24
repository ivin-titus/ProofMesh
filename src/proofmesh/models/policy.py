from pydantic import Field, field_validator
from proofmesh.models.base import (
    FrozenModel,
    Identifier,
    ImmutableDict,
    to_immutable_dict,
    to_immutable_tuple,
)
from proofmesh.models.session import OperatingProfile


class BudgetPolicy(FrozenModel):
    max_retries: int = Field(default=3, ge=1, le=20)
    max_continuation_steps: int = Field(default=10, ge=1, le=50)
    max_changed_files: int = Field(default=50, ge=1, le=1000)


class ScopeDefaultPolicy(FrozenModel):
    default_allow_paths: tuple[str, ...] = Field(default=("src/**", "tests/**"))
    default_restricted_paths: tuple[str, ...] = Field(default=(".git/**", ".github/**"))

    @field_validator("default_allow_paths", "default_restricted_paths", mode="before")
    @classmethod
    def convert_paths(cls, v: object) -> object:
        return to_immutable_tuple(v)


class GatePolicy(FrozenModel):
    provider: str = Field(min_length=1, max_length=64)
    command: tuple[str, ...] = Field(min_length=1)
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    mandatory: bool = True

    @field_validator("command", mode="before")
    @classmethod
    def convert_command(cls, v: object) -> object:
        return to_immutable_tuple(v)


class AdvisorPolicy(FrozenModel):
    enabled: bool = False
    protocol: str = Field(default="systemone", max_length=32)
    url: str | None = None
    timeout_ms: int = Field(default=2000, ge=100, le=30000)


class TrustedPolicy(FrozenModel):
    schema_version: int = Field(default=1, ge=1)
    profile: OperatingProfile = OperatingProfile.FLOW
    budget: BudgetPolicy = Field(default_factory=BudgetPolicy)
    scope: ScopeDefaultPolicy = Field(default_factory=ScopeDefaultPolicy)
    gates: ImmutableDict = Field(default_factory=dict)
    advisor: AdvisorPolicy = Field(default_factory=AdvisorPolicy)

    @field_validator("profile", mode="before")
    @classmethod
    def convert_profile(cls, v: object) -> object:
        if isinstance(v, str):
            return OperatingProfile(v)
        return v

    @field_validator("gates", mode="before")
    @classmethod
    def convert_gates(cls, v: object) -> object:
        if isinstance(v, dict):
            # Parse dict values into GatePolicy if needed
            converted = {}
            for k, val in v.items():
                if isinstance(val, dict):
                    converted[k] = GatePolicy.model_validate(val)
                else:
                    converted[k] = val
            return to_immutable_dict(converted)
        return to_immutable_dict(v)
