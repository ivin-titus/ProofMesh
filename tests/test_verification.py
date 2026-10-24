"""Tests for ProofMesh verification runner and evidence freshness checker.

Covers:
- Gate execution success / failure / timeout / missing executable
- Bounded stdout/stderr truncation
- Evidence freshness tracking (unchanged vs modified repository snapshots)
- SQLite storage round-trip persistence and re-validation
- Adversarial command containment (no shell injection)
- Pytest provider integration
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import pytest

from proofmesh.core.verification import check_evidence_freshness, run_gate
from proofmesh.models import (
    EvidenceRecord,
    EvidenceStatus,
    FileFingerprint,
    GatePolicy,
    RepoSnapshot,
    Session,
    SessionState,
)
from proofmesh.providers.pytest_runner import build_pytest_gate, run_pytest
from proofmesh.storage.store import ProofMeshStore


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Create a temporary repository directory with initial sample files."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    (repo / "app.py").write_text("print('hello')", encoding="utf-8")
    return repo


@pytest.fixture
def baseline_snapshot(temp_repo: Path) -> RepoSnapshot:
    """Create a deterministic baseline snapshot for testing."""
    now = datetime.now(timezone.utc)
    fp = FileFingerprint(
        path="app.py",
        sha256="sha256:5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03",
        size_bytes=14,
        is_tracked=True,
    )
    return RepoSnapshot(
        snapshot_id="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        repo_root=str(temp_repo),
        git_commit=None,
        git_dirty=False,
        files=(fp,),
        captured_at=now,
    )


def test_successful_gate_execution(temp_repo: Path, baseline_snapshot: RepoSnapshot):
    """Successful gate execution returns PASSED EvidenceRecord bound to snapshots."""
    policy = GatePolicy(
        provider="pytest",
        command=(sys.executable, "-c", "print('All 15 tests passed successfully')"),
        timeout_seconds=10,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="test-unit",
        gate_policy=policy,
        repo_root=temp_repo,
        session_id="sess-001",
        contract_revision=1,
        snapshot_before=baseline_snapshot,
        acceptance_criteria=("AC-1",),
    )

    assert isinstance(evidence, EvidenceRecord)
    assert evidence.status == EvidenceStatus.PASSED
    assert evidence.exit_code == 0
    assert evidence.gate_id == "test-unit"
    assert evidence.session_id == "sess-001"
    assert evidence.contract_revision == 1
    assert evidence.acceptance_criteria == ("AC-1",)
    assert evidence.provider_name == "pytest"
    assert evidence.provider_version == "1.0.0"
    assert evidence.config_digest.startswith("sha256:")
    assert len(evidence.config_digest) == 71
    assert evidence.duration_ms >= 0
    assert evidence.started_at <= evidence.ended_at
    assert evidence.snapshot_before in (
        baseline_snapshot.snapshot_id,
        baseline_snapshot.snapshot_id.removeprefix("sha256:")[:64],
    )
    assert "All 15 tests passed successfully" in evidence.summary
    assert "[stdout]" in evidence.summary


def test_failing_gate_execution(temp_repo: Path, baseline_snapshot: RepoSnapshot):
    """Failing gate returns FAILED status with actual exit code and bounded stderr excerpt."""
    policy = GatePolicy(
        provider="pytest",
        command=(
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('AssertionError: 2 != 3\\n'); sys.exit(2)",
        ),
        timeout_seconds=10,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="test-unit",
        gate_policy=policy,
        repo_root=temp_repo,
        session_id="sess-001",
        contract_revision=1,
        snapshot_before=baseline_snapshot,
    )

    assert evidence.status == EvidenceStatus.FAILED
    assert evidence.exit_code == 2
    assert "[stderr]" in evidence.summary
    assert "AssertionError: 2 != 3" in evidence.summary


def test_missing_executable_produces_failed_evidence(
    temp_repo: Path, baseline_snapshot: RepoSnapshot
):
    """Executing a non-existent binary returns FAILED status with exit code -2 without crashing."""
    policy = GatePolicy(
        provider="custom",
        command=("nonexistent_compiler_proofmesh_xyz", "--version"),
        timeout_seconds=5,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-custom",
        gate_policy=policy,
        repo_root=temp_repo,
        session_id="sess-001",
        contract_revision=1,
        snapshot_before=baseline_snapshot,
    )

    assert evidence.status == EvidenceStatus.FAILED
    assert evidence.exit_code == -2
    assert "Command 'nonexistent_compiler_proofmesh_xyz' not found" in evidence.summary


def test_gate_timeout_produces_failed_evidence(
    temp_repo: Path, baseline_snapshot: RepoSnapshot
):
    """Exceeding gate timeout returns FAILED status with exit code -1 and timeout reason."""
    policy = GatePolicy(
        provider="pytest",
        command=(sys.executable, "-c", "import time; time.sleep(5)"),
        timeout_seconds=1,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-slow",
        gate_policy=policy,
        repo_root=temp_repo,
        session_id="sess-001",
        contract_revision=1,
        snapshot_before=baseline_snapshot,
    )

    assert evidence.status == EvidenceStatus.FAILED
    assert evidence.exit_code == -1
    assert "timed out after 1s" in evidence.summary


def test_oversized_output_is_truncated(temp_repo: Path, baseline_snapshot: RepoSnapshot):
    """Gate producing huge stdout and stderr is safely truncated to <= 2000 chars."""
    policy = GatePolicy(
        provider="pytest",
        command=(
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('O' * 15000 + '\\n'); sys.stderr.write('E' * 15000 + '\\n')",
        ),
        timeout_seconds=10,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-verbose",
        gate_policy=policy,
        repo_root=temp_repo,
        session_id="sess-001",
        contract_revision=1,
        snapshot_before=baseline_snapshot,
    )

    assert len(evidence.summary) <= 2000
    assert "... [truncated]" in evidence.summary
    assert len(evidence.summary) >= 1


def test_evidence_freshness_logic(temp_repo: Path, baseline_snapshot: RepoSnapshot):
    """Freshness returns True for identical snapshots, False when repository snapshot changes."""
    policy = GatePolicy(
        provider="pytest",
        command=(sys.executable, "-c", "print('ok')"),
        timeout_seconds=5,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-test",
        gate_policy=policy,
        repo_root=temp_repo,
        session_id="sess-001",
        contract_revision=1,
        snapshot_before=baseline_snapshot,
    )

    # 1. Freshness against the snapshot produced by the gate run
    now = datetime.now(timezone.utc)
    # Reconstruct matching snapshot
    current_snap_same = RepoSnapshot(
        snapshot_id=evidence.snapshot_after
        if evidence.snapshot_after.startswith("sha256:")
        else f"sha256:{evidence.snapshot_after}",
        repo_root=str(temp_repo),
        git_commit=None,
        git_dirty=False,
        files=(),
        captured_at=now,
    )
    assert check_evidence_freshness(evidence, current_snap_same) is True

    # 2. Freshness against a different (drifted/modified) snapshot
    current_snap_changed = RepoSnapshot(
        snapshot_id="sha256:9999999999999999999999999999999999999999999999999999999999999999",
        repo_root=str(temp_repo),
        git_commit=None,
        git_dirty=False,
        files=(),
        captured_at=now,
    )
    assert check_evidence_freshness(evidence, current_snap_changed) is False


def test_adversarial_shell_injection_prevention(
    temp_repo: Path, baseline_snapshot: RepoSnapshot
):
    """Arguments with shell metacharacters must not execute shell commands (shell=False)."""
    evil_file = temp_repo / "evil_breached.txt"
    if evil_file.exists():
        evil_file.unlink()

    policy = GatePolicy(
        provider="pytest",
        command=(
            sys.executable,
            "-c",
            "import sys; print('argument:', sys.argv[1])",
            f"; touch '{evil_file.as_posix()}'",
        ),
        timeout_seconds=5,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-safe",
        gate_policy=policy,
        repo_root=temp_repo,
        session_id="sess-001",
        contract_revision=1,
        snapshot_before=baseline_snapshot,
    )

    assert evidence.status == EvidenceStatus.PASSED
    assert not evil_file.exists(), "Shell injection succeeded! File should not exist."


def test_evidence_persistence_in_store(temp_repo: Path, baseline_snapshot: RepoSnapshot):
    """EvidenceRecord produced by run_gate round-trips cleanly through SQLite store."""
    db_file = temp_repo / "proofmesh.db"
    store = ProofMeshStore(db_file)

    now = datetime.now(timezone.utc)
    # Register project, task revision, and session to satisfy foreign keys
    store.create_project("proj-1", str(temp_repo))
    from proofmesh.models import AcceptanceCriterion, ApprovalStatus, RiskLevel, ScopePolicy, TaskRevision

    revision = TaskRevision(
        task_id="task-1",
        revision=1,
        summary="Test task",
        acceptance_criteria=[
            AcceptanceCriterion(criterion_id="AC-1", description="Pass tests", required_gates=["gate-persisted"])
        ],
        scope=ScopePolicy(allow_paths=["**"], restricted_paths=[]),
        required_gates=["gate-persisted"],
        constraints=[],
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        contract_digest="sha256:" + "0" * 64,
    )
    store.save_task_revision(revision, project_id="proj-1")

    session = Session(
        session_id="sess-persisted",
        task_id="task-1",
        contract_revision=1,
        repo_root=str(temp_repo),
        baseline_snapshot_id="snap-baseline",
        policy_digest="sha256:" + "0" * 64,
        started_at=now,
        state=SessionState.ACTIVE,
    )
    store.save_session(session)

    policy = GatePolicy(
        provider="pytest",
        command=(sys.executable, "-c", "print('persisted gate passed')"),
        timeout_seconds=10,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-persisted",
        gate_policy=policy,
        repo_root=temp_repo,
        session_id="sess-persisted",
        contract_revision=1,
        snapshot_before=baseline_snapshot,
        acceptance_criteria=("AC-1", "AC-2"),
    )

    store.save_evidence(evidence)

    loaded = store.get_evidence(evidence.evidence_id)
    assert loaded is not None
    assert loaded.evidence_id == evidence.evidence_id
    assert loaded.session_id == "sess-persisted"
    assert loaded.contract_revision == 1
    assert loaded.gate_id == "gate-persisted"
    assert loaded.status == EvidenceStatus.PASSED
    assert loaded.exit_code == 0
    assert loaded.acceptance_criteria == ("AC-1", "AC-2")
    assert loaded.summary == evidence.summary
    assert loaded.config_digest == evidence.config_digest
    assert loaded.snapshot_before == evidence.snapshot_before
    assert loaded.snapshot_after == evidence.snapshot_after

    # List evidence for session
    ev_list = store.list_evidence_for_session("sess-persisted")
    assert len(ev_list) == 1
    assert ev_list[0].evidence_id == evidence.evidence_id


def test_pytest_runner_helpers(temp_repo: Path, baseline_snapshot: RepoSnapshot):
    """Test pytest runner provider helper functions."""
    gate = build_pytest_gate(command_args=["-v", "-k", "unit"], timeout_seconds=45)
    assert gate.provider == "pytest"
    assert gate.timeout_seconds == 45
    assert gate.mandatory is True
    assert gate.command[-3:] == ("-v", "-k", "unit")

    # Run pytest convenience function
    test_file = temp_repo / "test_sample.py"
    test_file.write_text("def test_ok(): assert True\n", encoding="utf-8")

    evidence = run_pytest(
        repo_root=temp_repo,
        session_id="sess-001",
        contract_revision=1,
        snapshot_before=baseline_snapshot,
        gate_id="test",
        acceptance_criteria=("AC-1",),
        command_args=[str(test_file)],
        timeout_seconds=20,
    )

    assert evidence.status == EvidenceStatus.PASSED
    assert evidence.exit_code == 0
    assert evidence.provider_name == "pytest"
    assert "test_sample.py" in evidence.summary or "passed" in evidence.summary


def test_empty_output_summary_formatting(temp_repo: Path, baseline_snapshot: RepoSnapshot):
    """Command that succeeds with no output produces a standard exit code summary."""
    policy = GatePolicy(
        provider="custom",
        command=(sys.executable, "-c", "pass"),
        timeout_seconds=5,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-empty",
        gate_policy=policy,
        repo_root=temp_repo,
        session_id="sess-001",
        contract_revision=1,
        snapshot_before=baseline_snapshot,
    )

    assert evidence.status == EvidenceStatus.PASSED
    assert evidence.exit_code == 0
    assert evidence.summary == "Gate 'gate-empty' completed with exit code 0"


def test_evidence_record_immutability(temp_repo: Path, baseline_snapshot: RepoSnapshot):
    """EvidenceRecord is strictly frozen and attributes cannot be mutated in place."""
    policy = GatePolicy(
        provider="pytest",
        command=(sys.executable, "-c", "print('ok')"),
        timeout_seconds=5,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-freeze",
        gate_policy=policy,
        repo_root=temp_repo,
        session_id="sess-001",
        contract_revision=1,
        snapshot_before=baseline_snapshot,
    )

    with pytest.raises(Exception):
        evidence.status = EvidenceStatus.FAILED  # type: ignore[misc]

    with pytest.raises(Exception):
        evidence.summary = "Tampered summary"  # type: ignore[misc]


def test_custom_snapshot_capture_injection(temp_repo: Path, baseline_snapshot: RepoSnapshot):
    """Passing a custom capture_snapshot_fn binds its returned snapshot to snapshot_after."""
    custom_snap_id = "sha256:7777777777777777777777777777777777777777777777777777777777777777"
    custom_snapshot = RepoSnapshot(
        snapshot_id=custom_snap_id,
        repo_root=str(temp_repo),
        git_commit=None,
        git_dirty=False,
        files=(),
        captured_at=datetime.now(timezone.utc),
    )

    policy = GatePolicy(
        provider="pytest",
        command=(sys.executable, "-c", "print('custom snapshot test')"),
        timeout_seconds=5,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-custom-snap",
        gate_policy=policy,
        repo_root=temp_repo,
        session_id="sess-001",
        contract_revision=1,
        snapshot_before=baseline_snapshot,
        capture_snapshot_fn=lambda root: custom_snapshot,
    )

    assert evidence.snapshot_after in (custom_snap_id, custom_snap_id.removeprefix("sha256:")[:64])
    assert check_evidence_freshness(evidence, custom_snapshot) is True

