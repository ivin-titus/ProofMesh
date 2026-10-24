"""Integration and lifecycle tests for ProofMesh Seeded Demo Flow (Checkpoint 6 & 10).

Validates:
- Full 10-phase deterministic seeded recovery demo without LLM/network calls.
- Task contract proposal and approval workflow.
- Out-of-scope / restricted file edits produce BLOCK with reasons and handoff card.
- Safe recovery: revert restricted edit, implement allowed changes, run real pytest.
- Markdown report and JSON receipt exported with tamper-evident digests.
- Deterministic repeatability: demo runs cleanly twice in a row on the same directory.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from proofmesh.demo import run_seeded_demo
from proofmesh.models import (
    ApprovalStatus,
    EvidenceStatus,
    VerdictOutcome,
)
from proofmesh.report import export_json_receipt, render_markdown_report


def test_seeded_demo_end_to_end(tmp_path: Path):
    """Test full 10-phase seeded recovery demo execution in an isolated environment."""
    target_dir = tmp_path / "demo_repo"
    db_file = tmp_path / "storage" / "proofmesh_demo.db"

    result = run_seeded_demo(target_dir=target_dir, db_path=db_file)

    assert result["status"] == "success"
    assert result["project_id"] == "seeded-demo-project"

    # Task & Approval
    task = result["task"]
    assert task.task_id == "task-calc-extension"
    assert task.revision == 1
    assert task.approval_status == ApprovalStatus.APPROVED
    assert task.approved_by == "alice"
    assert task.required_gates == ("pytest",)

    # Snapshots
    baseline = result["baseline_snapshot"]
    clean_snap = result["clean_snapshot"]
    violation_snap = result["violation_snapshot"]

    assert baseline.snapshot_id != clean_snap.snapshot_id
    assert clean_snap.snapshot_id != violation_snap.snapshot_id

    # Evidence
    evidence = result["evidence"]
    assert evidence.gate_id == "pytest"
    assert evidence.status == EvidenceStatus.PASSED
    assert evidence.exit_code == 0
    assert evidence.duration_ms >= 0
    assert evidence.snapshot_after == clean_snap.snapshot_id

    # Clean scope & ALLOW verdict
    clean_scope = result["clean_scope_result"]
    assert not clean_scope.has_violations
    assert clean_scope.total_changed_files == 2  # math_service.py and test_math.py

    allow_verdict = result["allow_verdict"]
    assert allow_verdict.verdict == VerdictOutcome.ALLOW
    assert "All mandatory gates passed" in allow_verdict.reasons[0]

    # Violation scope & BLOCK verdict
    violation_scope = result["violation_scope_result"]
    assert violation_scope.has_violations
    restricted_findings = [f for f in violation_scope.findings if f.restricted]
    assert len(restricted_findings) >= 1
    assert any("config/security.toml" in f.path for f in restricted_findings)

    block_verdict = result["block_verdict"]
    assert block_verdict.verdict == VerdictOutcome.BLOCK
    assert any("Scope violation" in r for r in block_verdict.reasons)

    # Handoff card
    handoff_card = result["handoff_card"]
    assert "# Task Handoff:" in handoff_card
    assert "config/security.toml" in handoff_card

    # Exported files
    report_file = target_dir / "report.md"
    receipt_file = target_dir / "report.json"
    assert report_file.is_file()
    assert receipt_file.is_file()

    report_content = report_file.read_text(encoding="utf-8")
    assert "# ProofMesh Verification Report" in report_content
    assert "task-calc-extension" in report_content
    assert "pytest" in report_content
    assert "ALLOW" in report_content

    receipt_data = json.loads(receipt_file.read_text(encoding="utf-8"))
    assert receipt_data["schema_version"] == "1.0"
    assert receipt_data["receipt_digest"].startswith("sha256:")
    assert receipt_data["task"]["task_id"] == "task-calc-extension"
    assert receipt_data["verdict"]["verdict"] == VerdictOutcome.ALLOW.value

    # Preserved blocked artifacts
    blocked_report_file = target_dir / "report-blocked.md"
    blocked_receipt_file = target_dir / "report-blocked.json"
    assert blocked_report_file.is_file()
    assert blocked_receipt_file.is_file()
    assert "BLOCK" in blocked_report_file.read_text(encoding="utf-8")
    blocked_receipt_data = json.loads(blocked_receipt_file.read_text(encoding="utf-8"))
    assert blocked_receipt_data["verdict"]["verdict"] == VerdictOutcome.BLOCK.value


def test_seeded_demo_runnable_twice_in_a_row_cleanly(tmp_path: Path):
    """Verify demo can run twice in a row from scratch on the exact same directory."""
    target_dir = tmp_path / "repeated_demo_repo"
    db_file = tmp_path / "storage" / "repeated_demo.db"

    # First run
    run1 = run_seeded_demo(target_dir=target_dir, db_path=db_file)
    assert run1["allow_verdict"].verdict == VerdictOutcome.ALLOW
    assert run1["block_verdict"].verdict == VerdictOutcome.BLOCK

    # Second run on the same target directory and database path
    run2 = run_seeded_demo(target_dir=target_dir, db_path=db_file)
    assert run2["allow_verdict"].verdict == VerdictOutcome.ALLOW
    assert run2["block_verdict"].verdict == VerdictOutcome.BLOCK

    # Output reports exist and are valid after second run
    assert (target_dir / "report.md").is_file()
    assert (target_dir / "report.json").is_file()


def test_report_and_receipt_rendering(tmp_path: Path):
    """Verify markdown report and JSON receipt match model structures and digests."""
    target_dir = tmp_path / "report_test_repo"
    db_file = tmp_path / "storage" / "report_test.db"

    res = run_seeded_demo(target_dir=target_dir, db_path=db_file)

    session = res["session"]
    task = res["task"]
    snapshot = res["clean_snapshot"]
    scope_result = res["clean_scope_result"]
    evidence = [res["evidence"]]
    verdict = res["allow_verdict"]

    md = render_markdown_report(session, task, snapshot, scope_result, evidence, verdict)
    assert "# ProofMesh Verification Report" in md
    assert "✅ ALLOW" in md
    assert "task-calc-extension" in md
    assert "alice" in md
    assert "fresh" in md

    receipt = export_json_receipt(session, task, snapshot, scope_result, evidence, verdict)
    assert receipt["schema_version"] == "1.0"
    assert "receipt_digest" in receipt
    assert receipt["verdict"]["verdict"] == VerdictOutcome.ALLOW.value
    assert receipt["task"]["task_id"] == "task-calc-extension"


def test_stale_evidence_invalidation_detected(tmp_path: Path):
    """Verify modifying code after a passing verification check marks evidence stale."""
    from proofmesh.core.evaluator import evaluate_session
    from proofmesh.core.repo_snapshot import capture_snapshot
    from proofmesh.core.scope_analyzer import analyze_scope
    from proofmesh.models import GatePolicy, TrustedPolicy

    target_dir = tmp_path / "stale_test_repo"
    db_file = tmp_path / "storage" / "stale_test.db"

    res = run_seeded_demo(target_dir=target_dir, db_path=db_file)
    session = res["session"]
    task = res["task"]
    baseline = res["baseline_snapshot"]
    evidence = res["evidence"]

    # At this point, target_dir has report artifacts.
    # Remove them so scope is clean for the test
    (target_dir / "config" / "security.toml").unlink(missing_ok=True)
    (target_dir / "report.json").unlink(missing_ok=True)
    (target_dir / "report.md").unlink(missing_ok=True)
    (target_dir / "report-blocked.json").unlink(missing_ok=True)
    (target_dir / "report-blocked.md").unlink(missing_ok=True)
    (target_dir / ".proofmesh-fixture").unlink(missing_ok=True)

    # Now make an additional allowed edit in src/math_service.py AFTER evidence was captured
    math_file = target_dir / "src" / "math_service.py"
    math_file.write_text(math_file.read_text(encoding="utf-8") + "\n# Extra edit after check\n", encoding="utf-8")

    new_snapshot = capture_snapshot(target_dir)
    assert new_snapshot.snapshot_id != evidence.snapshot_after

    clean_scope = analyze_scope(baseline, new_snapshot, task.scope)
    assert not clean_scope.has_violations

    policy = TrustedPolicy(
        gates={
            "pytest": GatePolicy(
                provider="pytest",
                command=("pytest",),
                timeout_seconds=30,
                mandatory=True,
            )
        }
    )

    # Evaluate with stale evidence
    stale_verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=new_snapshot,
        evidence_records=[evidence],
        scope_result=clean_scope,
        policy=policy,
    )

    assert stale_verdict.verdict == VerdictOutcome.BLOCK
    assert any("stale" in r.lower() for r in stale_verdict.reasons)

