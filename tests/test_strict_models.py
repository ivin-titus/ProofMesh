from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from pydantic import ValidationError

from proofmesh.config import get_default_policy, load_policy
from proofmesh.models import (
    AcceptanceCriterion,
    ApprovalStatus,
    EnforcementLevel,
    EventRecord,
    EvidenceRecord,
    EvidenceStatus,
    IntegrationStatus,
    OperatingProfile,
    RiskLevel,
    ScopePolicy,
    Session,
    SessionState,
    TaskRevision,
    TrustedPolicy,
    VerdictOutcome,
    VerdictRecord,
)

SAMPLE_DIGEST = "sha256:" + "a" * 64


def test_strict_model_extra_fields_forbidden():
    """Verify that models forbid unexpected fields."""
    with pytest.raises(ValidationError) as exc:
        AcceptanceCriterion.model_validate({
            "criterion_id": "AC-1",
            "description": "Valid description",
            "extra_field": "unexpected",
        })
    assert "extra_forbidden" in str(exc.value)


def test_strict_model_rejects_type_coercion():
    """Verify strict mode forbids implicit type coercion."""
    with pytest.raises(ValidationError) as exc:
        TaskRevision(
            task_id="task-1",
            revision="1",  # type: ignore[arg-type]
            summary="Test",
            contract_digest=SAMPLE_DIGEST,
        )
    assert "int_type" in str(exc.value)


def test_naive_timestamp_rejected():
    """Verify timestamps must be timezone-aware."""
    naive_dt = datetime.now()
    with pytest.raises(ValidationError) as exc:
        Session(
            session_id="sess-1",
            task_id="task-1",
            contract_revision=1,
            repo_root="/repo",
            baseline_snapshot_id="snap-1",
            policy_digest=SAMPLE_DIGEST,
            started_at=naive_dt,
        )
    assert "Timestamp must be timezone-aware" in str(exc.value)


def test_timezone_normalized_to_utc():
    """Verify timezone-aware non-UTC timestamps normalize to UTC."""
    ist = timezone(timedelta(hours=5, minutes=30))
    ist_dt = datetime(2026, 10, 24, 23, 0, 0, tzinfo=ist)
    session = Session(
        session_id="sess-1",
        task_id="task-1",
        contract_revision=1,
        repo_root="/repo",
        baseline_snapshot_id="snap-1",
        policy_digest=SAMPLE_DIGEST,
        started_at=ist_dt,
    )
    assert session.started_at.tzinfo == timezone.utc
    assert session.started_at.hour == 17
    assert session.started_at.minute == 30


def test_malformed_id_rejected():
    """Verify IDs must conform to TRD §5.6 lowercase identifier pattern."""
    with pytest.raises(ValidationError) as exc:
        TaskRevision(
            task_id="INVALID/ID/WITH/SLASHES",
            revision=1,
            summary="Summary",
            contract_digest=SAMPLE_DIGEST,
        )
    assert "string_pattern_mismatch" in str(exc.value)


def test_malformed_digest_rejected():
    """Verify contract digests must be sha256:<64-hex>."""
    with pytest.raises(ValidationError) as exc:
        TaskRevision(
            task_id="task-1",
            revision=1,
            summary="Summary",
            contract_digest="md5:bad_digest",
        )
    assert "string_pattern_mismatch" in str(exc.value)


def test_frozen_model_attribute_reassignment_blocked():
    """Verify FrozenModel instances cannot have attributes reassigned."""
    revision = TaskRevision(
        task_id="task-1",
        revision=1,
        summary="Initial summary",
        contract_digest=SAMPLE_DIGEST,
    )
    with pytest.raises(ValidationError):
        revision.summary = "Modified summary"  # type: ignore[misc]


def test_nested_container_immutability():
    """Verify that nested lists and mappings cannot be mutated in place after validation."""
    ac = AcceptanceCriterion(
        criterion_id="AC-1",
        description="Requirement 1",
        required_gates=["gate-lint"],
    )
    scope = ScopePolicy(allow_paths=["src/**"], restricted_paths=[".git/**"])
    revision = TaskRevision(
        task_id="task-1",
        revision=1,
        summary="Initial summary",
        acceptance_criteria=[ac],
        scope=scope,
        required_gates=["gate-lint"],
        constraints=["no-network"],
        contract_digest=SAMPLE_DIGEST,
    )

    # 1. Mutating acceptance_criteria in-place must fail
    with pytest.raises(AttributeError):
        revision.acceptance_criteria.append(ac)  # type: ignore[attr-defined]

    with pytest.raises(TypeError):
        revision.acceptance_criteria[0] = ac  # type: ignore[index]

    # 2. Mutating required_gates in-place must fail
    with pytest.raises(AttributeError):
        revision.required_gates.append("gate-test")  # type: ignore[attr-defined]

    # 3. Mutating scope allow_paths in-place must fail
    with pytest.raises(AttributeError):
        revision.scope.allow_paths.append("evil/**")  # type: ignore[attr-defined]

    # 4. Mutating event payload in-place must fail
    event = EventRecord(
        event_id="evt-1",
        session_id="sess-1",
        source_adapter="test",
        event_type="test",
        occurred_at=datetime.now(timezone.utc),
        summary="test event",
        payload={"immutable_key": "initial_value"},
    )
    with pytest.raises(TypeError):
        event.payload["immutable_key"] = "tampered"  # type: ignore[index]

    with pytest.raises(AttributeError):
        event.payload.update({"new_key": "val"})  # type: ignore[attr-defined]

    # 5. Deeply nested dictionaries and lists in event.payload must also be immutable
    nested_event = EventRecord(
        event_id="evt-2",
        session_id="sess-1",
        source_adapter="test",
        event_type="test",
        occurred_at=datetime.now(timezone.utc),
        summary="nested event",
        payload={
            "metadata": {"author": "dev", "tags": ["prod", "auth"]},
            "history": [{"step": 1, "status": "ok"}],
        },
    )
    # Cannot modify nested dict
    with pytest.raises(TypeError):
        nested_event.payload["metadata"]["author"] = "tampered"  # type: ignore[index]

    # Cannot modify nested list
    with pytest.raises(AttributeError):
        nested_event.payload["metadata"]["tags"].append("evil")  # type: ignore[attr-defined]

    with pytest.raises(TypeError):
        nested_event.payload["metadata"]["tags"][0] = "tampered"  # type: ignore[index]

    # Cannot modify nested dict inside list
    with pytest.raises(TypeError):
        nested_event.payload["history"][0]["status"] = "failed"  # type: ignore[index]


def test_default_policy_validation():
    """Verify that default trusted policy loads and validates correctly."""
    policy = get_default_policy()
    assert isinstance(policy, TrustedPolicy)
    assert policy.schema_version == 1
    assert policy.profile == OperatingProfile.FLOW
    assert policy.budget.max_retries == 3
    assert "test" in policy.gates
    assert policy.gates["test"].provider == "pytest"
    assert policy.gates["test"].mandatory is True
