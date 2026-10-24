-- Migration 002: Add snapshot observation fields and loop detector attempt tracking

ALTER TABLE snapshots ADD COLUMN complete INTEGER NOT NULL DEFAULT 1;
ALTER TABLE snapshots ADD COLUMN observation_errors_json TEXT NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS loop_attempts (
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    gate_id TEXT NOT NULL,
    failure_signature TEXT NOT NULL,
    attempt_count INTEGER NOT NULL,
    last_attempt_at TEXT NOT NULL,
    last_turn_id TEXT,
    PRIMARY KEY (session_id, gate_id, failure_signature)
);
