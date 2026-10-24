"""Tests for shared trusted policy, session isolation, and storage foundation."""

from datetime import datetime, timezone
from pathlib import Path
import pytest

from proofmesh.config import compute_policy_digest, resolve_trusted_policy
from proofmesh.models import (
    ApprovalStatus,
    BudgetPolicy,
    FileFingerprint,
    GatePolicy,
    IntegrationStatus,
    OperatingProfile,
    RepoSnapshot,
    RiskLevel,
    ScopeDefaultPolicy,
    ScopePolicy,
    Session,
    SessionState,
    TaskRevision,
    TrustedPolicy,
)
from proofmesh.storage.store import ProofMeshStore


def test_trusted_policy_resolution_and_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Packaged default policy and custom policy resolve with real SHA-256 digests."""
    # 1. Default policy resolution
    monkeypatch.delenv("PROOFMESH_POLICY", raising=False)
    default_policy, default_digest = resolve_trusted_policy()
    assert default_digest.startswith("sha256:")
    assert len(default_digest) == 71
    assert default_digest != "sha256:" + "0" * 64
    assert "test" in default_policy.gates
    assert default_policy.gates["test"].provider == "pytest"

    # 2. Custom policy resolution via environment variable
    custom_policy_file = tmp_path / "custom_policy.toml"
    custom_policy_file.write_text(
        """
        schema_version = 1
        profile = "strict"

        [budget]
        max_retries = 5
        max_continuation_steps = 15
        max_changed_files = 20

        [scope]
        default_allow_paths = ["src/**"]
        default_restricted_paths = ["secret/**"]

        [gates.custom_gate]
        provider = "pytest"
        command = ["pytest", "-v"]
        timeout_seconds = 45
        mandatory = true
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("PROOFMESH_POLICY", str(custom_policy_file))
    custom_policy, custom_digest = resolve_trusted_policy()
    assert custom_policy.profile == OperatingProfile.STRICT
    assert "custom_gate" in custom_policy.gates
    assert custom_digest != default_digest
    assert len(custom_digest) == 71

    # 3. Missing policy file raises FileNotFoundError
    monkeypatch.setenv("PROOFMESH_POLICY", str(tmp_path / "nonexistent.toml"))
    with pytest.raises(FileNotFoundError):
        resolve_trusted_policy()


def test_session_isolation_across_projects_and_workspaces(tmp_path: Path) -> None:
    """Two projects sharing a database must not leak sessions, snapshots, or revisions."""
    db_file = tmp_path / "shared_store" / "test.db"
    store = ProofMeshStore(db_file)

    proj_a = "project-alpha"
    proj_b = "project-beta"
    root_a = tmp_path / "workspace_a"
    root_b = tmp_path / "workspace_b"
    root_a.mkdir()
    root_b.mkdir()

    store.create_project(proj_a, str(root_a))
    store.create_project(proj_b, str(root_b))

    # Create dummy snapshots
    snap_a = RepoSnapshot(
        snapshot_id="sha256:" + "a" * 64,
        repo_root=str(root_a),
        git_commit="commita",
        git_dirty=False,
        files=(),
        captured_at=datetime.now(timezone.utc),
        complete=True,
    )
    snap_b = RepoSnapshot(
        snapshot_id="sha256:" + "b" * 64,
        repo_root=str(root_b),
        git_commit="commitb",
        git_dirty=False,
        files=(),
        captured_at=datetime.now(timezone.utc),
        complete=True,
    )
    store.save_snapshot(snap_a)
    store.save_snapshot(snap_b)

    # Create task revisions for each project
    rev_a = TaskRevision(
        task_id="task-alpha",
        revision=1,
        parent_revision=None,
        summary="Task in Alpha",
        acceptance_criteria=(),
        scope=ScopePolicy(allow_paths=("src/**",), restricted_paths=()),
        required_gates=("pytest",),
        constraints=(),
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="alice",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "1" * 64,
    )
    rev_b = TaskRevision(
        task_id="task-beta",
        revision=1,
        parent_revision=None,
        summary="Task in Beta",
        acceptance_criteria=(),
        scope=ScopePolicy(allow_paths=("src/**",), restricted_paths=()),
        required_gates=("pytest",),
        constraints=(),
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="bob",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "2" * 64,
    )
    store.save_task_revision(rev_a, project_id=proj_a)
    store.save_task_revision(rev_b, project_id=proj_b)

    # Start sessions for each project
    sess_a = Session(
        session_id="sess-alpha-001",
        task_id=rev_a.task_id,
        contract_revision=1,
        repo_root=str(root_a),
        baseline_snapshot_id=snap_a.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest="sha256:" + "9" * 64,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    sess_b = Session(
        session_id="sess-beta-001",
        task_id=rev_b.task_id,
        contract_revision=1,
        repo_root=str(root_b),
        baseline_snapshot_id=snap_b.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest="sha256:" + "9" * 64,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(sess_a)
    store.save_session(sess_b)

    # 1. Scoped session lookup by project_id
    loaded_a = store.get_session("sess-alpha-001", project_id=proj_a, repo_root=root_a)
    assert loaded_a is not None
    assert loaded_a.session_id == "sess-alpha-001"

    # Cross-project query must return None
    cross_lookup = store.get_session("sess-alpha-001", project_id=proj_b, repo_root=root_b)
    assert cross_lookup is None

    # Mismatched root directory returns None
    mismatched_root = store.get_session("sess-alpha-001", project_id=proj_a, repo_root=root_b)
    assert mismatched_root is None

    # 2. get_active_session_for_project respects project scoping
    active_b = store.get_active_session_for_project(proj_b, repo_root=root_b)
    assert active_b is not None
    assert active_b.session_id == "sess-beta-001"


def test_task_revision_immutability_and_atomic_approval(tmp_path: Path) -> None:
    """Duplicate conflicting proposals are rejected, and approval is atomic with parent supersession."""
    db_file = tmp_path / "store" / "test.db"
    store = ProofMeshStore(db_file)
    project_id = "test-project"
    store.create_project(project_id, str(tmp_path))

    rev1_proposed = TaskRevision(
        task_id="task-x",
        revision=1,
        parent_revision=None,
        summary="Initial proposed summary",
        acceptance_criteria=(),
        scope=ScopePolicy(allow_paths=("src/**",), restricted_paths=()),
        required_gates=("pytest",),
        constraints=(),
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.PROPOSED,
        contract_digest="sha256:" + "a" * 64,
    )
    store.save_task_revision(rev1_proposed, project_id=project_id)

    # Duplicate proposal with DIFFERENT content/digest must be rejected
    conflicting_rev1 = rev1_proposed.model_copy(
        update={"contract_digest": "sha256:" + "b" * 64, "summary": "Conflicting content"}
    )
    with pytest.raises(ValueError, match="cannot overwrite existing proposal"):
        store.save_task_revision(conflicting_rev1, project_id=project_id)

    # Approve revision 1 atomically
    approved_rev1 = store.approve_task_revision(
        task_id="task-x",
        revision=1,
        approved_by="alice",
        approved_at=datetime.now(timezone.utc),
    )
    assert approved_rev1.approval_status == ApprovalStatus.APPROVED
    assert approved_rev1.approved_by == "alice"

    # Cannot re-approve an already approved revision with different metadata
    with pytest.raises(ValueError, match="already approved"):
        store.approve_task_revision(
            task_id="task-x",
            revision=1,
            approved_by="charlie",
            approved_at=datetime.now(timezone.utc),
        )

    # Propose revision 2 amending revision 1
    rev2_proposed = TaskRevision(
        task_id="task-x",
        revision=2,
        parent_revision=1,
        summary="Revision 2 proposal",
        acceptance_criteria=(),
        scope=ScopePolicy(allow_paths=("src/**",), restricted_paths=()),
        required_gates=("pytest",),
        constraints=(),
        risk_level=RiskLevel.MEDIUM,
        approval_status=ApprovalStatus.PROPOSED,
        contract_digest="sha256:" + "c" * 64,
    )
    store.save_task_revision(rev2_proposed, project_id=project_id)

    # Approve revision 2: must atomically supersede parent revision 1
    approved_rev2 = store.approve_task_revision(
        task_id="task-x",
        revision=2,
        approved_by="bob",
        approved_at=datetime.now(timezone.utc),
        parent_revision=1,
    )
    assert approved_rev2.approval_status == ApprovalStatus.APPROVED

    # Check that parent revision 1 is now SUPERSEDED
    reloaded_rev1 = store.get_task_revision("task-x", 1)
    assert reloaded_rev1 is not None
    assert reloaded_rev1.approval_status == ApprovalStatus.SUPERSEDED


def test_snapshot_observation_and_loop_persistence(tmp_path: Path) -> None:
    """Snapshot observation completeness and loop attempt counter persist properly."""
    db_file = tmp_path / "store" / "test.db"
    store = ProofMeshStore(db_file)
    project_id = "test-project"
    store.create_project(project_id, str(tmp_path))

    # Incomplete snapshot with observation errors
    incomplete_snap = RepoSnapshot(
        snapshot_id="sha256:" + "f" * 64,
        repo_root=str(tmp_path),
        git_commit="deadbeef",
        git_dirty=True,
        files=(),
        captured_at=datetime.now(timezone.utc),
        complete=False,
        observation_errors=("Symlink at 'ext' points outside repository", "Permission denied on 'secret.key'"),
    )
    store.save_snapshot(incomplete_snap)

    reloaded_snap = store.get_snapshot(incomplete_snap.snapshot_id)
    assert reloaded_snap is not None
    assert reloaded_snap.complete is False
    assert len(reloaded_snap.observation_errors) == 2
    assert "Symlink at 'ext'" in reloaded_snap.observation_errors[0]

    # Test loop attempt counter persistence & duplicate turn suppression
    sess = Session(
        session_id="sess-loop-001",
        task_id="task-x",
        contract_revision=1,
        repo_root=str(tmp_path),
        baseline_snapshot_id=incomplete_snap.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest="sha256:" + "9" * 64,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    # Save a minimal task first for FK constraint
    rev = TaskRevision(
        task_id="task-x",
        revision=1,
        parent_revision=None,
        summary="Task X",
        acceptance_criteria=(),
        scope=ScopePolicy(allow_paths=("src/**",), restricted_paths=()),
        required_gates=("pytest",),
        constraints=(),
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        contract_digest="sha256:" + "1" * 64,
    )
    store.save_task_revision(rev, project_id=project_id)
    store.save_session(sess)

    # Attempt 1
    cnt1 = store.record_loop_attempt("sess-loop-001", "pytest", "AssertionError: 2 != 3", turn_id="turn-1")
    assert cnt1 == 1

    # Duplicate delivery of turn-1 must NOT increment
    cnt_dup = store.record_loop_attempt("sess-loop-001", "pytest", "AssertionError: 2 != 3", turn_id="turn-1")
    assert cnt_dup == 1

    # New turn-2 increments attempt to 2
    cnt2 = store.record_loop_attempt("sess-loop-001", "pytest", "AssertionError: 2 != 3", turn_id="turn-2")
    assert cnt2 == 2

    # Query counter
    assert store.get_loop_attempt_count("sess-loop-001", "pytest", "AssertionError: 2 != 3") == 2
