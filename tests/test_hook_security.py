"""Comprehensive security and contract enforcement tests for ProofMesh host hooks.

Validates:
1. Strict path normalization and workspace containment:
   - Traversal attack rejection ('../outside.txt', '/etc/passwd', 'foo/../../bar').
   - NUL byte injection rejection.
   - Windows-style backslashes normalized safely and drive/UNC prefixes rejected.
   - Symlink escape prevention (both symlinked files and parent directories).
   - Write tools (FILE_WRITE_TOOLS) with missing, empty, or invalid path arguments denied.
   - Bounded command checking: known destructive operations intercepted, no sentinel shortcuts.
2. Honest integration status reporting:
   - Defaults to UNGUARDED, never falsely reports ENFORCED.
   - Reports ENFORCED only when both hooks and MCP are active/verified.
   - Reports PARTIAL when only one is active.
   - Session lookup strictly validated by project_id and repo_root.
3. Stop hook continuation & LoopDetector retry budget exhaustion:
   - Blocks/continues when evidence is missing.
   - Halts and returns allow when retry budget is exhausted, keeping verdict as BLOCK.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pytest

from proofmesh.adapters.antigravity import AntigravityAdapter
from proofmesh.adapters.hook_protocol import (
    FILE_WRITE_TOOLS,
    PreInvocationPayload,
    PreToolUsePayload,
    StopPayload,
    ToolCallInfo,
    check_command_scope,
    evaluate_pre_tool_use,
    evaluate_stop,
    extract_target_file,
    normalize_and_validate_path,
)
from proofmesh.core.loop_detector import LoopDetector
from proofmesh.core.repo_snapshot import capture_snapshot
from proofmesh.models import (
    AcceptanceCriterion,
    ApprovalStatus,
    BudgetPolicy,
    EnforcementLevel,
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
from proofmesh.storage.store import ProofMeshStore


@pytest.fixture
def workspace_env(tmp_path: Path):
    """Create an isolated workspace environment with store, task, and policy."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    src_dir = repo_root / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('test app')\n", encoding="utf-8")

    db_path = tmp_path / "proofmesh_sec.db"
    store = ProofMeshStore(db_path)
    store.create_project("sec-project", root_path=str(repo_root))

    task_rev = TaskRevision(
        task_id="sec-task",
        revision=1,
        parent_revision=None,
        summary="Security test contract",
        risk_level=RiskLevel.MEDIUM,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="sec-lead",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "0" * 64,
        scope=ScopePolicy(
            allow_paths=("src/**", "tests/**"),
            restricted_paths=(".git/**", ".env*", "secrets/**"),
            max_changed_files=5,
        ),
        required_gates=("test-gate",),
        acceptance_criteria=(
            AcceptanceCriterion(criterion_id="ac-sec-1", description="Secure hooks", required_gates=("test-gate",)),
        ),
        constraints=("No sandbox escape",),
        raw_markdown="# Security Task",
    )
    store.save_task_revision(task_rev, project_id="sec-project")

    baseline = capture_snapshot(repo_root)
    store.save_snapshot(baseline)

    session = Session(
        session_id="sess-sec-1",
        task_id="sec-task",
        contract_revision=1,
        repo_root=str(repo_root),
        baseline_snapshot_id=baseline.snapshot_id,
        current_snapshot_id=baseline.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest="sha256:" + "1" * 64,
        integration_status=IntegrationStatus.UNGUARDED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(session)

    policy = TrustedPolicy(
        schema_version=1,
        profile=OperatingProfile.FLOW,
        budget=BudgetPolicy(max_retries=3),
    )

    return {
        "repo_root": repo_root,
        "store": store,
        "task_rev": task_rev,
        "session": session,
        "policy": policy,
        "scope_policy": task_rev.scope,
    }


# ==============================================================================
# 1. Path Traversal & Workspace Containment Tests
# ==============================================================================


def test_path_traversal_attacks_rejected(workspace_env):
    """Test that relative traversal, absolute system paths, and dot-dot patterns are rejected."""
    ws = workspace_env["repo_root"]
    scope = workspace_env["scope_policy"]

    traversal_vectors = [
        "../outside.txt",
        "/etc/passwd",
        "foo/../../bar",
        "src/../../../escaped.py",
        "./../../outside.txt",
        "src/../..",
    ]

    for vec in traversal_vectors:
        # 1. Directly in normalize_and_validate_path
        with pytest.raises(ValueError, match="(traversal|resolves outside|escaping workspace)"):
            normalize_and_validate_path(vec, workspace_root=ws)

        # 2. In extract_target_file
        with pytest.raises(ValueError):
            extract_target_file("write_file", {"Path": vec}, workspace_root=ws)

        # 3. In evaluate_pre_tool_use
        payload = PreToolUsePayload(
            conversationId="test-conv",
            toolCall=ToolCallInfo(name="write_file", args={"Path": vec}),
        )
        resp = evaluate_pre_tool_use(payload, scope_policy=scope, workspace_root=ws)
        assert resp.is_denied is True
        assert resp.decision == "deny"
        assert "ProofMesh path security" in resp.reason or "escaping" in resp.reason or "traversal" in resp.reason


def test_read_tool_path_traversal_denied(workspace_env):
    """Test that read-only tools targeting outside paths are also safely rejected."""
    ws = workspace_env["repo_root"]
    scope = workspace_env["scope_policy"]

    payload = PreToolUsePayload(
        conversationId="test-conv",
        toolCall=ToolCallInfo(name="read_file", args={"path": "../outside.txt"}),
    )
    resp = evaluate_pre_tool_use(payload, scope_policy=scope, workspace_root=ws)
    assert resp.is_denied is True
    assert "traversal" in resp.reason.lower() or "security" in resp.reason.lower()


# ==============================================================================
# 2. NUL Byte Injection Tests
# ==============================================================================


def test_nul_byte_injection_rejected(workspace_env):
    """Test that NUL byte injection vectors are immediately detected and rejected."""
    ws = workspace_env["repo_root"]
    scope = workspace_env["scope_policy"]

    nul_vectors = [
        "src/main.py\0.txt",
        "test\0payload.py",
        "src/\0/evil.py",
    ]

    for vec in nul_vectors:
        with pytest.raises(ValueError, match="NUL byte"):
            normalize_and_validate_path(vec, workspace_root=ws)

        payload = PreToolUsePayload(
            conversationId="test-conv",
            toolCall=ToolCallInfo(name="write_file", args={"Path": vec}),
        )
        resp = evaluate_pre_tool_use(payload, scope_policy=scope, workspace_root=ws)
        assert resp.is_denied is True
        assert "NUL byte" in resp.reason


# ==============================================================================
# 3. Windows-Style Backslashes, Drive Letters, & UNC Paths
# ==============================================================================


def test_windows_backslashes_normalized_safely(workspace_env):
    """Test safe normalization of Windows backslashes for valid in-scope paths."""
    ws = workspace_env["repo_root"]
    norm = normalize_and_validate_path("src\\sub\\module.py", workspace_root=ws)
    assert norm == "src/sub/module.py"


def test_windows_backslash_traversal_rejected(workspace_env):
    """Test that backslash traversal (e.g. '..\\outside') cannot bypass checks."""
    ws = workspace_env["repo_root"]
    scope = workspace_env["scope_policy"]

    backslash_attacks = [
        "..\\outside.txt",
        "src\\..\\..\\secret.key",
        "foo\\..\\..\\bar",
    ]

    for vec in backslash_attacks:
        with pytest.raises(ValueError, match="traversal"):
            normalize_and_validate_path(vec, workspace_root=ws)

        payload = PreToolUsePayload(
            conversationId="test-conv",
            toolCall=ToolCallInfo(name="edit_file", args={"Path": vec}),
        )
        resp = evaluate_pre_tool_use(payload, scope_policy=scope, workspace_root=ws)
        assert resp.is_denied is True


def test_drive_qualified_and_unc_paths_rejected(workspace_env):
    """Test that Windows drive prefixes (C:\\) and UNC network paths are rejected."""
    ws = workspace_env["repo_root"]

    prohibited = [
        "C:\\Windows\\system32\\cmd.exe",
        "C:/Windows/system32/calc.exe",
        "D:\\projects\\secret.txt",
        "\\\\server\\share\\file.txt",
        "//server/share/file.txt",
    ]

    for vec in prohibited:
        with pytest.raises(ValueError, match="(Drive-qualified|UNC network)"):
            normalize_and_validate_path(vec, workspace_root=ws)


# ==============================================================================
# 4. Symlink Escape Tests
# ==============================================================================


def test_symlink_file_escape_rejected(workspace_env, tmp_path):
    """Test that symlink pointing outside the workspace is detected and denied."""
    ws = workspace_env["repo_root"]
    scope = workspace_env["scope_policy"]

    # Create outside secret file
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.env"
    outside_file.write_text("API_KEY=leak\n", encoding="utf-8")

    # Create symlink inside workspace pointing outside
    symlink_file = ws / "symlink_secret"
    try:
        symlink_file.symlink_to(outside_file)
    except OSError:
        pytest.skip("Symlink creation not supported in current environment")

    # Attempt to edit through symlink
    payload = PreToolUsePayload(
        conversationId="test-conv",
        toolCall=ToolCallInfo(name="edit_file", args={"Path": "symlink_secret"}),
    )
    resp = evaluate_pre_tool_use(payload, scope_policy=scope, workspace_root=ws)
    assert resp.is_denied is True
    assert "escaping workspace root" in resp.reason


def test_symlink_directory_escape_for_nonexistent_file(workspace_env, tmp_path):
    """Test that writing a nonexistent file inside a symlinked outside directory is denied."""
    ws = workspace_env["repo_root"]
    scope = workspace_env["scope_policy"]

    outside_dir = tmp_path / "outside_target_dir"
    outside_dir.mkdir()

    symlink_dir = ws / "sym_folder"
    try:
        symlink_dir.symlink_to(outside_dir)
    except OSError:
        pytest.skip("Symlink creation not supported in current environment")

    # Nonexistent file inside symlinked directory
    payload = PreToolUsePayload(
        conversationId="test-conv",
        toolCall=ToolCallInfo(name="write_file", args={"Path": "sym_folder/new_exploit.py"}),
    )
    resp = evaluate_pre_tool_use(payload, scope_policy=scope, workspace_root=ws)
    assert resp.is_denied is True
    assert "escaping workspace root" in resp.reason


# ==============================================================================
# 5. File Write Tools Missing/Invalid Arguments
# ==============================================================================


@pytest.mark.parametrize("tool_name", list(FILE_WRITE_TOOLS))
def test_file_write_tools_missing_path_arguments_denied(workspace_env, tool_name):
    """Test that every FILE_WRITE_TOOL is strictly denied if path argument is missing."""
    ws = workspace_env["repo_root"]
    scope = workspace_env["scope_policy"]

    # 1. Missing args entirely
    payload_empty = PreToolUsePayload(
        conversationId="test-conv",
        toolCall=ToolCallInfo(name=tool_name, args={}),
    )
    resp = evaluate_pre_tool_use(payload_empty, scope_policy=scope, workspace_root=ws)
    assert resp.is_denied is True
    assert "missing, empty, or unrecognized" in resp.reason

    # 2. Empty string path
    payload_empty_str = PreToolUsePayload(
        conversationId="test-conv",
        toolCall=ToolCallInfo(name=tool_name, args={"Path": ""}),
    )
    resp_str = evaluate_pre_tool_use(payload_empty_str, scope_policy=scope, workspace_root=ws)
    assert resp_str.is_denied is True
    assert "missing, empty, or unrecognized" in resp_str.reason or "cannot be empty" in resp_str.reason

    # 3. Unrecognized argument key
    payload_unrec = PreToolUsePayload(
        conversationId="test-conv",
        toolCall=ToolCallInfo(name=tool_name, args={"destination": "src/new.py"}),
    )
    resp_unrec = evaluate_pre_tool_use(payload_unrec, scope_policy=scope, workspace_root=ws)
    assert resp_unrec.is_denied is True
    assert "missing, empty, or unrecognized" in resp_unrec.reason

    # 4. Non-string path argument
    payload_non_str = PreToolUsePayload(
        conversationId="test-conv",
        toolCall=ToolCallInfo(name=tool_name, args={"Path": 12345}),
    )
    resp_non_str = evaluate_pre_tool_use(payload_non_str, scope_policy=scope, workspace_root=ws)
    assert resp_non_str.is_denied is True


# ==============================================================================
# 6. Destructive Command Scope Denial & Sentinel Removal
# ==============================================================================


def test_destructive_command_interception(workspace_env):
    """Test that dangerous repo destructive operations are intercepted without fake sentinels."""
    scope = workspace_env["scope_policy"]

    destructive_cmds = [
        "git checkout -- .",
        "git restore src/app.py",
        "git reset --hard HEAD~1",
        "git reset HEAD",
        "rm -rf tests",
        "rm -rf src",
        "rm -rf .git",
        "rm -rf docs",
        "rm -rf .",
        "rm -rf *",
        "rm -r tests",
        "git clean -fd",
    ]

    for cmd in destructive_cmds:
        allowed, reason = check_command_scope(cmd, scope)
        assert allowed is False
        assert "destructive operation" in reason.lower()

        payload = PreToolUsePayload(
            conversationId="test-conv",
            toolCall=ToolCallInfo(name="run_command", args={"CommandLine": cmd}),
        )
        resp = evaluate_pre_tool_use(payload, scope_policy=scope)
        assert resp.is_denied is True


def test_command_targeting_restricted_path(workspace_env):
    """Test that shell operations targeting restricted paths are denied."""
    scope = workspace_env["scope_policy"]

    bad_cmd = "rm -f secrets/creds.json"
    allowed, reason = check_command_scope(bad_cmd, scope)
    assert allowed is False
    assert "restricted path pattern" in reason


def test_sentinel_free_command_checking(workspace_env):
    """Test that benign echo commands with 'blocked_command' are NOT artificially blocked."""
    scope = workspace_env["scope_policy"]
    allowed, reason = check_command_scope("echo hello world", scope)
    assert allowed is True
    assert reason is None


# ==============================================================================
# 7. Honest Integration Status Reporting
# ==============================================================================


def test_integration_status_honest_defaults(workspace_env):
    """Test that AntigravityAdapter defaults honestly to UNGUARDED instead of ENFORCED."""
    adapter = AntigravityAdapter(
        store=workspace_env["store"],
        repo_root=workspace_env["repo_root"],
    )
    # Default without explicit verification must be UNGUARDED
    assert adapter.get_integration_status() == IntegrationStatus.UNGUARDED


def test_integration_status_transitions(workspace_env):
    """Test accurate status reporting across active capability combinations."""
    store = workspace_env["store"]

    # 1. Neither active -> UNGUARDED
    ad_un = AntigravityAdapter(store=store, hooks_enabled=False, mcp_enabled=False)
    assert ad_un.get_integration_status() == IntegrationStatus.UNGUARDED

    # 2. Hooks only -> PARTIAL
    ad_hooks = AntigravityAdapter(store=store, hooks_enabled=True, mcp_enabled=False)
    assert ad_hooks.get_integration_status() == IntegrationStatus.PARTIAL

    # 3. MCP only -> PARTIAL
    ad_mcp = AntigravityAdapter(store=store, hooks_enabled=False, mcp_enabled=True)
    assert ad_mcp.get_integration_status() == IntegrationStatus.PARTIAL

    # 4. Both active -> ENFORCED
    ad_enforced = AntigravityAdapter(store=store, hooks_enabled=True, mcp_enabled=True)
    assert ad_enforced.get_integration_status() == IntegrationStatus.ENFORCED


def test_adapter_hook_invocation_activates_hooks_flag(workspace_env):
    """Test that handling a real hook event marks hooks_enabled active."""
    adapter = AntigravityAdapter(
        store=workspace_env["store"],
        repo_root=workspace_env["repo_root"],
        hooks_enabled=False,
        mcp_enabled=False,
    )
    assert adapter.get_integration_status() == IntegrationStatus.UNGUARDED

    # Handle a tool call
    payload = PreToolUsePayload(
        conversationId=workspace_env["session"].session_id,
        toolCall=ToolCallInfo(name="write_file", args={"Path": "src/app.py"}),
    )
    adapter.handle_pre_tool_use(payload)

    # Hooks are now verified active -> transitions to PARTIAL
    assert adapter.hooks_enabled is True
    assert adapter.get_integration_status() == IntegrationStatus.PARTIAL


# ==============================================================================
# 8. Session Resolution Scoped by Project and Repository
# ==============================================================================


def test_session_resolution_scoped_by_repo_root(tmp_path):
    """Test that _resolve_session never returns a session from another repository."""
    repo_a = tmp_path / "repo_a"
    repo_a.mkdir()
    repo_b = tmp_path / "repo_b"
    repo_b.mkdir()

    db_path = tmp_path / "multi_repo.db"
    store = ProofMeshStore(db_path)
    store.create_project("proj-b", root_path=str(repo_b))

    snap_b = capture_snapshot(repo_b)
    store.save_snapshot(snap_b)

    task_b = TaskRevision(
        task_id="task-b",
        revision=1,
        parent_revision=None,
        summary="Task B",
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="lead",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "b" * 64,
        scope=ScopePolicy(allow_paths=("src/**",)),
        required_gates=(),
        acceptance_criteria=(),
        constraints=(),
        raw_markdown="# Task B",
    )
    store.save_task_revision(task_b, project_id="proj-b")

    sess_b = Session(
        session_id="sess-repo-b",
        task_id="task-b",
        contract_revision=1,
        repo_root=str(repo_b),
        baseline_snapshot_id=snap_b.snapshot_id,
        current_snapshot_id=snap_b.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest="sha256:" + "b" * 64,
        integration_status=IntegrationStatus.UNGUARDED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(sess_b)

    # Adapter bound to repo_a must NOT find sess_b
    adapter_a = AntigravityAdapter(store=store, repo_root=repo_a, project_id="proj-a")
    resolved = adapter_a._resolve_session("sess-repo-b")
    assert resolved is None

    # Blind lookup without matching conversationId must also return None
    resolved_none = adapter_a._resolve_session(None)
    assert resolved_none is None


# ==============================================================================
# 9. Stop Hook Continuation & LoopDetector Retry Budget Exhaustion
# ==============================================================================


def test_evaluate_stop_continuation_on_missing_gates():
    """Test evaluate_stop forces continuation when verification gates are unfulfilled."""
    payload = StopPayload(conversationId="conv-stop-1", fullyIdle=True)
    resp = evaluate_stop(payload, unfulfilled_gates=("mandatory-gate",))
    assert resp.is_continued is True
    assert resp.decision == "continue"
    assert "mandatory-gate" in resp.reason


def test_evaluate_stop_retry_budget_exhaustion():
    """Test evaluate_stop respects LoopDetector budget, allowing host stop with BLOCK verdict."""
    payload = StopPayload(conversationId="conv-stop-2", fullyIdle=True)
    session_id = "sess-loop-1"
    gate_id = "failing-gate"
    budget = BudgetPolicy(max_retries=3)
    loop_detector = LoopDetector()

    block_verdict = VerdictRecord(
        verdict_id="verd-1",
        session_id=session_id,
        contract_revision=1,
        snapshot_id="sha256:" + "0" * 64,
        verdict=VerdictOutcome.BLOCK,
        enforcement_level=EnforcementLevel.ENFORCED,
        reasons=("Mandatory gate failing-gate failed",),
        evidence_ids=(),
        evaluated_at=datetime.now(timezone.utc),
    )

    # Attempts 1 and 2: within budget -> continues
    loop_detector.record_attempt(session_id, gate_id, "SyntaxError")
    resp_1 = evaluate_stop(
        payload,
        verdict=block_verdict,
        loop_detector=loop_detector,
        budget=budget,
        session_id=session_id,
        unfulfilled_gates=(gate_id,),
    )
    assert resp_1.is_continued is True
    assert resp_1.decision == "continue"

    loop_detector.record_attempt(session_id, gate_id, "SyntaxError")
    resp_2 = evaluate_stop(
        payload,
        verdict=block_verdict,
        loop_detector=loop_detector,
        budget=budget,
        session_id=session_id,
        unfulfilled_gates=(gate_id,),
    )
    assert resp_2.is_continued is True
    assert resp_2.decision == "continue"

    # Attempt 3: reaches max_retries (3) -> budget exhausted -> allows host stop!
    loop_detector.record_attempt(session_id, gate_id, "SyntaxError")
    resp_3 = evaluate_stop(
        payload,
        verdict=block_verdict,
        loop_detector=loop_detector,
        budget=budget,
        session_id=session_id,
        unfulfilled_gates=(gate_id,),
    )
    assert resp_3.is_continued is False
    assert resp_3.decision == "allow"
    # Verdict remains BLOCK and reason explains budget exhaustion
    assert block_verdict.verdict == VerdictOutcome.BLOCK
    assert "Retry budget exhausted" in resp_3.reason
    assert "verdict BLOCK" in resp_3.reason


def test_explicit_budget_exhausted_flag():
    """Test evaluate_stop halts with budget_exhausted=True."""
    payload = StopPayload(conversationId="conv-stop-3", fullyIdle=True)
    block_verdict = VerdictRecord(
        verdict_id="verd-2",
        session_id="sess-2",
        contract_revision=1,
        snapshot_id="sha256:" + "0" * 64,
        verdict=VerdictOutcome.BLOCK,
        enforcement_level=EnforcementLevel.ENFORCED,
        reasons=("Test failure",),
        evidence_ids=(),
        evaluated_at=datetime.now(timezone.utc),
    )
    resp = evaluate_stop(payload, verdict=block_verdict, budget_exhausted=True)
    assert resp.decision == "allow"
    assert resp.is_continued is False
    assert "Retry budget exhausted" in resp.reason


def test_antigravity_stop_missing_baseline_fails_closed(workspace_env):
    """Test handle_stop fails closed when baseline snapshot is missing from store, without falling back to current."""
    env = workspace_env
    missing_baseline_id = "sha256:" + "f" * 64
    session = env["session"].model_copy(update={
        "session_id": "sess-missing-baseline",
        "baseline_snapshot_id": missing_baseline_id,
    })
    env["store"].save_session(session)

    adapter = AntigravityAdapter(
        store=env["store"],
        policy=env["policy"],
        repo_root=env["repo_root"],
        project_id="sec-project",
        hooks_enabled=True,
    )

    payload = StopPayload(conversationId=session.session_id, fullyIdle=True)
    resp = adapter.handle_stop(payload)

    assert resp.decision == "continue"
    assert resp.is_continued is True
    assert "Baseline repository snapshot" in resp.reason
    assert "not found" in resp.reason


def test_antigravity_stop_incomplete_baseline_fails_closed(workspace_env):
    """Test handle_stop fails closed when baseline snapshot was incomplete."""
    env = workspace_env
    from proofmesh.models import RepoSnapshot
    incomplete_id = "sha256:" + "e" * 64
    incomplete_snap = RepoSnapshot(
        snapshot_id=incomplete_id,
        repo_root=str(env["repo_root"]),
        git_commit="abcdef0123456789",
        git_dirty=False,
        files=(),
        captured_at=datetime.now(timezone.utc),
        complete=False,
        observation_errors=("Unreadable baseline directory",),
    )
    env["store"].save_snapshot(incomplete_snap)

    session = env["session"].model_copy(update={
        "session_id": "sess-incomplete-baseline",
        "baseline_snapshot_id": incomplete_id,
    })
    env["store"].save_session(session)

    adapter = AntigravityAdapter(
        store=env["store"],
        policy=env["policy"],
        repo_root=env["repo_root"],
        project_id="sec-project",
        hooks_enabled=True,
    )

    payload = StopPayload(conversationId=session.session_id, fullyIdle=True)
    resp = adapter.handle_stop(payload)

    assert resp.decision == "continue"
    assert resp.is_continued is True
    assert "Incomplete baseline repository snapshot" in resp.reason
    assert "Unreadable baseline directory" in resp.reason


def test_antigravity_stop_policy_digest_mismatch_fails_closed(workspace_env):
    """Test handle_stop fails closed when session policy digest does not match adapter trusted policy digest."""
    env = workspace_env
    session = env["session"].model_copy(update={"policy_digest": "sha256:" + "d" * 64})
    env["store"].save_session(session)

    adapter = AntigravityAdapter(
        store=env["store"],
        policy=env["policy"],
        repo_root=env["repo_root"],
        project_id="sec-project",
        hooks_enabled=True,
    )

    payload = StopPayload(conversationId=session.session_id, fullyIdle=True)
    resp = adapter.handle_stop(payload)

    assert resp.decision == "continue"
    assert resp.is_continued is True
    assert "Policy digest mismatch" in resp.reason


def test_antigravity_adapter_resolves_trusted_policy_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test AntigravityAdapter resolves trusted policy via resolve_trusted_policy and respects PROOFMESH_POLICY."""
    custom_policy_content = """schema_version = 1
profile = "guided"

[budget]
max_retries = 5
max_continuation_steps = 15

[scope]
default_allow_paths = ["custom/**"]
default_restricted_paths = [".git/**"]

[gates.custom_gate]
provider = "pytest"
command = ["pytest", "custom"]
timeout_seconds = 20
mandatory = true
"""
    custom_policy_file = tmp_path / "custom_policy.toml"
    custom_policy_file.write_text(custom_policy_content, encoding="utf-8")
    monkeypatch.setenv("PROOFMESH_POLICY", str(custom_policy_file))
    db_file = tmp_path / "default.db"

    adapter = AntigravityAdapter(store=ProofMeshStore(db_file))
    assert adapter.policy.profile == OperatingProfile.GUIDED
    assert adapter.policy.budget.max_retries == 5
    assert "custom_gate" in adapter.policy.gates
    assert adapter.policy_digest.startswith("sha256:")
