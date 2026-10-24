"""Dedicated edge case tests for TaskFile lifecycle, approvals, and revisions."""

from datetime import datetime, timezone
from pathlib import Path
import pytest

from proofmesh.core.task_service import TaskService
from proofmesh.models import ApprovalStatus
from proofmesh.storage.store import ProofMeshStore

BASE_TASK_MD = """+++
task_id = "task-edge-test"
version = 1
summary = "Initial edge case testing task"
risk_level = "low"
allow_paths = ["src/**"]
restricted_paths = ["config/**"]
required_gates = ["pytest"]
constraints = ["Deterministic runs only"]
+++

## Acceptance criteria
- [AC-1] Core lifecycle functionality passes (gates: pytest)
"""

SELF_APPROVAL_FRONT_MATTER_MD = """+++
task_id = "task-edge-test"
version = 1
summary = "Attempted agent self-approval in front matter"
risk_level = "low"
allow_paths = ["src/**"]
restricted_paths = ["config/**"]
required_gates = ["pytest"]
constraints = ["Deterministic runs only"]
approval_status = "approved"
approved_by = "malicious_agent_007"
approved_at = "2026-10-24T00:00:00Z"
+++

## Acceptance criteria
- [AC-1] Core lifecycle functionality passes (gates: pytest)
"""

SELF_APPROVAL_BODY_MD = """+++
task_id = "task-edge-test"
version = 1
summary = "Attempted agent self-approval in markdown body"
risk_level = "low"
allow_paths = ["src/**"]
restricted_paths = ["config/**"]
required_gates = ["pytest"]
constraints = ["Deterministic runs only"]
+++

# task-edge-test: Header
approval_status = "approved"
approved_by = "injected_agent"
approved_at = "2026-10-24T00:00:00Z"

## Acceptance criteria
- [AC-1] Core lifecycle functionality passes (gates: pytest)
"""

AMENDMENT_REV2_MD = """+++
task_id = "task-edge-test"
version = 2
summary = "Amended edge case testing task"
risk_level = "medium"
allow_paths = ["src/**", "tests/**"]
restricted_paths = ["config/**"]
required_gates = ["pytest", "lint"]
constraints = ["Deterministic runs only"]
+++

## Acceptance criteria
- [AC-1] Core lifecycle functionality passes (gates: pytest)
- [AC-2] Secondary verification gate passed (gates: lint)
"""


@pytest.fixture
def store(tmp_path: Path) -> ProofMeshStore:
    db_file = tmp_path / "lifecycle_edges.db"
    return ProofMeshStore(db_file)


@pytest.fixture
def service(store: ProofMeshStore) -> TaskService:
    return TaskService(store)


# -----------------------------------------------------------------------------
# 1. Ignoring Self-Approval Metadata in TaskFile Content
# -----------------------------------------------------------------------------

def test_ignore_self_approval_metadata_in_front_matter(service: TaskService) -> None:
    """TaskFile front matter attempting to declare 'approved' status must be ignored.

    The proposed revision must ALWAYS be stored with ApprovalStatus.PROPOSED and
    no approved_by/approved_at metadata.
    """
    rev = service.propose_task(
        task_id="task-edge-test",
        content=SELF_APPROVAL_FRONT_MATTER_MD,
        project_id="proj-edge",
        known_gates={"pytest"},
    )

    # In-memory returned TaskRevision
    assert rev.approval_status == ApprovalStatus.PROPOSED
    assert rev.approved_by is None
    assert rev.approved_at is None
    assert rev.revision == 1

    # Database-persisted TaskRevision
    persisted = service.get_revision("task-edge-test", 1)
    assert persisted is not None
    assert persisted.approval_status == ApprovalStatus.PROPOSED
    assert persisted.approved_by is None
    assert persisted.approved_at is None

    # Must NOT be considered the active revision
    assert service.get_active_revision("task-edge-test") is None


def test_ignore_self_approval_metadata_in_body(service: TaskService) -> None:
    """TaskFile markdown body attempting to inject approval keywords must be ignored."""
    rev = service.propose_task(
        task_id="task-edge-test",
        content=SELF_APPROVAL_BODY_MD,
        project_id="proj-edge",
        known_gates={"pytest"},
    )

    assert rev.approval_status == ApprovalStatus.PROPOSED
    assert rev.approved_by is None
    assert rev.approved_at is None

    persisted = service.get_revision("task-edge-test", 1)
    assert persisted is not None
    assert persisted.approval_status == ApprovalStatus.PROPOSED
    assert service.get_active_revision("task-edge-test") is None


def test_ignore_self_approval_in_amendment_proposal(service: TaskService) -> None:
    """Amendment proposal injecting self-approval metadata must remain PROPOSED."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    service.approve_task("task-edge-test", 1, approved_by="alice")

    amendment_self_approve = AMENDMENT_REV2_MD.replace(
        'constraints = ["Deterministic runs only"]',
        'constraints = ["Deterministic runs only"]\napproval_status = "approved"\napproved_by = "rogue_bot"',
    )

    rev2 = service.propose_amendment(
        task_id="task-edge-test",
        content=amendment_self_approve,
        project_id="proj-edge",
        known_gates={"pytest", "lint"},
    )

    assert rev2.revision == 2
    assert rev2.approval_status == ApprovalStatus.PROPOSED
    assert rev2.approved_by is None
    assert rev2.approved_at is None

    # Active revision must still be rev 1 until legitimate approval
    active = service.get_active_revision("task-edge-test")
    assert active is not None
    assert active.revision == 1
    assert active.approval_status == ApprovalStatus.APPROVED


# -----------------------------------------------------------------------------
# 2. Duplicate Proposal Rejection and Idempotency
# -----------------------------------------------------------------------------

def test_duplicate_proposal_identical_content_is_idempotent(service: TaskService) -> None:
    """Re-proposing identical content for an existing unapproved proposal succeeds idempotently."""
    rev_a = service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    rev_b = service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")

    assert rev_a.contract_digest == rev_b.contract_digest
    assert rev_b.approval_status == ApprovalStatus.PROPOSED


def test_duplicate_proposal_different_content_is_rejected(service: TaskService) -> None:
    """Re-proposing different content for the same (task_id, revision) must be rejected."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")

    conflicting_content = BASE_TASK_MD.replace(
        'summary = "Initial edge case testing task"',
        'summary = "Conflicting altered summary without amending"',
    )

    with pytest.raises(ValueError, match="Conflicting proposal for task 'task-edge-test' revision 1"):
        service.propose_task("task-edge-test", conflicting_content, project_id="proj-edge")

    # Verify original revision remained untouched
    original = service.get_revision("task-edge-test", 1)
    assert original is not None
    assert original.summary == "Initial edge case testing task"


def test_duplicate_amendment_proposal_different_content_is_rejected(service: TaskService) -> None:
    """Conflicting duplicate amendment proposal for rev N+1 must be rejected."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    service.approve_task("task-edge-test", 1, approved_by="alice")

    service.propose_amendment("task-edge-test", AMENDMENT_REV2_MD, project_id="proj-edge")

    conflicting_amendment = AMENDMENT_REV2_MD.replace(
        'summary = "Amended edge case testing task"',
        'summary = "Conflicting amendment proposal"',
    )

    with pytest.raises(ValueError, match="Conflicting proposal for task 'task-edge-test' revision 2"):
        service.propose_amendment("task-edge-test", conflicting_amendment, project_id="proj-edge")


def test_proposing_already_approved_revision_rejected(service: TaskService) -> None:
    """Proposing revision 1 when revision 1 is already approved must fail."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    service.approve_task("task-edge-test", 1, approved_by="alice")

    with pytest.raises(ValueError, match="already been approved and cannot be overwritten"):
        service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")


# -----------------------------------------------------------------------------
# 3. Revision Gaps and Conflicting Parent Revisions
# -----------------------------------------------------------------------------

def test_amendment_rejects_version_gap(service: TaskService) -> None:
    """Amendment version must strictly be active_revision + 1."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    service.approve_task("task-edge-test", 1, approved_by="alice")

    # Version = 3 when active = 1 (skipping 2)
    gap_content = AMENDMENT_REV2_MD.replace("version = 2", "version = 3")
    with pytest.raises(ValueError, match="Amendment proposal revision must be 2, got 3"):
        service.propose_amendment("task-edge-test", gap_content, project_id="proj-edge")


def test_amendment_rejects_version_downgrade(service: TaskService) -> None:
    """Amendment cannot propose a version <= active revision."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    service.approve_task("task-edge-test", 1, approved_by="alice")

    # Version = 1 when active = 1
    downgrade_content = AMENDMENT_REV2_MD.replace("version = 2", "version = 1")
    with pytest.raises(ValueError, match="Amendment proposal revision must be 2, got 1"):
        service.propose_amendment("task-edge-test", downgrade_content, project_id="proj-edge")


def test_amendment_requires_active_approved_revision(service: TaskService) -> None:
    """Cannot propose amendment if task has only unapproved proposed revision."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")

    with pytest.raises(ValueError, match="has no active approved revision"):
        service.propose_amendment("task-edge-test", AMENDMENT_REV2_MD, project_id="proj-edge")


def test_amendment_rejects_conflicting_parent_revision_in_front_matter(service: TaskService) -> None:
    """If TaskFile front matter declares a conflicting parent_revision, reject proposal."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    service.approve_task("task-edge-test", 1, approved_by="alice")

    conflicting_parent_md = AMENDMENT_REV2_MD.replace(
        "version = 2",
        "version = 2\nparent_revision = 99",
    )
    with pytest.raises(ValueError, match="Conflicting parent_revision in TaskFile: expected 1, got 99"):
        service.propose_amendment("task-edge-test", conflicting_parent_md, project_id="proj-edge")


def test_amendment_accepts_matching_parent_revision_in_front_matter(service: TaskService) -> None:
    """If TaskFile front matter declares a matching parent_revision, proposal succeeds."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    service.approve_task("task-edge-test", 1, approved_by="alice")

    matching_parent_md = AMENDMENT_REV2_MD.replace(
        "version = 2",
        "version = 2\nparent_revision = 1",
    )
    rev2 = service.propose_amendment("task-edge-test", matching_parent_md, project_id="proj-edge")
    assert rev2.revision == 2
    assert rev2.parent_revision == 1


def test_amendment_rejects_conflicting_parent_task_id(service: TaskService) -> None:
    """If TaskFile declares conflicting parent_id, reject proposal."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    service.approve_task("task-edge-test", 1, approved_by="alice")

    conflicting_id_md = AMENDMENT_REV2_MD.replace(
        "version = 2",
        'version = 2\nparent_id = "other-task"',
    )
    with pytest.raises(ValueError, match="Conflicting parent task ID in TaskFile"):
        service.propose_amendment("task-edge-test", conflicting_id_md, project_id="proj-edge")


def test_initial_proposal_rejects_parent_revision(service: TaskService) -> None:
    """Initial revision 1 cannot specify a parent revision."""
    initial_with_parent = BASE_TASK_MD.replace(
        "version = 1",
        "version = 1\nparent_revision = 2",
    )
    with pytest.raises(ValueError, match="cannot specify a parent_revision"):
        service.propose_task("task-edge-test", initial_with_parent, project_id="proj-edge")


# -----------------------------------------------------------------------------
# 4. Atomic Approval and Parent Supersession
# -----------------------------------------------------------------------------

def test_atomic_approval_and_parent_supersession(service: TaskService) -> None:
    """Approving an amendment revision atomically marks the parent revision as SUPERSEDED."""
    # 1. Propose & approve rev 1
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    approved_rev1 = service.approve_task("task-edge-test", 1, approved_by="alice")

    assert approved_rev1.approval_status == ApprovalStatus.APPROVED
    assert approved_rev1.approved_by == "alice"
    assert approved_rev1.parent_revision is None

    # Active revision is 1
    active_v1 = service.get_active_revision("task-edge-test")
    assert active_v1 is not None and active_v1.revision == 1

    # 2. Propose amendment rev 2
    service.propose_amendment("task-edge-test", AMENDMENT_REV2_MD, project_id="proj-edge")

    # Prior to approval, rev 1 is still APPROVED and active
    assert service.get_revision("task-edge-test", 1).approval_status == ApprovalStatus.APPROVED
    assert service.get_revision("task-edge-test", 2).approval_status == ApprovalStatus.PROPOSED
    assert service.get_active_revision("task-edge-test").revision == 1

    # 3. Approve rev 2: must atomically supersede rev 1
    approved_rev2 = service.approve_task("task-edge-test", 2, approved_by="bob")
    assert approved_rev2.revision == 2
    assert approved_rev2.approval_status == ApprovalStatus.APPROVED
    assert approved_rev2.approved_by == "bob"

    # Parent rev 1 must now be SUPERSEDED
    reloaded_rev1 = service.get_revision("task-edge-test", 1)
    assert reloaded_rev1 is not None
    assert reloaded_rev1.approval_status == ApprovalStatus.SUPERSEDED

    # Active revision is now rev 2
    active_v2 = service.get_active_revision("task-edge-test")
    assert active_v2 is not None
    assert active_v2.revision == 2

    # 4. Chain a 3rd revision
    amendment_rev3_md = AMENDMENT_REV2_MD.replace("version = 2", "version = 3")
    service.propose_amendment("task-edge-test", amendment_rev3_md, project_id="proj-edge")
    approved_rev3 = service.approve_task("task-edge-test", 3, approved_by="charlie")

    assert approved_rev3.approval_status == ApprovalStatus.APPROVED
    # Rev 2 is now superseded, Rev 1 remains superseded
    assert service.get_revision("task-edge-test", 2).approval_status == ApprovalStatus.SUPERSEDED
    assert service.get_revision("task-edge-test", 1).approval_status == ApprovalStatus.SUPERSEDED
    assert service.get_active_revision("task-edge-test").revision == 3


# -----------------------------------------------------------------------------
# 5. Re-Approval Rejection
# -----------------------------------------------------------------------------

def test_re_approval_rejected_with_different_metadata(service: TaskService) -> None:
    """Cannot re-approve an already approved revision with a different approver."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    service.approve_task("task-edge-test", 1, approved_by="alice")

    with pytest.raises(ValueError, match="already approved and cannot be re-approved with different metadata"):
        service.approve_task("task-edge-test", 1, approved_by="charlie")


def test_re_approval_rejected_with_same_metadata(service: TaskService) -> None:
    """Cannot re-approve an already approved revision even with the same approver."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    service.approve_task("task-edge-test", 1, approved_by="alice")

    with pytest.raises(ValueError, match="already approved"):
        service.approve_task("task-edge-test", 1, approved_by="alice")


def test_approve_superseded_revision_rejected(service: TaskService) -> None:
    """Cannot approve a revision that has already been superseded by a later revision."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    service.approve_task("task-edge-test", 1, approved_by="alice")

    service.propose_amendment("task-edge-test", AMENDMENT_REV2_MD, project_id="proj-edge")
    service.approve_task("task-edge-test", 2, approved_by="bob")

    # Rev 1 is now SUPERSEDED; attempting to re-approve it must fail
    with pytest.raises(ValueError, match="Cannot approve superseded task revision"):
        service.approve_task("task-edge-test", 1, approved_by="alice")


# -----------------------------------------------------------------------------
# 6. Gate Allowlist Validation at Proposal Time
# -----------------------------------------------------------------------------

def test_proposal_rejects_unknown_gate_in_required_gates(service: TaskService) -> None:
    """Propose task rejects unknown gate ID in required_gates when known_gates provided."""
    typo_gates_content = BASE_TASK_MD.replace('required_gates = ["pytest"]', 'required_gates = ["pytset"]')

    with pytest.raises(ValueError, match="Unknown gate ID in required_gates: 'pytset'"):
        service.propose_task(
            task_id="task-edge-test",
            content=typo_gates_content,
            project_id="proj-edge",
            known_gates={"pytest", "lint"},
        )


def test_proposal_rejects_unknown_gate_in_criteria(service: TaskService) -> None:
    """Propose task rejects unknown gate in acceptance criteria."""
    typo_criterion_gate = BASE_TASK_MD.replace("(gates: pytest)", "(gates: typo-gate)")

    with pytest.raises(ValueError, match="Unknown gate ID 'typo-gate' referenced in criterion 'AC-1'"):
        service.propose_task(
            task_id="task-edge-test",
            content=typo_criterion_gate,
            project_id="proj-edge",
            known_gates={"pytest", "lint"},
        )


def test_amendment_proposal_rejects_unknown_gate(service: TaskService) -> None:
    """Amendment proposal rejects unknown gate ID when known_gates allowlist is active."""
    service.propose_task("task-edge-test", BASE_TASK_MD, project_id="proj-edge")
    service.approve_task("task-edge-test", 1, approved_by="alice")

    typo_amendment = AMENDMENT_REV2_MD.replace('required_gates = ["pytest", "lint"]', 'required_gates = ["unknown"]')
    with pytest.raises(ValueError, match="Unknown gate ID in required_gates: 'unknown'"):
        service.propose_amendment(
            task_id="task-edge-test",
            content=typo_amendment,
            project_id="proj-edge",
            known_gates={"pytest", "lint"},
        )
