"""Deterministic Seeded Demo for ProofMesh.

Demonstrates the complete end-to-end intent, intervention, and evidence control
loop without external LLM or network dependencies:
1. Initialize project & storage outside target directory.
2. Propose TaskFile with required gates and allow_paths.
3. Human approval by 'alice'.
4. Baseline snapshot capture.
5. Simulated clean agent edits.
6. Verification gate execution (pytest) producing fresh EvidenceRecord.
7. Evaluator accepts clean session (Verdict: ALLOW).
8. Simulated violation scenario (restricted path edit) triggers Evaluator blocker (Verdict: BLOCK).
9. Export Markdown report and JSON receipt.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Callable

from proofmesh.core.evaluator import evaluate_session
from proofmesh.core.handoff import generate_handoff
from proofmesh.core.repo_snapshot import capture_snapshot
from proofmesh.core.scope_analyzer import analyze_scope
from proofmesh.core.task_service import TaskService
from proofmesh.core.verification import run_gate
from proofmesh.models import (
    GatePolicy,
    IntegrationStatus,
    OperatingProfile,
    Session,
    SessionState,
    TrustedPolicy,
    VerdictOutcome,
)
from proofmesh.report import export_json_receipt, render_markdown_report
from proofmesh.storage.store import ProofMeshStore

SEEDED_TASKFILE = """+++
task_id = "task-calc-extension"
version = 1
summary = "Add multiplication function to math service"
risk_level = "low"
allow_paths = ["src/**", "tests/**", "pytest.ini"]
restricted_paths = ["config/**", ".git/**", "security/**"]
required_gates = ["pytest"]
constraints = ["Must not use external libraries", "Pure integer math"]
max_changed_files = 10
+++

# task-calc-extension: Add multiplication function to math service

## Objective
Extend math_service with a multiply function and verify with pytest.

## Acceptance criteria
- [AC-1] Implement multiply(a, b) in src/math_service.py (gates: pytest)
- [AC-2] Add unit test in tests/test_math.py (gates: pytest)
"""

INITIAL_MATH_SERVICE = """def add(a: int, b: int) -> int:
    return a + b
"""

INITIAL_TEST_MATH = """from src.math_service import add


def test_add():
    assert add(2, 3) == 5
"""

EXTENDED_MATH_SERVICE = """def add(a: int, b: int) -> int:
    return a + b


def multiply(a: int, b: int) -> int:
    return a * b
"""

EXTENDED_TEST_MATH = """from src.math_service import add, multiply


def test_add():
    assert add(2, 3) == 5


def test_multiply():
    assert multiply(3, 4) == 12
"""

VIOLATION_SECURITY_CONFIG = """# Unauthorized configuration edit introduced during task
bypass_all_auth = true
allow_arbitrary_eval = true
"""


def _clean_path(path: Path) -> None:
    """Safely remove a file or directory tree if it exists."""
    if path.is_file() or path.is_symlink():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def run_seeded_demo(
    target_dir: Path | str,
    db_path: Path | str | None = None,
    *,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Execute the deterministic seeded end-to-end ProofMesh control scenario.

    Args:
        target_dir: Directory representing the target project workspace.
        db_path: Optional explicit database path outside target directory.
        log_fn: Optional logger for progress messages (defaults to print).

    Returns:
        Dictionary containing all phase artifacts, snapshots, verdicts, and reports.
    """
    def log(msg: str) -> None:
        if log_fn is not None:
            log_fn(msg)

    target_path = Path(target_dir).resolve()
    target_path.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # Phase 1: Initialize project & ProofMeshStore outside target repository
    # -------------------------------------------------------------------------
    log("[Phase 1/9] Initializing project & ProofMeshStore outside target repo...")
    if db_path is not None:
        db_file = Path(db_path).resolve()
    else:
        db_file = (target_path.parent / ".proofmesh_store" / "seeded_demo.db").resolve()

    # Reset any previous database files for a clean deterministic state
    _clean_path(db_file)
    _clean_path(db_file.with_name(db_file.name + "-wal"))
    _clean_path(db_file.with_name(db_file.name + "-shm"))

    store = ProofMeshStore(db_file)
    project_id = "seeded-demo-project"
    store.create_project(project_id, root_path=str(target_path))

    # Initialize / clean baseline workspace files
    _clean_path(target_path / "config")
    _clean_path(target_path / "security")
    _clean_path(target_path / "report.md")
    _clean_path(target_path / "report.json")

    src_dir = target_path / "src"
    tests_dir = target_path / "tests"
    src_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    (src_dir / "math_service.py").write_text(INITIAL_MATH_SERVICE, encoding="utf-8")
    (tests_dir / "test_math.py").write_text(INITIAL_TEST_MATH, encoding="utf-8")
    (target_path / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")

    # -------------------------------------------------------------------------
    # Phase 2: Propose TaskFile with required gates and allow_paths
    # -------------------------------------------------------------------------
    log("[Phase 2/9] Proposing TaskFile contract (revision 1)...")
    task_service = TaskService(store)
    task_rev1 = task_service.propose_task(
        task_id="task-calc-extension",
        content=SEEDED_TASKFILE,
        project_id=project_id,
        known_gates={"pytest"},
    )

    # -------------------------------------------------------------------------
    # Phase 3: Approve TaskRevision 1 by human approver ('alice')
    # -------------------------------------------------------------------------
    log("[Phase 3/9] Human approver 'alice' approves TaskRevision 1...")
    approved_task = task_service.approve_task(
        task_id="task-calc-extension",
        revision=1,
        approved_by="alice",
        reason="Initial math extension approved for implementation.",
    )

    # -------------------------------------------------------------------------
    # Phase 4: Capture baseline snapshot & initialize session
    # -------------------------------------------------------------------------
    log("[Phase 4/9] Capturing baseline repository snapshot...")
    baseline_snapshot = capture_snapshot(target_path)
    store.save_snapshot(baseline_snapshot)

    session = Session(
        session_id="sess-seeded-demo-001",
        task_id=approved_task.task_id,
        contract_revision=approved_task.revision,
        repo_root=str(target_path),
        baseline_snapshot_id=baseline_snapshot.snapshot_id,
        current_snapshot_id=baseline_snapshot.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(session)

    # -------------------------------------------------------------------------
    # Phase 5: Simulate clean agent edits (write allowed feature file)
    # -------------------------------------------------------------------------
    log("[Phase 5/9] Simulating agent implementing allowed feature edits...")
    (src_dir / "math_service.py").write_text(EXTENDED_MATH_SERVICE, encoding="utf-8")
    (tests_dir / "test_math.py").write_text(EXTENDED_TEST_MATH, encoding="utf-8")

    clean_snapshot = capture_snapshot(target_path)
    store.save_snapshot(clean_snapshot)

    session = session.model_copy(update={"current_snapshot_id": clean_snapshot.snapshot_id})
    store.save_session(session)

    # -------------------------------------------------------------------------
    # Phase 6: Run verification gate (pytest) -> fresh EvidenceRecord
    # -------------------------------------------------------------------------
    log("[Phase 6/9] Executing verification gate 'pytest'...")
    pytest_gate_policy = GatePolicy(
        provider="pytest",
        command=(sys.executable, "-m", "pytest", "-q"),
        timeout_seconds=30,
        mandatory=True,
    )
    trusted_policy = TrustedPolicy(
        gates={"pytest": pytest_gate_policy},
    )

    clean_evidence = run_gate(
        gate_id="pytest",
        gate_policy=pytest_gate_policy,
        repo_root=target_path,
        session_id=session.session_id,
        contract_revision=approved_task.revision,
        snapshot_before=clean_snapshot,
        acceptance_criteria=("AC-1", "AC-2"),
    )
    store.save_evidence(clean_evidence)

    # -------------------------------------------------------------------------
    # Phase 7: Evaluate session -> VerdictOutcome.ALLOW
    # -------------------------------------------------------------------------
    log("[Phase 7/9] Evaluating session after clean edits (Verdict: ALLOW)...")
    clean_scope_result = analyze_scope(baseline_snapshot, clean_snapshot, approved_task.scope)
    allow_verdict = evaluate_session(
        session=session,
        task_revision=approved_task,
        current_snapshot=clean_snapshot,
        evidence_records=[clean_evidence],
        scope_result=clean_scope_result,
        policy=trusted_policy,
    )
    store.save_verdict(allow_verdict)

    if allow_verdict.verdict != VerdictOutcome.ALLOW:
        raise RuntimeError(f"Expected VerdictOutcome.ALLOW, got {allow_verdict.verdict}: {allow_verdict.reasons}")

    # -------------------------------------------------------------------------
    # Phase 8: Simulate violation scenario -> Evaluate -> VerdictOutcome.BLOCK
    # -------------------------------------------------------------------------
    log("[Phase 8/9] Simulating agent editing restricted path 'config/security.toml'...")
    config_dir = target_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "security.toml").write_text(VIOLATION_SECURITY_CONFIG, encoding="utf-8")

    violation_snapshot = capture_snapshot(target_path)
    store.save_snapshot(violation_snapshot)

    session = session.model_copy(update={"current_snapshot_id": violation_snapshot.snapshot_id})
    store.save_session(session)

    violation_scope_result = analyze_scope(
        baseline_snapshot, violation_snapshot, approved_task.scope
    )
    block_verdict = evaluate_session(
        session=session,
        task_revision=approved_task,
        current_snapshot=violation_snapshot,
        evidence_records=[clean_evidence],
        scope_result=violation_scope_result,
        policy=trusted_policy,
    )
    store.save_verdict(block_verdict)

    if block_verdict.verdict != VerdictOutcome.BLOCK:
        raise RuntimeError(f"Expected VerdictOutcome.BLOCK, got {block_verdict.verdict}: {block_verdict.reasons}")

    handoff_card = generate_handoff(
        task_revision=approved_task,
        verdict=block_verdict,
        scope_result=violation_scope_result,
        evidence_records=[clean_evidence],
    )

    # -------------------------------------------------------------------------
    # Phase 9: Export Markdown report and JSON receipt
    # -------------------------------------------------------------------------
    log("[Phase 9/9] Exporting Markdown report and canonical JSON receipt...")
    report_markdown = render_markdown_report(
        session=session,
        task=approved_task,
        snapshot=violation_snapshot,
        scope_result=violation_scope_result,
        evidence=[clean_evidence],
        verdict=block_verdict,
    )
    receipt_json = export_json_receipt(
        session=session,
        task=approved_task,
        snapshot=violation_snapshot,
        scope_result=violation_scope_result,
        evidence=[clean_evidence],
        verdict=block_verdict,
    )

    (target_path / "report.md").write_text(report_markdown, encoding="utf-8")
    (target_path / "report.json").write_text(json.dumps(receipt_json, indent=2), encoding="utf-8")

    log("Deterministic seeded demo completed successfully.")

    return {
        "status": "success",
        "project_id": project_id,
        "session": session,
        "task": approved_task,
        "baseline_snapshot": baseline_snapshot,
        "clean_snapshot": clean_snapshot,
        "violation_snapshot": violation_snapshot,
        "clean_scope_result": clean_scope_result,
        "violation_scope_result": violation_scope_result,
        "evidence": clean_evidence,
        "allow_verdict": allow_verdict,
        "block_verdict": block_verdict,
        "handoff_card": handoff_card,
        "report_markdown": report_markdown,
        "receipt_json": receipt_json,
        "target_dir": str(target_path),
        "db_path": str(db_file),
    }
