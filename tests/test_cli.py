"""Tests for ProofMesh Command-Line Interface (Checkpoint 6).

Covers all specified CLI commands:
- `proofmesh demo [--dir <path>]`
- `proofmesh init [--path <path>]`
- `proofmesh task propose <file>`
- `proofmesh task approve <task-id> <revision> --by <user>`
- `proofmesh status [--session-id <id>]`
- `proofmesh verify <gate-id>`
- `proofmesh evaluate`
- `proofmesh report [--json]`
- Error scenarios and exit code correctness.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from proofmesh.cli import main

SAMPLE_TASKFILE = """+++
task_id = "task-cli-test"
version = 1
summary = "CLI integration test task"
risk_level = "low"
allow_paths = ["src/**", "tests/**", "pytest.ini"]
restricted_paths = ["config/**", ".git/**"]
required_gates = ["test"]
+++

# task-cli-test

## Acceptance criteria
- [AC-1] Verify CLI execution (gates: test)
"""


def test_cli_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """Test `proofmesh demo --dir <path>` runs end-to-end and exits 0."""
    demo_dir = tmp_path / "cli_demo_target"
    db_file = tmp_path / "cli_demo.db"
    monkeypatch.setenv("PROOFMESH_DB", str(db_file))

    exit_code = main(["demo", "--dir", str(demo_dir)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Running ProofMesh seeded demo" in captured.out
    assert "Seeded demo completed successfully" in captured.out
    assert (demo_dir / "report.md").is_file()
    assert (demo_dir / "report.json").is_file()


def test_cli_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """Test `proofmesh init --path <path>` initializes project outside repo."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    db_file = tmp_path / "init_test.db"
    monkeypatch.setenv("PROOFMESH_DB", str(db_file))

    exit_code = main(["init", "--path", str(project_dir)])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Initialized ProofMesh for project" in captured.out
    assert str(project_dir) in captured.out


def test_cli_task_propose_and_approve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """Test `proofmesh task propose` and `proofmesh task approve`."""
    work_dir = tmp_path / "task_work"
    work_dir.mkdir()
    db_file = tmp_path / "task_test.db"
    monkeypatch.setenv("PROOFMESH_DB", str(db_file))
    monkeypatch.setenv("PROOFMESH_PROJECT_ID", "task-test-project")
    monkeypatch.chdir(work_dir)

    # Write TaskFile
    tf = work_dir / "TASK.md"
    tf.write_text(SAMPLE_TASKFILE, encoding="utf-8")

    # Propose
    exit_code = main(["task", "propose", str(tf)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Task proposed: task-cli-test (revision 1)" in captured.out

    # Approve
    exit_code = main(["task", "approve", "task-cli-test", "1", "--by", "alice", "--reason", "Approved for CLI test"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Task approved: task-cli-test rev 1 by alice" in captured.out


def test_cli_verify_and_evaluate_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """Test complete CLI workflow: init -> propose -> approve -> verify -> evaluate -> report."""
    work_dir = tmp_path / "full_flow_repo"
    work_dir.mkdir()
    src_dir = work_dir / "src"
    tests_dir = work_dir / "tests"
    src_dir.mkdir()
    tests_dir.mkdir()

    (src_dir / "app.py").write_text("def hello(): return 'world'\n", encoding="utf-8")
    (tests_dir / "test_app.py").write_text(
        "from src.app import hello\ndef test_hello(): assert hello() == 'world'\n",
        encoding="utf-8",
    )
    (work_dir / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")

    db_file = tmp_path / "full_flow.db"
    monkeypatch.setenv("PROOFMESH_DB", str(db_file))
    monkeypatch.setenv("PROOFMESH_PROJECT_ID", "full-flow-project")
    monkeypatch.chdir(work_dir)

    # 1. Propose and approve task
    tf = work_dir / "TASK.md"
    tf.write_text(SAMPLE_TASKFILE, encoding="utf-8")
    assert main(["task", "propose", str(tf)]) == 0
    assert main(["task", "approve", "task-cli-test", "1", "--by", "alice"]) == 0

    # 2. Status before verify
    assert main(["status"]) == 0
    status_out = capsys.readouterr().out
    assert "full-flow-project" in status_out
    assert "task-cli-test" in status_out

    # 3. Verify gate
    assert main(["verify", "test"]) == 0
    verify_out = capsys.readouterr().out
    assert "Gate 'test': PASSED" in verify_out

    # 4. Evaluate
    assert main(["evaluate"]) == 0
    eval_out = capsys.readouterr().out
    assert "✅ VERDICT: ALLOW" in eval_out

    # 5. Report (Markdown)
    assert main(["report"]) == 0
    report_out = capsys.readouterr().out
    assert "# ProofMesh Verification Report" in report_out
    assert "task-cli-test" in report_out
    assert "✅ ALLOW" in report_out

    # 6. Report (JSON)
    assert main(["report", "--json"]) == 0
    report_json_out = capsys.readouterr().out
    receipt = json.loads(report_json_out)
    assert receipt["schema_version"] == "1.0"
    assert receipt["receipt_digest"].startswith("sha256:")
    assert receipt["verdict"]["verdict"] == "ALLOW"


def test_cli_error_handling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """Test CLI error handling and exit codes."""
    db_file = tmp_path / "errors.db"
    monkeypatch.setenv("PROOFMESH_DB", str(db_file))
    monkeypatch.chdir(tmp_path)

    # Non-existent TaskFile -> exit 2
    exit_code = main(["task", "propose", "non_existent_file.md"])
    assert exit_code == 2

    # Non-existent task to approve -> exit 1
    exit_code = main(["task", "approve", "no-such-task", "1", "--by", "alice"])
    assert exit_code == 1

    # Verify unknown gate without active task -> exit 2
    exit_code = main(["verify", "unknown-gate"])
    assert exit_code == 2

    # Evaluate without active session -> exit 2
    exit_code = main(["evaluate"])
    assert exit_code == 2


def test_cli_status_and_report_with_session_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """Test `proofmesh status` and `proofmesh report` with explicit --session-id."""
    work_dir = tmp_path / "session_id_repo"
    work_dir.mkdir()
    src_dir = work_dir / "src"
    tests_dir = work_dir / "tests"
    src_dir.mkdir()
    tests_dir.mkdir()

    (src_dir / "app.py").write_text("def ping(): return True\n", encoding="utf-8")
    (tests_dir / "test_app.py").write_text("from src.app import ping\ndef test_ping(): assert ping()\n", encoding="utf-8")
    (work_dir / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")

    db_file = tmp_path / "session_id.db"
    monkeypatch.setenv("PROOFMESH_DB", str(db_file))
    monkeypatch.setenv("PROOFMESH_PROJECT_ID", "session-id-project")
    monkeypatch.chdir(work_dir)

    tf = work_dir / "TASK.md"
    tf.write_text(SAMPLE_TASKFILE, encoding="utf-8")
    assert main(["task", "propose", str(tf)]) == 0
    assert main(["task", "approve", "task-cli-test", "1", "--by", "bob"]) == 0
    assert main(["verify", "test"]) == 0

    # Get session ID from status
    assert main(["status"]) == 0
    status_out = capsys.readouterr().out
    import re
    m = re.search(r"Session Status:\s+(sess-[a-zA-Z0-9]+)", status_out)
    assert m is not None
    session_id = m.group(1)

    # Status with explicit session ID
    assert main(["status", "--session-id", session_id]) == 0
    captured = capsys.readouterr()
    assert session_id in captured.out

    # Report with explicit session ID
    assert main(["report", "--session-id", session_id]) == 0
    report_out = capsys.readouterr().out
    assert session_id in report_out


def test_cli_failing_gate_and_blocked_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """Test CLI exit codes when a gate fails or scope violation blocks evaluation."""
    work_dir = tmp_path / "failing_gate_repo"
    work_dir.mkdir()
    src_dir = work_dir / "src"
    tests_dir = work_dir / "tests"
    src_dir.mkdir()
    tests_dir.mkdir()

    # Broken test
    (src_dir / "app.py").write_text("def fail_me(): return False\n", encoding="utf-8")
    (tests_dir / "test_app.py").write_text("from src.app import fail_me\ndef test_fail(): assert fail_me() is True\n", encoding="utf-8")
    (work_dir / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")

    db_file = tmp_path / "failing.db"
    monkeypatch.setenv("PROOFMESH_DB", str(db_file))
    monkeypatch.setenv("PROOFMESH_PROJECT_ID", "failing-project")
    monkeypatch.chdir(work_dir)

    tf = work_dir / "TASK.md"
    tf.write_text(SAMPLE_TASKFILE, encoding="utf-8")
    assert main(["task", "propose", str(tf)]) == 0
    assert main(["task", "approve", "task-cli-test", "1", "--by", "alice"]) == 0
    capsys.readouterr()

    # Gate verify should fail and return 1
    exit_code = main(["verify", "test"])
    assert exit_code == 1
    verify_out = capsys.readouterr().out
    assert "Gate 'test': FAILED" in verify_out

    # Evaluate should fail and return 1 with BLOCK verdict
    eval_code = main(["evaluate"])
    assert eval_code == 1
    eval_out = capsys.readouterr().out
    assert "❌ VERDICT: BLOCK" in eval_out
    assert "Task Handoff:" in eval_out

