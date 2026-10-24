"""ProofMesh Command-Line Interface.

Thin CLI delegating directly to core services (TaskService, snapshot,
verification, evaluator, report, demo) per TRD §15.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Sequence
import uuid

from proofmesh.config import get_default_policy, load_policy_file
from proofmesh.core.evaluator import evaluate_session
from proofmesh.core.handoff import generate_handoff
from proofmesh.core.repo_snapshot import capture_snapshot
from proofmesh.core.scope_analyzer import analyze_scope
from proofmesh.core.task_service import TaskService
from proofmesh.core.taskfile_md import parse_taskfile
from proofmesh.core.verification import run_gate
from proofmesh.demo import run_seeded_demo
from proofmesh.models import (
    ApprovalStatus,
    EvidenceStatus,
    GatePolicy,
    IntegrationStatus,
    OperatingProfile,
    Session,
    SessionState,
    TrustedPolicy,
    VerdictOutcome,
)
from proofmesh.report import export_json_receipt, render_markdown_report
from proofmesh.storage.paths import get_project_db_path
from proofmesh.storage.store import ProofMeshStore


def _resolve_project(base_path: Path | None = None) -> tuple[str, Path, ProofMeshStore]:
    """Resolve project ID, root directory, and initialize ProofMeshStore outside the repo."""
    root_dir = (base_path or Path.cwd()).resolve()

    # Determine project ID
    proj_id = os.environ.get("PROOFMESH_PROJECT_ID")
    if not proj_id:
        raw_name = root_dir.name
        # Sanitize to pattern ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$
        clean = re.sub(r"[^a-zA-Z0-9_.-]", "-", raw_name).strip("-")
        proj_id = clean[:64] if clean else "default-project"

    # Determine db path outside repository
    db_env = os.environ.get("PROOFMESH_DB")
    if db_env:
        db_path = Path(db_env).resolve()
    else:
        db_path = get_project_db_path(proj_id)

    store = ProofMeshStore(db_path)
    store.create_project(proj_id, root_path=str(root_dir))
    return proj_id, root_dir, store


def _resolve_session(store: ProofMeshStore, session_id: str | None = None) -> Session | None:
    """Retrieve requested session or the latest session from store."""
    if session_id:
        return store.get_session(session_id)
    conn = store.get_connection()
    try:
        row = conn.execute(
            "SELECT session_id FROM sessions ORDER BY started_at DESC LIMIT 1;"
        ).fetchone()
        if row:
            return store.get_session(row["session_id"])
        return None
    finally:
        conn.close()


def _get_or_create_active_session(
    store: ProofMeshStore, project_id: str, repo_root: Path
) -> Session:
    """Get the active session, or auto-create one if an approved task revision exists."""
    existing = _resolve_session(store)
    if existing is not None and existing.state == SessionState.ACTIVE:
        return existing

    conn = store.get_connection()
    try:
        row = conn.execute(
            """
            SELECT tr.task_id, tr.revision
            FROM task_revisions tr
            JOIN tasks t ON tr.task_id = t.task_id
            WHERE t.project_id = ? AND tr.approval_status = 'approved'
            ORDER BY tr.revision DESC LIMIT 1;
            """,
            (project_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise ValueError(
            f"No approved task revision found for project '{project_id}'. "
            "Propose and approve a task contract first."
        )

    task_id = row["task_id"]
    revision_num = row["revision"]

    baseline = capture_snapshot(repo_root)
    store.save_snapshot(baseline)

    session_id = f"sess-{uuid.uuid4().hex[:10]}"
    session = Session(
        session_id=session_id,
        task_id=task_id,
        contract_revision=revision_num,
        repo_root=str(repo_root),
        baseline_snapshot_id=baseline.snapshot_id,
        current_snapshot_id=baseline.snapshot_id,
        profile=OperatingProfile.FLOW,
        policy_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    store.save_session(session)
    return session


def _resolve_policy(
    repo_root: Path, task_revision: TaskRevision | None = None
) -> TrustedPolicy:
    """Load policy from repo if present, otherwise use packaged default policy."""
    policy_file = repo_root / "policy.toml"
    if policy_file.is_file():
        base_policy = load_policy_file(policy_file)
    else:
        base_policy = get_default_policy()

    gates = dict(base_policy.gates)

    # Ensure python test runners use sys.executable
    if "pytest" not in gates:
        gates["pytest"] = GatePolicy(
            provider="pytest",
            command=(sys.executable, "-m", "pytest", "-q"),
            timeout_seconds=60,
            mandatory=True,
        )

    if "test" in gates and gates["test"].command == ("pytest",):
        gates["test"] = gates["test"].model_copy(
            update={"command": (sys.executable, "-m", "pytest", "-q")}
        )

    # If task specifically specifies required_gates with 'pytest' and not 'test',
    # don't let default policy's 'test' gate block the evaluation.
    if (
        task_revision is not None
        and "pytest" in task_revision.required_gates
        and "test" not in task_revision.required_gates
        and "test" in gates
    ):
        gates["test"] = gates["test"].model_copy(update={"mandatory": False})

    return base_policy.model_copy(update={"gates": gates})


# -----------------------------------------------------------------------------
# Command Handlers
# -----------------------------------------------------------------------------

def cmd_demo(args: argparse.Namespace) -> int:
    """Execute seeded end-to-end demo."""
    target_dir = Path(args.dir).resolve() if args.dir else Path.cwd() / "demo_target"
    print(f"Running ProofMesh seeded demo in: {target_dir}")
    result = run_seeded_demo(target_dir=target_dir, log_fn=print)
    print("\n✅ Seeded demo completed successfully.")
    print(f"Artifacts exported to:")
    print(f"  Markdown report: {target_dir / 'report.md'}")
    print(f"  JSON receipt:    {target_dir / 'report.json'}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize ProofMesh outside the repository for the given project path."""
    target_path = Path(args.path).resolve()
    if not target_path.exists():
        print(f"Error: Path does not exist: {target_path}", file=sys.stderr)
        return 2

    project_id, root_dir, store = _resolve_project(target_path)
    print(f"Initialized ProofMesh for project '{project_id}'")
    print(f"  Repository root: {root_dir}")
    print(f"  Database path:   {store.db_path}")
    return 0


def cmd_task_propose(args: argparse.Namespace) -> int:
    """Propose a new TaskFile revision."""
    task_file = Path(args.file).resolve()
    if not task_file.is_file():
        print(f"Error: TaskFile not found: {task_file}", file=sys.stderr)
        return 2

    content = task_file.read_text(encoding="utf-8")
    project_id, _, store = _resolve_project()

    try:
        parsed = parse_taskfile(content)
        task_service = TaskService(store)
        rev = task_service.propose_task(
            task_id=parsed.task_id,
            content=content,
            project_id=project_id,
        )
        print(f"Task proposed: {rev.task_id} (revision {rev.revision})")
        print(f"  Summary:         {rev.summary}")
        print(f"  Risk level:      {rev.risk_level.value}")
        print(f"  Contract digest: {rev.contract_digest}")
        print(f"  Approval status: {rev.approval_status.value}")
        return 0
    except Exception as e:
        print(f"Error proposing task: {e}", file=sys.stderr)
        return 2


def cmd_task_approve(args: argparse.Namespace) -> int:
    """Approve a proposed TaskFile revision."""
    project_id, _, store = _resolve_project()
    task_service = TaskService(store)

    try:
        approved = task_service.approve_task(
            task_id=args.task_id,
            revision=args.revision,
            approved_by=args.by,
            reason=args.reason,
            project_id=project_id,
        )
        approved_time = approved.approved_at.isoformat() if approved.approved_at else "now"
        print(f"Task approved: {approved.task_id} rev {approved.revision} by {approved.approved_by}")
        print(f"  Approved at: {approved_time}")
        print(f"  Status:      {approved.approval_status.value}")
        return 0
    except Exception as e:
        print(f"Error approving task: {e}", file=sys.stderr)
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    """Display active session status, latest snapshot, and verdicts."""
    project_id, root_dir, store = _resolve_project()
    session = _resolve_session(store, args.session_id)

    if session is None:
        print(f"Project '{project_id}' has no active or recorded sessions.")
        print(f"Repository: {root_dir}")
        print(f"Database:   {store.db_path}")
        return 0

    evidence_records = store.list_evidence_for_session(session.session_id)
    verdicts = store.list_verdicts_for_session(session.session_id)
    latest_verdict = verdicts[-1] if verdicts else None

    print(f"Session Status: {session.session_id}")
    print(f"  Project ID:           {project_id}")
    print(f"  Task ID:              {session.task_id} (rev {session.contract_revision})")
    print(f"  State:                {session.state.value}")
    print(f"  Integration Status:   {session.integration_status.value}")
    print(f"  Baseline Snapshot:    {session.baseline_snapshot_id[:24]}...")
    curr_snap = session.current_snapshot_id[:24] + "..." if session.current_snapshot_id else "None"
    print(f"  Current Snapshot:     {curr_snap}")
    print(f"  Evidence Records:     {len(evidence_records)}")
    if latest_verdict:
        badge = "ALLOW" if latest_verdict.verdict == VerdictOutcome.ALLOW else latest_verdict.verdict.value.upper()
        print(f"  Latest Verdict:       {badge} ({latest_verdict.enforcement_level.value})")
    else:
        print("  Latest Verdict:       (None evaluated yet)")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Execute an allowlisted verification gate."""
    project_id, root_dir, store = _resolve_project()

    try:
        session = _get_or_create_active_session(store, project_id, root_dir)
    except Exception as e:
        print(f"Error resolving active session: {e}", file=sys.stderr)
        return 2

    task_revision = store.get_task_revision(session.task_id, session.contract_revision)
    policy = _resolve_policy(root_dir, task_revision)
    gate_id = args.gate_id
    gate_policy = policy.gates.get(gate_id)

    if gate_policy is None:
        print(
            f"Error: Gate '{gate_id}' is not defined in trusted policy.",
            file=sys.stderr,
        )
        return 2

    snapshot_before = capture_snapshot(root_dir)
    try:
        evidence = run_gate(
            gate_id=gate_id,
            gate_policy=gate_policy,
            repo_root=root_dir,
            session_id=session.session_id,
            contract_revision=session.contract_revision,
            snapshot_before=snapshot_before,
        )
        store.save_evidence(evidence)

        # Update session with new snapshot after gate run
        session = session.model_copy(update={"current_snapshot_id": evidence.snapshot_after})
        store.save_session(session)

        status_str = "PASSED" if evidence.status == EvidenceStatus.PASSED else evidence.status.value.upper()
        print(f"Gate '{gate_id}': {status_str} (exit code: {evidence.exit_code}, {evidence.duration_ms}ms)")
        if evidence.summary:
            clean_summary = evidence.summary.strip()
            if clean_summary:
                print(f"Summary:\n{clean_summary}")

        return 0 if evidence.status == EvidenceStatus.PASSED else 1
    except Exception as e:
        print(f"Error executing gate '{gate_id}': {e}", file=sys.stderr)
        return 1


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Evaluate active session against scope, evidence, and policy."""
    project_id, root_dir, store = _resolve_project()

    session = _resolve_session(store)
    if session is None:
        print("Error: No active session to evaluate.", file=sys.stderr)
        return 2

    task_revision = store.get_task_revision(session.task_id, session.contract_revision)
    if task_revision is None:
        print(f"Error: TaskRevision {session.task_id} rev {session.contract_revision} not found.", file=sys.stderr)
        return 2

    baseline_snapshot = store.get_snapshot(session.baseline_snapshot_id)
    if baseline_snapshot is None:
        print(f"Error: Baseline snapshot {session.baseline_snapshot_id} not found.", file=sys.stderr)
        return 2

    current_snapshot = capture_snapshot(root_dir)
    store.save_snapshot(current_snapshot)

    session = session.model_copy(update={"current_snapshot_id": current_snapshot.snapshot_id})
    store.save_session(session)

    scope_result = analyze_scope(baseline_snapshot, current_snapshot, task_revision.scope)
    evidence_records = store.list_evidence_for_session(session.session_id)
    policy = _resolve_policy(root_dir, task_revision)

    verdict = evaluate_session(
        session=session,
        task_revision=task_revision,
        current_snapshot=current_snapshot,
        evidence_records=evidence_records,
        scope_result=scope_result,
        policy=policy,
    )
    store.save_verdict(verdict)

    if verdict.verdict == VerdictOutcome.ALLOW:
        print(f"✅ VERDICT: ALLOW (Enforcement: {verdict.enforcement_level.value})")
        for reason in verdict.reasons:
            print(f"  - {reason}")
        return 0
    else:
        print(f"❌ VERDICT: {verdict.verdict.value.upper()} (Enforcement: {verdict.enforcement_level.value})")
        for reason in verdict.reasons:
            print(f"  - {reason}")
        handoff = generate_handoff(task_revision, verdict, scope_result, evidence_records)
        print("\n" + handoff)
        return 1


def cmd_report(args: argparse.Namespace) -> int:
    """Render Markdown verification report or export canonical JSON receipt."""
    project_id, root_dir, store = _resolve_project()
    session = _resolve_session(store, args.session_id)

    if session is None:
        print("Error: No session found to report.", file=sys.stderr)
        return 2

    task_revision = store.get_task_revision(session.task_id, session.contract_revision)
    if task_revision is None:
        print("Error: Associated task revision not found.", file=sys.stderr)
        return 2

    baseline_snapshot = store.get_snapshot(session.baseline_snapshot_id)
    current_snapshot = store.get_snapshot(
        session.current_snapshot_id or session.baseline_snapshot_id
    )
    if baseline_snapshot is None or current_snapshot is None:
        print("Error: Snapshot records not found.", file=sys.stderr)
        return 2

    scope_result = analyze_scope(baseline_snapshot, current_snapshot, task_revision.scope)
    evidence_records = store.list_evidence_for_session(session.session_id)
    verdicts = store.list_verdicts_for_session(session.session_id)

    if verdicts:
        verdict = verdicts[-1]
    else:
        policy = _resolve_policy(root_dir, task_revision)
        verdict = evaluate_session(
            session=session,
            task_revision=task_revision,
            current_snapshot=current_snapshot,
            evidence_records=evidence_records,
            scope_result=scope_result,
            policy=policy,
        )
        store.save_verdict(verdict)

    if getattr(args, "json", False):
        receipt = export_json_receipt(
            session=session,
            task=task_revision,
            snapshot=current_snapshot,
            scope_result=scope_result,
            evidence=evidence_records,
            verdict=verdict,
        )
        print(json.dumps(receipt, indent=2))
    else:
        report_md = render_markdown_report(
            session=session,
            task=task_revision,
            snapshot=current_snapshot,
            scope_result=scope_result,
            evidence=evidence_records,
            verdict=verdict,
        )
        print(report_md)

    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    """Start the read-only local web status dashboard."""
    from proofmesh.ui import create_ui_server

    project_id, root_dir, store = _resolve_project()
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8765)
    session_id = getattr(args, "session_id", None)

    try:
        server = create_ui_server(
            store=store,
            session_id=session_id,
            repo_root=root_dir,
            host=host,
            port=port,
        )
    except Exception as e:
        print(f"Error initializing ProofMesh UI: {e}", file=sys.stderr)
        return 1

    print(f"ProofMesh UI running at http://{host}:{port}/ (Press Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ProofMesh UI.")
    finally:
        server.server_close()

    return 0


# -----------------------------------------------------------------------------
# Parser & Main
# -----------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="proofmesh",
        description="ProofMesh: Intent, intervention, and evidence control layer for coding agents.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # demo
    demo_p = subparsers.add_parser("demo", help="Run the deterministic seeded end-to-end demo")
    demo_p.add_argument("--dir", default=None, help="Target repository directory for demo")

    # init
    init_p = subparsers.add_parser("init", help="Initialize ProofMesh for a project directory")
    init_p.add_argument(
        "--path", default=".", help="Project root directory (default: current directory)"
    )

    # task
    task_p = subparsers.add_parser("task", help="Manage TaskFile contracts")
    task_sub = task_p.add_subparsers(dest="task_command", required=True)

    propose_p = task_sub.add_parser("propose", help="Propose a new TaskFile contract")
    propose_p.add_argument("file", help="Path to TaskFile Markdown file")

    approve_p = task_sub.add_parser("approve", help="Approve a proposed TaskFile revision")
    approve_p.add_argument("task_id", help="Task identifier")
    approve_p.add_argument("revision", type=int, help="Revision number to approve")
    approve_p.add_argument("--by", required=True, help="Identity of authorized approver")
    approve_p.add_argument("--reason", default=None, help="Optional approval justification")

    # status
    status_p = subparsers.add_parser("status", help="Display current session and contract status")
    status_p.add_argument("--session-id", default=None, help="Specific session ID to inspect")

    # verify
    verify_p = subparsers.add_parser("verify", help="Execute an allowlisted verification gate")
    verify_p.add_argument("gate_id", help="Identifier of verification gate to run (e.g. pytest)")

    # evaluate
    subparsers.add_parser("evaluate", help="Evaluate active session against scope, evidence, and policy")

    # report
    report_p = subparsers.add_parser("report", help="Render verification report or export JSON receipt")
    report_p.add_argument(
        "--json", action="store_true", help="Output canonical JSON receipt instead of Markdown"
    )
    report_p.add_argument("--session-id", default=None, help="Specific session ID to report")

    # ui
    ui_p = subparsers.add_parser("ui", help="Start the read-only local web status dashboard")
    ui_p.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    ui_p.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    ui_p.add_argument("--session-id", default=None, help="Specific session ID to view")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point function."""
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.subcommand == "demo":
        return cmd_demo(args)
    elif args.subcommand == "init":
        return cmd_init(args)
    elif args.subcommand == "task":
        if args.task_command == "propose":
            return cmd_task_propose(args)
        elif args.task_command == "approve":
            return cmd_task_approve(args)
        else:
            parser.print_help(sys.stderr)
            return 2
    elif args.subcommand == "status":
        return cmd_status(args)
    elif args.subcommand == "verify":
        return cmd_verify(args)
    elif args.subcommand == "evaluate":
        return cmd_evaluate(args)
    elif args.subcommand == "report":
        return cmd_report(args)
    elif args.subcommand == "ui":
        return cmd_ui(args)
    else:
        parser.print_help(sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
