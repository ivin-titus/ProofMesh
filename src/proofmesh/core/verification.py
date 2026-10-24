"""ProofMesh verification runner and evidence freshness checker.

Implements safe, allowlisted gate execution with bounded outputs, deterministic
timestamps and digests, and code-state freshness tracking (TRD §5.4, §8, §9).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from typing import Callable, Sequence
import uuid

from proofmesh.models import (
    EvidenceRecord,
    EvidenceStatus,
    FileFingerprint,
    GatePolicy,
    RepoSnapshot,
    Sha256Digest,
)

# Attempt to import capture_snapshot from repo_snapshot module (owned by Agent B);
# fall back to deterministic local implementation if not yet available in worktree.
try:
    from proofmesh.core.repo_snapshot import capture_snapshot
except ImportError:
    def capture_snapshot(
        repo_root: Path | str,
        exclude_patterns: Sequence[str] | None = None,
    ) -> RepoSnapshot:
        """Deterministic fallback snapshot capture when repo_snapshot module is absent."""
        root_path = Path(repo_root).resolve()
        patterns = tuple(exclude_patterns) if exclude_patterns is not None else (
            ".git/**",
            "__pycache__/**",
            "*.pyc",
            ".pytest_cache/**",
            "dist/**",
            ".venv/**",
            ".venv314/**",
        )

        fingerprints: list[FileFingerprint] = []
        if root_path.is_dir():
            for f in sorted(root_path.rglob("*")):
                if not f.is_file() or f.is_symlink():
                    continue
                rel = f.relative_to(root_path).as_posix()
                excluded = False
                for pat in patterns:
                    norm_pat = pat.rstrip("/")
                    if pat.endswith("/**"):
                        prefix = pat[:-3]
                        if rel == prefix or rel.startswith(prefix + "/"):
                            excluded = True
                            break
                    elif norm_pat in rel.split("/"):
                        excluded = True
                        break
                if excluded:
                    continue

                hasher = hashlib.sha256()
                try:
                    content = f.read_bytes()
                    hasher.update(content)
                    digest = f"sha256:{hasher.hexdigest()}"
                    fingerprints.append(
                        FileFingerprint(
                            path=rel,
                            sha256=digest,
                            size_bytes=len(content),
                            is_tracked=True,
                        )
                    )
                except OSError:
                    continue

        fingerprints_tuple = tuple(sorted(fingerprints, key=lambda x: x.path))
        snap_hasher = hashlib.sha256()
        for fp in fingerprints_tuple:
            snap_hasher.update(f"{fp.path}:{fp.sha256}:{fp.size_bytes}\n".encode("utf-8"))

        snapshot_id = f"sha256:{snap_hasher.hexdigest()}"
        return RepoSnapshot(
            snapshot_id=snapshot_id,
            repo_root=str(root_path),
            git_commit=None,
            git_dirty=False,
            files=fingerprints_tuple,
            captured_at=datetime.now(timezone.utc),
        )


def compute_gate_digest(gate_policy: GatePolicy) -> Sha256Digest:
    """Compute deterministic SHA-256 digest of gate policy configuration."""
    gate_dict = gate_policy.model_dump(mode="json")
    canonical_json = json.dumps(gate_dict, sort_keys=True)
    return f"sha256:{hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()}"


class _BoundedStreamDrainer:
    """Concurrently drains a process pipe up to max_bytes with safe binary/text decoding.
    
    Prevents pipe deadlocks by continuously consuming output while capping peak memory.
    """

    def __init__(self, stream, max_bytes: int = 65536) -> None:
        self.stream = stream
        self.max_bytes = max_bytes
        self.buffer = bytearray()
        self.truncated = False
        self._thread = threading.Thread(target=self._drain, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _drain(self) -> None:
        try:
            chunk_size = 4096
            while True:
                chunk = self.stream.read(chunk_size)
                if not chunk:
                    break
                if len(self.buffer) < self.max_bytes:
                    remaining = self.max_bytes - len(self.buffer)
                    take = min(len(chunk), remaining)
                    self.buffer.extend(chunk[:take])
                    if len(chunk) > take:
                        self.truncated = True
                else:
                    self.truncated = True
        except Exception:
            pass
        finally:
            try:
                self.stream.close()
            except Exception:
                pass

    def join(self, timeout: float = 2.0) -> None:
        self._thread.join(timeout=timeout)

    def get_text(self) -> str:
        text = self.buffer.decode("utf-8", errors="replace")
        if self.truncated:
            text += "\n... [truncated]"
        return text


def _format_summary(
    gate_id: str,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    max_chars: int = 2000,
) -> str:
    """Format a bounded summary (capped to max_chars) combining stdout and stderr excerpts."""
    stdout_clean = stdout.strip()
    stderr_clean = stderr.strip()

    if not stdout_clean and not stderr_clean:
        return f"Gate '{gate_id}' completed with exit code {exit_code}"

    if stdout_clean and not stderr_clean:
        full = f"[stdout]\n{stdout_clean}"
        if len(full) <= max_chars:
            return full
        suffix = "\n... [truncated]"
        return full[: max(10, max_chars - len(suffix))] + suffix

    if stderr_clean and not stdout_clean:
        full = f"[stderr]\n{stderr_clean}"
        if len(full) <= max_chars:
            return full
        suffix = "\n... [truncated]"
        return full[: max(10, max_chars - len(suffix))] + suffix

    # Both stdout and stderr are present
    combined = f"[stdout]\n{stdout_clean}\n\n[stderr]\n{stderr_clean}"
    if len(combined) <= max_chars:
        return combined

    budget_each = (max_chars - 50) // 2
    suffix = "\n... [truncated]"

    out_part = f"[stdout]\n{stdout_clean}"
    if len(out_part) > budget_each:
        out_part = out_part[: max(10, budget_each - len(suffix))] + suffix

    err_part = f"[stderr]\n{stderr_clean}"
    if len(err_part) > budget_each:
        err_part = err_part[: max(10, budget_each - len(suffix))] + suffix

    res = f"{out_part}\n\n{err_part}"
    if len(res) <= max_chars:
        return res
    return res[: max(10, max_chars - len(suffix))] + suffix


def run_gate(
    gate_id: str,
    gate_policy: GatePolicy,
    repo_root: Path | str,
    session_id: str,
    contract_revision: int,
    snapshot_before: RepoSnapshot,
    acceptance_criteria: tuple[str, ...] | Sequence[str] = (),
    *,
    capture_snapshot_fn: Callable[..., RepoSnapshot] | None = None,
    max_capture_bytes: int = 65536,
) -> EvidenceRecord:
    """Execute an allowlisted gate command and return an immutable, validated EvidenceRecord.

    Args:
        gate_id: Registered gate identifier.
        gate_policy: Validated GatePolicy containing fixed command, timeout, and provider.
        repo_root: Repository root path where command executes.
        session_id: Session identifier.
        contract_revision: Active contract revision number.
        snapshot_before: Code snapshot taken before gate run started.
        acceptance_criteria: Acceptance criteria satisfied by this gate.
        capture_snapshot_fn: Optional custom snapshot capture function (used for testing).
        max_capture_bytes: Peak byte buffer limit for stdout and stderr (default 64KB).

    Returns:
        Immutable EvidenceRecord bound to before/after code snapshots and exact exit metrics.
    """
    import shutil
    root_path = Path(repo_root).resolve()
    cmd_list = list(gate_policy.command)
    if cmd_list and cmd_list[0] == "pytest" and shutil.which("pytest") is None:
        cmd_list = [sys.executable, "-m", "pytest", *cmd_list[1:]]
    elif cmd_list and cmd_list[0] in ("python", "python3") and shutil.which(cmd_list[0]) is None:
        cmd_list = [sys.executable, *cmd_list[1:]]
    snap_fn = capture_snapshot_fn if capture_snapshot_fn is not None else capture_snapshot

    # Snapshot immediately before subprocess execution to detect runtime modifications
    try:
        actual_before = snap_fn(root_path)
    except Exception:
        actual_before = None

    started_at = datetime.now(timezone.utc)
    invalidation_reason: str | None = None

    try:
        proc = subprocess.Popen(
            cmd_list,
            shell=False,
            cwd=str(root_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        drain_out = _BoundedStreamDrainer(proc.stdout, max_bytes=max_capture_bytes)
        drain_err = _BoundedStreamDrainer(proc.stderr, max_bytes=max_capture_bytes)
        drain_out.start()
        drain_err.start()

        try:
            proc.wait(timeout=gate_policy.timeout_seconds)
            ended_at = datetime.now(timezone.utc)
            duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
            exit_code = proc.returncode
            drain_out.join()
            drain_err.join()
            stdout_text = drain_out.get_text()
            stderr_text = drain_err.get_text()
            status = EvidenceStatus.PASSED if exit_code == 0 else EvidenceStatus.FAILED
            summary = _format_summary(gate_id, exit_code, stdout_text, stderr_text, max_chars=2000)

        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                pass
            drain_out.join(timeout=1.0)
            drain_err.join(timeout=1.0)
            ended_at = datetime.now(timezone.utc)
            duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
            exit_code = -1
            status = EvidenceStatus.FAILED
            summary = f"Gate '{gate_id}' timed out after {gate_policy.timeout_seconds}s"

    except FileNotFoundError:
        ended_at = datetime.now(timezone.utc)
        duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
        exit_code = -2
        status = EvidenceStatus.FAILED
        cmd0 = gate_policy.command[0] if gate_policy.command else ""
        summary = f"Command '{cmd0}' not found"

    except OSError as exc:
        ended_at = datetime.now(timezone.utc)
        duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
        exit_code = -3
        status = EvidenceStatus.FAILED
        summary = f"Execution error for gate '{gate_id}': {exc}"

    # Capture snapshot after gate execution
    snapshot_after = snap_fn(root_path)

    # Detect if repository state changed during verification run
    repo_changed = False
    if actual_before is not None:
        if actual_before.snapshot_id != snapshot_after.snapshot_id:
            repo_changed = True
    elif snapshot_before.snapshot_id != snapshot_after.snapshot_id:
        repo_changed = True

    if repo_changed:
        invalidation_reason = (
            f"Repository state changed during verification: before={snapshot_before.snapshot_id} "
            f"after={snapshot_after.snapshot_id}"
        )
        if status == EvidenceStatus.PASSED:
            status = EvidenceStatus.FAILED
            warning = "\n\n[ProofMesh] Repository state changed during verification. Evidence invalidated."
            if len(summary) + len(warning) <= 2000:
                summary = summary + warning
            else:
                summary = summary[: 2000 - len(warning)] + warning

    config_digest = compute_gate_digest(gate_policy)
    evidence_id = f"ev-{uuid.uuid4().hex[:12]}"
    criteria_tuple = tuple(acceptance_criteria)

    return EvidenceRecord(
        evidence_id=evidence_id,
        session_id=session_id,
        contract_revision=contract_revision,
        gate_id=gate_id,
        acceptance_criteria=criteria_tuple,
        provider_name=gate_policy.provider,
        provider_version="1.0.0",
        config_digest=config_digest,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        snapshot_before=snapshot_before.snapshot_id,
        snapshot_after=snapshot_after.snapshot_id,
        status=status,
        exit_code=exit_code,
        summary=summary,
        invalidation_reason=invalidation_reason,
    )


def check_evidence_freshness(evidence: EvidenceRecord, current_snapshot: RepoSnapshot) -> bool:
    """Check if evidence is fresh relative to the current repository snapshot.

    Returns True if:
      - Evidence has no invalidation reason.
      - Evidence status is PASSED.
      - Evidence was captured against the identical snapshot as current_snapshot.
    """
    if evidence.invalidation_reason is not None:
        return False
    if evidence.status != EvidenceStatus.PASSED:
        return False
    return evidence.snapshot_after == current_snapshot.snapshot_id
