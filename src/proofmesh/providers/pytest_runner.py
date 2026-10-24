"""Pytest verification provider for ProofMesh.

Constructs allowlisted GatePolicy instances for pytest execution and provides
convenience helpers for running pytest gates (TRD §4, §8).
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Sequence

from proofmesh.core.verification import run_gate
from proofmesh.models import EvidenceRecord, GatePolicy, RepoSnapshot


def build_pytest_gate(
    command_args: Sequence[str] | None = None,
    timeout_seconds: int = 60,
    mandatory: bool = True,
    python_executable: str | None = None,
) -> GatePolicy:
    """Build a validated GatePolicy for executing pytest.

    Uses python -m pytest with strict argument arrays and configurable timeout.
    Never uses shell=True.
    """
    py_exec = python_executable or sys.executable
    if command_args is None:
        cmd = (py_exec, "-m", "pytest", "-q")
    else:
        cmd = (py_exec, "-m", "pytest", *command_args)

    return GatePolicy(
        provider="pytest",
        command=cmd,
        timeout_seconds=timeout_seconds,
        mandatory=mandatory,
    )


def run_pytest(
    repo_root: Path | str,
    session_id: str,
    contract_revision: int,
    snapshot_before: RepoSnapshot,
    gate_id: str = "test",
    acceptance_criteria: tuple[str, ...] = (),
    command_args: Sequence[str] | None = None,
    timeout_seconds: int = 60,
) -> EvidenceRecord:
    """Convenience function to run pytest as a gate and return EvidenceRecord."""
    policy = build_pytest_gate(command_args=command_args, timeout_seconds=timeout_seconds)
    return run_gate(
        gate_id=gate_id,
        gate_policy=policy,
        repo_root=repo_root,
        session_id=session_id,
        contract_revision=contract_revision,
        snapshot_before=snapshot_before,
        acceptance_criteria=acceptance_criteria,
    )
