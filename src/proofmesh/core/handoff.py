"""ProofMesh Handoff State Card Generator.

Generates compact, human- and LLM-readable Markdown state cards summarizing
the current task revision, verdict, scope findings, verification status,
and actionable next steps.
"""

from __future__ import annotations

from typing import Sequence

from proofmesh.core.evaluator import _is_snapshot_fresh
from proofmesh.models import (
    EvidenceRecord,
    EvidenceStatus,
    ScopeAnalysisResult,
    TaskRevision,
    VerdictOutcome,
    VerdictRecord,
)


def generate_handoff(
    task_revision: TaskRevision,
    verdict: VerdictRecord,
    scope_result: ScopeAnalysisResult,
    evidence_records: Sequence[EvidenceRecord],
) -> str:
    """Generate a compact, clear Markdown state card for task handoff.

    Args:
        task_revision: Active task revision.
        verdict: Evaluated verdict record.
        scope_result: Result of scope analysis.
        evidence_records: Collection of verification evidence records.

    Returns:
        Formatted Markdown state card string.
    """
    lines: list[str] = []

    # Header
    verdict_badge = "✅ ALLOW" if verdict.verdict == VerdictOutcome.ALLOW else f"❌ {verdict.verdict.value}"
    lines.append(f"# Task Handoff: {task_revision.task_id} (rev {task_revision.revision})")
    lines.append("")
    lines.append(f"- **Summary**: {task_revision.summary}")
    lines.append(f"- **Verdict**: {verdict_badge}")
    lines.append(f"- **Enforcement Level**: `{verdict.enforcement_level.value}`")
    lines.append(f"- **Snapshot ID**: `{verdict.snapshot_id}`")
    lines.append("")

    # Scope Summary
    lines.append("## Scope Summary")
    lines.append("")
    lines.append(f"- **Total changed files**: {scope_result.total_changed_files}")
    if scope_result.has_violations:
        lines.append("- **Status**: ❌ Scope violations detected")
        for finding in scope_result.findings:
            if not finding.allowed or finding.restricted:
                lines.append(f"  - `{finding.path}`: {finding.reason}")
        if scope_result.exceeded_file_limit:
            lines.append(
                f"  - Total changed files ({scope_result.total_changed_files}) exceeds policy limit."
            )
    else:
        lines.append("- **Status**: ✅ All changed files are within allowed scope")
    lines.append("")

    # Verification Status
    lines.append("## Verification Status")
    lines.append("")
    if not task_revision.required_gates:
        lines.append("No verification gates required for this task revision.")
    else:
        for gate in task_revision.required_gates:
            gate_records = [e for e in evidence_records if e.gate_id == gate]
            if not gate_records:
                lines.append(f"- Gate `{gate}`: ⚠️ **MISSING** (no evidence recorded)")
            else:
                latest = max(gate_records, key=lambda e: e.ended_at)
                is_fresh = _is_snapshot_fresh(
                    latest.snapshot_after, scope_result.current_snapshot_id
                ) or _is_snapshot_fresh(latest.snapshot_after, verdict.snapshot_id)
                freshness_str = "fresh" if is_fresh else f"STALE (snapshot: `{latest.snapshot_after}`)"

                if latest.status == EvidenceStatus.PASSED and is_fresh:
                    lines.append(f"- Gate `{gate}`: ✅ **PASSED** ({freshness_str})")
                elif latest.status == EvidenceStatus.PASSED and not is_fresh:
                    lines.append(f"- Gate `{gate}`: ⚠️ **PASSED BUT STALE** ({freshness_str})")
                else:
                    lines.append(
                        f"- Gate `{gate}`: ❌ **{latest.status.value}** (exit code: {latest.exit_code}, {freshness_str})"
                    )
                    if latest.summary:
                        lines.append(f"  - *Summary*: {latest.summary}")
    lines.append("")

    # Reasons & Blockers
    lines.append("## Reasons & Blockers")
    lines.append("")
    for r in verdict.reasons:
        prefix = "✅" if verdict.verdict == VerdictOutcome.ALLOW else "❌"
        lines.append(f"- {prefix} {r}")
    lines.append("")

    # Next Actions
    lines.append("## Next Actions")
    lines.append("")
    if verdict.verdict == VerdictOutcome.ALLOW:
        lines.append(
            "1. Task is verified and within approved scope. Ready for final user acceptance or merge."
        )
    else:
        step = 1
        if scope_result.has_violations:
            lines.append(
                f"{step}. Revert or adjust out-of-scope or restricted file modifications, or submit a contract amendment."
            )
            step += 1
        for gate in task_revision.required_gates:
            gate_records = [e for e in evidence_records if e.gate_id == gate]
            if not gate_records:
                lines.append(f"{step}. Run mandatory verification gate `{gate}`.")
                step += 1
            else:
                latest = max(gate_records, key=lambda e: e.ended_at)
                is_fresh = _is_snapshot_fresh(
                    latest.snapshot_after, scope_result.current_snapshot_id
                ) or _is_snapshot_fresh(latest.snapshot_after, verdict.snapshot_id)
                if latest.status != EvidenceStatus.PASSED:
                    lines.append(
                        f"{step}. Fix failing checks for gate `{gate}` (exit code {latest.exit_code}) and re-run."
                    )
                    step += 1
                elif not is_fresh:
                    lines.append(
                        f"{step}. Code has changed since gate `{gate}` ran; re-run gate on latest snapshot to refresh evidence."
                    )
                    step += 1

    return "\n".join(lines)
