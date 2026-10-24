from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Generator

from proofmesh.models import (
    AcceptanceCriterion,
    ApprovalStatus,
    EnforcementLevel,
    EventRecord,
    EvidenceRecord,
    EvidenceStatus,
    IntegrationStatus,
    OperatingProfile,
    RiskLevel,
    ScopePolicy,
    Session,
    SessionState,
    TaskRevision,
    VerdictOutcome,
    VerdictRecord,
    unfreeze_value,
)
from proofmesh.storage.migrations import apply_migrations
from proofmesh.storage.paths import _secure_directory, secure_db_file, validate_project_id


class ProofMeshStore:
    """SQLite storage for ProofMesh. Owns all SQL and returns validated domain models."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).resolve()
        # Ensure parent directory exists and file permissions are secured
        _secure_directory(self.db_path.parent)
        self._ensure_pragmas_and_schema()

    def get_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection with required safety pragmas."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=5.0,
            isolation_level=None,  # Explicit transaction management
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = FULL;")
        conn.execute("PRAGMA trusted_schema = OFF;")
        secure_db_file(self.db_path)
        return conn

    def _ensure_pragmas_and_schema(self) -> None:
        """Initialize connection, secure file permissions, and apply migrations."""
        conn = self.get_connection()
        try:
            apply_migrations(conn)
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Explicit write transaction with immediate lock and automatic rollback on error."""
        conn = self.get_connection()
        conn.execute("BEGIN IMMEDIATE;")
        try:
            yield conn
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Projects & Tasks
    # -------------------------------------------------------------------------

    def create_project(self, project_id: str, root_path: str, created_at: datetime | None = None) -> None:
        """Register a project."""
        validate_project_id(project_id)
        ts = (created_at or datetime.now(timezone.utc)).isoformat()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (project_id, root_path, created_at) VALUES (?, ?, ?)"
                " ON CONFLICT(project_id) DO UPDATE SET root_path = excluded.root_path;",
                (project_id, root_path, ts),
            )

    def get_project(self, project_id: str) -> dict[str, str] | None:
        """Retrieve project registration details."""
        validate_project_id(project_id)
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT project_id, root_path, created_at FROM projects WHERE project_id = ?;",
                (project_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "project_id": row["project_id"],
                "root_path": row["root_path"],
                "created_at": row["created_at"],
            }
        finally:
            conn.close()

    def create_task(self, task_id: str, project_id: str, created_at: datetime | None = None) -> None:
        """Create a task identity bound to a project."""
        validate_project_id(project_id)
        ts = (created_at or datetime.now(timezone.utc)).isoformat()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO tasks (task_id, project_id, created_at) VALUES (?, ?, ?)"
                " ON CONFLICT(task_id) DO NOTHING;",
                (task_id, project_id, ts),
            )

    # -------------------------------------------------------------------------
    # Task Revisions
    # -------------------------------------------------------------------------

    def save_task_revision(self, revision: TaskRevision, project_id: str) -> None:
        """Persist a task revision within an explicit transaction."""
        validate_project_id(project_id)
        ac_json = json.dumps([ac.model_dump(mode="json") for ac in revision.acceptance_criteria])
        scope_json = json.dumps(revision.scope.model_dump(mode="json"))
        gates_json = json.dumps(revision.required_gates)
        constraints_json = json.dumps(revision.constraints)
        approved_at_str = revision.approved_at.isoformat() if revision.approved_at else None

        with self.transaction() as conn:
            # Ensure task exists
            conn.execute(
                "INSERT INTO tasks (task_id, project_id, created_at) VALUES (?, ?, ?)"
                " ON CONFLICT(task_id) DO NOTHING;",
                (revision.task_id, project_id, datetime.now(timezone.utc).isoformat()),
            )
            # Insert revision
            conn.execute(
                """
                INSERT INTO task_revisions (
                    task_id, revision, summary, acceptance_criteria_json,
                    scope_json, required_gates_json, constraints_json,
                    risk_level, approval_status, approved_by, approved_at, contract_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    revision.task_id,
                    revision.revision,
                    revision.summary,
                    ac_json,
                    scope_json,
                    gates_json,
                    constraints_json,
                    revision.risk_level.value,
                    revision.approval_status.value,
                    revision.approved_by,
                    approved_at_str,
                    revision.contract_digest,
                ),
            )

    def get_task_revision(self, task_id: str, revision: int) -> TaskRevision | None:
        """Load and revalidate a task revision from the database."""
        conn = self.get_connection()
        try:
            row = conn.execute(
                """
                SELECT task_id, revision, summary, acceptance_criteria_json,
                       scope_json, required_gates_json, constraints_json,
                       risk_level, approval_status, approved_by, approved_at, contract_digest
                FROM task_revisions
                WHERE task_id = ? AND revision = ?;
                """,
                (task_id, revision),
            ).fetchone()

            if not row:
                return None

            return self._row_to_task_revision(row)
        finally:
            conn.close()

    def list_task_revisions(self, task_id: str) -> list[TaskRevision]:
        """List all revisions for a task ordered by revision number."""
        conn = self.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT task_id, revision, summary, acceptance_criteria_json,
                       scope_json, required_gates_json, constraints_json,
                       risk_level, approval_status, approved_by, approved_at, contract_digest
                FROM task_revisions
                WHERE task_id = ?
                ORDER BY revision ASC;
                """,
                (task_id,),
            ).fetchall()
            return [self._row_to_task_revision(r) for r in rows]
        finally:
            conn.close()

    def _row_to_task_revision(self, row: sqlite3.Row) -> TaskRevision:
        raw_ac = json.loads(row["acceptance_criteria_json"])
        ac_list = [AcceptanceCriterion.model_validate(item) for item in raw_ac]
        raw_scope = json.loads(row["scope_json"])
        scope = ScopePolicy.model_validate(raw_scope)

        approved_at = None
        if row["approved_at"]:
            approved_at = datetime.fromisoformat(row["approved_at"])

        return TaskRevision(
            task_id=row["task_id"],
            revision=row["revision"],
            summary=row["summary"],
            acceptance_criteria=ac_list,
            scope=scope,
            required_gates=json.loads(row["required_gates_json"]),
            constraints=json.loads(row["constraints_json"]),
            risk_level=RiskLevel(row["risk_level"]),
            approval_status=ApprovalStatus(row["approval_status"]),
            approved_by=row["approved_by"],
            approved_at=approved_at,
            contract_digest=row["contract_digest"],
        )

    # -------------------------------------------------------------------------
    # Sessions
    # -------------------------------------------------------------------------

    def save_session(self, session: Session) -> None:
        """Persist or update a session."""
        ended_at_str = session.ended_at.isoformat() if session.ended_at else None
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, task_id, contract_revision, repo_root,
                    baseline_snapshot_id, current_snapshot_id, profile,
                    policy_digest, integration_status, state, started_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    current_snapshot_id = excluded.current_snapshot_id,
                    integration_status = excluded.integration_status,
                    state = excluded.state,
                    ended_at = excluded.ended_at;
                """,
                (
                    session.session_id,
                    session.task_id,
                    session.contract_revision,
                    session.repo_root,
                    session.baseline_snapshot_id,
                    session.current_snapshot_id,
                    session.profile.value,
                    session.policy_digest,
                    session.integration_status.value,
                    session.state.value,
                    session.started_at.isoformat(),
                    ended_at_str,
                ),
            )

    def get_session(self, session_id: str) -> Session | None:
        """Retrieve and validate a session."""
        conn = self.get_connection()
        try:
            row = conn.execute(
                """
                SELECT session_id, task_id, contract_revision, repo_root,
                       baseline_snapshot_id, current_snapshot_id, profile,
                       policy_digest, integration_status, state, started_at, ended_at
                FROM sessions
                WHERE session_id = ?;
                """,
                (session_id,),
            ).fetchone()

            if not row:
                return None

            ended_at = None
            if row["ended_at"]:
                ended_at = datetime.fromisoformat(row["ended_at"])

            return Session(
                session_id=row["session_id"],
                task_id=row["task_id"],
                contract_revision=row["contract_revision"],
                repo_root=row["repo_root"],
                baseline_snapshot_id=row["baseline_snapshot_id"],
                current_snapshot_id=row["current_snapshot_id"],
                profile=OperatingProfile(row["profile"]),
                policy_digest=row["policy_digest"],
                integration_status=IntegrationStatus(row["integration_status"]),
                state=SessionState(row["state"]),
                started_at=datetime.fromisoformat(row["started_at"]),
                ended_at=ended_at,
            )
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Events
    # -------------------------------------------------------------------------

    def save_event(self, event: EventRecord) -> None:
        """Persist an event record."""
        payload_json = json.dumps(unfreeze_value(event.payload))
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    event_id, session_id, source_adapter, event_type,
                    occurred_at, agent_id, parent_agent_id, host_turn_id,
                    command_signature, exit_status, snapshot_before,
                    snapshot_after, summary, payload_schema_version, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    event.event_id,
                    event.session_id,
                    event.source_adapter,
                    event.event_type,
                    event.occurred_at.isoformat(),
                    event.agent_id,
                    event.parent_agent_id,
                    event.host_turn_id,
                    event.command_signature,
                    event.exit_status,
                    event.snapshot_before,
                    event.snapshot_after,
                    event.summary,
                    event.payload_schema_version,
                    payload_json,
                ),
            )

    def get_event(self, event_id: str) -> EventRecord | None:
        """Retrieve and validate a single event."""
        conn = self.get_connection()
        try:
            row = conn.execute(
                """
                SELECT event_id, session_id, source_adapter, event_type,
                       occurred_at, agent_id, parent_agent_id, host_turn_id,
                       command_signature, exit_status, snapshot_before,
                       snapshot_after, summary, payload_schema_version, payload_json
                FROM events
                WHERE event_id = ?;
                """,
                (event_id,),
            ).fetchone()

            if not row:
                return None

            return self._row_to_event(row)
        finally:
            conn.close()

    def list_events_for_session(self, session_id: str) -> list[EventRecord]:
        """List all events for a session ordered by time."""
        conn = self.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT event_id, session_id, source_adapter, event_type,
                       occurred_at, agent_id, parent_agent_id, host_turn_id,
                       command_signature, exit_status, snapshot_before,
                       snapshot_after, summary, payload_schema_version, payload_json
                FROM events
                WHERE session_id = ?
                ORDER BY occurred_at ASC;
                """,
                (session_id,),
            ).fetchall()
            return [self._row_to_event(r) for r in rows]
        finally:
            conn.close()

    def _row_to_event(self, row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            event_id=row["event_id"],
            session_id=row["session_id"],
            source_adapter=row["source_adapter"],
            event_type=row["event_type"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            agent_id=row["agent_id"],
            parent_agent_id=row["parent_agent_id"],
            host_turn_id=row["host_turn_id"],
            command_signature=row["command_signature"],
            exit_status=row["exit_status"],
            snapshot_before=row["snapshot_before"],
            snapshot_after=row["snapshot_after"],
            summary=row["summary"],
            payload_schema_version=row["payload_schema_version"],
            payload=json.loads(row["payload_json"]),
        )

    # -------------------------------------------------------------------------
    # Evidence
    # -------------------------------------------------------------------------

    def save_evidence(self, evidence: EvidenceRecord) -> None:
        """Persist an evidence record."""
        ac_json = json.dumps(evidence.acceptance_criteria)
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO evidence (
                    evidence_id, session_id, contract_revision, gate_id,
                    acceptance_criteria_json, provider_name, provider_version,
                    config_digest, started_at, ended_at, duration_ms,
                    snapshot_before, snapshot_after, status, exit_code,
                    summary, invalidation_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    evidence.evidence_id,
                    evidence.session_id,
                    evidence.contract_revision,
                    evidence.gate_id,
                    ac_json,
                    evidence.provider_name,
                    evidence.provider_version,
                    evidence.config_digest,
                    evidence.started_at.isoformat(),
                    evidence.ended_at.isoformat(),
                    evidence.duration_ms,
                    evidence.snapshot_before,
                    evidence.snapshot_after,
                    evidence.status.value,
                    evidence.exit_code,
                    evidence.summary,
                    evidence.invalidation_reason,
                ),
            )

    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None:
        """Retrieve and validate an evidence record."""
        conn = self.get_connection()
        try:
            row = conn.execute(
                """
                SELECT evidence_id, session_id, contract_revision, gate_id,
                       acceptance_criteria_json, provider_name, provider_version,
                       config_digest, started_at, ended_at, duration_ms,
                       snapshot_before, snapshot_after, status, exit_code,
                       summary, invalidation_reason
                FROM evidence
                WHERE evidence_id = ?;
                """,
                (evidence_id,),
            ).fetchone()

            if not row:
                return None

            return self._row_to_evidence(row)
        finally:
            conn.close()

    def list_evidence_for_session(self, session_id: str) -> list[EvidenceRecord]:
        """List all evidence records for a session."""
        conn = self.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT evidence_id, session_id, contract_revision, gate_id,
                       acceptance_criteria_json, provider_name, provider_version,
                       config_digest, started_at, ended_at, duration_ms,
                       snapshot_before, snapshot_after, status, exit_code,
                       summary, invalidation_reason
                FROM evidence
                WHERE session_id = ?
                ORDER BY started_at ASC;
                """,
                (session_id,),
            ).fetchall()
            return [self._row_to_evidence(r) for r in rows]
        finally:
            conn.close()

    def _row_to_evidence(self, row: sqlite3.Row) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=row["evidence_id"],
            session_id=row["session_id"],
            contract_revision=row["contract_revision"],
            gate_id=row["gate_id"],
            acceptance_criteria=json.loads(row["acceptance_criteria_json"]),
            provider_name=row["provider_name"],
            provider_version=row["provider_version"],
            config_digest=row["config_digest"],
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]),
            duration_ms=row["duration_ms"],
            snapshot_before=row["snapshot_before"],
            snapshot_after=row["snapshot_after"],
            status=EvidenceStatus(row["status"]),
            exit_code=row["exit_code"],
            summary=row["summary"],
            invalidation_reason=row["invalidation_reason"],
        )

    # -------------------------------------------------------------------------
    # Verdicts
    # -------------------------------------------------------------------------

    def save_verdict(self, verdict: VerdictRecord) -> None:
        """Persist a verdict record."""
        reasons_json = json.dumps(verdict.reasons)
        evidence_ids_json = json.dumps(verdict.evidence_ids)
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO verdicts (
                    verdict_id, session_id, contract_revision, snapshot_id,
                    verdict, enforcement_level, reasons_json, evidence_ids_json,
                    evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    verdict.verdict_id,
                    verdict.session_id,
                    verdict.contract_revision,
                    verdict.snapshot_id,
                    verdict.verdict.value,
                    verdict.enforcement_level.value,
                    reasons_json,
                    evidence_ids_json,
                    verdict.evaluated_at.isoformat(),
                ),
            )

    def get_verdict(self, verdict_id: str) -> VerdictRecord | None:
        """Retrieve and validate a verdict record."""
        conn = self.get_connection()
        try:
            row = conn.execute(
                """
                SELECT verdict_id, session_id, contract_revision, snapshot_id,
                       verdict, enforcement_level, reasons_json, evidence_ids_json,
                       evaluated_at
                FROM verdicts
                WHERE verdict_id = ?;
                """,
                (verdict_id,),
            ).fetchone()

            if not row:
                return None

            return self._row_to_verdict(row)
        finally:
            conn.close()

    def list_verdicts_for_session(self, session_id: str) -> list[VerdictRecord]:
        """List all verdicts for a session ordered by evaluation time."""
        conn = self.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT verdict_id, session_id, contract_revision, snapshot_id,
                       verdict, enforcement_level, reasons_json, evidence_ids_json,
                       evaluated_at
                FROM verdicts
                WHERE session_id = ?
                ORDER BY evaluated_at ASC;
                """,
                (session_id,),
            ).fetchall()
            return [self._row_to_verdict(r) for r in rows]
        finally:
            conn.close()

    def _row_to_verdict(self, row: sqlite3.Row) -> VerdictRecord:
        return VerdictRecord(
            verdict_id=row["verdict_id"],
            session_id=row["session_id"],
            contract_revision=row["contract_revision"],
            snapshot_id=row["snapshot_id"],
            verdict=VerdictOutcome(row["verdict"]),
            enforcement_level=EnforcementLevel(row["enforcement_level"]),
            reasons=json.loads(row["reasons_json"]),
            evidence_ids=json.loads(row["evidence_ids_json"]),
            evaluated_at=datetime.fromisoformat(row["evaluated_at"]),
        )
