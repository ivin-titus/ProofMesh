"""Tests for TaskFile markdown parsing, validation, contract digest, and task service lifecycle."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import pytest

from proofmesh.core.taskfile_md import (
    MAX_TASKFILE_SIZE_BYTES,
    compute_contract_digest,
    parse_taskfile,
    render_taskfile,
)
from proofmesh.core.task_service import TaskService
from proofmesh.models import (
    AcceptanceCriterion,
    ApprovalStatus,
    RiskLevel,
    ScopePolicy,
    TaskRevision,
)
from proofmesh.storage.store import ProofMeshStore


# -----------------------------------------------------------------------------
# Fixtures and Sample TaskFiles
# -----------------------------------------------------------------------------

VALID_TASKFILE_MD = """+++
task_id = "task-login-auth"
version = 1
summary = "Implement secure password reset and rate limiting"
risk_level = "medium"
allow_paths = ["src/auth/**", "tests/auth/**"]
restricted_paths = ["database/migrations/**", "config/security.toml"]
required_gates = ["pytest", "lint"]
constraints = ["Token expires in 15 minutes", "Max 3 attempts per hour"]
max_changed_files = 10
+++

# task-login-auth: Implement secure password reset and rate limiting

## Objective
Provide self-service password reset functionality via emailed magic link.

## Acceptance criteria
- [AC-1] User receives single-use reset token via email (gates: pytest, lint)
- [AC-2] Expired tokens are rejected with HTTP 400 (gates: pytest)
- [AC-3] Rate limiter triggers after 3 failed verification attempts
"""

AMENDMENT_TASKFILE_MD = """+++
task_id = "task-login-auth"
version = 2
summary = "Implement secure password reset with added lockout logging"
risk_level = "medium"
allow_paths = ["src/auth/**", "tests/auth/**", "src/telemetry/**"]
restricted_paths = ["database/migrations/**", "config/security.toml"]
required_gates = ["pytest", "lint"]
constraints = ["Token expires in 15 minutes", "Max 3 attempts per hour"]
max_changed_files = 15
+++

## Acceptance criteria
- [AC-1] User receives single-use reset token via email (gates: pytest, lint)
- [AC-2] Expired tokens are rejected with HTTP 400 (gates: pytest)
- [AC-3] Rate limiter triggers after 3 failed verification attempts
- [AC-4] Lockout event is emitted to security audit stream (gates: pytest)
"""


@pytest.fixture
def tmp_store(tmp_path: Path) -> ProofMeshStore:
    db_dir = tmp_path / "store"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_file = db_dir / "test_proofmesh.db"
    return ProofMeshStore(db_file)


# -----------------------------------------------------------------------------
# Unit Tests: TaskFile Markdown Parsing
# -----------------------------------------------------------------------------

def test_parse_valid_taskfile() -> None:
    """Verify parsing a complete, valid TaskFile with front matter and criteria."""
    known = {"pytest", "lint"}
    rev = parse_taskfile(VALID_TASKFILE_MD, known_gates=known)

    assert rev.task_id == "task-login-auth"
    assert rev.revision == 1
    assert rev.parent_revision is None
    assert rev.summary == "Implement secure password reset and rate limiting"
    assert rev.risk_level == RiskLevel.MEDIUM
    assert rev.approval_status == ApprovalStatus.PROPOSED
    assert rev.approved_by is None
    assert rev.approved_at is None
    assert rev.scope.allow_paths == ("src/auth/**", "tests/auth/**")
    assert rev.scope.restricted_paths == ("database/migrations/**", "config/security.toml")
    assert rev.scope.max_changed_files == 10
    assert rev.required_gates == ("pytest", "lint")
    assert rev.constraints == ("Token expires in 15 minutes", "Max 3 attempts per hour")

    assert len(rev.acceptance_criteria) == 3
    ac1 = rev.acceptance_criteria[0]
    assert ac1.criterion_id == "AC-1"
    assert ac1.description == "User receives single-use reset token via email"
    assert ac1.required_gates == ("pytest", "lint")

    ac2 = rev.acceptance_criteria[1]
    assert ac2.criterion_id == "AC-2"
    assert ac2.description == "Expired tokens are rejected with HTTP 400"
    assert ac2.required_gates == ("pytest",)

    ac3 = rev.acceptance_criteria[2]
    assert ac3.criterion_id == "AC-3"
    assert ac3.description == "Rate limiter triggers after 3 failed verification attempts"
    assert ac3.required_gates == ()

    assert rev.contract_digest.startswith("sha256:")
    assert len(rev.contract_digest) == 7 + 64


def test_deterministic_contract_digest() -> None:
    """Verify that contract digest is completely deterministic and ignores cosmetic whitespace."""
    content_a = VALID_TASKFILE_MD
    content_b = VALID_TASKFILE_MD.replace("\n\n", "\n\n\n")  # extra blank lines in body

    rev_a = parse_taskfile(content_a)
    rev_b = parse_taskfile(content_b)

    assert rev_a.contract_digest == rev_b.contract_digest


def test_render_and_reparse_roundtrip() -> None:
    """Verify rendering a TaskRevision to Markdown and reparsing preserves all fields."""
    original = parse_taskfile(VALID_TASKFILE_MD)
    rendered = render_taskfile(original)
    reparsed = parse_taskfile(rendered)

    assert reparsed.task_id == original.task_id
    assert reparsed.revision == original.revision
    assert reparsed.summary == original.summary
    assert reparsed.risk_level == original.risk_level
    assert reparsed.scope.allow_paths == original.scope.allow_paths
    assert reparsed.scope.restricted_paths == original.scope.restricted_paths
    assert reparsed.scope.max_changed_files == original.scope.max_changed_files
    assert reparsed.required_gates == original.required_gates
    assert reparsed.constraints == original.constraints
    assert reparsed.acceptance_criteria == original.acceptance_criteria
    assert reparsed.contract_digest == original.contract_digest


def test_subbullet_gates_syntax() -> None:
    """Verify that indented sub-bullet syntax for gates is supported."""
    content = """+++
task_id = "task-subbullet"
version = 1
summary = "Subbullet test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
+++

## Acceptance criteria
- [AC-10] First criterion
  - gates: test-gate, second-gate
- [AC-20] Second criterion with continuation text
  and additional explanation line
  - gates: single-gate
"""
    rev = parse_taskfile(content)
    assert len(rev.acceptance_criteria) == 2
    assert rev.acceptance_criteria[0].criterion_id == "AC-10"
    assert rev.acceptance_criteria[0].required_gates == ("test-gate", "second-gate")
    assert rev.acceptance_criteria[1].criterion_id == "AC-20"
    assert "additional explanation line" in rev.acceptance_criteria[1].description
    assert rev.acceptance_criteria[1].required_gates == ("single-gate",)


def test_custom_identifier_criterion_id() -> None:
    """Verify criteria can use identifier syntax as well as AC-N."""
    content = """+++
task_id = "task-identifier-criteria"
version = 1
summary = "Identifier criterion test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
+++

## Acceptance criteria
- [criterion-auth] Authentication check passes (gates: auth-gate)
- [ac-99] Standard lower AC
"""
    rev = parse_taskfile(content)
    assert rev.acceptance_criteria[0].criterion_id == "criterion-auth"
    assert rev.acceptance_criteria[1].criterion_id == "ac-99"


# -----------------------------------------------------------------------------
# Adversarial & Validation Tests
# -----------------------------------------------------------------------------

def test_reject_oversized_taskfile() -> None:
    """Verify content > 64 KiB is rejected before parsing."""
    large_summary = "x" * (MAX_TASKFILE_SIZE_BYTES + 100)
    oversized = f"""+++
task_id = "task-too-large"
version = 1
summary = "{large_summary}"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
+++

## Acceptance criteria
- [AC-1] Valid
"""
    with pytest.raises(ValueError, match="exceeds maximum limit of 64 KiB"):
        parse_taskfile(oversized)


def test_reject_malformed_toml() -> None:
    """Verify malformed TOML syntax raises ValueError."""
    bad_toml = """+++
task_id = "unterminated string
version = 1
+++

## Acceptance criteria
- [AC-1] Valid
"""
    with pytest.raises(ValueError, match="Malformed TOML"):
        parse_taskfile(bad_toml)


def test_reject_missing_front_matter_delimiter() -> None:
    """Verify TaskFile lacking +++ delimiter is rejected."""
    no_delims = """# Just Markdown
## Acceptance criteria
- [AC-1] Valid
"""
    with pytest.raises(ValueError, match="must begin with front matter delimited by '\\+\\+\\+'"):
        parse_taskfile(no_delims)


def test_reject_unclosed_front_matter() -> None:
    """Verify TaskFile lacking closing +++ delimiter is rejected."""
    unclosed = """+++
task_id = "task-1"
version = 1
summary = "Unclosed"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []

## Acceptance criteria
- [AC-1] Valid
"""
    with pytest.raises(ValueError, match="closing '\\+\\+\\+' delimiter not found"):
        parse_taskfile(unclosed)


def test_reject_extra_unexpected_front_matter_fields() -> None:
    """Verify unexpected extra front-matter fields are strictly forbidden."""
    unexpected_field = """+++
task_id = "task-extra"
version = 1
summary = "Test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
unexpected_actor = "rogue_agent"
injected_policy = "bypass"
+++

## Acceptance criteria
- [AC-1] Valid
"""
    with pytest.raises(ValueError, match="Unexpected front-matter field\\(s\\)"):
        parse_taskfile(unexpected_field)


def test_reject_missing_required_front_matter_fields() -> None:
    """Verify missing required front-matter fields are rejected."""
    missing_paths = """+++
task_id = "task-missing"
version = 1
summary = "Missing paths"
risk_level = "low"
+++

## Acceptance criteria
- [AC-1] Valid
"""
    with pytest.raises(ValueError, match="Missing required front-matter field\\(s\\)"):
        parse_taskfile(missing_paths)


def test_reject_invalid_task_id_format() -> None:
    """Verify invalid task_id format is rejected."""
    bad_id = """+++
task_id = "INVALID_TASK_ID!"
version = 1
summary = "Test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
+++

## Acceptance criteria
- [AC-1] Valid
"""
    with pytest.raises(ValueError, match="Invalid task_id"):
        parse_taskfile(bad_id)


def test_reject_invalid_version() -> None:
    """Verify non-integer or < 1 versions are rejected."""
    bad_version = """+++
task_id = "task-bad-ver"
version = 0
summary = "Test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
+++

## Acceptance criteria
- [AC-1] Valid
"""
    with pytest.raises(ValueError, match="Invalid version"):
        parse_taskfile(bad_version)


def test_reject_invalid_risk_level() -> None:
    """Verify invalid risk level is rejected."""
    bad_risk = """+++
task_id = "task-bad-risk"
version = 1
summary = "Test"
risk_level = "critical_danger"
allow_paths = ["*"]
restricted_paths = []
+++

## Acceptance criteria
- [AC-1] Valid
"""
    with pytest.raises(ValueError, match="Invalid risk_level"):
        parse_taskfile(bad_risk)


def test_reject_missing_acceptance_criteria_section() -> None:
    """Verify absence of '## Acceptance criteria' raises ValueError."""
    no_ac_section = """+++
task_id = "task-no-ac"
version = 1
summary = "Test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
+++

# Title
Some text here, but no criteria.
"""
    with pytest.raises(ValueError, match="Missing required section: '## Acceptance criteria'"):
        parse_taskfile(no_ac_section)


def test_reject_empty_acceptance_criteria_section() -> None:
    """Verify acceptance criteria section with no list items raises ValueError."""
    empty_ac = """+++
task_id = "task-empty-ac"
version = 1
summary = "Test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
+++

## Acceptance criteria
There are no criteria items in this section.
"""
    with pytest.raises(ValueError, match="must contain at least one criterion"):
        parse_taskfile(empty_ac)


def test_reject_duplicate_criterion_id() -> None:
    """Verify duplicate criterion IDs are rejected."""
    duplicate_ids = """+++
task_id = "task-dup-ac"
version = 1
summary = "Test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
+++

## Acceptance criteria
- [AC-1] First criterion
- [AC-1] Duplicate ID criterion
"""
    with pytest.raises(ValueError, match="Duplicate criterion ID: 'AC-1'"):
        parse_taskfile(duplicate_ids)


def test_reject_invalid_criterion_id_format() -> None:
    """Verify malformed criterion IDs are rejected."""
    bad_crit_id = """+++
task_id = "task-bad-crit-id"
version = 1
summary = "Test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
+++

## Acceptance criteria
- [AC-12345] Too many digits for AC- prefix
"""
    with pytest.raises(ValueError, match="Invalid criterion ID"):
        parse_taskfile(bad_crit_id)


def test_reject_unknown_gate_in_criteria() -> None:
    """Verify unknown gate ID referenced in criteria raises ValueError when known_gates is provided."""
    content = """+++
task_id = "task-unknown-gate"
version = 1
summary = "Test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
+++

## Acceptance criteria
- [AC-1] Criterion with unknown gate (gates: unauthorized-gate)
"""
    with pytest.raises(ValueError, match="Unknown gate ID 'unauthorized-gate'"):
        parse_taskfile(content, known_gates={"pytest", "lint"})


def test_reject_invalid_gate_id_format_in_criteria() -> None:
    """Verify malformed gate ID (e.g. uppercase, underscore) raises ValueError."""
    content = """+++
task_id = "task-invalid-gate"
version = 1
summary = "Test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
+++

## Acceptance criteria
- [AC-1] Criterion with bad gate format (gates: INVALID_GATE!)
"""
    with pytest.raises(ValueError, match="Invalid gate ID 'INVALID_GATE!'"):
        parse_taskfile(content)


def test_reject_unknown_gate_in_required_gates() -> None:
    """Verify unknown gate ID in front matter required_gates raises ValueError when known_gates is provided."""
    content = """+++
task_id = "task-unknown-req-gate"
version = 1
summary = "Test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
required_gates = ["pytest", "untrusted-runner"]
+++

## Acceptance criteria
- [AC-1] Criterion (gates: pytest)
"""
    with pytest.raises(ValueError, match="Unknown gate ID in required_gates: 'untrusted-runner'"):
        parse_taskfile(content, known_gates={"pytest", "lint"})


def test_reject_invalid_gate_id_format_in_required_gates() -> None:
    """Verify malformed gate ID in required_gates raises ValueError."""
    content = """+++
task_id = "task-invalid-req-gate"
version = 1
summary = "Test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
required_gates = ["pytest", "bad_gate_underscore"]
+++

## Acceptance criteria
- [AC-1] Criterion (gates: pytest)
"""
    with pytest.raises(ValueError, match="Invalid gate ID in required_gates: 'bad_gate_underscore'"):
        parse_taskfile(content)


def test_reject_malformed_criterion_bullet() -> None:
    """Verify bullet in Acceptance Criteria section without [ID] is rejected."""
    bad_bullet = """+++
task_id = "task-bad-bullet"
version = 1
summary = "Test"
risk_level = "low"
allow_paths = ["*"]
restricted_paths = []
+++

## Acceptance criteria
- This is a bullet without bracketed criterion ID
"""
    with pytest.raises(ValueError, match="Invalid acceptance criterion format"):
        parse_taskfile(bad_bullet)


# -----------------------------------------------------------------------------
# Lifecycle Tests: TaskService Workflow
# -----------------------------------------------------------------------------

def test_task_service_propose_and_approve_workflow(tmp_store: ProofMeshStore) -> None:
    """Test full propose -> approve workflow in SQLite store."""
    service = TaskService(tmp_store)
    project_id = "proj-alpha"

    # Initially, no active revision exists
    assert service.get_active_revision("task-login-auth") is None

    # Propose task revision 1
    proposed = service.propose_task(
        task_id="task-login-auth",
        content=VALID_TASKFILE_MD,
        project_id=project_id,
        known_gates={"pytest", "lint"},
    )

    assert proposed.task_id == "task-login-auth"
    assert proposed.revision == 1
    assert proposed.approval_status == ApprovalStatus.PROPOSED
    assert proposed.approved_by is None
    assert proposed.approved_at is None

    # Before approval, get_active_revision must STILL be None
    assert service.get_active_revision("task-login-auth") is None

    # Check store has persisted the proposed revision
    persisted_rev = service.get_revision("task-login-auth", 1)
    assert persisted_rev is not None
    assert persisted_rev.approval_status == ApprovalStatus.PROPOSED

    # Approve task revision 1
    approved = service.approve_task(
        task_id="task-login-auth",
        revision=1,
        approved_by="tech-lead-alice",
        reason="Initial contract approved for implementation",
    )

    assert approved.approval_status == ApprovalStatus.APPROVED
    assert approved.approved_by == "tech-lead-alice"
    assert approved.approved_at is not None
    assert isinstance(approved.approved_at, datetime)

    # Active revision is now revision 1
    active = service.get_active_revision("task-login-auth")
    assert active is not None
    assert active.revision == 1
    assert active.approval_status == ApprovalStatus.APPROVED
    assert active.approved_by == "tech-lead-alice"


def test_task_service_propose_rejects_non_version_one(tmp_store: ProofMeshStore) -> None:
    """Verify propose_task enforces revision == 1."""
    service = TaskService(tmp_store)
    with pytest.raises(ValueError, match="Initial task proposal must have revision 1, got 2"):
        service.propose_task(
            task_id="task-login-auth",
            content=AMENDMENT_TASKFILE_MD,  # has version = 2
            project_id="proj-alpha",
        )


def test_task_service_amendment_does_not_mutate_approved_revision(tmp_store: ProofMeshStore) -> None:
    """Verify propose_amendment creates rev N+1 without mutating active approved rev N."""
    service = TaskService(tmp_store)
    project_id = "proj-alpha"

    # Setup initial approved rev 1
    service.propose_task("task-login-auth", VALID_TASKFILE_MD, project_id=project_id)
    rev1 = service.approve_task("task-login-auth", 1, approved_by="alice")

    assert rev1.approval_status == ApprovalStatus.APPROVED
    digest_rev1_before = rev1.contract_digest

    # Propose amendment revision 2
    amended = service.propose_amendment(
        task_id="task-login-auth",
        content=AMENDMENT_TASKFILE_MD,
        project_id=project_id,
        known_gates={"pytest", "lint"},
    )

    assert amended.revision == 2
    assert amended.parent_revision == 1
    assert amended.approval_status == ApprovalStatus.PROPOSED
    assert len(amended.acceptance_criteria) == 4

    # Crucial check: Active approved revision in store is STILL rev 1 and has NOT changed
    rev1_after = service.get_revision("task-login-auth", 1)
    assert rev1_after is not None
    assert rev1_after.approval_status == ApprovalStatus.APPROVED
    assert rev1_after.approved_by == "alice"
    assert rev1_after.contract_digest == digest_rev1_before

    # Active revision remains rev 1 until amendment is approved
    assert service.get_active_revision("task-login-auth").revision == 1

    # Approve amendment rev 2
    rev2_approved = service.approve_task("task-login-auth", 2, approved_by="bob")
    assert rev2_approved.revision == 2
    assert rev2_approved.approval_status == ApprovalStatus.APPROVED

    # Now active revision is rev 2
    assert service.get_active_revision("task-login-auth").revision == 2

    # And rev 1 is still in history
    all_revs = service.list_revisions("task-login-auth")
    assert len(all_revs) == 2
    assert [r.revision for r in all_revs] == [1, 2]


def test_propose_amendment_requires_active_approved_revision(tmp_store: ProofMeshStore) -> None:
    """Verify an amendment cannot be proposed if no approved revision exists."""
    service = TaskService(tmp_store)
    project_id = "proj-alpha"

    # Only proposed, not yet approved
    service.propose_task("task-login-auth", VALID_TASKFILE_MD, project_id=project_id)

    with pytest.raises(ValueError, match="has no active approved revision"):
        service.propose_amendment("task-login-auth", AMENDMENT_TASKFILE_MD, project_id=project_id)


def test_propose_amendment_rejects_gap_in_version(tmp_store: ProofMeshStore) -> None:
    """Verify amendment revision must strictly equal active revision + 1."""
    service = TaskService(tmp_store)
    project_id = "proj-alpha"

    service.propose_task("task-login-auth", VALID_TASKFILE_MD, project_id=project_id)
    service.approve_task("task-login-auth", 1, approved_by="alice")

    # Content with version = 3 when active is 1
    skipped_rev_content = AMENDMENT_TASKFILE_MD.replace("version = 2", "version = 3")
    with pytest.raises(ValueError, match="Amendment proposal revision must be 2, got 3"):
        service.propose_amendment("task-login-auth", skipped_rev_content, project_id=project_id)


# -----------------------------------------------------------------------------
# Cross-Process Persistence Test
# -----------------------------------------------------------------------------

def test_task_service_task_id_mismatch(tmp_store: ProofMeshStore) -> None:
    """Verify propose_task and propose_amendment reject task_id mismatch."""
    service = TaskService(tmp_store)
    project_id = "proj-alpha"

    with pytest.raises(ValueError, match="does not match requested task_id"):
        service.propose_task("task-different-id", VALID_TASKFILE_MD, project_id=project_id)

    # Propose and approve rev 1 with correct id
    service.propose_task("task-login-auth", VALID_TASKFILE_MD, project_id=project_id)
    service.approve_task("task-login-auth", 1, approved_by="alice")

    mismatched_content = AMENDMENT_TASKFILE_MD.replace('task_id = "task-login-auth"', 'task_id = "task-other"')
    with pytest.raises(ValueError, match="does not match requested task_id"):
        service.propose_amendment("task-login-auth", mismatched_content, project_id=project_id)


def test_task_service_cannot_overwrite_approved_rev1(tmp_store: ProofMeshStore) -> None:
    """Verify propose_task cannot overwrite an already approved revision 1."""
    service = TaskService(tmp_store)
    project_id = "proj-alpha"

    service.propose_task("task-login-auth", VALID_TASKFILE_MD, project_id=project_id)
    service.approve_task("task-login-auth", 1, approved_by="alice")

    with pytest.raises(ValueError, match="revision 1 has already been approved"):
        service.propose_task("task-login-auth", VALID_TASKFILE_MD, project_id=project_id)


def test_task_service_approve_validation_and_errors(tmp_store: ProofMeshStore) -> None:
    """Verify approve_task validates inputs and non-existent revisions."""
    service = TaskService(tmp_store)
    project_id = "proj-alpha"

    service.propose_task("task-login-auth", VALID_TASKFILE_MD, project_id=project_id)

    # Missing approved_by
    with pytest.raises(ValueError, match="approved_by must be a non-empty string"):
        service.approve_task("task-login-auth", 1, approved_by="")

    with pytest.raises(ValueError, match="approved_by must be a non-empty string"):
        service.approve_task("task-login-auth", 1, approved_by="   ")

    # Non-existent revision
    with pytest.raises(ValueError, match="revision 99 not found"):
        service.approve_task("task-login-auth", 99, approved_by="alice")

    # Non-existent task
    with pytest.raises(ValueError, match="revision 1 not found"):
        service.approve_task("task-non-existent", 1, approved_by="alice")


def test_separate_process_persistence(tmp_path: Path) -> None:
    """Verify proposed and approved task revisions persist across separate Python processes."""
    import os
    repo_root = Path(__file__).resolve().parent.parent
    db_dir = tmp_path / "store"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_file = db_dir / "cross_proc.db"
    project_id = "proj-cross-proc"
    env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}
    cwd = str(repo_root)

    # Script for Process 1: Propose Task
    script_step1 = f"""
from proofmesh.storage.store import ProofMeshStore
from proofmesh.core.task_service import TaskService

store = ProofMeshStore({repr(str(db_file))})
service = TaskService(store)
rev = service.propose_task(
    task_id="task-login-auth",
    content={repr(VALID_TASKFILE_MD)},
    project_id={repr(project_id)},
)
assert rev.revision == 1
assert rev.approval_status.value == "proposed"
print("STEP_1_PROPOSE_OK")
"""

    # Run Process 1
    res1 = subprocess.run(
        [sys.executable, "-c", script_step1],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=cwd,
    )
    assert "STEP_1_PROPOSE_OK" in res1.stdout

    # Script for Process 2: Verify Proposed State & Approve Task
    script_step2 = f"""
from proofmesh.storage.store import ProofMeshStore
from proofmesh.core.task_service import TaskService
from proofmesh.models import ApprovalStatus

store = ProofMeshStore({repr(str(db_file))})
service = TaskService(store)

# Must not be active before approval
assert service.get_active_revision("task-login-auth") is None

# Load revision 1
rev1 = service.get_revision("task-login-auth", 1)
assert rev1 is not None
assert rev1.approval_status == ApprovalStatus.PROPOSED

# Approve revision 1
approved = service.approve_task("task-login-auth", 1, approved_by="process2-worker")
assert approved.approval_status == ApprovalStatus.APPROVED
assert approved.approved_by == "process2-worker"
print("STEP_2_APPROVE_OK")
"""

    # Run Process 2
    res2 = subprocess.run(
        [sys.executable, "-c", script_step2],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=cwd,
    )
    assert "STEP_2_APPROVE_OK" in res2.stdout

    # Script for Process 3: Verify Approved Active Revision from a Third Process
    script_step3 = f"""
from proofmesh.storage.store import ProofMeshStore
from proofmesh.core.task_service import TaskService
from proofmesh.models import ApprovalStatus

store = ProofMeshStore({repr(str(db_file))})
service = TaskService(store)

active = service.get_active_revision("task-login-auth")
assert active is not None
assert active.revision == 1
assert active.approval_status == ApprovalStatus.APPROVED
assert active.approved_by == "process2-worker"
assert active.approved_at is not None
print("STEP_3_VERIFY_ACTIVE_OK")
"""

    # Run Process 3
    res3 = subprocess.run(
        [sys.executable, "-c", script_step3],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=cwd,
    )
    assert "STEP_3_VERIFY_ACTIVE_OK" in res3.stdout
