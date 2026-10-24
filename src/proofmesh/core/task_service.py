"""Task service for managing task proposals, amendments, and approval lifecycle."""

from datetime import datetime, timezone

from proofmesh.core.taskfile_md import parse_taskfile
from proofmesh.models import ApprovalStatus, TaskRevision
from proofmesh.storage.store import ProofMeshStore


class TaskService:
    """Service governing TaskFile lifecycle without agent self-approval."""

    def __init__(self, store: ProofMeshStore) -> None:
        self.store = store

    def _ensure_project(self, project_id: str) -> None:
        """Ensure project exists in projects table so foreign keys succeed."""
        if self.store.get_project(project_id) is None:
            self.store.create_project(project_id, root_path=".")

    def _get_project_id_for_task(self, task_id: str) -> str:
        """Resolve project_id from tasks table for an existing task."""
        conn = self.store.get_connection()
        try:
            row = conn.execute(
                "SELECT project_id FROM tasks WHERE task_id = ?;",
                (task_id,),
            ).fetchone()
            if row and row["project_id"]:
                return str(row["project_id"])
            return "default"
        finally:
            conn.close()

    def propose_task(
        self,
        task_id: str,
        content: str,
        project_id: str,
        known_gates: set[str] | None = None,
    ) -> TaskRevision:
        """Propose an initial task contract (revision 1).

        Args:
            task_id: The expected task identifier.
            content: Raw Markdown TaskFile content.
            project_id: The owning project ID.
            known_gates: Optional allowlist of known gate IDs.

        Returns:
            The persisted TaskRevision with ApprovalStatus.PROPOSED.

        Raises:
            ValueError: If parsing fails, task_id does not match, revision != 1,
                or revision 1 is already approved.
        """
        parsed = parse_taskfile(content, known_gates=known_gates)
        if parsed.task_id != task_id:
            raise ValueError(
                f"Task ID in content '{parsed.task_id}' does not match requested task_id '{task_id}'"
            )

        if parsed.revision != 1:
            raise ValueError(f"Initial task proposal must have revision 1, got {parsed.revision}")

        existing = self.store.get_task_revision(task_id, 1)
        if existing is not None and existing.approval_status == ApprovalStatus.APPROVED:
            raise ValueError(f"Task '{task_id}' revision 1 has already been approved and cannot be overwritten")

        self._ensure_project(project_id)
        revision = parsed.model_copy(
            update={
                "parent_revision": None,
                "approval_status": ApprovalStatus.PROPOSED,
            }
        )
        self.store.save_task_revision(revision, project_id=project_id)
        return revision

    def approve_task(
        self,
        task_id: str,
        revision: int,
        approved_by: str,
        reason: str | None = None,
        project_id: str | None = None,
    ) -> TaskRevision:
        """Approve a proposed task revision.

        Args:
            task_id: Task identifier.
            revision: Revision number to approve.
            approved_by: Identity of human approver or authorized authority.
            reason: Optional justification text.
            project_id: Optional project ID (resolved from store if omitted).

        Returns:
            The updated TaskRevision with ApprovalStatus.APPROVED.

        Raises:
            ValueError: If approved_by is missing, revision does not exist,
                or revision is superseded.
        """
        if not approved_by or not approved_by.strip():
            raise ValueError("approved_by must be a non-empty string")

        rev = self.store.get_task_revision(task_id, revision)
        if rev is None:
            raise ValueError(f"Task revision '{task_id}' revision {revision} not found")

        if rev.approval_status == ApprovalStatus.SUPERSEDED:
            raise ValueError(
                f"Cannot approve superseded task revision '{task_id}' revision {revision}"
            )

        resolved_project_id = project_id if project_id is not None else self._get_project_id_for_task(task_id)
        self._ensure_project(resolved_project_id)

        now_utc = datetime.now(timezone.utc)
        updated = rev.model_copy(
            update={
                "approval_status": ApprovalStatus.APPROVED,
                "approved_by": approved_by.strip(),
                "approved_at": now_utc,
            }
        )
        self.store.save_task_revision(updated, project_id=resolved_project_id)

        # Mark parent revision as SUPERSEDED upon amendment approval
        if rev.parent_revision is not None:
            parent = self.store.get_task_revision(task_id, rev.parent_revision)
            if parent is not None and parent.approval_status == ApprovalStatus.APPROVED:
                parent_superseded = parent.model_copy(
                    update={"approval_status": ApprovalStatus.SUPERSEDED}
                )
                self.store.save_task_revision(parent_superseded, project_id=resolved_project_id)

        return updated

    def propose_amendment(
        self,
        task_id: str,
        content: str,
        project_id: str,
        known_gates: set[str] | None = None,
    ) -> TaskRevision:
        """Propose an amendment (revision N+1) to an active approved revision N.

        Args:
            task_id: Task identifier.
            content: Raw Markdown TaskFile content for revision N+1.
            project_id: Owning project ID.
            known_gates: Optional allowlist of known gate IDs.

        Returns:
            The persisted TaskRevision with ApprovalStatus.PROPOSED and parent_revision=N.

        Raises:
            ValueError: If there is no active approved revision, task_id does not match,
                new revision != N+1, or parsing fails.
        """
        active_rev = self.get_active_revision(task_id)
        if active_rev is None:
            raise ValueError(
                f"Cannot propose amendment: task '{task_id}' has no active approved revision"
            )

        n = active_rev.revision
        parsed = parse_taskfile(content, known_gates=known_gates)

        if parsed.task_id != task_id:
            raise ValueError(
                f"Task ID in content '{parsed.task_id}' does not match requested task_id '{task_id}'"
            )

        if parsed.revision != n + 1:
            raise ValueError(f"Amendment proposal revision must be {n + 1}, got {parsed.revision}")

        self._ensure_project(project_id)
        amended = parsed.model_copy(
            update={
                "parent_revision": n,
                "approval_status": ApprovalStatus.PROPOSED,
            }
        )

        self.store.save_task_revision(amended, project_id=project_id)
        return amended

    def get_active_revision(self, task_id: str) -> TaskRevision | None:
        """Retrieve the active approved revision (highest revision with ApprovalStatus.APPROVED)."""
        revisions = self.store.list_task_revisions(task_id)
        approved = [r for r in revisions if r.approval_status == ApprovalStatus.APPROVED]
        if not approved:
            return None
        return max(approved, key=lambda r: r.revision)

    def get_revision(self, task_id: str, revision: int) -> TaskRevision | None:
        """Retrieve a specific task revision by number."""
        return self.store.get_task_revision(task_id, revision)

    def list_revisions(self, task_id: str) -> list[TaskRevision]:
        """List all revisions for a task ordered by revision number."""
        return self.store.list_task_revisions(task_id)
