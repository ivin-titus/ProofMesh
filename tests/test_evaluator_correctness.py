"""Adversarial and correctness tests for Evaluator, Freshness, and Persistent Loop Detection."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from proofmesh.config import compute_policy_digest
from proofmesh.core.evaluator import evaluate_session
from proofmesh.core.handoff import generate_handoff
from proofmesh.core.loop_detector import LoopDetector
from proofmesh.core.verification import compute_gate_digest
from proofmesh.models import (
    AcceptanceCriterion,
    ApprovalStatus,
    BudgetPolicy,
    EnforcementLevel,
    EvidenceRecord,
    EvidenceStatus,
    GatePolicy,
    IntegrationStatus,
    OperatingProfile,
    PathChange,
    RepoSnapshot,
    RiskLevel,
    ScopeAnalysisResult,
    ScopeChangeType,
    ScopeFinding,
    ScopePolicy,
    Session,
    SessionState,
    TaskRevision,
    TrustedPolicy,
    VerdictOutcome,
)
from proofmesh.storage.store import ProofMeshStore

SNAP_A = "sha256:" + "a" * 64
SNAP_B = "sha256:" + "b" * 64


def make_clean_scope(baseline_id: str = SNAP_A, current_id: str = SNAP_B) -> ScopeAnalysisResult:
    return ScopeAnalysisResult(
        baseline_snapshot_id=baseline_id,
        current_snapshot_id=current_id,
        changes=(
            PathChange(
                path="src/main.py",
                change_type=ScopeChangeType.MODIFIED,
                old_sha256="sha256:" + "1" * 64,
                new_sha256="sha256:" + "2" * 64,
            ),
        ),
        findings=(
            ScopeFinding(
                path="src/main.py",
                allowed=True,
                restricted=False,
                reason="Path in allowlist",
            ),
        ),
        total_changed_files=1,
        exceeded_file_limit=False,
        has_violations=False,
    )


def make_session(
    session_id: str = "sess-correctness-01",
    policy_digest: str = "sha256:" + "e" * 64,
    revision: int = 1,
) -> Session:
    return Session(
        session_id=session_id,
        task_id="task-01",
        contract_revision=revision,
        repo_root="/repo",
        baseline_snapshot_id=SNAP_A,
        current_snapshot_id=SNAP_B,
        profile=OperatingProfile.FLOW,
        policy_digest=policy_digest,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )


def make_task(revision: int = 1, required_gates: tuple[str, ...] = ("test",)) -> TaskRevision:
    ac = AcceptanceCriterion(
        criterion_id="AC-1",
        description="Verify correctness",
        required_gates=required_gates,
    )
    return TaskRevision(
        task_id="task-01",
        revision=revision,
        summary="Verification task",
        acceptance_criteria=(ac,),
        scope=ScopePolicy(allow_paths=("src/**",), restricted_paths=(".git/**",)),
        required_gates=required_gates,
        constraints=(),
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="approver",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "d" * 64,
    )


def make_policy(
    profile: OperatingProfile = OperatingProfile.FLOW,
    gate_cmd: tuple[str, ...] = ("pytest", "-v"),
) -> TrustedPolicy:
    return TrustedPolicy(
        profile=profile,
        budget=BudgetPolicy(max_retries=3),
        gates={
            "test": GatePolicy(
                provider="pytest",
                command=gate_cmd,
                timeout_seconds=30,
                mandatory=True,
            )
        },
    )


def test_evaluator_blocks_on_incomplete_snapshot():
    """Incomplete snapshot (e.g. symlink escaping root or unreadable path) evaluates to BLOCK."""
    policy = make_policy(profile=OperatingProfile.FLOW)
    policy_digest = compute_policy_digest(policy)
    session = make_session(policy_digest=policy_digest)
    task = make_task(required_gates=("test",))

    incomplete_snapshot = RepoSnapshot(
        snapshot_id=SNAP_B,
        repo_root="/repo",
        git_commit="deadbeef",
        git_dirty=False,
        files=(),
        captured_at=datetime.now(timezone.utc),
        complete=False,
        observation_errors=("Symlink '../outside' points outside repository root",),
    )

    scope = make_clean_scope()
    gate_policy = policy.gates["test"]
    config_digest = compute_gate_digest(gate_policy)

    evidence = EvidenceRecord(
        evidence_id="ev-01",
        session_id=session.session_id,
        contract_revision=1,
        gate_id="test",
        acceptance_criteria=("AC-1",),
        provider_name="pytest",
        provider_version="1.0.0",
        config_digest=config_digest,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=2),
        ended_at=datetime.now(timezone.utc),
        duration_ms=2000,
        snapshot_before=SNAP_A,
        snapshot_after=SNAP_B,
        status=EvidenceStatus.PASSED,
        exit_code=0,
        summary="Passed cleanly",
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=incomplete_snapshot,
        evidence_records=[evidence],
        scope_result=scope,
        policy=policy,
        effective_policy_digest=policy_digest,
    )

    assert verdict.verdict == VerdictOutcome.BLOCK
    assert any("Incomplete repository snapshot" in r for r in verdict.reasons)
    assert any("Symlink '../outside' points outside repository root" in r for r in verdict.reasons)


def test_evaluator_guided_profile_incomplete_snapshot_requires_approval():
    """In GUIDED profile, incomplete snapshot yields REQUIRE_APPROVAL rather than hard BLOCK."""
    policy = make_policy(profile=OperatingProfile.GUIDED)
    policy_digest = compute_policy_digest(policy)
    session = make_session(policy_digest=policy_digest)
    task = make_task(required_gates=("test",))

    incomplete_snapshot = RepoSnapshot(
        snapshot_id=SNAP_B,
        repo_root="/repo",
        git_commit="deadbeef",
        git_dirty=False,
        files=(),
        captured_at=datetime.now(timezone.utc),
        complete=False,
        observation_errors=("Unreadable file: /repo/secret.bin",),
    )

    scope = make_clean_scope()
    gate_policy = policy.gates["test"]
    config_digest = compute_gate_digest(gate_policy)

    evidence = EvidenceRecord(
        evidence_id="ev-01",
        session_id=session.session_id,
        contract_revision=1,
        gate_id="test",
        acceptance_criteria=("AC-1",),
        provider_name="pytest",
        provider_version="1.0.0",
        config_digest=config_digest,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=2),
        ended_at=datetime.now(timezone.utc),
        duration_ms=2000,
        snapshot_before=SNAP_A,
        snapshot_after=SNAP_B,
        status=EvidenceStatus.PASSED,
        exit_code=0,
        summary="Passed cleanly",
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=incomplete_snapshot,
        evidence_records=[evidence],
        scope_result=scope,
        policy=policy,
        effective_policy_digest=policy_digest,
    )

    assert verdict.verdict == VerdictOutcome.REQUIRE_APPROVAL
    assert any("Incomplete repository snapshot" in r for r in verdict.reasons)


def test_evaluator_blocks_on_policy_digest_mismatch():
    """Policy digest mismatch between session and effective policy blocks evaluation."""
    policy = make_policy()
    policy_digest_actual = compute_policy_digest(policy)
    tampered_digest = "sha256:" + "9" * 64
    session = make_session(policy_digest=tampered_digest)
    task = make_task()

    snapshot = RepoSnapshot(
        snapshot_id=SNAP_B,
        repo_root="/repo",
        git_commit="deadbeef",
        git_dirty=False,
        files=(),
        captured_at=datetime.now(timezone.utc),
    )

    scope = make_clean_scope()
    gate_policy = policy.gates["test"]
    config_digest = compute_gate_digest(gate_policy)

    evidence = EvidenceRecord(
        evidence_id="ev-01",
        session_id=session.session_id,
        contract_revision=1,
        gate_id="test",
        acceptance_criteria=("AC-1",),
        provider_name="pytest",
        provider_version="1.0.0",
        config_digest=config_digest,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=2),
        ended_at=datetime.now(timezone.utc),
        duration_ms=2000,
        snapshot_before=SNAP_A,
        snapshot_after=SNAP_B,
        status=EvidenceStatus.PASSED,
        exit_code=0,
        summary="Passed",
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[evidence],
        scope_result=scope,
        policy=policy,
        effective_policy_digest=policy_digest_actual,
    )

    assert verdict.verdict == VerdictOutcome.BLOCK
    assert any("Policy digest mismatch" in r for r in verdict.reasons)


def test_evaluator_rejects_cross_session_evidence():
    """Evidence from another session ID is strictly filtered and cannot satisfy mandatory gates."""
    policy = make_policy()
    policy_digest = compute_policy_digest(policy)
    session = make_session(session_id="sess-legit", policy_digest=policy_digest)
    task = make_task(required_gates=("test",))

    snapshot = RepoSnapshot(
        snapshot_id=SNAP_B,
        repo_root="/repo",
        git_commit="deadbeef",
        git_dirty=False,
        files=(),
        captured_at=datetime.now(timezone.utc),
    )

    scope = make_clean_scope()
    config_digest = compute_gate_digest(policy.gates["test"])

    # Foreign evidence from a different session
    foreign_evidence = EvidenceRecord(
        evidence_id="ev-foreign",
        session_id="sess-attacker-or-other",
        contract_revision=1,
        gate_id="test",
        acceptance_criteria=("AC-1",),
        provider_name="pytest",
        provider_version="1.0.0",
        config_digest=config_digest,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=2),
        ended_at=datetime.now(timezone.utc),
        duration_ms=2000,
        snapshot_before=SNAP_A,
        snapshot_after=SNAP_B,
        status=EvidenceStatus.PASSED,
        exit_code=0,
        summary="Foreign passing evidence",
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[foreign_evidence],
        scope_result=scope,
        policy=policy,
        effective_policy_digest=policy_digest,
    )

    assert verdict.verdict == VerdictOutcome.BLOCK
    assert any("Missing mandatory evidence for gate 'test'" in r for r in verdict.reasons)
    assert "ev-foreign" not in verdict.evidence_ids


def test_evaluator_rejects_obsolete_contract_revision_evidence():
    """Evidence recorded against revision 1 cannot satisfy revision 2 requirements."""
    policy = make_policy()
    policy_digest = compute_policy_digest(policy)
    session = make_session(session_id="sess-rev2", revision=2, policy_digest=policy_digest)
    task = make_task(revision=2, required_gates=("test",))

    snapshot = RepoSnapshot(
        snapshot_id=SNAP_B,
        repo_root="/repo",
        git_commit="deadbeef",
        git_dirty=False,
        files=(),
        captured_at=datetime.now(timezone.utc),
    )

    scope = make_clean_scope()
    config_digest = compute_gate_digest(policy.gates["test"])

    old_rev_evidence = EvidenceRecord(
        evidence_id="ev-rev1",
        session_id="sess-rev2",
        contract_revision=1,  # Outdated revision
        gate_id="test",
        acceptance_criteria=("AC-1",),
        provider_name="pytest",
        provider_version="1.0.0",
        config_digest=config_digest,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=2),
        ended_at=datetime.now(timezone.utc),
        duration_ms=2000,
        snapshot_before=SNAP_A,
        snapshot_after=SNAP_B,
        status=EvidenceStatus.PASSED,
        exit_code=0,
        summary="Revision 1 evidence",
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[old_rev_evidence],
        scope_result=scope,
        policy=policy,
        effective_policy_digest=policy_digest,
    )

    assert verdict.verdict == VerdictOutcome.BLOCK
    assert any("Missing mandatory evidence for gate 'test'" in r for r in verdict.reasons)


def test_evaluator_rejects_obsolete_gate_config_digest():
    """Evidence executed under previous gate policy parameters is rejected when policy changes."""
    policy = make_policy(gate_cmd=("pytest", "-v", "--strict-markers"))
    policy_digest = compute_policy_digest(policy)
    session = make_session(policy_digest=policy_digest)
    task = make_task(required_gates=("test",))

    snapshot = RepoSnapshot(
        snapshot_id=SNAP_B,
        repo_root="/repo",
        git_commit="deadbeef",
        git_dirty=False,
        files=(),
        captured_at=datetime.now(timezone.utc),
    )

    scope = make_clean_scope()
    obsolete_config_digest = "sha256:" + "8" * 64

    evidence = EvidenceRecord(
        evidence_id="ev-obsolete-config",
        session_id=session.session_id,
        contract_revision=1,
        gate_id="test",
        acceptance_criteria=("AC-1",),
        provider_name="pytest",
        provider_version="1.0.0",
        config_digest=obsolete_config_digest,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=2),
        ended_at=datetime.now(timezone.utc),
        duration_ms=2000,
        snapshot_before=SNAP_A,
        snapshot_after=SNAP_B,
        status=EvidenceStatus.PASSED,
        exit_code=0,
        summary="Executed with older config",
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[evidence],
        scope_result=scope,
        policy=policy,
        effective_policy_digest=policy_digest,
    )

    assert verdict.verdict == VerdictOutcome.BLOCK
    assert any("configuration digest" in r and "does not match policy digest" in r for r in verdict.reasons)


def test_evaluator_requires_exact_snapshot_equality():
    """Evidence with slight hash difference is treated as stale; substring matches are rejected."""
    policy = make_policy()
    policy_digest = compute_policy_digest(policy)
    session = make_session(policy_digest=policy_digest)
    task = make_task(required_gates=("test",))

    # Evidence has hash ending with '1', current snapshot has hash ending with '2'
    ev_snap = "sha256:" + "1" * 63 + "1"
    cur_snap = "sha256:" + "1" * 63 + "2"

    snapshot = RepoSnapshot(
        snapshot_id=cur_snap,
        repo_root="/repo",
        git_commit="deadbeef",
        git_dirty=False,
        files=(),
        captured_at=datetime.now(timezone.utc),
    )

    scope = make_clean_scope(baseline_id=SNAP_A, current_id=cur_snap)
    config_digest = compute_gate_digest(policy.gates["test"])

    evidence = EvidenceRecord(
        evidence_id="ev-near-match",
        session_id=session.session_id,
        contract_revision=1,
        gate_id="test",
        acceptance_criteria=("AC-1",),
        provider_name="pytest",
        provider_version="1.0.0",
        config_digest=config_digest,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=2),
        ended_at=datetime.now(timezone.utc),
        duration_ms=2000,
        snapshot_before=SNAP_A,
        snapshot_after=ev_snap,
        status=EvidenceStatus.PASSED,
        exit_code=0,
        summary="Passed",
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[evidence],
        scope_result=scope,
        policy=policy,
        effective_policy_digest=policy_digest,
    )

    assert verdict.verdict == VerdictOutcome.BLOCK
    assert any("Evidence for gate 'test' is stale" in r for r in verdict.reasons)


def test_loop_detector_budget_exhaustion_across_simulated_restart(tmp_path: Path):
    """LoopDetector backed by SQLite store survives process restart and filters duplicate turn_ids."""
    db_file = tmp_path / "loop_store.db"
    store = ProofMeshStore(db_file)
    store.create_project("proj-loop", str(tmp_path))

    task = make_task(required_gates=("pytest",))
    store.save_task_revision(task, project_id="proj-loop")

    session_id = "sess-loop-01"
    session = Session(
        session_id=session_id,
        task_id="task-01",
        contract_revision=1,
        repo_root=str(tmp_path),
        baseline_snapshot_id=SNAP_A,
        current_snapshot_id=SNAP_B,
        profile=OperatingProfile.FLOW,
        policy_digest="sha256:" + "0" * 64,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(session)

    gate_id = "pytest"
    error_sig = "AssertionError: expected True but got False"
    budget = BudgetPolicy(max_retries=3)

    # 1. Process 1: Initial detector instance
    detector1 = LoopDetector(store=store)

    # First failure on turn 1
    c1 = detector1.record_failure(session_id, gate_id, error_sig, turn_id="turn-1")
    assert c1 == 1

    # Duplicate delivery on same turn_id does not increment attempt count
    c1_dup = detector1.record_failure(session_id, gate_id, error_sig, turn_id="turn-1")
    assert c1_dup == 1

    # Second failure on turn 2
    c2 = detector1.record_failure(session_id, gate_id, error_sig, turn_id="turn-2")
    assert c2 == 2
    assert not detector1.is_budget_exhausted(session_id, gate_id, error_sig, budget)

    # 2. Process Restart: New detector instance pointing to the same persistent store
    detector2 = LoopDetector(store=store)

    assert detector2.get_failure_count(session_id, gate_id, error_sig) == 2
    assert not detector2.is_budget_exhausted(session_id, gate_id, error_sig, budget)

    # Third failure on turn 3
    c3 = detector2.record_failure(session_id, gate_id, error_sig, turn_id="turn-3")
    assert c3 == 3

    # Budget is now exhausted
    assert detector2.is_budget_exhausted(session_id, gate_id, error_sig, budget) is True
    # 3-arg convenience calling convention
    assert detector2.is_budget_exhausted(session_id, gate_id, budget) is True


def test_handoff_incorporates_policy_level_mandatory_gates():
    """Handoff card surfaces policy-level mandatory gates even when omitted from task revision."""
    task = make_task(required_gates=())  # Task omits required gates
    policy = make_policy()  # Policy defines 'test' as mandatory=True
    scope = make_clean_scope()

    verdict = evaluate_session(
        session=make_session(policy_digest=compute_policy_digest(policy)),
        task_revision=task,
        current_snapshot=RepoSnapshot(
            snapshot_id=SNAP_B,
            repo_root="/repo",
            git_commit=None,
            git_dirty=False,
            files=(),
            captured_at=datetime.now(timezone.utc),
        ),
        evidence_records=[],
        scope_result=scope,
        policy=policy,
    )

    card = generate_handoff(
        task_revision=task,
        verdict=verdict,
        scope_result=scope,
        evidence_records=[],
        policy=policy,
    )

    assert "## Verification Status" in card
    assert "Gate `test`: ⚠️ **MISSING** (no evidence recorded)" in card
    assert "Run mandatory verification gate `test`." in card
