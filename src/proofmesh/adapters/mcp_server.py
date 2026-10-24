"""ProofMesh official Python Model Context Protocol (MCP) server.

Exposes core ProofMesh control-layer tools over the official MCP SDK without
duplicating policy, verification, or evaluation logic in the adapter layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer
    except ImportError:
        from mcp.server import Server as MCPServer  # type: ignore

from proofmesh.config import get_default_policy
from proofmesh.core.evaluator import evaluate_session
from proofmesh.core.handoff import generate_handoff
from proofmesh.core.repo_snapshot import capture_snapshot
from proofmesh.core.scope_analyzer import analyze_scope
from proofmesh.core.task_service import TaskService
from proofmesh.core.verification import run_gate
from proofmesh.models import (
    OperatingProfile,
    Session,
    SessionState,
    TrustedPolicy,
    VerdictOutcome,
)
from proofmesh.storage.paths import get_project_db_path
from proofmesh.storage.store import ProofMeshStore


def _get_active_session_from_store(store: ProofMeshStore) -> Session | None:
    """Query the most recently started session from the database."""
    conn = store.get_connection()
    try:
        row = conn.execute(
            "SELECT session_id FROM sessions ORDER BY started_at DESC LIMIT 1;"
        ).fetchone()
        if row and row["session_id"]:
            return store.get_session(str(row["session_id"]))
        return None
    finally:
        conn.close()


def create_mcp_server(
    store: ProofMeshStore | None = None,
    repo_root: Path | str | None = None,
    session_id: str | None = None,
    policy: TrustedPolicy | None = None,
    name: str = "proofmesh",
) -> MCPServer:
    """Create and configure an official MCP server instance with ProofMesh tools.

    Args:
        store: Persistence store instance. If None, connects to default project db.
        repo_root: Workspace root directory. Defaults to current working directory.
        session_id: Default active session ID to bind. If None, queries latest session.
        policy: Trusted project policy. If None, loads packaged default policy.
        name: Server name identifier for MCP initialization.

    Returns:
        Configured MCPServer instance ready for execution or testing.
    """
    effective_repo_root = Path(repo_root).resolve() if repo_root else Path.cwd()
    effective_policy = policy or get_default_policy()
    effective_store = store or ProofMeshStore(get_project_db_path("default"))
    task_service = TaskService(effective_store)

    server = MCPServer(name)

    def _resolve_session(explicit_id: str | None) -> Session:
        target = explicit_id or session_id
        if target:
            sess = effective_store.get_session(target)
            if sess is not None:
                return sess
            raise ValueError(f"ProofMesh session '{target}' not found in store")
        active = _get_active_session_from_store(effective_store)
        if active is not None:
            return active
        raise ValueError("No active ProofMesh session found in store")

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
            baseline = capture_snapshot(root)
            effective_store.save_snapshot(baseline)

        # Capture and save current snapshot
        current = capture_snapshot(root)
        effective_store.save_snapshot(current)

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

        task_rev = effective_store.get_task_revision(sess.task_id, sess.contract_revision)
        if task_rev is None:
            return {
                "error": f"Task revision not found for {sess.task_id} rev {sess.contract_revision}"
            }

        current = capture_snapshot(root)
        effective_store.save_snapshot(current)

        baseline = effective_store.get_snapshot(sess.baseline_snapshot_id) or current
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

        task_rev = effective_store.get_task_revision(sess.task_id, sess.contract_revision)
        if task_rev is None:
            return {
                "error": f"Task revision not found for {sess.task_id} rev {sess.contract_revision}"
            }

        current = capture_snapshot(root)
        effective_store.save_snapshot(current)

        baseline = effective_store.get_snapshot(sess.baseline_snapshot_id) or current
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

        if verdict.verdict == VerdictOutcome.ALLOW:
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
        return {
            "status": "BLOCKED",
            "verdict": verdict.verdict.value,
            "message": "Completion claim rejected: unresolved blockers or missing verification.",
            "reasons": list(verdict.reasons),
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
        baseline = effective_store.get_snapshot(sess.baseline_snapshot_id) or current
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
) -> None:
    """Launch ProofMesh MCP server on stdio transport."""
    server = create_mcp_server(
        store=store,
        repo_root=repo_root,
        session_id=session_id,
        policy=policy,
    )
    server.run(transport="stdio")
