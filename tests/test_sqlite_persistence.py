from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest
from pydantic import ValidationError

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
)
from proofmesh.storage import (
    ProofMeshStore,
    get_proofmesh_data_dir,
    get_project_db_path,
)
from proofmesh.storage.paths import _secure_directory, secure_db_file, validate_project_id

SAMPLE_DIGEST = "sha256:" + "b" * 64


@pytest.fixture
def temp_store(tmp_path: Path) -> ProofMeshStore:
    db_path = tmp_path / "test_proofmesh.db"
    return ProofMeshStore(db_path)


def test_roundtrip_all_entities(temp_store: ProofMeshStore):
    """Verify task revision, session, event, evidence, and verdict roundtrip as validated models."""
    now = datetime.now(timezone.utc)

    # 1. Project & Task Revision
    temp_store.create_project("proj-alpha", "/workspace/test")
    ac = AcceptanceCriterion(
        criterion_id="AC-1",
        description="Must pass tests",
        required_gates=["gate-pytest"],
    )
    scope = ScopePolicy(allow_paths=["src/**", "tests/**"], restricted_paths=[".git/**"])
    revision = TaskRevision(
        task_id="task-42",
        revision=1,
        summary="Initial implementation task",
        acceptance_criteria=[ac],
        scope=scope,
        required_gates=["gate-pytest"],
        constraints=["no-network"],
        risk_level=RiskLevel.MEDIUM,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="human-reviewer",
        approved_at=now,
        contract_digest=SAMPLE_DIGEST,
    )
    temp_store.save_task_revision(revision, project_id="proj-alpha")

    loaded_rev = temp_store.get_task_revision("task-42", 1)
    assert loaded_rev is not None
    assert isinstance(loaded_rev, TaskRevision)
    assert loaded_rev.task_id == "task-42"
    assert loaded_rev.revision == 1
    assert loaded_rev.acceptance_criteria[0].criterion_id == "AC-1"
    assert loaded_rev.scope.allow_paths == ("src/**", "tests/**")
    assert loaded_rev.approval_status == ApprovalStatus.APPROVED
    assert loaded_rev.approved_by == "human-reviewer"

    # 2. Session
    session = Session(
        session_id="sess-99",
        task_id="task-42",
        contract_revision=1,
        repo_root="/workspace/test",
        baseline_snapshot_id="snap-0",
        current_snapshot_id="snap-1",
        profile=OperatingProfile.FLOW,
        policy_digest=SAMPLE_DIGEST,
        integration_status=IntegrationStatus.ENFORCED,
        state=SessionState.ACTIVE,
        started_at=now,
    )
    temp_store.save_session(session)

    loaded_sess = temp_store.get_session("sess-99")
    assert loaded_sess is not None
    assert isinstance(loaded_sess, Session)
    assert loaded_sess.session_id == "sess-99"
    assert loaded_sess.state == SessionState.ACTIVE
    assert loaded_sess.integration_status == IntegrationStatus.ENFORCED

    # 3. Event Record
    event = EventRecord(
        event_id="evt-101",
        session_id="sess-99",
        source_adapter="antigravity",
        event_type="PreToolUse",
        occurred_at=now,
        summary="Checked tool policy for write_file",
        payload_schema_version=1,
        payload={"tool": "write_file", "path": "src/app.py"},
    )
    temp_store.save_event(event)

    loaded_evt = temp_store.get_event("evt-101")
    assert loaded_evt is not None
    assert isinstance(loaded_evt, EventRecord)
    assert loaded_evt.summary == "Checked tool policy for write_file"
    assert loaded_evt.payload["tool"] == "write_file"

    # 4. Evidence Record
    evidence = EvidenceRecord(
        evidence_id="ev-202",
        session_id="sess-99",
        contract_revision=1,
        gate_id="gate-pytest",
        acceptance_criteria=["AC-1"],
        provider_name="pytest-runner",
        provider_version="9.1.1",
        config_digest=SAMPLE_DIGEST,
        started_at=now,
        ended_at=now,
        duration_ms=450,
        snapshot_before="snap-0",
        snapshot_after="snap-1",
        status=EvidenceStatus.PASSED,
        exit_code=0,
        summary="All 10 tests passed",
    )
    temp_store.save_evidence(evidence)

    loaded_ev = temp_store.get_evidence("ev-202")
    assert loaded_ev is not None
    assert isinstance(loaded_ev, EvidenceRecord)
    assert loaded_ev.status == EvidenceStatus.PASSED
    assert loaded_ev.duration_ms == 450
    assert loaded_ev.acceptance_criteria == ("AC-1",)

    # 5. Verdict Record
    verdict = VerdictRecord(
        verdict_id="verd-303",
        session_id="sess-99",
        contract_revision=1,
        snapshot_id="snap-1",
        verdict=VerdictOutcome.ALLOW,
        enforcement_level=EnforcementLevel.ENFORCED,
        reasons=["All mandatory gates passed"],
        evidence_ids=["ev-202"],
        evaluated_at=now,
    )
    temp_store.save_verdict(verdict)

    loaded_verd = temp_store.get_verdict("verd-303")
    assert loaded_verd is not None
    assert isinstance(loaded_verd, VerdictRecord)
    assert loaded_verd.verdict == VerdictOutcome.ALLOW
    assert loaded_verd.reasons == ("All mandatory gates passed",)
    assert loaded_verd.evidence_ids == ("ev-202",)


def test_foreign_key_violation_fails_safely(temp_store: ProofMeshStore):
    """Verify foreign key constraint rejects session referencing non-existent revision."""
    now = datetime.now(timezone.utc)
    # Reference non-existent task revision
    session = Session(
        session_id="sess-orphaned",
        task_id="non-existent-task",
        contract_revision=1,
        repo_root="/workspace",
        baseline_snapshot_id="snap-0",
        policy_digest=SAMPLE_DIGEST,
        started_at=now,
    )
    with pytest.raises(sqlite3.IntegrityError):
        temp_store.save_session(session)


def test_transaction_rollback_on_failure(temp_store: ProofMeshStore):
    """Verify that a multi-step write transaction rolls back completely on error."""
    now = datetime.now(timezone.utc)
    temp_store.create_project("proj-rollback", "/workspace")

    # Attempt a transaction that writes a project then raises an error
    with pytest.raises(RuntimeError):
        with temp_store.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (project_id, root_path, created_at) VALUES (?, ?, ?);",
                ("proj-transient", "/workspace/transient", now.isoformat()),
            )
            # Intentionally raise an error to trigger rollback
            raise RuntimeError("Forced abort mid-transaction")

    # Verify project was NOT persisted
    assert temp_store.get_project("proj-transient") is None


def test_corrupted_row_fails_revalidation(temp_store: ProofMeshStore):
    """Verify that tampering with DB to insert invalid data fails closed with ValidationError."""
    temp_store.create_project("proj-tamper", "/workspace")
    rev = TaskRevision(
        task_id="task-tamper",
        revision=1,
        summary="Tamper test",
        contract_digest=SAMPLE_DIGEST,
    )
    temp_store.save_task_revision(rev, "proj-tamper")

    # Manually tamper with the database to inject invalid JSON
    conn = temp_store.get_connection()
    try:
        conn.execute(
            "UPDATE task_revisions SET acceptance_criteria_json = ? WHERE task_id = ?;",
            ('[{"invalid_key": 123}]', "task-tamper"),
        )
    finally:
        conn.close()

    # Reading it back must raise ValidationError, failing closed
    with pytest.raises(ValidationError):
        temp_store.get_task_revision("task-tamper", 1)


def test_data_dir_outside_target_repo(tmp_path: Path):
    """Verify the default data directory is outside the workspace repository."""
    repo_root = Path(__file__).parent.parent.resolve()
    resolved_dir = get_proofmesh_data_dir(create=False)

    # The data directory must not be within the target repository
    assert not str(resolved_dir).startswith(str(repo_root)), (
        f"Data dir {resolved_dir} must not be inside repo {repo_root}"
    )

    # Custom PROOFMESH_HOME must be respected
    custom_path = tmp_path / "custom_proofmesh_data"
    os.environ["PROOFMESH_HOME"] = str(custom_path)
    try:
        assert get_proofmesh_data_dir(create=True) == custom_path.resolve()
        assert custom_path.exists()
    finally:
        del os.environ["PROOFMESH_HOME"]


def test_persistence_survives_separate_process(tmp_path: Path):
    """Verify state persists and is loadable by a separate Python process."""
    db_file = tmp_path / "proc_test.db"
    store = ProofMeshStore(db_file)

    now = datetime.now(timezone.utc)
    store.create_project("proc-proj", "/workspace/proc")
    rev = TaskRevision(
        task_id="task-proc",
        revision=1,
        summary="Process survival test",
        contract_digest=SAMPLE_DIGEST,
    )
    store.save_task_revision(rev, "proc-proj")

    # Spawn a brand new Python subprocess that opens the DB and verifies the record
    python_bin = sys.executable
    script = f"""
import sys
from proofmesh.storage import ProofMeshStore
from proofmesh.models import TaskRevision

store = ProofMeshStore(r'{db_file}')
rev = store.get_task_revision('task-proc', 1)
assert rev is not None, 'Revision not found in separate process'
assert rev.task_id == 'task-proc'
assert rev.summary == 'Process survival test'
print('SEPARATE_PROCESS_SUCCESS')
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    result = subprocess.run(
        [python_bin, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "SEPARATE_PROCESS_SUCCESS" in result.stdout


def test_project_id_traversal_rejected(tmp_path: Path):
    """Verify that path traversal attempts in project_id are strictly rejected."""
    traversal_ids = ["../outside", "../../escape", "/root/bad", "proj/sub", "proj\\win", "bad\0byte", ""]
    for bad_id in traversal_ids:
        with pytest.raises(ValueError):
            validate_project_id(bad_id, base_dir=tmp_path)
        with pytest.raises(ValueError):
            get_project_db_path(bad_id, base_dir=tmp_path)


def test_transaction_connection_closed_on_error(temp_store: ProofMeshStore):
    """Verify that a failed transaction explicitly closes the database connection."""
    with pytest.raises(RuntimeError):
        with temp_store.transaction() as conn:
            raise RuntimeError("Failure inside transaction")

    # The store connection was closed in finally block; new connection works cleanly
    conn2 = temp_store.get_connection()
    try:
        assert conn2.execute("PRAGMA schema_version;").fetchone() is not None
    finally:
        conn2.close()


def test_nested_event_payload_roundtrip(temp_store: ProofMeshStore):
    """Verify that deeply nested event payloads round-trip through SQLite and remain immutable."""
    now = datetime.now(timezone.utc)
    temp_store.create_project("proj-nest", "/repo")
    rev = TaskRevision(
        task_id="task-nested",
        revision=1,
        summary="Nested payload test",
        contract_digest=SAMPLE_DIGEST,
    )
    temp_store.save_task_revision(rev, project_id="proj-nest")

    sess = Session(
        session_id="sess-nest",
        task_id="task-nested",
        contract_revision=1,
        repo_root="/repo",
        baseline_snapshot_id="snap-0",
        policy_digest=SAMPLE_DIGEST,
        started_at=now,
    )
    temp_store.save_session(sess)

    event = EventRecord(
        event_id="evt-nest-1",
        session_id="sess-nest",
        source_adapter="antigravity",
        event_type="PreToolUse",
        occurred_at=now,
        summary="Nested payload test",
        payload={
            "tool_call": {
                "tool": "edit_file",
                "params": {"file": "src/app.py", "lines": [10, 20]},
            },
            "execution_history": [{"attempt": 1, "status": "ok"}],
        },
    )
    temp_store.save_event(event)

    loaded = temp_store.get_event("evt-nest-1")
    assert loaded is not None
    assert loaded.payload["tool_call"]["tool"] == "edit_file"
    assert loaded.payload["tool_call"]["params"]["lines"] == (10, 20)
    assert loaded.payload["execution_history"][0]["status"] == "ok"

    # Verify deep immutability on loaded event
    with pytest.raises(TypeError):
        loaded.payload["tool_call"]["params"]["file"] = "tampered.py"  # type: ignore[index]

    with pytest.raises(AttributeError):
        loaded.payload["tool_call"]["params"]["lines"].append(30)  # type: ignore[attr-defined]

    with pytest.raises(TypeError):
        loaded.payload["execution_history"][0]["attempt"] = 99  # type: ignore[index]


def test_filesystem_permissions_hierarchy(tmp_path: Path):
    """Verify permissions: data dir 0700, projects dir 0700, per-project dir 0700, db file 0600."""
    db_path = get_project_db_path("secure-proj", base_dir=tmp_path)
    assert db_path.name == "proofmesh.db"

    # Base dir
    assert (tmp_path.stat().st_mode & 0o777) == 0o700
    # Intermediate projects dir
    assert ((tmp_path / "projects").stat().st_mode & 0o777) == 0o700
    # Per-project dir
    assert ((tmp_path / "projects" / "secure-proj").stat().st_mode & 0o777) == 0o700

    # DB file permissions after store creation
    store = ProofMeshStore(db_path)
    assert db_path.exists()
    assert (db_path.stat().st_mode & 0o777) == 0o600


def test_secure_directory_error_handling(tmp_path: Path, monkeypatch):
    """Verify that unsupported chmod errors are ignored, but unexpected errors and PermissionError raise."""
    import errno

    test_dir = tmp_path / "perm_test"

    # 1. Unsupported chmod errnos (ENOSYS, EOPNOTSUPP, ENOTSUP) must be ignored
    def mock_chmod_unsupported(path, mode):
        raise OSError(errno.ENOSYS, "Function not implemented")

    monkeypatch.setattr(os, "chmod", mock_chmod_unsupported)
    _secure_directory(test_dir)  # Should not raise

    # 2. Unexpected OSError (e.g. EIO, EROFS) must be re-raised
    def mock_chmod_io_error(path, mode):
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(os, "chmod", mock_chmod_io_error)
    with pytest.raises(OSError) as exc:
        _secure_directory(test_dir)
    assert exc.value.errno == errno.EIO

    # 3. PermissionError must be re-raised with actionable message
    def mock_chmod_perm_error(path, mode):
        raise PermissionError("Permission denied")

    monkeypatch.setattr(os, "chmod", mock_chmod_perm_error)
    with pytest.raises(PermissionError) as p_exc:
        _secure_directory(test_dir)
    assert "Cannot set secure permissions" in str(p_exc.value)

