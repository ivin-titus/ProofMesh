from pathlib import Path
import os
import pytest
from unittest.mock import patch

from proofmesh.core.repo_snapshot import capture_snapshot
from proofmesh.core.evaluator import evaluate_session
from proofmesh.models import (
    ApprovalStatus,
    BudgetPolicy,
    GatePolicy,
    IntegrationStatus,
    OperatingProfile,
    RiskLevel,
    ScopeAnalysisResult,
    ScopePolicy,
    Session,
    SessionState,
    TaskRevision,
    TrustedPolicy,
    VerdictOutcome,
)
from datetime import datetime, timezone


def make_minimal_eval_session(snapshot_id: str) -> Session:
    now = datetime.now(timezone.utc)
    return Session(
        session_id="sess-01",
        task_id="task-01",
        contract_revision=1,
        repo_root="/dummy",
        baseline_snapshot_id=snapshot_id,
        current_snapshot_id=snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest="sha256:" + "a" * 64,
        integration_status=IntegrationStatus.UNGUARDED,
        state=SessionState.ACTIVE,
        started_at=now,
    )


def make_minimal_task_revision() -> TaskRevision:
    return TaskRevision(
        task_id="task-01",
        revision=1,
        summary="Test task",
        acceptance_criteria=(),
        scope=ScopePolicy(allow_paths=("**",), restricted_paths=()),
        required_gates=(),
        constraints=(),
        risk_level=RiskLevel.LOW,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="tester",
        approved_at=datetime.now(timezone.utc),
        contract_digest="sha256:" + "a" * 64,
    )


def test_complete_snapshot_clean_workspace(tmp_path: Path):
    f1 = tmp_path / "hello.txt"
    f1.write_text("hello world\n", encoding="utf-8")

    snap = capture_snapshot(tmp_path)
    assert snap.complete is True
    assert len(snap.observation_errors) == 0
    assert len(snap.files) == 1
    assert snap.files[0].path == "hello.txt"
    assert snap.snapshot_id.startswith("sha256:")


def test_repeatable_complete_snapshot(tmp_path: Path):
    (tmp_path / "a.py").write_text("print('a')\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("print('b')\n", encoding="utf-8")

    snap1 = capture_snapshot(tmp_path)
    snap2 = capture_snapshot(tmp_path)

    assert snap1.snapshot_id == snap2.snapshot_id
    assert snap1.complete is True
    assert snap2.complete is True


def test_broken_symlink_marks_incomplete(tmp_path: Path):
    broken_link = tmp_path / "broken.txt"
    broken_link.symlink_to(tmp_path / "nonexistent.txt")

    snap = capture_snapshot(tmp_path)
    assert snap.complete is False
    assert any("Broken symlink 'broken.txt'" in err for err in snap.observation_errors)


def test_escaping_symlink_marks_incomplete(tmp_path: Path):
    outside_file = tmp_path.parent / "outside.txt"
    outside_file.write_text("secret\n", encoding="utf-8")

    escaping_link = tmp_path / "escape.txt"
    escaping_link.symlink_to(outside_file)

    snap = capture_snapshot(tmp_path)
    assert snap.complete is False
    assert any("resolves outside workspace root" in err for err in snap.observation_errors)


def test_broken_symlink_directory_marks_incomplete(tmp_path: Path):
    broken_dir_link = tmp_path / "broken_dir"
    broken_dir_link.symlink_to(tmp_path / "nonexistent_dir")

    snap = capture_snapshot(tmp_path)
    assert snap.complete is False
    assert any("Broken symlink" in err and "broken_dir" in err for err in snap.observation_errors)


def test_escaping_symlink_directory_marks_incomplete(tmp_path: Path):
    outside_dir = tmp_path.parent / "outside_dir"
    outside_dir.mkdir(exist_ok=True)

    escaping_dir_link = tmp_path / "escape_dir"
    escaping_dir_link.symlink_to(outside_dir)

    snap = capture_snapshot(tmp_path)
    assert snap.complete is False
    assert any("resolves outside workspace root" in err for err in snap.observation_errors)


def test_valid_in_root_symlink_is_complete(tmp_path: Path):
    real_file = tmp_path / "real.txt"
    real_file.write_text("content\n", encoding="utf-8")

    valid_link = tmp_path / "link.txt"
    valid_link.symlink_to(real_file)

    snap = capture_snapshot(tmp_path)
    assert snap.complete is True
    assert len(snap.observation_errors) == 0
    # Both real.txt and link.txt are valid files
    paths = {f.path for f in snap.files}
    assert "real.txt" in paths
    assert "link.txt" in paths


def test_unreadable_file_marks_incomplete(tmp_path: Path):
    bad_file = tmp_path / "unreadable.txt"
    bad_file.write_text("secret\n", encoding="utf-8")

    # Simulate OSError on open
    orig_open = open

    def fake_open(file, *args, **kwargs):
        if str(file) == str(bad_file):
            raise PermissionError(f"Permission denied: {file}")
        return orig_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=fake_open):
        snap = capture_snapshot(tmp_path)
        assert snap.complete is False
        assert any("Unreadable file 'unreadable.txt'" in err for err in snap.observation_errors)


def test_directory_traversal_walk_error_marks_incomplete(tmp_path: Path):
    sub_dir = tmp_path / "sub"
    sub_dir.mkdir()
    (sub_dir / "file.txt").write_text("hi\n")

    orig_walk = os.walk

    def fake_walk(top, *args, **kwargs):
        onerror = kwargs.get("onerror")
        if onerror:
            onerror(PermissionError(f"Simulated dir error on {top}"))
        return orig_walk(top, *args, **kwargs)

    with patch("os.walk", side_effect=fake_walk):
        snap = capture_snapshot(tmp_path)
        assert snap.complete is False
        assert any("Directory traversal error" in err for err in snap.observation_errors)


def test_incomplete_snapshot_causes_evaluator_to_block(tmp_path: Path):
    broken_link = tmp_path / "broken.txt"
    broken_link.symlink_to(tmp_path / "nonexistent.txt")

    incomplete_snap = capture_snapshot(tmp_path)
    assert incomplete_snap.complete is False

    session = make_minimal_eval_session(incomplete_snap.snapshot_id)
    task_rev = make_minimal_task_revision()
    scope = ScopeAnalysisResult(
        baseline_snapshot_id=incomplete_snap.snapshot_id,
        current_snapshot_id=incomplete_snap.snapshot_id,
        changes=(),
        findings=(),
        total_changed_files=0,
        exceeded_file_limit=False,
        has_violations=False,
    )
    policy = TrustedPolicy(profile=OperatingProfile.FLOW)

    verdict = evaluate_session(
        session=session,
        task_revision=task_rev,
        current_snapshot=incomplete_snap,
        evidence_records=(),
        scope_result=scope,
        policy=policy,
        effective_policy_digest=session.policy_digest,
    )
    assert verdict.verdict == VerdictOutcome.BLOCK
    assert any("incomplete" in r.lower() for r in verdict.reasons)
