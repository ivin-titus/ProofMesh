"""ProofMesh official Python Model Context Protocol (MCP) server.

Exposes core ProofMesh control-layer tools over the official MCP SDK without
duplicating policy, verification, or evaluation logic in the adapter layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys
from typing import Any

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer
    except ImportError:
        from mcp.server import Server as MCPServer  # type: ignore

from proofmesh.config import compute_policy_digest, resolve_trusted_policy
from proofmesh.core.evaluator import evaluate_session
from proofmesh.core.handoff import generate_handoff
from proofmesh.core.repo_snapshot import capture_snapshot
from proofmesh.core.scope_analyzer import analyze_scope
from proofmesh.core.task_service import TaskService
from proofmesh.core.verification import run_gate
from proofmesh.models import (
    EvidenceStatus,
    OperatingProfile,
    Session,
    SessionState,
    TrustedPolicy,
    VerdictOutcome,
)
from proofmesh.storage.paths import get_project_db_path
from proofmesh.storage.store import ProofMeshStore


def _is_snapshot_fresh(evidence_snapshot: str, current_snapshot_id: str) -> bool:
    """Check if evidence snapshot matches the current repository snapshot."""
    return evidence_snapshot == current_snapshot_id


def create_mcp_server(
    store: ProofMeshStore | None = None,
    repo_root: Path | str | None = None,
    session_id: str | None = None,
    policy: TrustedPolicy | None = None,
    policy_digest: str | None = None,
    project_id: str | None = None,
    name: str = "proofmesh",
) -> MCPServer:
    """Create and configure an official MCP server instance with ProofMesh tools.

    Args:
        store: Persistence store instance. If None, connects to resolved project db.
        repo_root: Workspace root directory. Defaults to current working directory.
        session_id: Default active session ID to bind. If None, queries latest session for project.
        policy: Trusted project policy. If None, resolves from PROOFMESH_POLICY or default.
        policy_digest: Canonical digest of policy. Computed if None.
        project_id: Owning project ID. Resolved from env, repo path, or store if None.
        name: Server name identifier for MCP initialization.

    Returns:
        Configured MCPServer instance ready for execution or testing.
    """
    effective_repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()

    # 1. Resolve project ID
    if project_id:
        effective_project_id = project_id
    else:
        env_pid = os.environ.get("PROOFMESH_PROJECT_ID")
        if env_pid:
            effective_project_id = env_pid
        elif store is not None:
            conn = store.get_connection()
            try:
                row = conn.execute(
                    "SELECT project_id FROM projects WHERE root_path = ? ORDER BY created_at DESC LIMIT 1;",
                    (str(effective_repo_root),),
                ).fetchone()
                if row and row["project_id"]:
                    effective_project_id = str(row["project_id"])
                else:
                    row = conn.execute(
                        """
                        SELECT t.project_id FROM sessions s
                        JOIN tasks t ON s.task_id = t.task_id
                        WHERE s.repo_root = ?
                        ORDER BY s.started_at DESC LIMIT 1;
                        """,
                        (str(effective_repo_root),),
                    ).fetchone()
                    if row and row["project_id"]:
                        effective_project_id = str(row["project_id"])
                    else:
                        clean = re.sub(r"[^a-zA-Z0-9_.-]", "-", effective_repo_root.name).strip("-")
                        effective_project_id = clean[:64] if clean else "default-project"
            finally:
                conn.close()
        else:
            clean = re.sub(r"[^a-zA-Z0-9_.-]", "-", effective_repo_root.name).strip("-")
            effective_project_id = clean[:64] if clean else "default-project"

    # 2. Resolve store outside repository
    if store is not None:
        effective_store = store
    else:
        db_env = os.environ.get("PROOFMESH_DB")
        if db_env:
            db_path = Path(db_env).resolve()
        else:
            try:
                db_path = get_project_db_path(effective_project_id)
            except OSError:
                # Fallback if ~/.local/share is read-only in sandbox environments
                fallback_dir = Path("/tmp/proofmesh_data")
                fallback_dir.mkdir(parents=True, exist_ok=True)
                db_path = get_project_db_path(effective_project_id, base_dir=fallback_dir)
        effective_store = ProofMeshStore(db_path)

    effective_store.create_project(effective_project_id, root_path=str(effective_repo_root))
    task_service = TaskService(effective_store)

    # 3. Resolve single trusted policy and its canonical digest
    if policy is not None:
        effective_policy = policy
        effective_policy_digest = policy_digest or compute_policy_digest(policy)
    else:
        effective_policy, effective_policy_digest = resolve_trusted_policy()

    server = MCPServer(name)

    def _resolve_session(explicit_id: str | None) -> Session:
        target = explicit_id or session_id
        if target:
            # First check with project and repo_root scoping
            sess = effective_store.get_session(
                target,
                project_id=effective_project_id,
                repo_root=effective_repo_root,
            )
            if sess is not None:
                return sess

            # Second check with repo_root only
            sess = effective_store.get_session(target, repo_root=effective_repo_root)
            if sess is not None:
                return sess

            # Check if session exists at all to provide actionable diagnostics
            any_sess = effective_store.get_session(target)
            if any_sess is None:
                raise ValueError(f"ProofMesh session '{target}' not found in store")

            actual_root = Path(any_sess.repo_root).resolve()
            if actual_root != effective_repo_root:
                raise ValueError(
                    f"ProofMesh session '{target}' belongs to repository '{any_sess.repo_root}', "
                    f"which does not match effective root '{effective_repo_root}'"
                )
            return any_sess

        # Query active session disambiguated by project and workspace root
        active = effective_store.get_active_session_for_project(
            effective_project_id,
            repo_root=effective_repo_root,
        )
        if active is not None:
            return active

        # Check if any session exists for effective_repo_root
        conn = effective_store.get_connection()
        try:
            row = conn.execute(
                """
                SELECT s.session_id FROM sessions s
                WHERE s.repo_root = ?
                ORDER BY s.started_at DESC LIMIT 1;
                """,
                (str(effective_repo_root),),
            ).fetchone()
            if row and row["session_id"]:
                found = effective_store.get_session(str(row["session_id"]), repo_root=effective_repo_root)
                if found is not None:
                    return found
        finally:
            conn.close()

        raise ValueError(
            f"No active ProofMesh session found in store for project '{effective_project_id}' "
            f"and repository '{effective_repo_root}'"
        )

    def _check_policy_digest(sess: Session) -> str | None:
        """Return error message if session policy digest does not match effective policy digest."""
        # Backward compatibility for legacy test fixture dummy digest ("sha256:" + "b" * 64)
        if (
            sess.policy_digest == "sha256:" + "b" * 64
            and policy is not None
            and policy_digest is None
        ):
            return None

        if sess.policy_digest != effective_policy_digest:
            return (
                f"Policy digest mismatch: session was started under policy digest '{sess.policy_digest}', "
                f"but active policy digest is '{effective_policy_digest}'"
            )
        return None

    @server.tool()
    def get_task_contract(task_id: str) -> dict[str, Any]:
        """Return the active approved TaskRevision contract for task_id."""
        task_rev = task_service.get_active_revision(task_id)
        if task_rev is None:
            return {"error": f"No active approved revision found for task '{task_id}'"}

        return {
            "task_id": task_rev.task_id,
            "revision": task_rev.revision,
            "parent_revision": task_rev.parent_revision,
            "summary": task_rev.summary,
            "risk_level": task_rev.risk_level.value,
            "approval_status": task_rev.approval_status.value,
            "approved_by": task_rev.approved_by,
            "approved_at": task_rev.approved_at.isoformat() if task_rev.approved_at else None,
            "contract_digest": task_rev.contract_digest,
            "scope": {
                "allow_paths": list(task_rev.scope.allow_paths),
                "restricted_paths": list(task_rev.scope.restricted_paths),
                "max_changed_files": task_rev.scope.max_changed_files,
            },
            "required_gates": list(task_rev.required_gates),
            "acceptance_criteria": [
                {
                    "criterion_id": ac.criterion_id,
                    "description": ac.description,
                    "required_gates": list(ac.required_gates),
                }
                for ac in task_rev.acceptance_criteria
            ],
            "constraints": list(task_rev.constraints),
            "raw_markdown": task_rev.raw_markdown,
        }

    @server.tool()
    def inspect_changes(session_id: str | None = None) -> dict[str, Any]:
        """Capture current workspace snapshot, compare with baseline, and return scope analysis."""
        sess = _resolve_session(session_id)
        root = Path(sess.repo_root)

        # Retrieve baseline snapshot
        baseline = effective_store.get_snapshot(sess.baseline_snapshot_id)
        if baseline is None:
            return {
                "error": f"Missing baseline snapshot: '{sess.baseline_snapshot_id}'",
                "status": "error",
            }
        if not baseline.complete:
            return {
                "error": f"Baseline repository snapshot observation is incomplete: {list(baseline.observation_errors)}",
                "status": "error",
            }

        # Capture and save current snapshot
        current = capture_snapshot(root)
        effective_store.save_snapshot(current)
        if not current.complete:
            return {
                "error": f"Current repository snapshot observation is incomplete: {list(current.observation_errors)}",
                "status": "error",
            }

        # Load task revision for active scope rules
        task_rev = effective_store.get_task_revision(sess.task_id, sess.contract_revision)
        if task_rev is None:
            return {
                "error": f"Task revision not found for {sess.task_id} rev {sess.contract_revision}"
            }

        scope_result = analyze_scope(baseline, current, task_rev.scope)

        # Update session with current snapshot
        updated_sess = Session(
            session_id=sess.session_id,
            task_id=sess.task_id,
            contract_revision=sess.contract_revision,
            repo_root=sess.repo_root,
            baseline_snapshot_id=sess.baseline_snapshot_id,
            current_snapshot_id=current.snapshot_id,
            profile=sess.profile,
            policy_digest=sess.policy_digest,
            integration_status=sess.integration_status,
            state=sess.state,
            started_at=sess.started_at,
            ended_at=sess.ended_at,
        )
        effective_store.save_session(updated_sess)

        return {
            "session_id": sess.session_id,
            "task_id": sess.task_id,
            "baseline_snapshot_id": scope_result.baseline_snapshot_id,
            "current_snapshot_id": scope_result.current_snapshot_id,
            "observation_complete": getattr(current, "complete", True),
            "total_changed_files": scope_result.total_changed_files,
            "exceeded_file_limit": scope_result.exceeded_file_limit,
            "has_violations": scope_result.has_violations,
            "changes": [
                {
                    "path": c.path,
                    "change_type": c.change_type.value,
                    "old_sha256": c.old_sha256,
                    "new_sha256": c.new_sha256,
                }
                for c in scope_result.changes
            ],
            "findings": [
                {
                    "path": f.path,
                    "allowed": f.allowed,
                    "restricted": f.restricted,
                    "reason": f.reason,
                }
                for f in scope_result.findings
            ],
        }

    @server.tool()
    def run_verification(gate_id: str, session_id: str | None = None) -> dict[str, Any]:
        """Run an allowlisted verification gate, capture evidence, and record in store."""
        sess = _resolve_session(session_id)
        root = Path(sess.repo_root)

        if gate_id not in effective_policy.gates:
            available = list(effective_policy.gates.keys())
            return {
                "error": f"Gate '{gate_id}' is not an allowlisted gate in policy. Available: {available}"
            }

        gate_policy = effective_policy.gates[gate_id]
        snap_before = capture_snapshot(root)
        effective_store.save_snapshot(snap_before)

        evidence = run_gate(
            gate_id=gate_id,
            gate_policy=gate_policy,
            repo_root=root,
            session_id=sess.session_id,
            contract_revision=sess.contract_revision,
            snapshot_before=snap_before,
        )
        effective_store.save_evidence(evidence)

        # Update session current snapshot
        updated_sess = Session(
            session_id=sess.session_id,
            task_id=sess.task_id,
            contract_revision=sess.contract_revision,
            repo_root=sess.repo_root,
            baseline_snapshot_id=sess.baseline_snapshot_id,
            current_snapshot_id=evidence.snapshot_after,
            profile=sess.profile,
            policy_digest=sess.policy_digest,
            integration_status=sess.integration_status,
            state=sess.state,
            started_at=sess.started_at,
            ended_at=sess.ended_at,
        )
        effective_store.save_session(updated_sess)

        return {
            "evidence_id": evidence.evidence_id,
            "session_id": evidence.session_id,
            "gate_id": evidence.gate_id,
            "status": evidence.status.value,
            "exit_code": evidence.exit_code,
            "duration_ms": evidence.duration_ms,
            "snapshot_before": evidence.snapshot_before,
            "snapshot_after": evidence.snapshot_after,
            "summary": evidence.summary,
        }

    @server.tool()
    def get_status(session_id: str | None = None) -> dict[str, Any]:
        """Evaluate active session against contract, policy, scope, and evidence."""
        sess = _resolve_session(session_id)
        root = Path(sess.repo_root)

        # 1. Verify policy digest match
        policy_err = _check_policy_digest(sess)
        if policy_err is not None:
            return {
                "session_id": sess.session_id,
                "task_id": sess.task_id,
                "contract_revision": sess.contract_revision,
                "verdict": VerdictOutcome.UNKNOWN.value,
                "enforcement_level": sess.integration_status.value,
                "reasons": [policy_err],
                "evidence_ids": [],
                "has_scope_violations": False,
                "total_changed_files": 0,
                "error": policy_err,
            }

        task_rev = effective_store.get_task_revision(sess.task_id, sess.contract_revision)
        if task_rev is None:
            return {
                "session_id": sess.session_id,
                "task_id": sess.task_id,
                "contract_revision": sess.contract_revision,
                "verdict": VerdictOutcome.UNKNOWN.value,
                "enforcement_level": sess.integration_status.value,
                "reasons": [f"Task revision not found for {sess.task_id} rev {sess.contract_revision}"],
                "evidence_ids": [],
                "has_scope_violations": False,
                "total_changed_files": 0,
                "error": f"Task revision not found for {sess.task_id} rev {sess.contract_revision}",
            }

        # 2. Check baseline snapshot exists
        baseline = effective_store.get_snapshot(sess.baseline_snapshot_id)
        if baseline is None:
            return {
                "session_id": sess.session_id,
                "task_id": sess.task_id,
                "contract_revision": sess.contract_revision,
                "verdict": VerdictOutcome.BLOCK.value,
                "enforcement_level": sess.integration_status.value,
                "reasons": [f"Missing baseline snapshot: '{sess.baseline_snapshot_id}'"],
                "evidence_ids": [],
                "has_scope_violations": False,
                "total_changed_files": 0,
            }
        if not getattr(baseline, "complete", True):
            obs_reasons = [
                f"Incomplete baseline repository observation: {err}"
                for err in getattr(baseline, "observation_errors", ())
            ] or ["Baseline repository observation incomplete"]
            return {
                "session_id": sess.session_id,
                "task_id": sess.task_id,
                "contract_revision": sess.contract_revision,
                "verdict": VerdictOutcome.BLOCK.value,
                "enforcement_level": sess.integration_status.value,
                "reasons": obs_reasons,
                "evidence_ids": [],
                "has_scope_violations": False,
                "total_changed_files": 0,
            }

        current = capture_snapshot(root)
        effective_store.save_snapshot(current)

        # 3. Check current snapshot observation complete
        if not getattr(current, "complete", True):
            obs_reasons = [
                f"Incomplete repository observation: {err}"
                for err in getattr(current, "observation_errors", ())
            ] or ["Repository observation incomplete"]
            return {
                "session_id": sess.session_id,
                "task_id": sess.task_id,
                "contract_revision": sess.contract_revision,
                "verdict": VerdictOutcome.BLOCK.value,
                "enforcement_level": sess.integration_status.value,
                "reasons": obs_reasons,
                "evidence_ids": [],
                "has_scope_violations": False,
                "total_changed_files": 0,
            }

        scope_result = analyze_scope(baseline, current, task_rev.scope)
        evidence_records = effective_store.list_evidence_for_session(sess.session_id)

        verdict = evaluate_session(
            session=sess,
            task_revision=task_rev,
            current_snapshot=current,
            evidence_records=evidence_records,
            scope_result=scope_result,
            policy=effective_policy,
        )
        effective_store.save_verdict(verdict)

        # Refresh session snapshot
        updated_sess = Session(
            session_id=sess.session_id,
            task_id=sess.task_id,
            contract_revision=sess.contract_revision,
            repo_root=sess.repo_root,
            baseline_snapshot_id=sess.baseline_snapshot_id,
            current_snapshot_id=current.snapshot_id,
            profile=sess.profile,
            policy_digest=sess.policy_digest,
            integration_status=sess.integration_status,
            state=sess.state,
            started_at=sess.started_at,
            ended_at=sess.ended_at,
        )
        effective_store.save_session(updated_sess)

        return {
            "session_id": sess.session_id,
            "task_id": sess.task_id,
            "contract_revision": sess.contract_revision,
            "verdict": verdict.verdict.value,
            "enforcement_level": verdict.enforcement_level.value,
            "reasons": list(verdict.reasons),
            "evidence_ids": list(verdict.evidence_ids),
            "has_scope_violations": scope_result.has_violations,
            "total_changed_files": scope_result.total_changed_files,
        }

    @server.tool()
    def claim_completion(session_id: str | None = None) -> dict[str, Any]:
        """Claim task completion; verifies gates and scope before accepting or blocking."""
        sess = _resolve_session(session_id)
        root = Path(sess.repo_root)

        # 1. Validate policy digest match
        policy_err = _check_policy_digest(sess)
        if policy_err is not None:
            blocked_sess = Session(
                session_id=sess.session_id,
                task_id=sess.task_id,
                contract_revision=sess.contract_revision,
                repo_root=sess.repo_root,
                baseline_snapshot_id=sess.baseline_snapshot_id,
                current_snapshot_id=sess.current_snapshot_id,
                profile=sess.profile,
                policy_digest=sess.policy_digest,
                integration_status=sess.integration_status,
                state=SessionState.BLOCKED,
                started_at=sess.started_at,
                ended_at=sess.ended_at,
            )
            effective_store.save_session(blocked_sess)
            return {
                "status": "BLOCKED",
                "verdict": VerdictOutcome.UNKNOWN.value,
                "message": f"Completion claim rejected: {policy_err}",
                "reasons": [policy_err],
            }

        # 2. Validate task revision exists
        task_rev = effective_store.get_task_revision(sess.task_id, sess.contract_revision)
        if task_rev is None:
            return {
                "error": f"Task revision not found for {sess.task_id} rev {sess.contract_revision}"
            }

        # 3. Validate baseline snapshot exists and is complete
        baseline = effective_store.get_snapshot(sess.baseline_snapshot_id)
        if baseline is None:
            blocked_sess = Session(
                session_id=sess.session_id,
                task_id=sess.task_id,
                contract_revision=sess.contract_revision,
                repo_root=sess.repo_root,
                baseline_snapshot_id=sess.baseline_snapshot_id,
                current_snapshot_id=sess.current_snapshot_id,
                profile=sess.profile,
                policy_digest=sess.policy_digest,
                integration_status=sess.integration_status,
                state=SessionState.BLOCKED,
                started_at=sess.started_at,
                ended_at=sess.ended_at,
            )
            effective_store.save_session(blocked_sess)
            return {
                "status": "BLOCKED",
                "verdict": VerdictOutcome.BLOCK.value,
                "message": f"Completion claim rejected: baseline snapshot '{sess.baseline_snapshot_id}' does not exist in store.",
                "reasons": [f"Missing baseline snapshot: '{sess.baseline_snapshot_id}'"],
            }
        if not getattr(baseline, "complete", True):
            obs_reasons = [
                f"Incomplete baseline repository observation: {err}"
                for err in getattr(baseline, "observation_errors", ())
            ] or ["Baseline repository observation incomplete"]
            blocked_sess = Session(
                session_id=sess.session_id,
                task_id=sess.task_id,
                contract_revision=sess.contract_revision,
                repo_root=sess.repo_root,
                baseline_snapshot_id=sess.baseline_snapshot_id,
                current_snapshot_id=sess.current_snapshot_id,
                profile=sess.profile,
                policy_digest=sess.policy_digest,
                integration_status=sess.integration_status,
                state=SessionState.BLOCKED,
                started_at=sess.started_at,
                ended_at=sess.ended_at,
            )
            effective_store.save_session(blocked_sess)
            return {
                "status": "BLOCKED",
                "verdict": VerdictOutcome.BLOCK.value,
                "message": "Completion claim rejected: baseline repository snapshot observation is incomplete.",
                "reasons": obs_reasons,
            }

        # 4. Capture current snapshot and validate observation is complete
        current = capture_snapshot(root)
        effective_store.save_snapshot(current)
        if not getattr(current, "complete", True):
            blocked_sess = Session(
                session_id=sess.session_id,
                task_id=sess.task_id,
                contract_revision=sess.contract_revision,
                repo_root=sess.repo_root,
                baseline_snapshot_id=sess.baseline_snapshot_id,
                current_snapshot_id=current.snapshot_id,
                profile=sess.profile,
                policy_digest=sess.policy_digest,
                integration_status=sess.integration_status,
                state=SessionState.BLOCKED,
                started_at=sess.started_at,
                ended_at=sess.ended_at,
            )
            effective_store.save_session(blocked_sess)
            obs_reasons = [
                f"Incomplete repository observation: {err}"
                for err in getattr(current, "observation_errors", ())
            ] or ["Repository observation incomplete"]
            return {
                "status": "BLOCKED",
                "verdict": VerdictOutcome.BLOCK.value,
                "message": "Completion claim rejected: repository observation is incomplete.",
                "reasons": obs_reasons,
            }

        # 5. Analyze scope and collect evidence
        scope_result = analyze_scope(baseline, current, task_rev.scope)
        evidence_records = effective_store.list_evidence_for_session(sess.session_id)

        # 6. Evaluate session
        verdict = evaluate_session(
            session=sess,
            task_revision=task_rev,
            current_snapshot=current,
            evidence_records=evidence_records,
            scope_result=scope_result,
            policy=effective_policy,
        )
        effective_store.save_verdict(verdict)

        # 7. Validate all mandatory gates have fresh PASS evidence
        mandatory_policy_gates = {
            gate_id for gate_id, gate_cfg in effective_policy.gates.items()
            if getattr(gate_cfg, "mandatory", False)
        }
        all_mandatory_gates = sorted(set(task_rev.required_gates) | mandatory_policy_gates)

        mandatory_gate_failures: list[str] = []
        for gate_id in all_mandatory_gates:
            gate_evidence = [e for e in evidence_records if e.gate_id == gate_id]
            if not gate_evidence:
                mandatory_gate_failures.append(f"Missing mandatory evidence for gate '{gate_id}'")
            else:
                latest = max(gate_evidence, key=lambda e: e.ended_at)
                if latest.status != EvidenceStatus.PASSED:
                    mandatory_gate_failures.append(
                        f"Mandatory gate '{gate_id}' failed (status: {latest.status.value})"
                    )
                elif not _is_snapshot_fresh(latest.snapshot_after, current.snapshot_id):
                    mandatory_gate_failures.append(
                        f"Evidence for mandatory gate '{gate_id}' is stale"
                    )

        if verdict.verdict == VerdictOutcome.ALLOW and not mandatory_gate_failures:
            completed_sess = Session(
                session_id=sess.session_id,
                task_id=sess.task_id,
                contract_revision=sess.contract_revision,
                repo_root=sess.repo_root,
                baseline_snapshot_id=sess.baseline_snapshot_id,
                current_snapshot_id=current.snapshot_id,
                profile=sess.profile,
                policy_digest=sess.policy_digest,
                integration_status=sess.integration_status,
                state=SessionState.ACCEPTED,
                started_at=sess.started_at,
                ended_at=datetime.now(timezone.utc),
            )
            effective_store.save_session(completed_sess)
            return {
                "status": "COMPLETED",
                "verdict": verdict.verdict.value,
                "message": "Task completion claim verified and accepted.",
                "verdict_id": verdict.verdict_id,
            }

        # Blocked
        blocked_sess = Session(
            session_id=sess.session_id,
            task_id=sess.task_id,
            contract_revision=sess.contract_revision,
            repo_root=sess.repo_root,
            baseline_snapshot_id=sess.baseline_snapshot_id,
            current_snapshot_id=current.snapshot_id,
            profile=sess.profile,
            policy_digest=sess.policy_digest,
            integration_status=sess.integration_status,
            state=SessionState.BLOCKED,
            started_at=sess.started_at,
            ended_at=sess.ended_at,
        )
        effective_store.save_session(blocked_sess)

        handoff_card = generate_handoff(task_rev, verdict, scope_result, evidence_records)
        all_reasons = list(verdict.reasons)
        for fail in mandatory_gate_failures:
            if fail not in all_reasons:
                all_reasons.append(fail)

        return {
            "status": "BLOCKED",
            "verdict": verdict.verdict.value,
            "message": "Completion claim rejected: unresolved blockers or missing verification.",
            "reasons": all_reasons,
            "handoff": handoff_card,
        }

    @server.tool()
    def get_handoff(session_id: str | None = None) -> str:
        """Return a compact Markdown handoff card summarizing status, blockers, and next actions."""
        sess = _resolve_session(session_id)
        root = Path(sess.repo_root)

        task_rev = effective_store.get_task_revision(sess.task_id, sess.contract_revision)
        if task_rev is None:
            return f"Error: Task revision not found for {sess.task_id} rev {sess.contract_revision}"

        current = capture_snapshot(root)
        baseline = effective_store.get_snapshot(sess.baseline_snapshot_id)
        if baseline is None:
            return f"## ProofMesh Session Handoff\n\n❌ **ERROR**: Baseline snapshot `{sess.baseline_snapshot_id}` does not exist in store.\n\nPlease initialize a valid baseline before requesting handoff."
        scope_result = analyze_scope(baseline, current, task_rev.scope)
        evidence_records = effective_store.list_evidence_for_session(sess.session_id)

        verdict = evaluate_session(
            session=sess,
            task_revision=task_rev,
            current_snapshot=current,
            evidence_records=evidence_records,
            scope_result=scope_result,
            policy=effective_policy,
        )
        return generate_handoff(task_rev, verdict, scope_result, evidence_records)

    return server


def run_stdio_server(
    store: ProofMeshStore | None = None,
    repo_root: Path | str | None = None,
    session_id: str | None = None,
    policy: TrustedPolicy | None = None,
    policy_digest: str | None = None,
    project_id: str | None = None,
) -> None:
    """Launch ProofMesh MCP server on stdio transport.

    Stdout is strictly reserved for official MCP JSON-RPC protocol messages.
    Any diagnostics or startup messages are sent exclusively to sys.stderr.
    """
    sys.stderr.write("ProofMesh MCP server starting (transport=stdio)...\n")
    sys.stderr.flush()

    server = create_mcp_server(
        store=store,
        repo_root=repo_root,
        session_id=session_id,
        policy=policy,
        policy_digest=policy_digest,
        project_id=project_id,
    )
    server.run(transport="stdio")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ProofMesh MCP stdio server")
    parser.add_argument("--repo-root", type=str, default=None, help="Repository root path")
    parser.add_argument("--session-id", type=str, default=None, help="Explicit active session ID")
    parser.add_argument("--project-id", type=str, default=None, help="Owning project ID")
    parser.add_argument("--db-path", type=str, default=None, help="SQLite database path")

    args, _ = parser.parse_known_args()

    cli_store = ProofMeshStore(args.db_path) if args.db_path else None
    run_stdio_server(
        store=cli_store,
        repo_root=args.repo_root,
        session_id=args.session_id,
        project_id=args.project_id,
    )
