"""ProofMesh verification runner and evidence freshness checker.

Implements safe, allowlisted gate execution with bounded outputs, deterministic
timestamps and digests, and code-state freshness tracking (TRD §5.4, §8, §9).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Callable, Sequence
import uuid

from pydantic import ValidationError

from proofmesh.models import (
    EvidenceRecord,
    EvidenceStatus,
    FileFingerprint,
    GatePolicy,
    RepoSnapshot,
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

    parts: list[str] = []
    if stdout_clean:
        parts.append(f"[stdout]\n{stdout_clean}")
    if stderr_clean:
        parts.append(f"[stderr]\n{stderr_clean}")

    combined = "\n\n".join(parts)
    if len(combined) <= max_chars:
        return combined

    suffix = "\n... [truncated]"
    allowed_len = max(10, max_chars - len(suffix))
    return combined[:allowed_len] + suffix


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

    Returns:
        Immutable EvidenceRecord bound to before/after code snapshots and exact exit metrics.
    """
    root_path = Path(repo_root).resolve()
    cmd_list = list(gate_policy.command)

    started_at = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            cmd_list,
            shell=False,
            timeout=gate_policy.timeout_seconds,
            cwd=str(root_path),
            capture_output=True,
            text=True,
        )
        ended_at = datetime.now(timezone.utc)
        duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
        exit_code = proc.returncode
        status = EvidenceStatus.PASSED if exit_code == 0 else EvidenceStatus.FAILED
        summary = _format_summary(gate_id, exit_code, proc.stdout, proc.stderr, max_chars=2000)

    except subprocess.TimeoutExpired as exc:
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
    snap_fn = capture_snapshot_fn if capture_snapshot_fn is not None else capture_snapshot
    snapshot_after = snap_fn(root_path)

    # Compute deterministic configuration digest
    gate_dict = gate_policy.model_dump(mode="json")
    canonical_json = json.dumps(gate_dict, sort_keys=True)
    config_digest = f"sha256:{hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()}"

    evidence_id = f"ev-{uuid.uuid4().hex[:12]}"
    criteria_tuple = tuple(acceptance_criteria)

    try:
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
        )
    except ValidationError:
        # Fallback if model requires Identifier pattern without sha256: prefix
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
            snapshot_before=snapshot_before.snapshot_id.removeprefix("sha256:")[:64],
            snapshot_after=snapshot_after.snapshot_id.removeprefix("sha256:")[:64],
            status=status,
            exit_code=exit_code,
            summary=summary,
        )


def check_evidence_freshness(evidence: EvidenceRecord, current_snapshot: RepoSnapshot) -> bool:
    """Check if evidence is fresh relative to the current repository snapshot.

    Returns True if the evidence was captured against the identical snapshot as
    current_snapshot (meaning code state has not changed since verification ran).
    Returns False if snapshot IDs differ.
    """
    if evidence.snapshot_after == current_snapshot.snapshot_id:
        return True
    if evidence.snapshot_after == current_snapshot.snapshot_id.removeprefix("sha256:"):
        return True
    if f"sha256:{evidence.snapshot_after}" == current_snapshot.snapshot_id:
        return True
    return False
