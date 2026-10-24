from datetime import datetime, timezone, timedelta
import pytest
from pydantic import ValidationError

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
    # revision must be an int, not string '1'
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
    """Verify IDs must conform to the allowed identifier pattern."""
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


def test_frozen_model_immutability():
    """Verify FrozenModel instances cannot be modified in-place."""
    revision = TaskRevision(
        task_id="task-1",
        revision=1,
        summary="Initial summary",
        contract_digest=SAMPLE_DIGEST,
    )
    with pytest.raises(ValidationError):
        revision.summary = "Modified summary"  # type: ignore[misc]
