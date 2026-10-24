"""Task service for managing task proposals, amendments, and approval lifecycle."""

from datetime import datetime, timezone
import re
import tomllib

from proofmesh.core.taskfile_md import parse_taskfile
from proofmesh.models import ApprovalStatus, TaskRevision
from proofmesh.storage.store import ProofMeshStore

UNTRUSTED_OR_STRIPPED_FM_KEYS = {
    "approval_status",
    "approved_by",
    "approved_at",
    "parent_revision",
    "parent_id",
    "parent_task_id",
}


def _sanitize_and_validate_front_matter(
    content: str,
    expected_task_id: str | None = None,
    expected_parent_revision: int | None = None,
    is_initial_proposal: bool = False,
) -> str:
    """Validate untrusted or parent fields in front matter and strip them for parsing.

    Ensures that any self-approval metadata (approval_status, approved_by, approved_at)
    in front matter is ignored, and validates parent linkage before stripping.
    """
    lines = content.splitlines(keepends=True)
    start_idx: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "+++":
            start_idx = idx
            break
        # Let parse_taskfile report missing or invalid front-matter delimiter
        return content

    if start_idx is None:
        return content

    end_idx: int | None = None
    for idx in range(start_idx + 1, len(lines)):
        if lines[idx].strip() == "+++":
            end_idx = idx
            break

    if end_idx is None:
        return content

    fm_lines = lines[start_idx + 1 : end_idx]
    toml_text = "".join(fm_lines)

    try:
        fm = tomllib.loads(toml_text)
    except Exception:
        # Let parse_taskfile handle malformed TOML
        return content

    if isinstance(fm, dict):
        # Validate parent linkage if specified in front matter
        if "parent_revision" in fm:
            parent_rev = fm["parent_revision"]
            if is_initial_proposal:
                if parent_rev is not None:
                    raise ValueError(
                        f"Initial task proposal cannot specify a parent_revision (got {parent_rev})"
                    )
            elif expected_parent_revision is not None:
                if parent_rev != expected_parent_revision:
                    raise ValueError(
                        f"Conflicting parent_revision in TaskFile: expected {expected_parent_revision}, got {parent_rev}"
                    )

        if "parent_id" in fm or "parent_task_id" in fm:
            parent_id_val = str(fm.get("parent_id") or fm.get("parent_task_id"))
            if expected_task_id is not None and parent_id_val != expected_task_id:
                raise ValueError(
                    f"Conflicting parent task ID in TaskFile: expected '{expected_task_id}', got '{parent_id_val}'"
                )

    # Filter out untrusted keys so parse_taskfile won't reject them as unexpected fields
    cleaned_fm_lines: list[str] = []
    key_pattern = re.compile(r"^\s*([a-zA-Z0-9_-]+)\s*=")
    for line in fm_lines:
        match = key_pattern.match(line)
        if match and match.group(1) in UNTRUSTED_OR_STRIPPED_FM_KEYS:
            continue
        cleaned_fm_lines.append(line)

    return "".join(lines[: start_idx + 1] + cleaned_fm_lines + lines[end_idx:])


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
                revision 1 is already approved, or duplicate proposal has conflicting content.
        """
        sanitized_content = _sanitize_and_validate_front_matter(
            content,
            expected_task_id=task_id,
            is_initial_proposal=True,
        )
        parsed = parse_taskfile(sanitized_content, known_gates=known_gates)
        if parsed.task_id != task_id:
            raise ValueError(
                f"Task ID in content '{parsed.task_id}' does not match requested task_id '{task_id}'"
            )

        if parsed.revision != 1:
            raise ValueError(f"Initial task proposal must have revision 1, got {parsed.revision}")

        existing = self.store.get_task_revision(task_id, 1)
        if existing is not None:
            if existing.approval_status == ApprovalStatus.APPROVED:
                raise ValueError(
                    f"Task '{task_id}' revision 1 has already been approved and cannot be overwritten"
                )
            if existing.contract_digest != parsed.contract_digest:
                raise ValueError(
                    f"Conflicting proposal for task '{task_id}' revision 1: cannot overwrite existing proposal with different content"
                )

        self._ensure_project(project_id)
        revision = parsed.model_copy(
            update={
                "parent_revision": None,
                "approval_status": ApprovalStatus.PROPOSED,
                "approved_by": None,
                "approved_at": None,
                "raw_markdown": content,
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
        """Approve a proposed task revision atomically superseding any parent revision.

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
                revision is superseded, or revision is already approved.
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

        if rev.approval_status == ApprovalStatus.APPROVED:
            if rev.approved_by != approved_by.strip():
                raise ValueError(
                    f"Task revision '{task_id}' revision {revision} is already approved and cannot be re-approved with different metadata"
                )
            raise ValueError(
                f"Task revision '{task_id}' revision {revision} is already approved"
            )

        resolved_project_id = project_id if project_id is not None else self._get_project_id_for_task(task_id)
        self._ensure_project(resolved_project_id)

        now_utc = datetime.now(timezone.utc)
        return self.store.approve_task_revision(
            task_id=task_id,
            revision=revision,
            approved_by=approved_by.strip(),
            approved_at=now_utc,
            parent_revision=rev.parent_revision,
            project_id=resolved_project_id,
        )

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
                new revision != N+1, conflicting parent IDs/revisions, duplicate proposal
                conflicts, or parsing fails.
        """
        active_rev = self.get_active_revision(task_id)
        if active_rev is None:
            raise ValueError(
                f"Cannot propose amendment: task '{task_id}' has no active approved revision"
            )

        n = active_rev.revision
        sanitized_content = _sanitize_and_validate_front_matter(
            content,
            expected_task_id=task_id,
            expected_parent_revision=n,
            is_initial_proposal=False,
        )
        parsed = parse_taskfile(sanitized_content, known_gates=known_gates)

        if parsed.task_id != task_id:
            raise ValueError(
                f"Task ID in content '{parsed.task_id}' does not match requested task_id '{task_id}'"
            )

        if parsed.revision != n + 1:
            raise ValueError(f"Amendment proposal revision must be {n + 1}, got {parsed.revision}")

        existing = self.store.get_task_revision(task_id, n + 1)
        if existing is not None:
            if existing.approval_status == ApprovalStatus.APPROVED:
                raise ValueError(
                    f"Task '{task_id}' revision {n + 1} has already been approved and cannot be overwritten"
                )
            if existing.contract_digest != parsed.contract_digest:
                raise ValueError(
                    f"Conflicting proposal for task '{task_id}' revision {n + 1}: cannot overwrite existing proposal with different content"
                )

        self._ensure_project(project_id)
        amended = parsed.model_copy(
            update={
                "parent_revision": n,
                "approval_status": ApprovalStatus.PROPOSED,
                "approved_by": None,
                "approved_at": None,
                "raw_markdown": content,
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
