-- Migration 001: Initial schema for ProofMesh
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    root_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_revisions (
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    summary TEXT NOT NULL,
    acceptance_criteria_json TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    required_gates_json TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    contract_digest TEXT NOT NULL,
    PRIMARY KEY (task_id, revision)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    contract_revision INTEGER NOT NULL,
    repo_root TEXT NOT NULL,
    baseline_snapshot_id TEXT NOT NULL,
    current_snapshot_id TEXT,
    profile TEXT NOT NULL,
    policy_digest TEXT NOT NULL,
    integration_status TEXT NOT NULL,
    state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    FOREIGN KEY (task_id, contract_revision) REFERENCES task_revisions(task_id, revision) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    source_adapter TEXT NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    agent_id TEXT,
    parent_agent_id TEXT,
    host_turn_id TEXT,
    command_signature TEXT,
    exit_status INTEGER,
    snapshot_before TEXT,
    snapshot_after TEXT,
    summary TEXT NOT NULL,
    payload_schema_version INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    contract_revision INTEGER NOT NULL,
    gate_id TEXT NOT NULL,
    acceptance_criteria_json TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    config_digest TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    snapshot_before TEXT NOT NULL,
    snapshot_after TEXT NOT NULL,
    status TEXT NOT NULL,
    exit_code INTEGER,
    summary TEXT NOT NULL,
    invalidation_reason TEXT
);

CREATE TABLE IF NOT EXISTS verdicts (
    verdict_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    contract_revision INTEGER NOT NULL,
    snapshot_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    enforcement_level TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    evaluated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_revisions_task ON task_revisions(task_id);
CREATE INDEX IF NOT EXISTS idx_sessions_task ON sessions(task_id, contract_revision);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_evidence_session ON evidence(session_id, gate_id, status);
CREATE INDEX IF NOT EXISTS idx_verdicts_session ON verdicts(session_id, evaluated_at);
