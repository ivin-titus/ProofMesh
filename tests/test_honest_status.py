from datetime import datetime, timezone
from pathlib import Path
import pytest

from proofmesh.adapters.antigravity import AntigravityAdapter
from proofmesh.cli import _get_or_create_active_session
from proofmesh.config import resolve_trusted_policy
from proofmesh.core.repo_snapshot import capture_snapshot
from proofmesh.models import (
    ApprovalStatus,
    IntegrationStatus,
    OperatingProfile,
    RiskLevel,
    ScopePolicy,
    Session,
    SessionState,
    TaskRevision,
)
from proofmesh.storage.store import ProofMeshStore


def test_cli_creates_unguarded_session(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "code.py").write_text("print(1)\n")

    db_path = tmp_path / "test.db"
    store = ProofMeshStore(db_path)
    store.create_project("p1", root_path=str(repo))

    task_rev = TaskRevision(
        task_id="t1",
        revision=1,
        parent_revision=None,
        summary="Test task",
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="tester",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "a" * 64,
        scope=ScopePolicy(allow_paths=("src/**",), restricted_paths=()),
        required_gates=(),
        acceptance_criteria=(),
        constraints=(),
        raw_markdown="# Task",
    )
    store.save_task_revision(task_rev, project_id="p1")

    session = _get_or_create_active_session(store, "p1", repo)
    assert session.integration_status == IntegrationStatus.UNGUARDED


def test_cli_detects_policy_digest_mismatch(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "code.py").write_text("print(1)\n")

    db_path = tmp_path / "test.db"
    store = ProofMeshStore(db_path)
    store.create_project("p1", root_path=str(repo))

    task_rev = TaskRevision(
        task_id="t1",
        revision=1,
        parent_revision=None,
        summary="Test task",
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="tester",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "a" * 64,
        scope=ScopePolicy(allow_paths=("src/**",), restricted_paths=()),
        required_gates=(),
        acceptance_criteria=(),
        constraints=(),
        raw_markdown="# Task",
    )
    store.save_task_revision(task_rev, project_id="p1")

    # Save session with different/fake policy digest
    fake_digest = "sha256:" + "0" * 64
    session = Session(
        session_id="sess-fake-pol",
        task_id="t1",
        contract_revision=1,
        repo_root=str(repo),
        baseline_snapshot_id="sha256:" + "1" * 64,
        current_snapshot_id=None,
        profile=OperatingProfile.FLOW,
        policy_digest=fake_digest,
        integration_status=IntegrationStatus.UNGUARDED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(session)

    with pytest.raises(ValueError) as exc_info:
        _get_or_create_active_session(store, "p1", repo)
    assert "does not match current trusted policy digest" in str(exc_info.value)


def test_antigravity_status_truthful_semantics(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()

    db_path = tmp_path / "test.db"
    store = ProofMeshStore(db_path)
    store.create_project("p1", root_path=str(repo))

    # 1. Default adapter: neither hooks nor mcp -> UNGUARDED
    adapter_default = AntigravityAdapter(store=store, repo_root=repo, project_id="p1")
    assert adapter_default.get_integration_status() == IntegrationStatus.UNGUARDED

    # 2. Even if passed a session that has ENFORCED stored, adapter reports UNGUARDED if inactive
    session_with_enforced = Session(
        session_id="sess-enforced",
        task_id="t1",
        contract_revision=1,
        repo_root=str(repo),
        baseline_snapshot_id="sha256:" + "1" * 64,
        current_snapshot_id=None,
        profile=OperatingProfile.FLOW,
        policy_digest="sha256:" + "a" * 64,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    assert adapter_default.get_integration_status(session_with_enforced) == IntegrationStatus.UNGUARDED

    # 3. Hook-only -> PARTIAL
    adapter_hooks = AntigravityAdapter(store=store, repo_root=repo, project_id="p1", hooks_enabled=True, mcp_enabled=False)
    assert adapter_hooks.get_integration_status() == IntegrationStatus.PARTIAL

    # 4. MCP-only -> PARTIAL
    adapter_mcp = AntigravityAdapter(store=store, repo_root=repo, project_id="p1", hooks_enabled=False, mcp_enabled=True)
    assert adapter_mcp.get_integration_status() == IntegrationStatus.PARTIAL

    # 5. Both active -> ENFORCED
    adapter_both = AntigravityAdapter(store=store, repo_root=repo, project_id="p1", hooks_enabled=True, mcp_enabled=True)
    assert adapter_both.get_integration_status() == IntegrationStatus.ENFORCED
