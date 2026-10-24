"""Complete recovery control loop tests for ProofMesh Seeded Demo.

Validates:
- 10-phase recovery control loop transitions through BLOCK to final ALLOW.
- Deliberate out-of-scope change triggers BLOCK and produces 'report-blocked.md'/'report-blocked.json'.
- Correction safely reverts the violation, implements allowed code, and passes verification.
- Final state produces ALLOW, 'report.md', and 'report.json'.
- Exported receipt reflects final ALLOW state while earlier blocking receipt is preserved.
- Full recovery loop runs cleanly twice from scratch on the same directory and database.
"""

from __future__ import annotations

import json
from pathlib import Path

from proofmesh.demo import FIXTURE_MARKER, run_seeded_demo
from proofmesh.models import (
    ApprovalStatus,
    EvidenceStatus,
    VerdictOutcome,
)
from proofmesh.storage.store import ProofMeshStore


def test_complete_recovery_loop_transitions_block_to_allow(tmp_path: Path):
    """Test full 10-phase seeded demo recovery execution."""
    target_dir = tmp_path / "recovery_demo_repo"
    db_file = tmp_path / "storage" / "recovery_demo.db"

    result = run_seeded_demo(target_dir=target_dir, db_path=db_file)

    assert result["status"] == "success"
    assert result["project_id"] == "seeded-demo-project"

    # Fixture marker verified
    assert (target_dir / FIXTURE_MARKER).is_file()

    # Task & Approval
    task = result["task"]
    assert task.task_id == "task-calc-extension"
    assert task.revision == 1
    assert task.approval_status == ApprovalStatus.APPROVED
    assert task.approved_by == "alice"
    assert task.required_gates == ("pytest",)

    # Snapshots
    baseline = result["baseline_snapshot"]
    violation_snap = result["violation_snapshot"]
    clean_snap = result["clean_snapshot"]

    assert baseline.snapshot_id != violation_snap.snapshot_id
    assert violation_snap.snapshot_id != clean_snap.snapshot_id
    assert baseline.snapshot_id != clean_snap.snapshot_id

    # Phase 6: Blocked State
    violation_scope = result["violation_scope_result"]
    assert violation_scope.has_violations
    restricted_findings = [f for f in violation_scope.findings if f.restricted]
    assert len(restricted_findings) >= 1
    assert any("config/security.toml" in f.path for f in restricted_findings)

    block_verdict = result["block_verdict"]
    assert block_verdict.verdict == VerdictOutcome.BLOCK
    assert any("Scope violation" in r for r in block_verdict.reasons)

    handoff_card = result["handoff_card"]
    assert "# Task Handoff:" in handoff_card
    assert "config/security.toml" in handoff_card

    # Blocked exported artifacts on disk
    blocked_report_file = target_dir / "report-blocked.md"
    blocked_receipt_file = target_dir / "report-blocked.json"
    assert blocked_report_file.is_file()
    assert blocked_receipt_file.is_file()

    blocked_md_content = blocked_report_file.read_text(encoding="utf-8")
    assert "# ProofMesh Verification Report" in blocked_md_content
    assert "BLOCK" in blocked_md_content

    blocked_receipt_data = json.loads(blocked_receipt_file.read_text(encoding="utf-8"))
    assert blocked_receipt_data["schema_version"] == "1.0"
    assert blocked_receipt_data["receipt_digest"].startswith("sha256:")
    assert blocked_receipt_data["verdict"]["verdict"] == VerdictOutcome.BLOCK.value

    # Phase 7 & 8: Recovery & Evidence
    evidence = result["evidence"]
    assert evidence.gate_id == "pytest"
    assert evidence.status == EvidenceStatus.PASSED
    assert evidence.exit_code == 0
    assert evidence.duration_ms >= 0
    assert evidence.snapshot_after == clean_snap.snapshot_id

    # Phase 9: Clean Scope & Final ALLOW Verdict
    clean_scope = result["clean_scope_result"]
    assert not clean_scope.has_violations
    assert clean_scope.total_changed_files == 2  # math_service.py and test_math.py

    allow_verdict = result["allow_verdict"]
    assert allow_verdict.verdict == VerdictOutcome.ALLOW
    assert "All mandatory gates passed" in allow_verdict.reasons[0]
    assert result["verdict"].verdict == VerdictOutcome.ALLOW

    # Phase 10: Final Exported Report & Receipt reflect ALLOW
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

    # Verify return dict contains both preserved blocked receipt and final allow receipt
    assert result["receipt_json"]["verdict"]["verdict"] == VerdictOutcome.ALLOW.value
    assert result["blocked_receipt_json"]["verdict"]["verdict"] == VerdictOutcome.BLOCK.value

    # Verify target directory does not have leftover violation files
    assert not (target_dir / "config" / "security.toml").exists()


def test_recovery_loop_runnable_twice_cleanly(tmp_path: Path):
    """Verify the full recovery loop runs cleanly twice from scratch without errors."""
    target_dir = tmp_path / "repeated_recovery_repo"
    db_file = tmp_path / "storage" / "repeated_recovery.db"

    # Run 1
    run1 = run_seeded_demo(target_dir=target_dir, db_path=db_file)
    assert run1["block_verdict"].verdict == VerdictOutcome.BLOCK
    assert run1["allow_verdict"].verdict == VerdictOutcome.ALLOW
    assert run1["receipt_json"]["verdict"]["verdict"] == VerdictOutcome.ALLOW.value

    # Run 2 on exact same workspace and database path
    run2 = run_seeded_demo(target_dir=target_dir, db_path=db_file)
    assert run2["block_verdict"].verdict == VerdictOutcome.BLOCK
    assert run2["allow_verdict"].verdict == VerdictOutcome.ALLOW
    assert run2["receipt_json"]["verdict"]["verdict"] == VerdictOutcome.ALLOW.value

    # Verify all 4 report files exist after run 2
    assert (target_dir / "report.md").is_file()
    assert (target_dir / "report.json").is_file()
    assert (target_dir / "report-blocked.md").is_file()
    assert (target_dir / "report-blocked.json").is_file()

    # Verify database persistence
    store = ProofMeshStore(db_file)
    task_rev = store.get_task_revision("task-calc-extension", 1)
    assert task_rev is not None
    assert task_rev.approval_status == ApprovalStatus.APPROVED
