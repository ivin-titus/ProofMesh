"""Tests for bounded subprocess execution, safe draining, and evidence invalidation."""

from datetime import datetime, timezone
from pathlib import Path
import sys
import pytest

from proofmesh.core.repo_snapshot import capture_snapshot
from proofmesh.core.verification import check_evidence_freshness, compute_gate_digest, run_gate
from proofmesh.models import (
    EvidenceRecord,
    EvidenceStatus,
    GatePolicy,
    RepoSnapshot,
)


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    """Create a temporary repository root with baseline source files."""
    repo = tmp_path / "bounded_repo"
    repo.mkdir()
    (repo / "source.py").write_text("print('stable codebase')", encoding="utf-8")
    return repo


def test_noisy_child_process_output_flooding_bounded_memory(repo_dir: Path):
    """Child process writing large volumes of output (e.g. 5MB) must not deadlock pipes or blow memory."""
    snap_before = capture_snapshot(repo_dir)

    # Generate ~2.5 MB on stdout and ~2.5 MB on stderr
    command = (
        sys.executable,
        "-c",
        (
            "import sys\n"
            "stdout_chunk = 'X' * 8192 + '\\n'\n"
            "stderr_chunk = 'Y' * 8192 + '\\n'\n"
            "for _ in range(300):\n"
            "    sys.stdout.write(stdout_chunk)\n"
            "    sys.stderr.write(stderr_chunk)\n"
            "sys.stdout.flush()\n"
            "sys.stderr.flush()\n"
        ),
    )

    policy = GatePolicy(
        provider="pytest",
        command=command,
        timeout_seconds=15,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-flood",
        gate_policy=policy,
        repo_root=repo_dir,
        session_id="sess-flood",
        contract_revision=1,
        snapshot_before=snap_before,
        max_capture_bytes=32768,  # Strictly bounded to 32KB buffer
    )

    assert isinstance(evidence, EvidenceRecord)
    assert evidence.status == EvidenceStatus.PASSED
    assert evidence.exit_code == 0
    # Summary must be strictly capped to 2000 chars and indicate truncation
    assert len(evidence.summary) <= 2000
    assert "... [truncated]" in evidence.summary
    assert "[stdout]" in evidence.summary
    assert "[stderr]" in evidence.summary


def test_child_process_timeout_clean_kill(repo_dir: Path):
    """Child process exceeding timeout must be cleanly killed with proc.kill() and exit_code -1."""
    snap_before = capture_snapshot(repo_dir)

    policy = GatePolicy(
        provider="custom",
        command=(sys.executable, "-c", "import time; time.sleep(10)"),
        timeout_seconds=1,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-timeout",
        gate_policy=policy,
        repo_root=repo_dir,
        session_id="sess-timeout",
        contract_revision=1,
        snapshot_before=snap_before,
    )

    assert evidence.status == EvidenceStatus.FAILED
    assert evidence.exit_code == -1
    assert "timed out after 1s" in evidence.summary


def test_binary_and_invalid_utf8_output_handling(repo_dir: Path):
    """Binary or invalid UTF-8 output is decoded safely with errors='replace' without crash."""
    snap_before = capture_snapshot(repo_dir)

    command = (
        sys.executable,
        "-c",
        (
            "import sys\n"
            "sys.stdout.buffer.write(b'valid prefix: ' + b'\\xff\\xfe\\xfd' + b' :valid suffix\\n')\n"
            "sys.stderr.buffer.write(b'stderr err: ' + b'\\x80\\x81\\x82' + b'\\n')\n"
        ),
    )

    policy = GatePolicy(
        provider="custom",
        command=command,
        timeout_seconds=5,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-binary",
        gate_policy=policy,
        repo_root=repo_dir,
        session_id="sess-binary",
        contract_revision=1,
        snapshot_before=snap_before,
    )

    assert evidence.status == EvidenceStatus.PASSED
    assert evidence.exit_code == 0
    assert "valid prefix:" in evidence.summary
    assert "valid suffix" in evidence.summary
    assert "stderr err:" in evidence.summary
    # Replacement characters should be present without raising UnicodeDecodeError
    assert "\ufffd" in evidence.summary


def test_child_process_modifying_source_files_invalidated(repo_dir: Path):
    """If child process modifies repository files during test, evidence is marked FAILED and stale."""
    snap_before = capture_snapshot(repo_dir)
    dirty_file = repo_dir / "unexpected_output.txt"

    command = (
        sys.executable,
        "-c",
        f"with open('{dirty_file}', 'w') as f: f.write('unauthorized file mutation')\n",
    )

    policy = GatePolicy(
        provider="pytest",
        command=command,
        timeout_seconds=5,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-dirty",
        gate_policy=policy,
        repo_root=repo_dir,
        session_id="sess-dirty",
        contract_revision=1,
        snapshot_before=snap_before,
    )

    # Process exit code was 0, but evidence must NOT be passing
    assert evidence.exit_code == 0
    assert evidence.status == EvidenceStatus.FAILED
    assert evidence.invalidation_reason is not None
    assert "Repository state changed during verification" in evidence.invalidation_reason
    assert "[ProofMesh] Repository state changed during verification. Evidence invalidated." in evidence.summary

    # Code state changed after verification; freshness check must return False
    snap_after = capture_snapshot(repo_dir)
    assert snap_before.snapshot_id != snap_after.snapshot_id
    assert check_evidence_freshness(evidence, snap_before) is False
    assert check_evidence_freshness(evidence, snap_after) is False


def test_strict_sha256_digest_enforcement_without_fallback(repo_dir: Path):
    """EvidenceRecord strictly requires valid sha256: digests without prefix trimming fallback."""
    snap_before = capture_snapshot(repo_dir)

    policy = GatePolicy(
        provider="pytest",
        command=(sys.executable, "-c", "print('clean run')"),
        timeout_seconds=5,
        mandatory=True,
    )

    evidence = run_gate(
        gate_id="gate-clean",
        gate_policy=policy,
        repo_root=repo_dir,
        session_id="sess-clean",
        contract_revision=1,
        snapshot_before=snap_before,
    )

    assert evidence.snapshot_before.startswith("sha256:")
    assert len(evidence.snapshot_before) == 71
    assert evidence.snapshot_after.startswith("sha256:")
    assert len(evidence.snapshot_after) == 71
    assert evidence.config_digest.startswith("sha256:")
    assert len(evidence.config_digest) == 71
    assert evidence.config_digest == compute_gate_digest(policy)
    assert evidence.invalidation_reason is None
    assert check_evidence_freshness(evidence, snap_before) is True
