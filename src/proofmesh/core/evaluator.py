"""ProofMesh Core Evaluator.

Evaluates session status deterministically against contract revision,
repository snapshot, evidence records, scope analysis, and policy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence
import uuid

from proofmesh.models import (
    EnforcementLevel,
    EvidenceRecord,
    EvidenceStatus,
    RepoSnapshot,
    ScopeAnalysisResult,
    Session,
    TaskRevision,
    TrustedPolicy,
    VerdictOutcome,
    VerdictRecord,
)


def _is_snapshot_fresh(evidence_snapshot: str, current_snapshot_id: str) -> bool:
    """Check if evidence snapshot matches the current repository snapshot."""
    if evidence_snapshot == current_snapshot_id:
        return True
    if current_snapshot_id.startswith("sha256:"):
        hex_part = current_snapshot_id[7:]
        candidates = {
            f"snap-{hex_part}"[:63],
            hex_part[:63],
            current_snapshot_id.replace(":", "-")[:63],
        }
        if evidence_snapshot in candidates:
            return True
    return False


def evaluate_session(
    session: Session,
    task_revision: TaskRevision,
    current_snapshot: RepoSnapshot,
    evidence_records: Sequence[EvidenceRecord],
    scope_result: ScopeAnalysisResult,
    policy: TrustedPolicy,
) -> VerdictRecord:
    """Evaluate session status deterministically against policy, scope, and evidence.

    Args:
        session: Active session being evaluated.
        task_revision: Active approved task revision containing required gates and constraints.
        current_snapshot: Deterministic snapshot of current repository state.
        evidence_records: Sequence of evidence records collected for this session.
        scope_result: Scope analysis result between baseline and current snapshot.
        policy: Project trusted policy.

    Returns:
        VerdictRecord containing outcome (ALLOW or BLOCK), reasons, fresh evidence IDs,
        and evaluation metadata.
    """
    reasons: list[str] = []
    verdict = VerdictOutcome.ALLOW
    evidence_ids: list[str] = []

    # 1. Scope Checks
    if scope_result.has_violations:
        verdict = VerdictOutcome.BLOCK
        # Report specific findings that are violated
        for finding in scope_result.findings:
            if not finding.allowed or finding.restricted:
                reasons.append(f"Scope violation: {finding.reason}")
        if scope_result.exceeded_file_limit:
            reasons.append(
                f"Scope violation: Exceeded maximum allowed changed files ({scope_result.total_changed_files})"
            )
        if not reasons:
            reasons.append("Scope violation: unapproved repository changes detected")

    # 2. Mandatory Verification Gate Checks
    mandatory_policy_gates = {
        gate_id for gate_id, gate_cfg in policy.gates.items()
        if getattr(gate_cfg, "mandatory", False)
    }
    all_required_gates = sorted(set(task_revision.required_gates) | mandatory_policy_gates)

    for gate in all_required_gates:
        # Find all evidence records for this gate
        gate_evidence = [e for e in evidence_records if e.gate_id == gate]

        if not gate_evidence:
            reasons.append(f"Missing mandatory evidence for gate '{gate}'")
            verdict = VerdictOutcome.BLOCK
        else:
            # Take latest evidence record for that gate (sorted by ended_at)
            latest = max(gate_evidence, key=lambda e: e.ended_at)

            if latest.status != EvidenceStatus.PASSED:
                reasons.append(
                    f"Gate '{gate}' did not pass (status: {latest.status.value}, exit_code: {latest.exit_code})"
                )
                verdict = VerdictOutcome.BLOCK
            elif not _is_snapshot_fresh(latest.snapshot_after, current_snapshot.snapshot_id):
                reasons.append(
                    f"Evidence for gate '{gate}' is stale (snapshot {latest.snapshot_after} != current {current_snapshot.snapshot_id})"
                )
                verdict = VerdictOutcome.BLOCK
            else:
                evidence_ids.append(latest.evidence_id)

    # 3. Verdict Finalization
    if verdict == VerdictOutcome.ALLOW and not reasons:
        reasons = ["All mandatory gates passed with fresh evidence and clean scope"]

    raw_level = (
        session.integration_status.value
        if hasattr(session.integration_status, "value")
        else session.integration_status
    )
    enforcement_level = EnforcementLevel(raw_level)

    verdict_id = f"verd-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    snap_id = current_snapshot.snapshot_id

    try:
        return VerdictRecord(
            verdict_id=verdict_id,
            session_id=session.session_id,
            contract_revision=task_revision.revision,
            snapshot_id=snap_id,
            verdict=verdict,
            enforcement_level=enforcement_level,
            reasons=tuple(reasons),
            evidence_ids=tuple(evidence_ids),
            evaluated_at=now,
        )
    except Exception:
        # Fallback if VerdictRecord schema strictly requires Identifier pattern (no colon, <= 64 chars)
        clean_snap_id = snap_id.replace("sha256:", "snap-")[:63]
        return VerdictRecord(
            verdict_id=verdict_id,
            session_id=session.session_id,
            contract_revision=task_revision.revision,
            snapshot_id=clean_snap_id,
            verdict=verdict,
            enforcement_level=enforcement_level,
            reasons=tuple(reasons),
            evidence_ids=tuple(evidence_ids),
            evaluated_at=now,
        )
