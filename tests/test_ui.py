"""Tests for ProofMesh read-only local web status panel."""

from __future__ import annotations

import json
from pathlib import Path
import threading
import urllib.error
import urllib.request
import pytest

from proofmesh.demo import run_seeded_demo
from proofmesh.storage.store import ProofMeshStore
from proofmesh.ui import (
    create_ui_server,
    get_receipt_for_session,
    render_dashboard_html,
)


def test_render_dashboard_html_none() -> None:
    """Fallback HTML is rendered when no session receipt exists."""
    html = render_dashboard_html(None)
    assert "<!DOCTYPE html>" in html
    assert "No Active ProofMesh Session" in html


def test_render_dashboard_html_populated(tmp_path: Path) -> None:
    """Dashboard HTML renders tables, badges, pills, and contract metadata."""
    demo_dir = tmp_path / "demo_target"
    db_file = tmp_path / "store" / "demo.db"
    demo_result = run_seeded_demo(demo_dir, db_path=db_file)
    blocked_receipt = demo_result["blocked_receipt_json"]

    html_blocked = render_dashboard_html(blocked_receipt)
    assert "<!DOCTYPE html>" in html_blocked
    assert "ProofMesh Control Layer" in html_blocked
    assert "task-calc-extension" in html_blocked
    assert "BLOCK" in html_blocked
    assert "config/security.toml" in html_blocked
    assert "Restricted" in html_blocked

    final_receipt = demo_result["receipt_json"]
    html_final = render_dashboard_html(final_receipt)
    assert "ALLOW" in html_final
    assert "pytest" in html_final


def test_ui_server_endpoints_and_security(tmp_path: Path) -> None:
    """Test HTTP server endpoints (HTML, /api/status), 405 rejection, and localhost binding."""
    demo_dir = tmp_path / "demo_target"
    db_file = tmp_path / "store" / "demo.db"
    run_seeded_demo(demo_dir, db_path=db_file)

    store = ProofMeshStore(db_file)

    # Security check: Non-localhost binding must raise ValueError
    with pytest.raises(ValueError, match="must only bind to 127.0.0.1 or localhost"):
        create_ui_server(store, host="0.0.0.0", port=0)

    # Start server on ephemeral port (0)
    server = create_ui_server(store, host="127.0.0.1", port=0)
    host, port = server.server_address

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base_url = f"http://{host}:{port}"
    try:
        # 1. GET / -> HTML
        req = urllib.request.Request(f"{base_url}/")
        with opener.open(req) as resp:
            assert resp.status == 200
            assert "text/html" in resp.headers.get("Content-Type", "")
            content = resp.read().decode("utf-8")
            assert "ProofMesh Control Layer" in content
            assert "task-calc-extension" in content

        # 2. GET /api/status -> JSON
        req_api = urllib.request.Request(f"{base_url}/api/status")
        with opener.open(req_api) as resp:
            assert resp.status == 200
            assert "application/json" in resp.headers.get("Content-Type", "")
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("schema_version") == "1.0"
            assert "verdict" in data

        # 3. POST / -> 405 Method Not Allowed
        post_req = urllib.request.Request(f"{base_url}/", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            opener.open(post_req)
        assert exc_info.value.code == 405

        # 4. GET /unknown -> 404 Not Found
        unknown_req = urllib.request.Request(f"{base_url}/nonexistent")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            opener.open(unknown_req)
        assert exc_info.value.code == 404

    finally:
        server.shutdown()
        server.server_close()


def test_ui_workspace_scoping_and_foreign_session_rejection(tmp_path: Path) -> None:
    """Verify UI scopes sessions strictly to configured repo_root and rejects foreign sessions."""
    from datetime import datetime, timezone
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
    from proofmesh.ui import get_dashboard_data

    repo_a = tmp_path / "repo_a"
    repo_a.mkdir()
    (repo_a / "a.txt").write_text("a\n")

    repo_b = tmp_path / "repo_b"
    repo_b.mkdir()
    (repo_b / "b.txt").write_text("b\n")

    db_file = tmp_path / "shared.db"
    store = ProofMeshStore(db_file)
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
        scope=ScopePolicy(allow_paths=("**",), restricted_paths=()),
        required_gates=(),
        acceptance_criteria=(),
        constraints=(),
        raw_markdown="# Task A",
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
        scope=ScopePolicy(allow_paths=("**",), restricted_paths=()),
        required_gates=(),
        acceptance_criteria=(),
        constraints=(),
        raw_markdown="# Task B",
    )
    store.save_task_revision(task_b, project_id="proj-b")

    snap_a = capture_snapshot(repo_a)
    store.save_snapshot(snap_a)
    snap_b = capture_snapshot(repo_b)
    store.save_snapshot(snap_b)

    # Session A
    sess_a = Session(
        session_id="sess-a",
        task_id="task-a",
        contract_revision=1,
        repo_root=str(repo_a),
        baseline_snapshot_id=snap_a.snapshot_id,
        current_snapshot_id=snap_a.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest="sha256:" + "a" * 64,
        integration_status=IntegrationStatus.UNGUARDED,
        state=SessionState.ACTIVE,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    store.save_session(sess_a)

    # Session B created LATER
    sess_b = Session(
        session_id="sess-b",
        task_id="task-b",
        contract_revision=1,
        repo_root=str(repo_b),
        baseline_snapshot_id=snap_b.snapshot_id,
        current_snapshot_id=snap_b.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest="sha256:" + "b" * 64,
        integration_status=IntegrationStatus.UNGUARDED,
        state=SessionState.ACTIVE,
        started_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    store.save_session(sess_b)

    # 1. Unscoped request for repo_a returns sess_a (NOT the newer sess_b!)
    data_a = get_dashboard_data(store, repo_root=repo_a)
    assert data_a is not None
    assert data_a["session"]["session_id"] == "sess-a"

    # 2. Unscoped request for repo_b returns sess_b
    data_b = get_dashboard_data(store, repo_root=repo_b)
    assert data_b is not None
    assert data_b["session"]["session_id"] == "sess-b"

    # 3. Explicit request for foreign session_b while scoped to repo_a returns None
    data_cross = get_dashboard_data(store, repo_root=repo_a, session_id="sess-b")
    assert data_cross is None


def test_ui_deterministic_digest_across_repeated_requests(tmp_path: Path) -> None:
    """Verify repeated get_dashboard_data calls for identical unevaluated state produce deterministic receipt_digest."""
    from datetime import datetime, timezone
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
    from proofmesh.ui import get_dashboard_data

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("print(1)\n")

    db_file = tmp_path / "test.db"
    store = ProofMeshStore(db_file)
    store.create_project("p1", root_path=str(repo))

    task = TaskRevision(
        task_id="t1",
        revision=1,
        parent_revision=None,
        summary="Task",
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="tester",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "a" * 64,
        scope=ScopePolicy(allow_paths=("**",), restricted_paths=()),
        required_gates=(),
        acceptance_criteria=(),
        constraints=(),
        raw_markdown="# Task",
    )
    store.save_task_revision(task, project_id="p1")

    snap = capture_snapshot(repo)
    store.save_snapshot(snap)

    sess = Session(
        session_id="sess-det",
        task_id="t1",
        contract_revision=1,
        repo_root=str(repo),
        baseline_snapshot_id=snap.snapshot_id,
        current_snapshot_id=snap.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest="sha256:" + "a" * 64,
        integration_status=IntegrationStatus.UNGUARDED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(sess)

    # Call get_dashboard_data twice
    data1 = get_dashboard_data(store, repo_root=repo, session_id="sess-det")
    data2 = get_dashboard_data(store, repo_root=repo, session_id="sess-det")

    assert data1 is not None and data2 is not None
    # receipt_id changes (per-export UUID), but receipt_digest is deterministic
    assert data1["receipt_digest"] == data2["receipt_digest"]
    assert data1["receipt_digest"].startswith("sha256:")

