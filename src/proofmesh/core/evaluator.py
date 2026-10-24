"""ProofMesh Core Evaluator.

Evaluates session status deterministically against contract revision,
repository snapshot, evidence records, scope analysis, and policy.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Sequence
import uuid

from proofmesh.config import compute_policy_digest
from proofmesh.core.verification import compute_gate_digest
from proofmesh.models import (
    EnforcementLevel,
    EvidenceRecord,
    EvidenceStatus,
    OperatingProfile,
    RepoSnapshot,
    ScopeAnalysisResult,
    Session,
    TaskRevision,
    TrustedPolicy,
    VerdictOutcome,
    VerdictRecord,
)


def _is_snapshot_fresh(evidence_snapshot: str, current_snapshot_id: str) -> bool:
    """Check if evidence snapshot matches the current repository snapshot.

    Requires exact equality between evidence.snapshot_after and current_snapshot.snapshot_id.
    """
    return evidence_snapshot == current_snapshot_id


def evaluate_session(
    session: Session,
    task_revision: TaskRevision,
    current_snapshot: RepoSnapshot,
    evidence_records: Sequence[EvidenceRecord],
    scope_result: ScopeAnalysisResult,
    policy: TrustedPolicy,
    effective_policy_digest: str | None = None,
    baseline_snapshot: RepoSnapshot | None = None,
) -> VerdictRecord:
    """Evaluate session status deterministically against policy, scope, and evidence.

    Args:
        session: Active session being evaluated.
        task_revision: Active approved task revision containing required gates and constraints.
        current_snapshot: Deterministic snapshot of current repository state.
        evidence_records: Sequence of evidence records collected for this session.
        scope_result: Scope analysis result between baseline and current snapshot.
        policy: Project trusted policy.
        effective_policy_digest: Authoritative digest of current trusted policy (optional).
        baseline_snapshot: Optional baseline repository snapshot for observation completeness verification.

    Returns:
        VerdictRecord containing outcome (ALLOW or BLOCK), reasons, fresh evidence IDs,
        and evaluation metadata.
    """
    reasons: list[str] = []
    verdict = VerdictOutcome.ALLOW
    evidence_ids: list[str] = []

    # 1. Snapshot Completeness Checks (fail closed if snapshot observation failed)
    if baseline_snapshot is not None and getattr(baseline_snapshot, "complete", True) is False:
        if policy.profile == OperatingProfile.GUIDED:
            verdict = VerdictOutcome.REQUIRE_APPROVAL
        else:
            verdict = VerdictOutcome.BLOCK
        err_msg = (
            ", ".join(baseline_snapshot.observation_errors)
            if baseline_snapshot.observation_errors
            else "baseline repository snapshot is incomplete"
        )
        reasons.append(f"Incomplete baseline repository snapshot: {err_msg}")

    if getattr(current_snapshot, "complete", True) is False:
        if policy.profile == OperatingProfile.GUIDED:
            verdict = VerdictOutcome.REQUIRE_APPROVAL
        else:
            verdict = VerdictOutcome.BLOCK
        err_msg = (
            ", ".join(current_snapshot.observation_errors)
            if current_snapshot.observation_errors
            else "repository snapshot is incomplete"
        )
        reasons.append(f"Incomplete repository snapshot: {err_msg}")

    # 2. Policy Digest Verification Check
    computed_digest = compute_policy_digest(policy)
    target_digest = (
        effective_policy_digest if effective_policy_digest is not None else computed_digest
    )
    if session.policy_digest != target_digest:
        verdict = VerdictOutcome.BLOCK
        reasons.append(
            f"Policy digest mismatch: session pinned to '{session.policy_digest}', but effective policy digest is '{target_digest}'"
        )

    # 3. Scope Checks
    if scope_result.has_violations:
        verdict = VerdictOutcome.BLOCK
        for finding in scope_result.findings:
            if not finding.allowed or finding.restricted:
                reasons.append(f"Scope violation: {finding.reason}")
        if scope_result.exceeded_file_limit:
            reasons.append(
                f"Scope violation: Exceeded maximum allowed changed files ({scope_result.total_changed_files})"
            )
        if not reasons:
            reasons.append("Scope violation: unapproved repository changes detected")

    # 4. Strictly Filter Evidence Records by Session ID and Contract Revision
    eligible_evidence = [
        e
        for e in evidence_records
        if e.session_id == session.session_id
        and e.contract_revision == task_revision.revision
    ]

    # 5. Mandatory Verification Gate Checks
    mandatory_policy_gates = {
        gate_id
        for gate_id, gate_cfg in policy.gates.items()
        if getattr(gate_cfg, "mandatory", False)
    }
    all_required_gates = sorted(set(task_revision.required_gates) | mandatory_policy_gates)

    for gate in all_required_gates:
        # Find all eligible evidence records for this gate
        gate_evidence = [e for e in eligible_evidence if e.gate_id == gate]

        if not gate_evidence:
            reasons.append(f"Missing mandatory evidence for gate '{gate}'")
            verdict = VerdictOutcome.BLOCK
        else:
            # Take latest evidence record for that gate (sorted by ended_at)
            latest = max(gate_evidence, key=lambda e: e.ended_at)

            # Check gate configuration digest against current policy
            if gate in policy.gates:
                expected_config = compute_gate_digest(policy.gates[gate])
                if latest.config_digest != expected_config:
                    reasons.append(
                        f"Gate '{gate}' configuration digest '{latest.config_digest}' does not match policy digest '{expected_config}'"
                    )
                    verdict = VerdictOutcome.BLOCK

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
            elif latest.invalidation_reason is not None:
                reasons.append(
                    f"Evidence for gate '{gate}' was invalidated: {latest.invalidation_reason}"
                )
                verdict = VerdictOutcome.BLOCK
            else:
                evidence_ids.append(latest.evidence_id)

    # 6. Verdict Finalization
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
