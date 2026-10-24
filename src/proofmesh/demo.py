"""Deterministic Seeded Demo with Safe Recovery for ProofMesh.

Demonstrates the complete end-to-end intent, intervention, and evidence control
loop without external LLM or network dependencies:
1. Initialize fixture & storage outside target directory.
2. Propose TaskFile contract (revision 1) with required gates and allow_paths.
3. Human approver 'alice' approves TaskRevision 1.
4. Capture baseline repository snapshot.
5. Introduce deliberate restricted/out-of-scope change (config/security.toml).
6. Evaluate -> BLOCK. Generate handoff explaining blockers. Save 'report-blocked.md' and 'report-blocked.json'.
7. Correct the issue safely: revert restricted change, implement allowed code edits in src/math_service.py and tests/test_math.py.
8. Run real configured check (pytest) -> fresh EvidenceRecord.
9. Evaluate -> ALLOW. All gates passed with fresh evidence and clean scope.
10. Export final accepted 'report.md' and 'report.json'.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Callable

from proofmesh.config import compute_policy_digest
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

FIXTURE_MARKER = ".proofmesh-fixture"
DEMO_SNAPSHOT_EXCLUDES = (
    ".proofmesh-fixture",
    "report*.md",
    "report*.json",
)


def _capture_demo_snapshot(repo_root: Path | str) -> RepoSnapshot:
    """Capture snapshot excluding ProofMesh control artifacts."""
    return capture_snapshot(repo_root, exclude_patterns=DEMO_SNAPSHOT_EXCLUDES)

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

PYTEST_INI_CONTENT = "[pytest]\npythonpath = .\n"


def _validate_and_prepare_target(target_path: Path) -> None:
    """Validate target directory safety and ensure fixture marker is present.

    Refuses to modify non-empty directories that do not contain the dedicated
    ProofMesh fixture marker file (.proofmesh-fixture), or directories that contain
    colliding files that cannot be proven to be prior demo-owned artifacts, or
    symlink escapes resolving outside target directory.
    """
    canonical_target = target_path.resolve()

    if target_path.exists():
        if not target_path.is_dir():
            raise ValueError(f"Target path '{target_path}' exists and is not a directory.")

        # Check key subpaths for symlink escapes
        for sub_name in ("src", "tests", "config"):
            sub_path = target_path / sub_name
            if sub_path.is_symlink():
                resolved_sub = sub_path.resolve()
                if not resolved_sub.is_relative_to(canonical_target):
                    raise ValueError(
                        f"Symlink escape detected in target directory: subpath '{sub_name}' "
                        f"resolves to '{resolved_sub}' outside canonical target root '{canonical_target}'."
                    )

        # Recursively check all entries for symlink escapes
        for entry in target_path.rglob("*"):
            if entry.is_symlink():
                resolved_entry = entry.resolve()
                if not resolved_entry.is_relative_to(canonical_target):
                    raise ValueError(
                        f"Symlink escape detected in target directory: entry '{entry.name}' "
                        f"resolves to '{resolved_entry}' outside canonical target root '{canonical_target}'."
                    )

        entries = list(target_path.iterdir())
        if entries:
            marker = target_path / FIXTURE_MARKER
            if not marker.exists():
                raise ValueError(
                    f"Target directory '{target_path}' is non-empty and does not contain "
                    f"the ProofMesh fixture marker ('{FIXTURE_MARKER}'). "
                    f"Refusing to modify or delete files in caller directory."
                )

            # Check colliding files to ensure foreign pre-existing files are not overwritten
            math_svc = target_path / "src" / "math_service.py"
            if math_svc.is_file():
                content = math_svc.read_text(encoding="utf-8")
                if content not in (INITIAL_MATH_SERVICE, EXTENDED_MATH_SERVICE):
                    raise ValueError(
                        f"Target directory '{target_path}' contains pre-existing 'src/math_service.py' "
                        f"with foreign content. Refusing to overwrite user file."
                    )

            math_test = target_path / "tests" / "test_math.py"
            if math_test.is_file():
                content = math_test.read_text(encoding="utf-8")
                if content not in (INITIAL_TEST_MATH, EXTENDED_TEST_MATH):
                    raise ValueError(
                        f"Target directory '{target_path}' contains pre-existing 'tests/test_math.py' "
                        f"with foreign content. Refusing to overwrite user file."
                    )

            pytest_ini = target_path / "pytest.ini"
            if pytest_ini.is_file():
                content = pytest_ini.read_text(encoding="utf-8")
                if content != PYTEST_INI_CONTENT:
                    raise ValueError(
                        f"Target directory '{target_path}' contains pre-existing 'pytest.ini' "
                        f"with foreign content. Refusing to overwrite user file."
                    )

            sec_cfg = target_path / "config" / "security.toml"
            if sec_cfg.is_file():
                content = sec_cfg.read_text(encoding="utf-8")
                if content != VIOLATION_SECURITY_CONFIG:
                    raise ValueError(
                        f"Target directory '{target_path}' contains pre-existing 'config/security.toml' "
                        f"with foreign content. Refusing to overwrite user file."
                    )
    else:
        target_path.mkdir(parents=True, exist_ok=True)

    marker = target_path / FIXTURE_MARKER
    if not marker.exists():
        marker.write_text("proofmesh-fixture-workspace\n", encoding="utf-8")


def _validate_and_prepare_database(db_file: Path, project_id: str) -> None:
    """Validate database safety and ensure caller-supplied non-demo files are not touched."""
    db_file.parent.mkdir(parents=True, exist_ok=True)

    if not db_file.exists():
        return

    try:
        conn = sqlite3.connect(db_file)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}
            if tables and "projects" not in tables:
                raise ValueError(
                    f"Database path '{db_file}' exists and does not contain ProofMesh schema. "
                    f"Refusing to overwrite or delete caller-supplied database."
                )
            if "projects" in tables:
                cursor.execute("SELECT project_id FROM projects;")
                existing_project_ids = {row[0] for row in cursor.fetchall()}
                foreign_projects = existing_project_ids - {project_id}
                if foreign_projects:
                    raise ValueError(
                        f"Database path '{db_file}' contains non-demo projects ({foreign_projects}). "
                        f"Refusing to overwrite or delete caller-supplied database."
                    )
                if project_id in existing_project_ids and "tasks" in tables:
                    cursor.execute("SELECT task_id FROM tasks WHERE project_id = ?;", (project_id,))
                    task_ids = {row[0] for row in cursor.fetchall()}
                    foreign_tasks = task_ids - {"task-calc-extension"}
                    if foreign_tasks:
                        raise ValueError(
                            f"Database path '{db_file}' contains project '{project_id}' with non-demo tasks ({foreign_tasks}). "
                            f"Refusing to overwrite or reset caller-supplied database."
                        )
                if "task_revisions" in tables:
                    cursor.execute("SELECT task_id FROM task_revisions;")
                    rev_tasks = {row[0] for row in cursor.fetchall()}
                    if rev_tasks - {"task-calc-extension"}:
                        raise ValueError(
                            f"Database path '{db_file}' contains non-demo task revisions ({rev_tasks - {'task-calc-extension'}}). "
                            f"Refusing to reset caller-supplied database."
                        )
                if "sessions" in tables:
                    cursor.execute("SELECT task_id FROM sessions;")
                    sess_tasks = {row[0] for row in cursor.fetchall()}
                    if sess_tasks - {"task-calc-extension"}:
                        raise ValueError(
                            f"Database path '{db_file}' contains sessions for non-demo tasks ({sess_tasks - {'task-calc-extension'}}). "
                            f"Refusing to reset caller-supplied database."
                        )
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise ValueError(
            f"Database path '{db_file}' exists but is not a valid SQLite database: {e}. "
            f"Refusing to overwrite caller-supplied file."
        ) from e


def _reset_demo_database(db_file: Path, project_id: str) -> None:
    """Reset seeded demo data in an existing demo database without deleting the file."""
    if not db_file.exists():
        return

    conn = sqlite3.connect(db_file)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        if "projects" in tables:
            cursor.execute("PRAGMA foreign_keys = OFF;")
            if "verdicts" in tables:
                cursor.execute(
                    "DELETE FROM verdicts WHERE session_id IN "
                    "(SELECT session_id FROM sessions WHERE task_id IN "
                    "(SELECT task_id FROM tasks WHERE project_id = ?));",
                    (project_id,),
                )
            if "evidence" in tables:
                cursor.execute(
                    "DELETE FROM evidence WHERE session_id IN "
                    "(SELECT session_id FROM sessions WHERE task_id IN "
                    "(SELECT task_id FROM tasks WHERE project_id = ?));",
                    (project_id,),
                )
            if "loop_failure_attempts" in tables:
                cursor.execute(
                    "DELETE FROM loop_failure_attempts WHERE session_id IN "
                    "(SELECT session_id FROM sessions WHERE task_id IN "
                    "(SELECT task_id FROM tasks WHERE project_id = ?));",
                    (project_id,),
                )
            if "sessions" in tables:
                cursor.execute(
                    "DELETE FROM sessions WHERE task_id IN "
                    "(SELECT task_id FROM tasks WHERE project_id = ?);",
                    (project_id,),
                )
            if "task_revisions" in tables:
                cursor.execute(
                    "DELETE FROM task_revisions WHERE task_id IN "
                    "(SELECT task_id FROM tasks WHERE project_id = ?);",
                    (project_id,),
                )
            if "tasks" in tables:
                cursor.execute(
                    "DELETE FROM tasks WHERE project_id = ?;",
                    (project_id,),
                )
            if "projects" in tables:
                cursor.execute(
                    "DELETE FROM projects WHERE project_id = ?;",
                    (project_id,),
                )
            conn.commit()
            cursor.execute("PRAGMA foreign_keys = ON;")
    finally:
        conn.close()


def _safe_write_report(file_path: Path, content: str) -> None:
    """Write report file only if it doesn't exist or is proven to be demo-owned."""
    if file_path.exists():
        try:
            existing = file_path.read_text(encoding="utf-8")
        except Exception:
            raise ValueError(
                f"Existing report file '{file_path}' cannot be read as UTF-8 text. "
                "Refusing to overwrite potential user file."
            )
        if "task-calc-extension" not in existing and "seeded-demo-project" not in existing:
            raise ValueError(
                f"Existing report file '{file_path}' does not contain seeded demo markers "
                "('task-calc-extension' or 'seeded-demo-project'). Refusing to overwrite user report file."
            )
    file_path.write_text(content, encoding="utf-8")


def _clean_demo_artifacts(target_path: Path) -> None:
    """Clean known demo artifacts safely without deleting arbitrary directories."""
    for filename in ("report.md", "report.json", "report-blocked.md", "report-blocked.json"):
        rep_file = target_path / filename
        if rep_file.exists():
            try:
                content = rep_file.read_text(encoding="utf-8")
            except Exception:
                raise ValueError(
                    f"Existing report file '{rep_file}' cannot be read as UTF-8 text. "
                    "Refusing to delete potential user file."
                )
            if "task-calc-extension" not in content and "seeded-demo-project" not in content:
                raise ValueError(
                    f"Existing file '{rep_file}' does not contain seeded demo markers "
                    "('task-calc-extension' or 'seeded-demo-project'). Refusing to delete user report file."
                )
            rep_file.unlink()

    violation_file = target_path / "config" / "security.toml"
    if violation_file.exists():
        content = violation_file.read_text(encoding="utf-8")
        if content != VIOLATION_SECURITY_CONFIG:
            raise ValueError(
                f"Temporary file '{violation_file}' has been altered by an external process. "
                "Refusing to delete altered file."
            )
        violation_file.unlink(missing_ok=True)
    config_dir = target_path / "config"
    if config_dir.is_dir() and not any(config_dir.iterdir()):
        config_dir.rmdir()


def run_seeded_demo(
    target_dir: Path | str,
    db_path: Path | str | None = None,
    *,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Execute the deterministic seeded end-to-end ProofMesh recovery control scenario.

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

    # -------------------------------------------------------------------------
    # Phase 1: Initialize fixture & storage outside target directory
    # -------------------------------------------------------------------------
    log("[Phase 1/10] Initializing fixture & ProofMeshStore outside target repo...")
    _validate_and_prepare_target(target_path)

    if db_path is not None:
        db_file = Path(db_path).resolve()
    else:
        db_dir = (target_path.parent / ".proofmesh_store").resolve()
        db_dir.mkdir(parents=True, exist_ok=True)
        db_file = db_dir / "seeded_demo.db"

    project_id = "seeded-demo-project"
    _validate_and_prepare_database(db_file, project_id)
    _reset_demo_database(db_file, project_id)

    store = ProofMeshStore(db_file)
    store.create_project(project_id, root_path=str(target_path))

    # Clean existing demo-specific artifacts safely
    _clean_demo_artifacts(target_path)

    src_dir = target_path / "src"
    tests_dir = target_path / "tests"
    src_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    (src_dir / "math_service.py").write_text(INITIAL_MATH_SERVICE, encoding="utf-8")
    (tests_dir / "test_math.py").write_text(INITIAL_TEST_MATH, encoding="utf-8")
    (target_path / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")

    # -------------------------------------------------------------------------
    # Phase 2: Propose TaskFile contract (revision 1) with required gates and allow_paths
    # -------------------------------------------------------------------------
    log("[Phase 2/10] Proposing TaskFile contract (revision 1)...")
    task_service = TaskService(store)
    task_rev1 = task_service.propose_task(
        task_id="task-calc-extension",
        content=SEEDED_TASKFILE,
        project_id=project_id,
        known_gates={"pytest"},
    )

    # -------------------------------------------------------------------------
    # Phase 3: Human approver 'alice' approves TaskRevision 1
    # -------------------------------------------------------------------------
    log("[Phase 3/10] Human approver 'alice' approves TaskRevision 1...")
    approved_task = task_service.approve_task(
        task_id="task-calc-extension",
        revision=1,
        approved_by="alice",
        reason="Initial math extension approved for implementation.",
    )

    # -------------------------------------------------------------------------
    # Phase 4: Capture baseline repository snapshot
    # -------------------------------------------------------------------------
    log("[Phase 4/10] Capturing baseline repository snapshot...")
    baseline_snapshot = _capture_demo_snapshot(target_path)
    store.save_snapshot(baseline_snapshot)

    pytest_gate_policy = GatePolicy(
        provider="pytest",
        command=(sys.executable, "-m", "pytest", "-q"),
        timeout_seconds=30,
        mandatory=True,
    )
    trusted_policy = TrustedPolicy(
        gates={"pytest": pytest_gate_policy},
    )
    policy_digest = compute_policy_digest(trusted_policy)

    session = Session(
        session_id="sess-seeded-demo-001",
        task_id=approved_task.task_id,
        contract_revision=approved_task.revision,
        repo_root=str(target_path),
        baseline_snapshot_id=baseline_snapshot.snapshot_id,
        current_snapshot_id=baseline_snapshot.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest=policy_digest,
        integration_status=IntegrationStatus.UNGUARDED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(session)

    # -------------------------------------------------------------------------
    # Phase 5: Introduce deliberate restricted/out-of-scope change (e.g. config/security.toml)
    # -------------------------------------------------------------------------
    log("[Phase 5/10] Introducing deliberate out-of-scope edit to 'config/security.toml'...")
    config_dir = target_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "security.toml").write_text(VIOLATION_SECURITY_CONFIG, encoding="utf-8")

    violation_snapshot = _capture_demo_snapshot(target_path)
    store.save_snapshot(violation_snapshot)

    session = session.model_copy(update={"current_snapshot_id": violation_snapshot.snapshot_id})
    store.save_session(session)

    # -------------------------------------------------------------------------
    # Phase 6: Evaluate -> BLOCK. Generate handoff explaining blockers. Save 'report-blocked.md' and 'report-blocked.json'
    # -------------------------------------------------------------------------
    log("[Phase 6/10] Evaluating session under out-of-scope violation (Verdict: BLOCK)...")
    violation_scope_result = analyze_scope(
        baseline_snapshot, violation_snapshot, approved_task.scope
    )
    block_verdict = evaluate_session(
        session=session,
        task_revision=approved_task,
        current_snapshot=violation_snapshot,
        evidence_records=[],
        scope_result=violation_scope_result,
        policy=trusted_policy,
        baseline_snapshot=baseline_snapshot,
    )
    store.save_verdict(block_verdict)

    if block_verdict.verdict != VerdictOutcome.BLOCK:
        raise RuntimeError(f"Expected VerdictOutcome.BLOCK, got {block_verdict.verdict}: {block_verdict.reasons}")

    handoff_card = generate_handoff(
        task_revision=approved_task,
        verdict=block_verdict,
        scope_result=violation_scope_result,
        evidence_records=[],
    )

    blocked_report_markdown = render_markdown_report(
        session=session,
        task=approved_task,
        snapshot=violation_snapshot,
        scope_result=violation_scope_result,
        evidence=[],
        verdict=block_verdict,
    )
    blocked_receipt_json = export_json_receipt(
        session=session,
        task=approved_task,
        snapshot=violation_snapshot,
        scope_result=violation_scope_result,
        evidence=[],
        verdict=block_verdict,
    )

    _safe_write_report(target_path / "report-blocked.md", blocked_report_markdown)
    _safe_write_report(target_path / "report-blocked.json", json.dumps(blocked_receipt_json, indent=2))

    # -------------------------------------------------------------------------
    # Phase 7: Correct the issue safely: revert restricted change, implement allowed code edits in src/math_service.py and tests/test_math.py
    # -------------------------------------------------------------------------
    log("[Phase 7/10] Recovering safely: reverting restricted change and implementing allowed edits...")
    violation_file = config_dir / "security.toml"
    if violation_file.exists():
        content = violation_file.read_text(encoding="utf-8")
        if content != VIOLATION_SECURITY_CONFIG:
            raise ValueError(
                f"Temporary file '{violation_file}' has been altered by an external process. "
                "Refusing to delete altered file."
            )
        violation_file.unlink()
    if config_dir.is_dir() and not any(config_dir.iterdir()):
        config_dir.rmdir()

    (src_dir / "math_service.py").write_text(EXTENDED_MATH_SERVICE, encoding="utf-8")
    (tests_dir / "test_math.py").write_text(EXTENDED_TEST_MATH, encoding="utf-8")

    clean_snapshot = _capture_demo_snapshot(target_path)
    store.save_snapshot(clean_snapshot)

    session = session.model_copy(update={"current_snapshot_id": clean_snapshot.snapshot_id})
    store.save_session(session)

    # -------------------------------------------------------------------------
    # Phase 8: Run real configured check (pytest) -> fresh EvidenceRecord
    # -------------------------------------------------------------------------
    log("[Phase 8/10] Executing verification gate 'pytest' against recovered code...")
    clean_evidence = run_gate(
        gate_id="pytest",
        gate_policy=pytest_gate_policy,
        repo_root=target_path,
        session_id=session.session_id,
        contract_revision=approved_task.revision,
        snapshot_before=clean_snapshot,
        acceptance_criteria=("AC-1", "AC-2"),
        capture_snapshot_fn=_capture_demo_snapshot,
    )
    store.save_evidence(clean_evidence)

    # -------------------------------------------------------------------------
    # Phase 9: Evaluate -> ALLOW. All gates passed with fresh evidence and clean scope
    # -------------------------------------------------------------------------
    log("[Phase 9/10] Evaluating recovered session (Verdict: ALLOW)...")
    clean_scope_result = analyze_scope(baseline_snapshot, clean_snapshot, approved_task.scope)
    allow_verdict = evaluate_session(
        session=session,
        task_revision=approved_task,
        current_snapshot=clean_snapshot,
        evidence_records=[clean_evidence],
        scope_result=clean_scope_result,
        policy=trusted_policy,
        baseline_snapshot=baseline_snapshot,
    )
    store.save_verdict(allow_verdict)

    if allow_verdict.verdict != VerdictOutcome.ALLOW:
        raise RuntimeError(f"Expected VerdictOutcome.ALLOW, got {allow_verdict.verdict}: {allow_verdict.reasons}")

    # -------------------------------------------------------------------------
    # Phase 10: Export final accepted 'report.md' and 'report.json'
    # -------------------------------------------------------------------------
    log("[Phase 10/10] Exporting final accepted 'report.md' and 'report.json'...")
    report_markdown = render_markdown_report(
        session=session,
        task=approved_task,
        snapshot=clean_snapshot,
        scope_result=clean_scope_result,
        evidence=[clean_evidence],
        verdict=allow_verdict,
    )
    receipt_json = export_json_receipt(
        session=session,
        task=approved_task,
        snapshot=clean_snapshot,
        scope_result=clean_scope_result,
        evidence=[clean_evidence],
        verdict=allow_verdict,
    )

    _safe_write_report(target_path / "report.md", report_markdown)
    _safe_write_report(target_path / "report.json", json.dumps(receipt_json, indent=2))

    log("Deterministic seeded demo recovery loop completed successfully.")

    return {
        "status": "success",
        "project_id": project_id,
        "session": session,
        "task": approved_task,
        "baseline_snapshot": baseline_snapshot,
        "violation_snapshot": violation_snapshot,
        "clean_snapshot": clean_snapshot,
        "violation_scope_result": violation_scope_result,
        "clean_scope_result": clean_scope_result,
        "evidence": clean_evidence,
        "block_verdict": block_verdict,
        "allow_verdict": allow_verdict,
        "verdict": allow_verdict,
        "handoff_card": handoff_card,
        "blocked_report_markdown": blocked_report_markdown,
        "blocked_receipt_json": blocked_receipt_json,
        "report_markdown": report_markdown,
        "receipt_json": receipt_json,
        "target_dir": str(target_path),
        "db_path": str(db_file),
    }
