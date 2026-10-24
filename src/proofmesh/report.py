"""ProofMesh report rendering and receipt export.

Provides human-readable Markdown reports and canonical JSON receipts
from persisted verification records, snapshots, verdicts, and scope findings.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Sequence
import uuid

from proofmesh.core.evaluator import _is_snapshot_fresh
from proofmesh.models import (
    EvidenceRecord,
    EvidenceStatus,
    RepoSnapshot,
    ScopeAnalysisResult,
    Session,
    TaskRevision,
    VerdictOutcome,
    VerdictRecord,
)


def render_markdown_report(
    session: Session,
    task: TaskRevision,
    snapshot: RepoSnapshot,
    scope_result: ScopeAnalysisResult,
    evidence: Sequence[EvidenceRecord],
    verdict: VerdictRecord,
) -> str:
    """Render a clean, human-readable Markdown verification report.

    Args:
        session: Active session.
        task: Active task revision contract.
        snapshot: Current repository snapshot.
        scope_result: Scope analysis result between baseline and current snapshot.
        evidence: Sequence of verification evidence records.
        verdict: Evaluated verdict record.

    Returns:
        Formatted Markdown report string.
    """
    lines: list[str] = []

    # Verdict Badge
    if verdict.verdict == VerdictOutcome.ALLOW:
        verdict_badge = "✅ ALLOW (ACCEPTED)"
    elif verdict.verdict == VerdictOutcome.BLOCK:
        verdict_badge = "❌ BLOCK (BLOCKED)"
    elif verdict.verdict == VerdictOutcome.REQUIRE_APPROVAL:
        verdict_badge = "⚠️ REQUIRE_APPROVAL (NEEDS_APPROVAL)"
    elif verdict.verdict == VerdictOutcome.WARN:
        verdict_badge = "⚠️ WARN"
    else:
        verdict_badge = f"❓ {verdict.verdict.value.upper()}"

    lines.append("# ProofMesh Verification Report")
    lines.append("")
    lines.append(f"**Session ID**: `{session.session_id}`  ")
    lines.append(f"**Verdict**: **{verdict_badge}**  ")
    lines.append(f"**Enforcement Level**: `{verdict.enforcement_level.value}`  ")
    lines.append(f"**Evaluated At**: {verdict.evaluated_at.isoformat()}  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Task & Contract Summary
    lines.append("## Task Contract")
    lines.append("")
    lines.append(f"- **Task ID**: `{task.task_id}` (Revision {task.revision})")
    lines.append(f"- **Summary**: {task.summary}")
    lines.append(f"- **Risk Level**: `{task.risk_level.value}`")
    lines.append(f"- **Approval Status**: `{task.approval_status.value}`")
    if task.approved_by:
        approved_time = task.approved_at.isoformat() if task.approved_at else "unknown"
        lines.append(f"- **Approved By**: `{task.approved_by}` at {approved_time}")
    lines.append(f"- **Contract Digest**: `{task.contract_digest}`")
    lines.append(f"- **Current Snapshot ID**: `{snapshot.snapshot_id}`")
    if snapshot.git_commit:
        dirty_flag = " (dirty)" if snapshot.git_dirty else " (clean)"
        lines.append(f"- **Git Commit**: `{snapshot.git_commit}`{dirty_flag}")
    lines.append("")

    # Scope Findings Table
    lines.append("## Scope Analysis")
    lines.append("")
    lines.append(f"- **Total changed files**: {scope_result.total_changed_files}")
    if scope_result.exceeded_file_limit:
        lines.append("  - ⚠️ **Exceeded configured file count limit**")
    if scope_result.has_violations:
        lines.append("- **Scope Status**: ❌ **Violations detected**")
    else:
        lines.append("- **Scope Status**: ✅ **Clean (all changes within allowed scope)**")
    lines.append("")

    if not scope_result.changes:
        lines.append("No file changes detected between baseline and current snapshot.")
    else:
        lines.append("| Path | Change | Scope Finding | Reason |")
        lines.append("| --- | --- | --- | --- |")
        finding_map = {f.path: f for f in scope_result.findings}
        for change in scope_result.changes:
            finding = finding_map.get(change.path)
            if finding is None:
                scope_badge = "Unknown"
                reason = "No finding recorded"
            elif finding.restricted:
                scope_badge = "❌ Restricted"
                reason = finding.reason
            elif not finding.allowed:
                scope_badge = "❌ Not Allowed"
                reason = finding.reason
            else:
                scope_badge = "✅ Allowed"
                reason = finding.reason or "Within allowed paths"

            lines.append(
                f"| `{change.path}` | `{change.change_type.value}` | {scope_badge} | {reason} |"
            )
    lines.append("")

    # Verification Evidence Table
    lines.append("## Verification Evidence")
    lines.append("")
    if not evidence:
        lines.append("No verification evidence records recorded for this session.")
    else:
        lines.append("| Gate ID | Provider | Status | Exit Code | Duration | Freshness | Summary |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for rec in evidence:
            is_fresh = _is_snapshot_fresh(rec.snapshot_after, snapshot.snapshot_id)
            freshness_badge = "fresh" if is_fresh else "stale"
            if rec.status == EvidenceStatus.PASSED:
                status_badge = "✅ PASSED"
            elif rec.status == EvidenceStatus.FAILED:
                status_badge = "❌ FAILED"
            else:
                status_badge = f"⚠️ {rec.status.value.upper()}"

            clean_summary = rec.summary.replace("\n", " ").strip()
            if len(clean_summary) > 60:
                clean_summary = clean_summary[:57] + "..."

            lines.append(
                f"| `{rec.gate_id}` | {rec.provider_name} | {status_badge} | {rec.exit_code} | "
                f"{rec.duration_ms}ms | {freshness_badge} | {clean_summary} |"
            )
    lines.append("")

    # Reasons & Blockers
    lines.append("## Reasons & Blockers")
    lines.append("")
    if verdict.reasons:
        for reason in verdict.reasons:
            lines.append(f"- {reason}")
    else:
        lines.append("- None")
    lines.append("")

    # Handoff / Next Actions
    lines.append("## Next Actions")
    lines.append("")
    if verdict.verdict == VerdictOutcome.ALLOW:
        lines.append("✅ **All criteria and gates passed with fresh evidence and clean scope.**")
        lines.append("Task is ready for review and integration.")
    elif verdict.verdict == VerdictOutcome.REQUIRE_APPROVAL:
        lines.append("⚠️ **Task requires human review and explicit approval before continuing.**")
    else:
        lines.append("❌ **Task is blocked.**")
        lines.append("Resolve the blockers listed above and re-evaluate verification before merge.")
    lines.append("")

    return "\n".join(lines)


def export_json_receipt(
    session: Session,
    task: TaskRevision,
    snapshot: RepoSnapshot,
    scope_result: ScopeAnalysisResult,
    evidence: Sequence[EvidenceRecord],
    verdict: VerdictRecord,
) -> dict[str, Any]:
    """Export a canonical JSON-serializable receipt with entity fields and tamper-evident digest.

    Args:
        session: Active session.
        task: Active task revision contract.
        snapshot: Current repository snapshot.
        scope_result: Scope analysis result between baseline and current snapshot.
        evidence: Sequence of verification evidence records.
        verdict: Evaluated verdict record.

    Returns:
        Canonical dictionary serializable to JSON.
    """
    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "receipt_id": f"rcpt-{uuid.uuid4().hex[:12]}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "digest_type": "integrity_checksum",
        "digest_description": "Unkeyed SHA-256 integrity digest over canonical JSON fields. Not an identity digital signature.",
        "session": session.model_dump(mode="json"),
        "task": task.model_dump(mode="json"),
        "snapshot": {
            "snapshot_id": snapshot.snapshot_id,
            "repo_root": snapshot.repo_root,
            "git_commit": snapshot.git_commit,
            "git_dirty": snapshot.git_dirty,
            "captured_at": snapshot.captured_at.isoformat(),
            "file_count": len(snapshot.files),
            "files": [f.model_dump(mode="json") for f in snapshot.files],
        },
        "scope": scope_result.model_dump(mode="json"),
        "evidence": [e.model_dump(mode="json") for e in evidence],
        "verdict": verdict.model_dump(mode="json"),
    }

    # Compute deterministic receipt digest over canonical content (excluding receipt_digest itself)
    canonical_repr = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    receipt_digest = f"sha256:{hashlib.sha256(canonical_repr.encode('utf-8')).hexdigest()}"
    receipt["receipt_digest"] = receipt_digest

    return receipt
