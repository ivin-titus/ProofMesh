"""Tests verifying strict read-only HTTP behavior and status accuracy for ProofMesh UI."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any
import urllib.error
import urllib.request
import pytest

from proofmesh.demo import run_seeded_demo
from proofmesh.models import (
    AcceptanceCriterion,
    ApprovalStatus,
    EvidenceRecord,
    EvidenceStatus,
    FileFingerprint,
    IntegrationStatus,
    OperatingProfile,
    RepoSnapshot,
    RiskLevel,
    ScopePolicy,
    Session,
    SessionState,
    TaskRevision,
)
from proofmesh.storage.store import ProofMeshStore
from proofmesh.ui import (
    create_ui_server,
    get_receipt_for_session,
    render_dashboard_html,
)

SAMPLE_DIGEST = "sha256:" + "a" * 64


def dump_all_db_rows(db_path: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Capture a snapshot of all user tables and rows in the SQLite database."""
    conn = sqlite3.connect(str(db_path))
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
            ).fetchall()
        ]
        dump: dict[str, list[tuple[Any, ...]]] = {}
        for table in tables:
            dump[table] = conn.execute(f"SELECT * FROM {table} ORDER BY rowid;").fetchall()
        return dump
    finally:
        conn.close()


def setup_unevaluated_session(
    tmp_path: Path,
    task_summary: str = "Test task without evaluation",
    extra_path: str = "src/feature.py",
) -> tuple[ProofMeshStore, Path, str]:
    """Create a store containing a session with task, snapshots, and evidence, but NO verdicts."""
    db_path = tmp_path / "unevaluated.db"
    store = ProofMeshStore(db_path)
    now = datetime.now(timezone.utc)

    store.create_project("proj-test", "/workspace/test", created_at=now)
    task = TaskRevision(
        task_id="task-test",
        revision=1,
        summary=task_summary,
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="AC-1",
                description="Must verify code safety",
                required_gates=["gate-pytest"],
            )
        ],
        scope=ScopePolicy(allow_paths=["src/**"], restricted_paths=["secrets/**"]),
        required_gates=["gate-pytest"],
        constraints=["sandboxed"],
        risk_level=RiskLevel.MEDIUM,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="tech-lead",
        approved_at=now,
        contract_digest=SAMPLE_DIGEST,
    )
    store.save_task_revision(task, "proj-test")

    snap_baseline_id = "sha256:" + "0" * 64
    snap_current_id = "sha256:" + "1" * 64

    snap_baseline = RepoSnapshot(
        snapshot_id=snap_baseline_id,
        repo_root="/workspace/test",
        git_commit="c0ffee0123456789",
        git_dirty=False,
        captured_at=now,
        complete=True,
        files=[
            FileFingerprint(
                path="src/main.py",
                sha256="sha256:" + "1" * 64,
                size_bytes=120,
            )
        ],
    )
    store.save_snapshot(snap_baseline)

    snap_current = RepoSnapshot(
        snapshot_id=snap_current_id,
        repo_root="/workspace/test",
        git_commit="c0ffee0123456789",
        git_dirty=True,
        captured_at=now,
        complete=True,
        files=[
            FileFingerprint(
                path="src/main.py",
                sha256="sha256:" + "2" * 64,
                size_bytes=130,
            ),
            FileFingerprint(
                path=extra_path,
                sha256="sha256:" + "3" * 64,
                size_bytes=45,
            ),
        ],
    )
    store.save_snapshot(snap_current)

    session = Session(
        session_id="sess-uneval-01",
        task_id="task-test",
        contract_revision=1,
        repo_root="/workspace/test",
        baseline_snapshot_id=snap_baseline_id,
        current_snapshot_id=snap_current_id,
        profile=OperatingProfile.FLOW,
        policy_digest=SAMPLE_DIGEST,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=now,
    )
    store.save_session(session)

    evidence = EvidenceRecord(
        evidence_id="ev-001",
        session_id="sess-uneval-01",
        contract_revision=1,
        gate_id="gate-pytest",
        acceptance_criteria=["AC-1"],
        provider_name="pytest-runner",
        provider_version="9.1.1",
        config_digest=SAMPLE_DIGEST,
        started_at=now,
        ended_at=now,
        duration_ms=250,
        snapshot_before=snap_baseline_id,
        snapshot_after=snap_current_id,
        status=EvidenceStatus.PASSED,
        exit_code=0,
        summary="Tests executed successfully",
    )
    store.save_evidence(evidence)

    # Confirm that NO verdicts are stored
    assert len(store.list_verdicts_for_session("sess-uneval-01")) == 0
    return store, db_path, "sess-uneval-01"


def test_get_root_does_not_modify_database_unevaluated(tmp_path: Path) -> None:
    """Assert GET / on an unevaluated session does NOT insert or update any rows in SQLite."""
    store, db_path, session_id = setup_unevaluated_session(tmp_path)

    before_dump = dump_all_db_rows(db_path)
    assert len(before_dump["verdicts"]) == 0

    server = create_ui_server(store, session_id=session_id, host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base_url = f"http://{host}:{port}"
    try:
        # Request GET / multiple times
        for _ in range(3):
            req = urllib.request.Request(f"{base_url}/")
            with opener.open(req) as resp:
                assert resp.status == 200
                body = resp.read().decode("utf-8")
                assert "ProofMesh Control Layer" in body
                assert "Unevaluated" in body
    finally:
        server.shutdown()
        server.server_close()

    after_dump = dump_all_db_rows(db_path)

    # Database state must be completely untouched
    assert before_dump == after_dump
    assert len(after_dump["verdicts"]) == 0
    assert len(store.list_verdicts_for_session(session_id)) == 0


def test_get_root_does_not_modify_database_evaluated(tmp_path: Path) -> None:
    """Assert GET / on an evaluated session does NOT insert or update any rows in SQLite."""
    demo_dir = tmp_path / "demo_target"
    db_file = tmp_path / "store" / "demo.db"
    run_seeded_demo(demo_dir, db_path=db_file)
    store = ProofMeshStore(db_file)

    before_dump = dump_all_db_rows(db_file)
    assert len(before_dump["verdicts"]) > 0

    server = create_ui_server(store, host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base_url = f"http://{host}:{port}"
    try:
        for _ in range(3):
            req = urllib.request.Request(f"{base_url}/")
            with opener.open(req) as resp:
                assert resp.status == 200
                body = resp.read().decode("utf-8")
                assert "ProofMesh Control Layer" in body
    finally:
        server.shutdown()
        server.server_close()

    after_dump = dump_all_db_rows(db_file)
    assert before_dump == after_dump


def test_get_api_status_does_not_modify_database(tmp_path: Path) -> None:
    """Assert GET /api/status does not modify database for unevaluated or evaluated sessions."""
    store, db_path, session_id = setup_unevaluated_session(tmp_path)

    before_dump = dump_all_db_rows(db_path)
    assert len(before_dump["verdicts"]) == 0

    server = create_ui_server(store, session_id=session_id, host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base_url = f"http://{host}:{port}"
    try:
        req = urllib.request.Request(f"{base_url}/api/status")
        with opener.open(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["schema_version"] == "1.0"
            assert data["verdict"] is None

        req_receipt = urllib.request.Request(f"{base_url}/api/receipt")
        with opener.open(req_receipt) as resp:
            assert resp.status == 200
            receipt_data = json.loads(resp.read().decode("utf-8"))
            assert receipt_data["verdict"] is None
    finally:
        server.shutdown()
        server.server_close()

    after_dump = dump_all_db_rows(db_path)
    assert before_dump == after_dump
    assert len(after_dump["verdicts"]) == 0


def test_unevaluated_session_shows_unevaluated_badge_and_status(tmp_path: Path) -> None:
    """Assert unevaluated session shows 'Unevaluated' badge, status, and persisted label."""
    store, db_path, session_id = setup_unevaluated_session(tmp_path)

    receipt = get_receipt_for_session(store, session_id)
    assert receipt is not None
    assert receipt["verdict"] is None

    html = render_dashboard_html(receipt)
    assert "<!DOCTYPE html>" in html
    # Unevaluated badge
    assert "badge-neutral" in html
    assert "Unevaluated" in html
    assert "⏳ Unevaluated" in html

    # Unevaluated status in details
    assert "Status:</strong> <span class=\"pill pill-neutral\">Unevaluated</span>" in html
    assert "Evaluated At:</strong> Unevaluated (no evaluation recorded)" in html

    # Clearly labeled as Last Persisted Evaluation
    assert "Last Persisted Evaluation" in html

    # Snapshot timestamp rendered
    assert "Snapshot Captured At:" in html
    assert receipt["snapshot"]["captured_at"] in html

    # Live check / live evaluation disclaimer present
    assert "Auto-refresh checks for newly persisted records; it does not execute live checks." in html

    # Should NOT have ALLOW or BLOCK verdict
    assert "✅ ALLOW" not in html
    assert "❌ BLOCK" not in html


def test_html_escaping_of_untrusted_strings(tmp_path: Path) -> None:
    """Assert HTML escaping of malicious/untrusted strings in TaskFile summary, scope paths, evidence, and reasons."""
    malicious_summary = "<script>alert('xss-task-summary')</script>"
    malicious_path = '"><img src=x onerror=alert(\'xss-path\')>.py'

    store, db_path, session_id = setup_unevaluated_session(
        tmp_path,
        task_summary=malicious_summary,
        extra_path=malicious_path,
    )

    server = create_ui_server(store, session_id=session_id, host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base_url = f"http://{host}:{port}"
    try:
        req = urllib.request.Request(f"{base_url}/")
        with opener.open(req) as resp:
            content = resp.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()

    # Raw script or img tag injection must NEVER appear in the HTML
    assert "<script>alert('xss-task-summary')</script>" not in content
    assert '"><img src=x onerror=alert(\'xss-path\')>.py' not in content

    # Safely escaped representations MUST appear
    assert "&lt;script&gt;alert(&#x27;xss-task-summary&#x27;)&lt;/script&gt;" in content
    assert "&quot;&gt;&lt;img src=x onerror=alert(&#x27;xss-path&#x27;)&gt;.py" in content


def test_binding_to_non_localhost_raises_value_error(tmp_path: Path) -> None:
    """Assert binding to non-localhost hosts strictly raises ValueError."""
    store = ProofMeshStore(tmp_path / "bind_test.db")

    for forbidden_host in ("0.0.0.0", "192.168.1.50", "example.com", "8.8.8.8", "10.0.0.1"):
        with pytest.raises(ValueError, match="ProofMesh UI must only bind to 127.0.0.1 or localhost"):
            create_ui_server(store, host=forbidden_host, port=0)

    # Allowed local hosts must succeed
    server1 = create_ui_server(store, host="127.0.0.1", port=0)
    server1.server_close()

    server2 = create_ui_server(store, host="localhost", port=0)
    server2.server_close()


def test_mutating_http_methods_rejected_405(tmp_path: Path) -> None:
    """Assert POST, PUT, DELETE, PATCH return 405 Method Not Allowed."""
    store, db_path, session_id = setup_unevaluated_session(tmp_path)
    server = create_ui_server(store, session_id=session_id, host="127.0.0.1", port=0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base_url = f"http://{host}:{port}"
    try:
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            req = urllib.request.Request(f"{base_url}/", data=b'{"key": "val"}', method=method)
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                opener.open(req)
            assert exc_info.value.code == 405
    finally:
        server.shutdown()
        server.server_close()
