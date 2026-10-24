"""Integration tests for ProofMesh MCP server and Antigravity host adapter.

Covers:
- Real MCP request/response roundtrips for all exposed tools.
- Hook lifecycle evaluation: PreInvocation reminder, PreToolUse scope denial,
  and Stop continuation on missing or stale evidence.
- Verified integration status reporting (ENFORCED, PARTIAL, UNGUARDED).
- Fixture parity with tests/fixtures/host_payloads/antigravity/.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import pytest

from proofmesh.config import compute_policy_digest

from proofmesh.adapters.antigravity import AntigravityAdapter
from proofmesh.adapters.hook_protocol import (
    HookDecision,
    PreInvocationPayload,
    PreInvocationResponse,
    PreToolUseAllowResponse,
    PreToolUseDenyResponse,
    PreToolUsePayload,
    StopAllowResponse,
    StopContinueResponse,
    StopPayload,
    evaluate_pre_tool_use,
    evaluate_stop,
    parse_hook_payload,
)
from proofmesh.adapters.mcp_server import create_mcp_server
from proofmesh.core.repo_snapshot import capture_snapshot
from proofmesh.core.task_service import TaskService
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

FIXTURES_DIR = Path(__file__).parent / "fixtures"
AGY_FIXTURES = FIXTURES_DIR / "host_payloads" / "antigravity"


@pytest.fixture
def test_env(tmp_path: Path):
    """Set up an isolated repo, SQLite store, test task revision, and test policy."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    src_dir = repo_root / "src"
    src_dir.mkdir()
    test_file = src_dir / "main.py"
    test_file.write_text("print('hello ProofMesh')\n", encoding="utf-8")

    db_path = tmp_path / "proofmesh_test.db"
    store = ProofMeshStore(db_path)
    store.create_project("test-project", root_path=str(repo_root))

    # Create approved task revision
    task_rev = TaskRevision(
        task_id="task-42",
        revision=1,
        parent_revision=None,
        summary="Implement MCP integration",
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="tech-lead",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "a" * 64,
        scope=ScopePolicy(
            allow_paths=("src/**", "tests/**"),
            restricted_paths=(".git/**", ".github/**", "sensitive/**"),
            max_changed_files=10,
        ),
        required_gates=("test-gate",),
        acceptance_criteria=(
            AcceptanceCriterion(
                criterion_id="ac-1",
                description="MCP tools are exposed and functional",
                required_gates=("test-gate",),
            ),
        ),
        constraints=("No arbitrary shell execution",),
        raw_markdown="# Task 42\nImplement MCP integration",
    )
    store.save_task_revision(task_rev, project_id="test-project")

    # Baseline snapshot
    baseline_snap = capture_snapshot(repo_root)
    store.save_snapshot(baseline_snap)

    # Active session
    # Trusted policy with allowlisted gate
    policy = TrustedPolicy(
        schema_version=1,
        profile=OperatingProfile.FLOW,
        gates={
            "test-gate": GatePolicy(
                provider="pytest",
                command=("python3", "-c", "print('gate passed')"),
                timeout_seconds=10,
                mandatory=True,
            ),
            "failing-gate": GatePolicy(
                provider="pytest",
                command=("python3", "-c", "import sys; sys.exit(1)"),
                timeout_seconds=10,
                mandatory=False,
            ),
        },
    )
    policy_digest = compute_policy_digest(policy)

    session = Session(
        session_id="sess-integration-test-1",
        task_id=task_rev.task_id,
        contract_revision=task_rev.revision,
        repo_root=str(repo_root),
        baseline_snapshot_id=baseline_snap.snapshot_id,
        current_snapshot_id=baseline_snap.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest=policy_digest,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(session)

    return {
        "repo_root": repo_root,
        "store": store,
        "task_rev": task_rev,
        "baseline_snap": baseline_snap,
        "session": session,
        "policy": policy,
    }


def _extract_text_or_json(call_result) -> dict | str:
    """Helper to extract parsed JSON or text from MCP tool call response."""
    text = call_result.content[0].text
    try:
        return json.loads(text)
    except Exception:
        return text


# ==============================================================================
# 1. Real MCP Request / Response Tests for All Exposed Tools
# ==============================================================================


@pytest.mark.anyio
async def test_mcp_list_tools(test_env):
    """Verify that all 6 required tools are properly exposed on the MCP server."""
    server = create_mcp_server(
        store=test_env["store"],
        repo_root=test_env["repo_root"],
        session_id=test_env["session"].session_id,
        policy=test_env["policy"],
    )
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}
    expected_tools = {
        "get_task_contract",
        "inspect_changes",
        "run_verification",
        "get_status",
        "claim_completion",
        "get_handoff",
    }
    assert expected_tools.issubset(tool_names), f"Missing tools: {expected_tools - tool_names}"


@pytest.mark.anyio
async def test_mcp_get_task_contract(test_env):
    """Test get_task_contract tool returns active approved TaskRevision contract."""
    server = create_mcp_server(
        store=test_env["store"],
        repo_root=test_env["repo_root"],
        session_id=test_env["session"].session_id,
        policy=test_env["policy"],
    )
    res = await server.call_tool("get_task_contract", arguments={"task_id": "task-42"})
    assert res.is_error is False
    data = _extract_text_or_json(res)
    assert isinstance(data, dict)
    assert data["task_id"] == "task-42"
    assert data["revision"] == 1
    assert data["approval_status"] == "approved"
    assert "src/**" in data["scope"]["allow_paths"]
    assert "test-gate" in data["required_gates"]
    assert len(data["acceptance_criteria"]) == 1
    assert data["acceptance_criteria"][0]["criterion_id"] == "ac-1"


@pytest.mark.anyio
async def test_mcp_inspect_changes(test_env):
    """Test inspect_changes tool detects repo modifications and checks scope."""
    server = create_mcp_server(
        store=test_env["store"],
        repo_root=test_env["repo_root"],
        session_id=test_env["session"].session_id,
        policy=test_env["policy"],
    )

    # 1. No changes initially
    res_clean = await server.call_tool("inspect_changes", arguments={})
    data_clean = _extract_text_or_json(res_clean)
    assert data_clean["total_changed_files"] == 0
    assert data_clean["has_violations"] is False

    # 2. Modify in-scope file
    main_py = test_env["repo_root"] / "src" / "main.py"
    main_py.write_text("print('updated!')\n")

    res_modified = await server.call_tool("inspect_changes", arguments={})
    data_modified = _extract_text_or_json(res_modified)
    assert data_modified["total_changed_files"] == 1
    assert data_modified["has_violations"] is False
    assert any(c["path"] == "src/main.py" for c in data_modified["changes"])

    # 3. Add out-of-scope file
    bad_file = test_env["repo_root"] / "sensitive" / "secret.key"
    bad_file.parent.mkdir(parents=True, exist_ok=True)
    bad_file.write_text("shhh")

    res_violation = await server.call_tool("inspect_changes", arguments={})
    data_violation = _extract_text_or_json(res_violation)
    assert data_violation["has_violations"] is True
    assert any(f["restricted"] is True for f in data_violation["findings"])


@pytest.mark.anyio
async def test_mcp_run_verification(test_env):
    """Test run_verification executes allowlisted gate and records evidence."""
    server = create_mcp_server(
        store=test_env["store"],
        repo_root=test_env["repo_root"],
        session_id=test_env["session"].session_id,
        policy=test_env["policy"],
    )

    # Disallowed gate
    res_unknown = await server.call_tool("run_verification", arguments={"gate_id": "nonexistent"})
    data_unknown = _extract_text_or_json(res_unknown)
    assert "error" in data_unknown

    # Allowlisted gate
    res_gate = await server.call_tool("run_verification", arguments={"gate_id": "test-gate"})
    assert res_gate.is_error is False
    data_gate = _extract_text_or_json(res_gate)
    assert data_gate["status"] == "PASSED"
    assert data_gate["exit_code"] == 0
    assert data_gate["gate_id"] == "test-gate"
    assert "evidence_id" in data_gate

    # Verify persisted in database
    ev_records = test_env["store"].list_evidence_for_session(test_env["session"].session_id)
    assert len(ev_records) == 1
    assert ev_records[0].evidence_id == data_gate["evidence_id"]


@pytest.mark.anyio
async def test_mcp_get_status_and_claim_completion(test_env):
    """Test get_status and claim_completion transitions from BLOCK to ACCEPTED."""
    server = create_mcp_server(
        store=test_env["store"],
        repo_root=test_env["repo_root"],
        session_id=test_env["session"].session_id,
        policy=test_env["policy"],
    )

    # 1. Before verification: get_status is BLOCK
    res_status = await server.call_tool("get_status", arguments={})
    data_status = _extract_text_or_json(res_status)
    assert data_status["verdict"] == "BLOCK"
    assert any("Missing mandatory evidence" in r for r in data_status["reasons"])

    # 2. Before verification: claim_completion is rejected
    res_claim_blocked = await server.call_tool("claim_completion", arguments={})
    data_claim_blocked = _extract_text_or_json(res_claim_blocked)
    assert data_claim_blocked["status"] == "BLOCKED"
    assert data_claim_blocked["verdict"] == "BLOCK"
    assert "handoff" in data_claim_blocked

    # 3. Run mandatory verification
    await server.call_tool("run_verification", arguments={"gate_id": "test-gate"})

    # 4. After verification: get_status is ALLOW
    res_status_fresh = await server.call_tool("get_status", arguments={})
    data_status_fresh = _extract_text_or_json(res_status_fresh)
    assert data_status_fresh["verdict"] == "ALLOW"

    # 5. After verification: claim_completion succeeds and session is ACCEPTED
    res_claim_ok = await server.call_tool("claim_completion", arguments={})
    data_claim_ok = _extract_text_or_json(res_claim_ok)
    assert data_claim_ok["status"] == "COMPLETED"
    assert data_claim_ok["verdict"] == "ALLOW"

    saved_sess = test_env["store"].get_session(test_env["session"].session_id)
    assert saved_sess.state == SessionState.ACCEPTED


@pytest.mark.anyio
async def test_mcp_get_handoff(test_env):
    """Test get_handoff tool generates human- and LLM-readable Markdown state card."""
    server = create_mcp_server(
        store=test_env["store"],
        repo_root=test_env["repo_root"],
        session_id=test_env["session"].session_id,
        policy=test_env["policy"],
    )
    res = await server.call_tool("get_handoff", arguments={})
    assert res.is_error is False
    card = res.content[0].text
    assert "# Task Handoff: task-42" in card
    assert "## Scope Summary" in card
    assert "## Verification Status" in card
    assert "## Next Actions" in card


# ==============================================================================
# 2. Hook Lifecycle Evaluation: PreToolUse Scope Denial & Stop Continuation
# ==============================================================================


def test_hook_pre_tool_use_denial_for_out_of_scope_paths(test_env):
    """Test PreToolUse hook denies file modifications outside allowed scope or in restricted paths."""
    adapter = AntigravityAdapter(
        store=test_env["store"],
        policy=test_env["policy"],
        repo_root=test_env["repo_root"],
    )

    # 1. In-scope write -> ALLOW
    allow_payload = PreToolUsePayload(
        conversationId=test_env["session"].session_id,
        toolCall={"name": "write_file", "args": {"Path": "src/new_feature.py"}},
    )
    resp_allow = adapter.handle_pre_tool_use(allow_payload)
    assert resp_allow.decision == "allow"
    assert resp_allow.is_denied is False

    # 2. Out-of-scope write -> DENY
    out_of_scope_payload = PreToolUsePayload(
        conversationId=test_env["session"].session_id,
        toolCall={"name": "write_file", "args": {"Path": "random_dir/script.py"}},
    )
    resp_deny_scope = adapter.handle_pre_tool_use(out_of_scope_payload)
    assert resp_deny_scope.decision == "deny"
    assert resp_deny_scope.is_denied is True
    assert "outside approved scope" in resp_deny_scope.reason

    # 3. Restricted path write -> DENY
    restricted_payload = PreToolUsePayload(
        conversationId=test_env["session"].session_id,
        toolCall={"name": "edit_file", "args": {"Path": ".git/config"}},
    )
    resp_deny_restricted = adapter.handle_pre_tool_use(restricted_payload)
    assert resp_deny_restricted.decision == "deny"
    assert "restricted by scope policy" in resp_deny_restricted.reason

    # 4. Command attempting destructive operation -> DENY
    destructive_cmd_payload = PreToolUsePayload(
        conversationId=test_env["session"].session_id,
        toolCall={"name": "run_command", "args": {"CommandLine": "git reset --hard HEAD"}},
    )
    resp_cmd_deny = adapter.handle_pre_tool_use(destructive_cmd_payload)
    assert resp_cmd_deny.decision == "deny"
    assert "destructive" in resp_cmd_deny.reason


def test_hook_stop_continuation_when_evidence_missing_or_stale(test_env):
    """Test Stop hook forces continuation when verification is missing or stale."""
    adapter = AntigravityAdapter(
        store=test_env["store"],
        policy=test_env["policy"],
        repo_root=test_env["repo_root"],
    )
    stop_payload = StopPayload(
        conversationId=test_env["session"].session_id,
        terminationReason="NO_TOOL_CALL",
        fullyIdle=True,
    )

    # 1. Missing evidence -> continue
    resp_continue_missing = adapter.handle_stop(stop_payload)
    assert resp_continue_missing.decision == "continue"
    assert resp_continue_missing.is_continued is True
    assert "Missing mandatory evidence" in resp_continue_missing.reason

    # 2. Run gate to satisfy verification
    server = create_mcp_server(
        store=test_env["store"],
        repo_root=test_env["repo_root"],
        session_id=test_env["session"].session_id,
        policy=test_env["policy"],
    )

    import anyio
    anyio.run(server.call_tool, "run_verification", {"gate_id": "test-gate"})

    # 3. Clean verified state -> allow stop
    resp_allow = adapter.handle_stop(stop_payload)
    assert resp_allow.decision == "allow"
    assert resp_allow.is_continued is False

    # 4. Modify code after verification -> evidence becomes stale -> continue
    main_py = test_env["repo_root"] / "src" / "main.py"
    main_py.write_text("print('stale code now')\n")

    resp_continue_stale = adapter.handle_stop(stop_payload)
    assert resp_continue_stale.decision == "continue"
    assert "stale" in resp_continue_stale.reason.lower()


def test_hook_pre_invocation_reminder(test_env):
    """Test PreInvocation hook builds a compact ephemeral message for agent guidance."""
    adapter = AntigravityAdapter(
        store=test_env["store"],
        policy=test_env["policy"],
        repo_root=test_env["repo_root"],
    )
    payload = PreInvocationPayload(
        conversationId=test_env["session"].session_id,
        invocationNum=0,
    )
    resp = adapter.handle_pre_invocation(payload)
    assert len(resp.injectSteps) == 1
    msg = resp.injectSteps[0]["ephemeralMessage"]
    assert "task-42" in msg
    assert "Required Gates: test-gate" in msg
    assert len(msg) <= 600


# ==============================================================================
# 3. Verified Integration Status Reporting (ENFORCED, PARTIAL, UNGUARDED)
# ==============================================================================


def test_verified_integration_status_reporting(test_env):
    """Verify integration status transitions: ENFORCED, PARTIAL, UNGUARDED."""
    # Both active -> ENFORCED
    adapter_enforced = AntigravityAdapter(
        store=test_env["store"],
        hooks_enabled=True,
        mcp_enabled=True,
    )
    assert adapter_enforced.get_integration_status() == IntegrationStatus.ENFORCED

    # Only MCP active -> PARTIAL
    adapter_partial = AntigravityAdapter(
        store=test_env["store"],
        hooks_enabled=False,
        mcp_enabled=True,
    )
    assert adapter_partial.get_integration_status() == IntegrationStatus.PARTIAL

    # Neither active -> UNGUARDED
    adapter_unguarded = AntigravityAdapter(
        store=test_env["store"],
        hooks_enabled=False,
        mcp_enabled=False,
    )
    assert adapter_unguarded.get_integration_status() == IntegrationStatus.UNGUARDED


# ==============================================================================
# 4. Fixture Parity with Antigravity Host Payloads
# ==============================================================================


def test_antigravity_fixtures_parity(test_env):
    """Verify adapter handles real captured Antigravity host payload fixtures."""
    adapter = AntigravityAdapter(
        store=test_env["store"],
        policy=test_env["policy"],
        repo_root=test_env["repo_root"],
    )

    # 1. PreInvocation payload fixture
    pre_inv_raw = (AGY_FIXTURES / "pre_invocation_payload.json").read_text()
    parsed_inv = parse_hook_payload(pre_inv_raw)
    assert isinstance(parsed_inv, PreInvocationPayload)
    assert parsed_inv.conversationId == "34cedfce-9a25-4828-b0e9-91c7963e05d2"

    # 2. PreToolUse payload & deny response fixture
    pre_tool_raw = (AGY_FIXTURES / "pre_tool_use_payload.json").read_text()
    parsed_tool = parse_hook_payload(pre_tool_raw)
    assert isinstance(parsed_tool, PreToolUsePayload)
    assert parsed_tool.toolCall.name == "run_command"
    assert parsed_tool.toolCall.args["CommandLine"] == "git reset --hard HEAD"

    resp_tool = adapter.handle_pre_tool_use(parsed_tool)
    assert resp_tool.decision == "deny"
    assert "destructive operation" in resp_tool.reason

    # Compare structure with fixture
    deny_fixture = json.loads((AGY_FIXTURES / "pre_tool_use_deny_response.json").read_text())
    assert resp_tool.decision == deny_fixture["decision"]

    # 3. Stop payload & continue response fixture
    stop_raw = (AGY_FIXTURES / "stop_payload.json").read_text()
    parsed_stop = parse_hook_payload(stop_raw)
    assert isinstance(parsed_stop, StopPayload)
    assert parsed_stop.fullyIdle is True

    # When evaluated with unfulfilled gates
    resp_stop = evaluate_stop(
        parsed_stop,
        unfulfilled_gates=("mandatory_gate",),
        handoff_summary=None,
    )
    assert resp_stop.decision == "continue"

    continue_fixture = json.loads((AGY_FIXTURES / "stop_continue_response.json").read_text())
    assert resp_stop.decision == continue_fixture["decision"]
