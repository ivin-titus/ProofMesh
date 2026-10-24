"""Tests for ProofMesh MCP server entrypoint, stdio subprocess, and handler invariant enforcement."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

from proofmesh.adapters.mcp_server import create_mcp_server
from proofmesh.config import compute_policy_digest, resolve_trusted_policy
from proofmesh.core.repo_snapshot import capture_snapshot
from proofmesh.models import (
    AcceptanceCriterion,
    ApprovalStatus,
    GatePolicy,
    IntegrationStatus,
    OperatingProfile,
    RiskLevel,
    ScopePolicy,
    Session,
    SessionState,
    TaskRevision,
    TrustedPolicy,
    VerdictOutcome,
)
from proofmesh.storage.store import ProofMeshStore


def _extract_data(call_result) -> dict | str:
    """Helper to extract parsed JSON or text from MCP tool call response."""
    text = call_result.content[0].text
    try:
        return json.loads(text)
    except Exception:
        return text


# ==============================================================================
# 1. Subprocess Smoke Test over Stdio
# ==============================================================================


def test_subprocess_mcp_smoke(tmp_path: Path):
    """Invoke sys.executable -m proofmesh.adapters.mcp_server as a real subprocess over stdio.

    Verifies:
    - MCP JSON-RPC initialize request/response roundtrip.
    - notifications/initialized handling.
    - tools/list request returning all ProofMesh tools.
    - tools/call invoking get_task_contract.
    - Clean termination.
    - Stdout contains exclusively valid JSON-RPC messages; stderr receives diagnostics.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    (repo_root / "src" / "app.py").write_text("print('smoke test')\n", encoding="utf-8")

    db_path = tmp_path / "test_smoke.db"
    store = ProofMeshStore(db_path)
    project_id = "smoke-project"
    store.create_project(project_id, root_path=str(repo_root))

    task_rev = TaskRevision(
        task_id="task-smoke",
        revision=1,
        parent_revision=None,
        summary="MCP Smoke Test Contract",
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="tester",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "a" * 64,
        scope=ScopePolicy(allow_paths=("src/**",), restricted_paths=(".git/**",), max_changed_files=5),
        required_gates=("test-gate",),
        acceptance_criteria=(
            AcceptanceCriterion(
                criterion_id="ac-smoke-1",
                description="Subprocess MCP works",
                required_gates=("test-gate",),
            ),
        ),
        constraints=("No arbitrary execution",),
        raw_markdown="# Smoke Task\nContract",
    )
    store.save_task_revision(task_rev, project_id=project_id)

    snap = capture_snapshot(repo_root)
    store.save_snapshot(snap)

    policy, policy_digest = resolve_trusted_policy()
    session = Session(
        session_id="sess-smoke-1",
        task_id=task_rev.task_id,
        contract_revision=task_rev.revision,
        repo_root=str(repo_root),
        baseline_snapshot_id=snap.snapshot_id,
        current_snapshot_id=snap.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest=policy_digest,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(session)

    # Launch subprocess with clean stdio
    cmd = [
        sys.executable,
        "-m",
        "proofmesh.adapters.mcp_server",
        "--repo-root",
        str(repo_root),
        "--session-id",
        session.session_id,
        "--project-id",
        project_id,
        "--db-path",
        str(db_path),
    ]

    env = {
        **os.environ,
        "PYTHONPATH": "src",
        "PROOFMESH_PROJECT_ID": project_id,
        "PROOFMESH_DB": str(db_path),
    }

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    try:
        # 1. Send JSON-RPC initialize
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test-client", "version": "1.0.0"},
            },
        }
        proc.stdin.write(json.dumps(init_req) + "\n")
        proc.stdin.flush()

        init_raw = proc.stdout.readline()
        assert init_raw, "Subprocess returned empty response on initialize"
        init_resp = json.loads(init_raw)
        assert init_resp.get("id") == 1
        assert "result" in init_resp
        assert init_resp["result"]["serverInfo"]["name"] == "proofmesh"

        # 2. Send notifications/initialized
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()

        # 3. Request tools/list
        tools_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        proc.stdin.write(json.dumps(tools_req) + "\n")
        proc.stdin.flush()

        tools_raw = proc.stdout.readline()
        tools_resp = json.loads(tools_raw)
        assert tools_resp.get("id") == 2
        tool_names = {t["name"] for t in tools_resp["result"]["tools"]}
        expected_tools = {
            "get_task_contract",
            "inspect_changes",
            "run_verification",
            "get_status",
            "claim_completion",
            "get_handoff",
        }
        assert expected_tools.issubset(tool_names), f"Missing tools: {expected_tools - tool_names}"

        # 4. Call get_task_contract tool
        contract_req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "get_task_contract",
                "arguments": {"task_id": "task-smoke"},
            },
        }
        proc.stdin.write(json.dumps(contract_req) + "\n")
        proc.stdin.flush()

        contract_raw = proc.stdout.readline()
        contract_resp = json.loads(contract_raw)
        assert contract_resp.get("id") == 3
        assert contract_resp["result"].get("isError") is False
        parsed_contract = json.loads(contract_resp["result"]["content"][0]["text"])
        assert parsed_contract["task_id"] == "task-smoke"
        assert parsed_contract["revision"] == 1
        assert parsed_contract["summary"] == "MCP Smoke Test Contract"

        # 5. Clean termination
        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)

    # Verify diagnostic message went to stderr, not stdout
    stderr_output = proc.stderr.read()
    assert "ProofMesh MCP server starting (transport=stdio)..." in stderr_output


# ==============================================================================
# 2. Policy Mismatch Rejection in MCP Handlers
# ==============================================================================


@pytest.mark.anyio
async def test_policy_mismatch_rejection_in_handlers(tmp_path: Path):
    """Verify that MCP handlers reject evaluation and completion claims on policy digest mismatch."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    (repo_root / "src" / "code.py").write_text("x = 1\n", encoding="utf-8")

    db_path = tmp_path / "test_mismatch.db"
    store = ProofMeshStore(db_path)
    project_id = "mismatch-project"
    store.create_project(project_id, root_path=str(repo_root))

    task_rev = TaskRevision(
        task_id="task-mismatch",
        revision=1,
        parent_revision=None,
        summary="Policy mismatch test",
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="tester",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "c" * 64,
        scope=ScopePolicy(allow_paths=("src/**",), restricted_paths=()),
        required_gates=(),
        acceptance_criteria=(),
        constraints=(),
    )
    store.save_task_revision(task_rev, project_id=project_id)

    snap = capture_snapshot(repo_root)
    store.save_snapshot(snap)

    # Session pinned to digest A
    pinned_digest = "sha256:" + "1" * 64
    session = Session(
        session_id="sess-mismatch-1",
        task_id=task_rev.task_id,
        contract_revision=task_rev.revision,
        repo_root=str(repo_root),
        baseline_snapshot_id=snap.snapshot_id,
        current_snapshot_id=snap.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest=pinned_digest,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(session)

    # Server created with policy that has a DIFFERENT digest B
    server_policy = TrustedPolicy(
        schema_version=1,
        profile=OperatingProfile.FLOW,
        gates={
            "check": GatePolicy(
                provider="pytest",
                command=("python3", "-c", "print('ok')"),
                timeout_seconds=5,
                mandatory=False,
            )
        },
    )
    server_digest = compute_policy_digest(server_policy)
    assert server_digest != pinned_digest

    server = create_mcp_server(
        store=store,
        repo_root=repo_root,
        session_id=session.session_id,
        policy=server_policy,
        project_id=project_id,
    )

    # 1. get_status must return UNKNOWN verdict and indicate policy digest mismatch
    res_status = await server.call_tool("get_status", arguments={})
    status_data = _extract_data(res_status)
    assert status_data["verdict"] == "UNKNOWN"
    assert "error" in status_data
    assert "Policy digest mismatch" in status_data["error"]
    assert any("Policy digest mismatch" in r for r in status_data["reasons"])

    # 2. claim_completion must be BLOCKED with UNKNOWN verdict
    res_claim = await server.call_tool("claim_completion", arguments={})
    claim_data = _extract_data(res_claim)
    assert claim_data["status"] == "BLOCKED"
    assert claim_data["verdict"] == "UNKNOWN"
    assert "Policy digest mismatch" in claim_data["message"]

    # Verify session was NOT accepted
    reloaded_sess = store.get_session(session.session_id)
    assert reloaded_sess.state != SessionState.ACCEPTED


# ==============================================================================
# 3. Completion Claim Rejection When Baseline is Missing
# ==============================================================================


@pytest.mark.anyio
async def test_claim_completion_rejection_missing_baseline(tmp_path: Path):
    """Verify that claim_completion fails closed when baseline snapshot is not found in store."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    (repo_root / "src" / "code.py").write_text("x = 42\n", encoding="utf-8")

    db_path = tmp_path / "test_missing_baseline.db"
    store = ProofMeshStore(db_path)
    project_id = "missing-baseline-project"
    store.create_project(project_id, root_path=str(repo_root))

    task_rev = TaskRevision(
        task_id="task-mb",
        revision=1,
        parent_revision=None,
        summary="Missing baseline test",
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="tester",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "b" * 64,
        scope=ScopePolicy(allow_paths=("src/**",), restricted_paths=()),
        required_gates=(),
        acceptance_criteria=(),
        constraints=(),
    )
    store.save_task_revision(task_rev, project_id=project_id)

    policy, policy_digest = resolve_trusted_policy()

    # Session points to a baseline snapshot that does NOT exist in the database
    nonexistent_snapshot_id = "sha256:" + "0" * 64
    session = Session(
        session_id="sess-mb-1",
        task_id=task_rev.task_id,
        contract_revision=task_rev.revision,
        repo_root=str(repo_root),
        baseline_snapshot_id=nonexistent_snapshot_id,
        current_snapshot_id=None,
        profile=OperatingProfile.FLOW,
        policy_digest=policy_digest,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(session)

    server = create_mcp_server(
        store=store,
        repo_root=repo_root,
        session_id=session.session_id,
        policy=policy,
        policy_digest=policy_digest,
        project_id=project_id,
    )

    # get_status should report missing baseline
    res_status = await server.call_tool("get_status", arguments={})
    status_data = _extract_data(res_status)
    assert status_data["verdict"] == "BLOCK"
    assert any("Missing baseline snapshot" in r for r in status_data["reasons"])

    # claim_completion must reject completion claim
    res_claim = await server.call_tool("claim_completion", arguments={})
    claim_data = _extract_data(res_claim)
    assert claim_data["status"] == "BLOCKED"
    assert claim_data["verdict"] == "BLOCK"
    assert "baseline snapshot" in claim_data["message"]

    reloaded_sess = store.get_session(session.session_id)
    assert reloaded_sess.state != SessionState.ACCEPTED


# ==============================================================================
# 4. Completion Claim Rejection When Evidence is Stale
# ==============================================================================


@pytest.mark.anyio
async def test_claim_completion_rejection_stale_evidence(tmp_path: Path):
    """Verify that claim_completion rejects when code changes after verification was run."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    src_file = repo_root / "main.py"
    src_file.write_text("print('initial')\n", encoding="utf-8")

    db_path = tmp_path / "test_stale.db"
    store = ProofMeshStore(db_path)
    project_id = "stale-project"
    store.create_project(project_id, root_path=str(repo_root))

    task_rev = TaskRevision(
        task_id="task-stale",
        revision=1,
        parent_revision=None,
        summary="Stale evidence test",
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="tester",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "d" * 64,
        scope=ScopePolicy(allow_paths=("*.py",), restricted_paths=()),
        required_gates=("check-code",),
        acceptance_criteria=(
            AcceptanceCriterion(
                criterion_id="ac-1",
                description="Code check passes",
                required_gates=("check-code",),
            ),
        ),
        constraints=(),
    )
    store.save_task_revision(task_rev, project_id=project_id)

    snap = capture_snapshot(repo_root)
    store.save_snapshot(snap)

    policy = TrustedPolicy(
        schema_version=1,
        profile=OperatingProfile.FLOW,
        gates={
            "check-code": GatePolicy(
                provider="pytest",
                command=("python3", "-c", "print('gate ok')"),
                timeout_seconds=5,
                mandatory=True,
            )
        },
    )
    policy_digest = compute_policy_digest(policy)

    session = Session(
        session_id="sess-stale-1",
        task_id=task_rev.task_id,
        contract_revision=task_rev.revision,
        repo_root=str(repo_root),
        baseline_snapshot_id=snap.snapshot_id,
        current_snapshot_id=snap.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest=policy_digest,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(session)

    server = create_mcp_server(
        store=store,
        repo_root=repo_root,
        session_id=session.session_id,
        policy=policy,
        policy_digest=policy_digest,
        project_id=project_id,
    )

    # 1. Run verification gate -> generates PASS evidence for initial snapshot
    res_gate = await server.call_tool("run_verification", arguments={"gate_id": "check-code"})
    gate_data = _extract_data(res_gate)
    assert gate_data["status"] == "PASSED"

    # 2. Modify code after verification -> snapshot advances, invalidating freshness
    src_file.write_text("print('modified after gate')\n", encoding="utf-8")

    # 3. claim_completion must reject due to stale evidence
    res_claim = await server.call_tool("claim_completion", arguments={})
    claim_data = _extract_data(res_claim)
    assert claim_data["status"] == "BLOCKED"
    assert claim_data["verdict"] == "BLOCK"
    assert any("stale" in r.lower() for r in claim_data["reasons"])

    reloaded_sess = store.get_session(session.session_id)
    assert reloaded_sess.state != SessionState.ACCEPTED


# ==============================================================================
# 5. Session Lookup Disambiguation
# ==============================================================================


@pytest.mark.anyio
async def test_session_resolution_disambiguation(tmp_path: Path):
    """Verify that _resolve_session does not blindly grab sessions from another repository or project."""
    repo_a = tmp_path / "repo_a"
    repo_a.mkdir()
    (repo_a / "a.py").write_text("a = 1\n")

    repo_b = tmp_path / "repo_b"
    repo_b.mkdir()
    (repo_b / "b.py").write_text("b = 2\n")

    # Shared database
    db_path = tmp_path / "shared.db"
    store = ProofMeshStore(db_path)

    store.create_project("proj-a", root_path=str(repo_a))
    store.create_project("proj-b", root_path=str(repo_b))

    task_a = TaskRevision(
        task_id="task-a",
        revision=1,
        parent_revision=None,
        summary="Task A",
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="tester",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "a" * 64,
        scope=ScopePolicy(allow_paths=("*.py",), restricted_paths=()),
        required_gates=(),
        acceptance_criteria=(),
        constraints=(),
    )
    store.save_task_revision(task_a, project_id="proj-a")

    task_b = TaskRevision(
        task_id="task-b",
        revision=1,
        parent_revision=None,
        summary="Task B",
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="tester",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "b" * 64,
        scope=ScopePolicy(allow_paths=("*.py",), restricted_paths=()),
        required_gates=(),
        acceptance_criteria=(),
        constraints=(),
    )
    store.save_task_revision(task_b, project_id="proj-b")

    snap_a = capture_snapshot(repo_a)
    snap_b = capture_snapshot(repo_b)
    store.save_snapshot(snap_a)
    store.save_snapshot(snap_b)

    policy, policy_digest = resolve_trusted_policy()

    sess_a = Session(
        session_id="sess-project-a",
        task_id="task-a",
        contract_revision=1,
        repo_root=str(repo_a),
        baseline_snapshot_id=snap_a.snapshot_id,
        current_snapshot_id=snap_a.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest=policy_digest,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    store.save_session(sess_a)

    # Session B started MORE RECENTLY
    sess_b = Session(
        session_id="sess-project-b",
        task_id="task-b",
        contract_revision=1,
        repo_root=str(repo_b),
        baseline_snapshot_id=snap_b.snapshot_id,
        current_snapshot_id=snap_b.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest=policy_digest,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    store.save_session(sess_b)

    # Create MCP server targeting repo_a and proj-a
    server_a = create_mcp_server(
        store=store,
        repo_root=repo_a,
        project_id="proj-a",
        policy=policy,
        policy_digest=policy_digest,
    )

    # Automatic session resolution must resolve sess_a, NOT the newer sess_b!
    status_a = await server_a.call_tool("get_status", arguments={})
    data_a = _extract_data(status_a)
    assert data_a["session_id"] == "sess-project-a"
    assert data_a["task_id"] == "task-a"

    # Attempting to query session_b in server_a must fail with workspace mismatch
    with pytest.raises(Exception) as exc_info:
        await server_a.call_tool("get_status", arguments={"session_id": "sess-project-b"})
    assert "does not match effective root" in str(exc_info.value) or (
        exc_info.value.__cause__ and "does not match effective root" in str(exc_info.value.__cause__)
    )


@pytest.mark.anyio
async def test_inspect_changes_and_handoff_missing_baseline_never_substituted(tmp_path: Path):
    """Verify missing baseline snapshot is never reconstructed or substituted in inspect_changes or get_handoff."""
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

    policy, policy_digest = resolve_trusted_policy()
    missing_baseline_id = "sha256:" + "f" * 64
    session = Session(
        session_id="sess-missing-base",
        task_id="t1",
        contract_revision=1,
        repo_root=str(repo),
        baseline_snapshot_id=missing_baseline_id,
        current_snapshot_id=None,
        profile=OperatingProfile.FLOW,
        policy_digest=policy_digest,
        integration_status=IntegrationStatus.UNGUARDED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(session)

    server = create_mcp_server(
        store=store,
        repo_root=repo,
        project_id="p1",
        policy=policy,
        policy_digest=policy_digest,
    )

    # 1. inspect_changes must return error and NOT save missing_baseline_id to store
    inspect_res = await server.call_tool("inspect_changes", arguments={"session_id": "sess-missing-base"})
    data = _extract_data(inspect_res)
    assert "Missing baseline snapshot" in str(data)
    assert store.get_snapshot(missing_baseline_id) is None

    # 2. get_handoff must return error markdown indicating missing baseline
    handoff_res = await server.call_tool("get_handoff", arguments={"session_id": "sess-missing-base"})
    handoff_text = handoff_res.content[0].text
    assert "Baseline snapshot" in handoff_text
    assert "does not exist in store" in handoff_text


@pytest.mark.anyio
async def test_incomplete_baseline_fails_closed_in_all_mcp_tools(tmp_path: Path):
    """Verify incomplete baseline snapshot causes inspect_changes, get_status, and claim_completion to fail closed."""
    from proofmesh.models import RepoSnapshot

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "code.py").write_text("print(1)\n")

    db_path = tmp_path / "test_incomplete.db"
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

    # Incomplete baseline snapshot
    inc_baseline_id = "sha256:" + "e" * 64
    inc_baseline = RepoSnapshot(
        snapshot_id=inc_baseline_id,
        repo_root=str(repo),
        git_commit=None,
        git_dirty=False,
        files=(),
        captured_at=datetime.now(timezone.utc),
        complete=False,
        observation_errors=("Broken symlink in baseline: broken.txt",),
    )
    store.save_snapshot(inc_baseline)

    policy, policy_digest = resolve_trusted_policy()
    session = Session(
        session_id="sess-inc-base",
        task_id="t1",
        contract_revision=1,
        repo_root=str(repo),
        baseline_snapshot_id=inc_baseline_id,
        current_snapshot_id=None,
        profile=OperatingProfile.FLOW,
        policy_digest=policy_digest,
        integration_status=IntegrationStatus.UNGUARDED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(session)

    server = create_mcp_server(
        store=store,
        repo_root=repo,
        project_id="p1",
        policy=policy,
        policy_digest=policy_digest,
    )

    # 1. inspect_changes rejects incomplete baseline
    res_inspect = await server.call_tool("inspect_changes", arguments={"session_id": "sess-inc-base"})
    data_inspect = _extract_data(res_inspect)
    assert "incomplete" in str(data_inspect).lower()

    # 2. get_status rejects incomplete baseline
    res_status = await server.call_tool("get_status", arguments={"session_id": "sess-inc-base"})
    data_status = _extract_data(res_status)
    assert data_status["verdict"].lower() == "block"
    assert any("incomplete" in r.lower() for r in data_status["reasons"])

    # 3. claim_completion rejects incomplete baseline and does NOT accept
    res_claim = await server.call_tool("claim_completion", arguments={"session_id": "sess-inc-base"})
    data_claim = _extract_data(res_claim)
    assert data_claim["status"] == "BLOCKED"
    assert data_claim["verdict"].lower() == "block"
    reloaded_sess = store.get_session("sess-inc-base")
    assert reloaded_sess.state != SessionState.ACCEPTED

