"""Unit and adversarial tests for Evaluator, Loop Detector, and Handoff Card."""

from datetime import datetime, timedelta, timezone

from proofmesh.core.evaluator import evaluate_session
from proofmesh.core.handoff import generate_handoff
from proofmesh.core.loop_detector import LoopDetector
from proofmesh.models import (
    AcceptanceCriterion,
    ApprovalStatus,
    BudgetPolicy,
    EnforcementLevel,
    EvidenceRecord,
    EvidenceStatus,
    GatePolicy,
    IntegrationStatus,
    OperatingProfile,
    PathChange,
    RepoSnapshot,
    RiskLevel,
    ScopeAnalysisResult,
    ScopeChangeType,
    ScopeFinding,
    ScopePolicy,
    Session,
    SessionState,
    TaskRevision,
    TrustedPolicy,
    VerdictOutcome,
    VerdictRecord,
)

SAMPLE_DIGEST = "sha256:" + "a" * 64
SAMPLE_SNAP_0 = "sha256:" + "0" * 64
SAMPLE_SNAP_1 = "sha256:" + "1" * 64
SAMPLE_SNAP_2 = "sha256:" + "2" * 64
SAMPLE_SNAP_1_ID = SAMPLE_SNAP_1.replace("sha256:", "snap-")[:63]


def make_test_session(
    session_id: str = "sess-01",
    task_id: str = "task-01",
    revision: int = 1,
    integration_status: IntegrationStatus = IntegrationStatus.ENFORCED,
) -> Session:
    now = datetime.now(timezone.utc)
    return Session(
        session_id=session_id,
        task_id=task_id,
        contract_revision=revision,
        repo_root="/repo",
        baseline_snapshot_id="snap-0",
        current_snapshot_id="snap-1",
        profile=OperatingProfile.FLOW,
        policy_digest=SAMPLE_DIGEST,
        integration_status=integration_status,
        state=SessionState.ACTIVE,
        started_at=now,
    )


def make_test_task_revision(
    task_id: str = "task-01",
    revision: int = 1,
    required_gates: tuple[str, ...] = ("test-gate",),
) -> TaskRevision:
    ac = AcceptanceCriterion(
        criterion_id="AC-1",
        description="Core logic must work",
        required_gates=required_gates,
    )
    return TaskRevision(
        task_id=task_id,
        revision=revision,
        summary="Test task implementation",
        acceptance_criteria=(ac,),
        scope=ScopePolicy(allow_paths=("src/**",), restricted_paths=(".git/**",)),
        required_gates=required_gates,
        constraints=(),
        risk_level=RiskLevel.MEDIUM,
        approval_status=ApprovalStatus.APPROVED,
        approved_by="tester",
        approved_at=datetime.now(timezone.utc),
        contract_digest=SAMPLE_DIGEST,
    )


def make_test_snapshot(snapshot_id: str = SAMPLE_SNAP_1) -> RepoSnapshot:
    return RepoSnapshot(
        snapshot_id=snapshot_id,
        repo_root="/repo",
        git_commit="abcdef0123456789",
        git_dirty=False,
        files=(),
        captured_at=datetime.now(timezone.utc),
    )


def make_clean_scope_result(
    baseline_id: str = SAMPLE_SNAP_0,
    current_id: str = SAMPLE_SNAP_1,
) -> ScopeAnalysisResult:
    return ScopeAnalysisResult(
        baseline_snapshot_id=baseline_id,
        current_snapshot_id=current_id,
        changes=(
            PathChange(
                path="src/main.py",
                change_type=ScopeChangeType.MODIFIED,
                old_sha256=SAMPLE_DIGEST,
                new_sha256=SAMPLE_DIGEST,
            ),
        ),
        findings=(
            ScopeFinding(
                path="src/main.py",
                allowed=True,
                restricted=False,
                reason="Path is allowlisted",
            ),
        ),
        total_changed_files=1,
        exceeded_file_limit=False,
        has_violations=False,
    )


def make_violation_scope_result(
    baseline_id: str = SAMPLE_SNAP_0,
    current_id: str = SAMPLE_SNAP_1,
) -> ScopeAnalysisResult:
    return ScopeAnalysisResult(
        baseline_snapshot_id=baseline_id,
        current_snapshot_id=current_id,
        changes=(
            PathChange(
                path="restricted/secret.key",
                change_type=ScopeChangeType.MODIFIED,
                old_sha256=SAMPLE_DIGEST,
                new_sha256=SAMPLE_DIGEST,
            ),
        ),
        findings=(
            ScopeFinding(
                path="restricted/secret.key",
                allowed=False,
                restricted=True,
                reason="Matches restricted pattern 'restricted/**'",
            ),
        ),
        total_changed_files=1,
        exceeded_file_limit=False,
        has_violations=True,
    )


def make_test_evidence(
    evidence_id: str = "ev-01",
    session_id: str = "sess-01",
    gate_id: str = "test-gate",
    status: EvidenceStatus = EvidenceStatus.PASSED,
    exit_code: int = 0,
    snapshot_before: str = "snap-0",
    snapshot_after: str = SAMPLE_SNAP_1_ID,
    ended_at: datetime | None = None,
    summary: str = "10 tests passed",
) -> EvidenceRecord:
    now = datetime.now(timezone.utc)
    end = ended_at if ended_at is not None else now
    return EvidenceRecord(
        evidence_id=evidence_id,
        session_id=session_id,
        contract_revision=1,
        gate_id=gate_id,
        acceptance_criteria=("AC-1",),
        provider_name="pytest-runner",
        provider_version="9.1.1",
        config_digest=SAMPLE_DIGEST,
        started_at=end - timedelta(seconds=2),
        ended_at=end,
        duration_ms=2000,
        snapshot_before=snapshot_before,
        snapshot_after=snapshot_after,
        status=status,
        exit_code=exit_code,
        summary=summary,
    )


def make_test_policy() -> TrustedPolicy:
    return TrustedPolicy(
        profile=OperatingProfile.FLOW,
        budget=BudgetPolicy(max_retries=3),
        gates={
            "test-gate": GatePolicy(
                provider="pytest",
                command=("pytest",),
                timeout_seconds=30,
                mandatory=True,
            )
        },
    )


# =============================================================================
# Evaluator Tests
# =============================================================================


def test_evaluate_session_all_mandatory_gates_pass_and_fresh_and_scope_clean():
    """All required gates passed, evidence is fresh, and scope is clean -> ALLOW."""
    session = make_test_session()
    task = make_test_task_revision(required_gates=("test-gate",))
    snapshot = make_test_snapshot(SAMPLE_SNAP_1)
    scope = make_clean_scope_result()
    policy = make_test_policy()

    # Evidence matching current snapshot
    evidence = make_test_evidence(
        evidence_id="ev-01",
        gate_id="test-gate",
        status=EvidenceStatus.PASSED,
        exit_code=0,
        snapshot_after=SAMPLE_SNAP_1_ID,
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[evidence],
        scope_result=scope,
        policy=policy,
    )

    assert isinstance(verdict, VerdictRecord)
    assert verdict.verdict == VerdictOutcome.ALLOW
    assert verdict.enforcement_level == EnforcementLevel.ENFORCED
    assert verdict.contract_revision == 1
    assert "ev-01" in verdict.evidence_ids
    assert len(verdict.reasons) == 1
    assert "All mandatory gates passed with fresh evidence and clean scope" in verdict.reasons[0]


def test_evaluate_session_missing_mandatory_gate():
    """Missing evidence for a mandatory gate -> BLOCK with missing gate reason."""
    session = make_test_session()
    task = make_test_task_revision(required_gates=("test-gate", "lint-gate"))
    snapshot = make_test_snapshot(SAMPLE_SNAP_1)
    scope = make_clean_scope_result()
    policy = make_test_policy()

    # Only test-gate evidence is provided
    evidence = make_test_evidence(
        evidence_id="ev-01",
        gate_id="test-gate",
        status=EvidenceStatus.PASSED,
        snapshot_after="snap-1",
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[evidence],
        scope_result=scope,
        policy=policy,
    )

    assert verdict.verdict == VerdictOutcome.BLOCK
    assert any("Missing mandatory evidence for gate 'lint-gate'" in r for r in verdict.reasons)


def test_evaluate_session_failed_gate():
    """Failed mandatory gate -> BLOCK with exit code and status."""
    session = make_test_session()
    task = make_test_task_revision(required_gates=("test-gate",))
    snapshot = make_test_snapshot(SAMPLE_SNAP_1)
    scope = make_clean_scope_result()
    policy = make_test_policy()

    evidence = make_test_evidence(
        evidence_id="ev-01",
        gate_id="test-gate",
        status=EvidenceStatus.FAILED,
        exit_code=2,
        snapshot_after="snap-1",
        summary="3 of 10 tests failed",
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[evidence],
        scope_result=scope,
        policy=policy,
    )

    assert verdict.verdict == VerdictOutcome.BLOCK
    assert any(
        "Gate 'test-gate' did not pass (status: FAILED, exit_code: 2)" in r
        for r in verdict.reasons
    )


def test_evaluate_session_stale_evidence():
    """Evidence verified against an older snapshot -> BLOCK with staleness reason."""
    session = make_test_session()
    task = make_test_task_revision(required_gates=("test-gate",))
    snapshot = make_test_snapshot(SAMPLE_SNAP_1)
    scope = make_clean_scope_result()
    policy = make_test_policy()

    # Evidence verified against older snapshot 'snap-old'
    evidence = make_test_evidence(
        evidence_id="ev-01",
        gate_id="test-gate",
        status=EvidenceStatus.PASSED,
        exit_code=0,
        snapshot_after="snap-old",
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[evidence],
        scope_result=scope,
        policy=policy,
    )

    assert verdict.verdict == VerdictOutcome.BLOCK
    assert any("Evidence for gate 'test-gate' is stale" in r for r in verdict.reasons)


def test_evaluate_session_scope_violation():
    """Out-of-scope or restricted file modified -> BLOCK with scope violation reason."""
    session = make_test_session()
    task = make_test_task_revision(required_gates=("test-gate",))
    snapshot = make_test_snapshot(SAMPLE_SNAP_1)
    scope = make_violation_scope_result()
    policy = make_test_policy()

    evidence = make_test_evidence(
        evidence_id="ev-01",
        gate_id="test-gate",
        status=EvidenceStatus.PASSED,
        snapshot_after="snap-1",
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[evidence],
        scope_result=scope,
        policy=policy,
    )

    assert verdict.verdict == VerdictOutcome.BLOCK
    assert any("Scope violation:" in r for r in verdict.reasons)
    assert any("restricted/secret.key" in r or "restricted" in r for r in verdict.reasons)


def test_evaluate_session_multiple_blockers_combined():
    """Scope violation AND failed gate AND missing gate all reported in reasons."""
    session = make_test_session()
    task = make_test_task_revision(required_gates=("gate-1", "gate-2", "gate-3"))
    snapshot = make_test_snapshot(SAMPLE_SNAP_1)
    scope = make_violation_scope_result()
    policy = make_test_policy()

    # gate-1 failed, gate-2 stale, gate-3 missing
    ev1 = make_test_evidence(
        evidence_id="ev-01",
        gate_id="gate-1",
        status=EvidenceStatus.FAILED,
        exit_code=1,
        snapshot_after="snap-1",
    )
    ev2 = make_test_evidence(
        evidence_id="ev-02",
        gate_id="gate-2",
        status=EvidenceStatus.PASSED,
        snapshot_after="snap-stale",
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[ev1, ev2],
        scope_result=scope,
        policy=policy,
    )

    assert verdict.verdict == VerdictOutcome.BLOCK
    assert any("Scope violation:" in r for r in verdict.reasons)
    assert any("Gate 'gate-1' did not pass" in r for r in verdict.reasons)
    assert any("Evidence for gate 'gate-2' is stale" in r for r in verdict.reasons)
    assert any("Missing mandatory evidence for gate 'gate-3'" in r for r in verdict.reasons)


def test_evaluate_session_selects_latest_evidence():
    """When multiple evidence records exist for a gate, evaluator picks the latest by ended_at."""
    session = make_test_session()
    task = make_test_task_revision(required_gates=("test-gate",))
    snapshot = make_test_snapshot(SAMPLE_SNAP_1)
    scope = make_clean_scope_result()
    policy = make_test_policy()

    now = datetime.now(timezone.utc)
    older_evidence = make_test_evidence(
        evidence_id="ev-old",
        gate_id="test-gate",
        status=EvidenceStatus.FAILED,
        exit_code=1,
        snapshot_after=SAMPLE_SNAP_1_ID,
        ended_at=now - timedelta(minutes=5),
    )
    newer_evidence = make_test_evidence(
        evidence_id="ev-new",
        gate_id="test-gate",
        status=EvidenceStatus.PASSED,
        exit_code=0,
        snapshot_after=SAMPLE_SNAP_1_ID,
        ended_at=now,
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[older_evidence, newer_evidence],
        scope_result=scope,
        policy=policy,
    )

    assert verdict.verdict == VerdictOutcome.ALLOW
    assert "ev-new" in verdict.evidence_ids
    assert "ev-old" not in verdict.evidence_ids


# =============================================================================
# Loop Detector Tests
# =============================================================================


def test_loop_detector_records_failures_and_counts():
    detector = LoopDetector()

    c1 = detector.record_failure("sess-1", "pytest", "AssertionError: expected 1 got 2")
    assert c1 == 1

    c2 = detector.record_failure("sess-1", "pytest", "AssertionError: expected 1 got 2")
    assert c2 == 2

    # Different signature for same gate
    c_diff = detector.record_failure("sess-1", "pytest", "SyntaxError: invalid syntax")
    assert c_diff == 1

    # Different gate
    c_gate2 = detector.record_failure("sess-1", "lint", "E501 line too long")
    assert c_gate2 == 1


def test_loop_detector_budget_exhaustion():
    detector = LoopDetector()
    budget = BudgetPolicy(max_retries=3)
    sig = "AssertionError: foo != bar"

    assert not detector.is_budget_exhausted("sess-1", "pytest", sig, budget)

    detector.record_failure("sess-1", "pytest", sig)  # 1
    detector.record_failure("sess-1", "pytest", sig)  # 2
    assert not detector.is_budget_exhausted("sess-1", "pytest", sig, budget)

    detector.record_failure("sess-1", "pytest", sig)  # 3
    assert detector.is_budget_exhausted("sess-1", "pytest", sig, budget)

    # Alias record_attempt and 3-arg calling convention
    detector.reset()
    assert not detector.is_budget_exhausted("sess-1", "pytest", budget)
    detector.record_attempt("sess-1", "pytest", sig)
    detector.record_attempt("sess-1", "pytest", sig)
    detector.record_attempt("sess-1", "pytest", sig)
    assert detector.is_budget_exhausted("sess-1", "pytest", budget)


def test_loop_detector_reset():
    detector = LoopDetector()
    detector.record_failure("sess-1", "pytest", "err1")
    detector.record_failure("sess-2", "pytest", "err1")

    # Reset only sess-1
    detector.reset("sess-1")
    assert detector.get_failure_count("sess-1", "pytest", "err1") == 0
    assert detector.get_failure_count("sess-2", "pytest", "err1") == 1

    # Reset all
    detector.reset()
    assert detector.get_failure_count("sess-2", "pytest", "err1") == 0


# =============================================================================
# Handoff Tests
# =============================================================================


def test_generate_handoff_allow_card():
    task = make_test_task_revision(required_gates=("test-gate",))
    scope = make_clean_scope_result()
    ev = make_test_evidence(
        evidence_id="ev-01",
        gate_id="test-gate",
        status=EvidenceStatus.PASSED,
        snapshot_after="snap-1",
    )
    verdict = VerdictRecord(
        verdict_id="verd-allow123",
        session_id="sess-01",
        contract_revision=1,
        snapshot_id="snap-1",
        verdict=VerdictOutcome.ALLOW,
        enforcement_level=EnforcementLevel.ENFORCED,
        reasons=("All mandatory gates passed with fresh evidence and clean scope",),
        evidence_ids=("ev-01",),
        evaluated_at=datetime.now(timezone.utc),
    )

    card = generate_handoff(task, verdict, scope, [ev])

    assert "# Task Handoff: task-01 (rev 1)" in card
    assert "- **Verdict**: ✅ ALLOW" in card
    assert "- **Total changed files**: 1" in card
    assert "All changed files are within allowed scope" in card
    assert "Gate `test-gate`: ✅ **PASSED**" in card
    assert "Ready for final user acceptance or merge" in card


def test_generate_handoff_block_card():
    task = make_test_task_revision(required_gates=("test-gate", "lint-gate"))
    scope = make_violation_scope_result()
    ev = make_test_evidence(
        evidence_id="ev-01",
        gate_id="test-gate",
        status=EvidenceStatus.FAILED,
        exit_code=1,
        snapshot_after="snap-1",
        summary="Test assertions failed",
    )
    verdict = VerdictRecord(
        verdict_id="verd-block123",
        session_id="sess-01",
        contract_revision=1,
        snapshot_id="snap-1",
        verdict=VerdictOutcome.BLOCK,
        enforcement_level=EnforcementLevel.ENFORCED,
        reasons=(
            "Scope violation: Matches restricted pattern 'restricted/**'",
            "Gate 'test-gate' did not pass (status: FAILED, exit_code: 1)",
            "Missing mandatory evidence for gate 'lint-gate'",
        ),
        evidence_ids=(),
        evaluated_at=datetime.now(timezone.utc),
    )

    card = generate_handoff(task, verdict, scope, [ev])

    assert "# Task Handoff: task-01 (rev 1)" in card
    assert "- **Verdict**: ❌ BLOCK" in card
    assert "Scope violations detected" in card
    assert "`restricted/secret.key`" in card
    assert "Gate `test-gate`: ❌ **FAILED**" in card
    assert "Gate `lint-gate`: ⚠️ **MISSING**" in card
    assert "Next Actions" in card
    assert "Revert or adjust out-of-scope or restricted file modifications" in card
    assert "Run mandatory verification gate `lint-gate`" in card
    assert "Fix failing checks for gate `test-gate`" in card


def test_evaluate_session_no_required_gates_scope_clean():
    """Task revision with no required gates and policy with no mandatory gates evaluates to ALLOW."""
    session = make_test_session()
    task = make_test_task_revision(required_gates=())
    snapshot = make_test_snapshot(SAMPLE_SNAP_1)
    scope = make_clean_scope_result()
    policy = make_test_policy().model_copy(update={"gates": {}})

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[],
        scope_result=scope,
        policy=policy,
    )

    assert verdict.verdict == VerdictOutcome.ALLOW
    assert "All mandatory gates passed with fresh evidence and clean scope" in verdict.reasons[0]
    assert len(verdict.evidence_ids) == 0


def test_evaluate_session_policy_mandatory_gate_enforced_even_if_task_omits_it():
    """Policy mandatory gate is enforced even if task_revision.required_gates is empty."""
    session = make_test_session()
    task = make_test_task_revision(required_gates=())  # task attempts to bypass gates
    snapshot = make_test_snapshot(SAMPLE_SNAP_1)
    scope = make_clean_scope_result()
    policy = make_test_policy()  # contains mandatory 'test-gate'

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[],
        scope_result=scope,
        policy=policy,
    )

    assert verdict.verdict == VerdictOutcome.BLOCK
    assert "Missing mandatory evidence for gate 'test-gate'" in verdict.reasons[0]


def test_evaluate_session_exceeded_file_limit():
    """Scope analysis exceeding file limit evaluates to BLOCK."""
    session = make_test_session()
    task = make_test_task_revision(required_gates=())
    snapshot = make_test_snapshot(SAMPLE_SNAP_1)
    scope = ScopeAnalysisResult(
        baseline_snapshot_id=SAMPLE_SNAP_0,
        current_snapshot_id=SAMPLE_SNAP_1,
        changes=(),
        findings=(),
        total_changed_files=75,
        exceeded_file_limit=True,
        has_violations=True,
    )
    policy = make_test_policy().model_copy(update={"gates": {}})

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[],
        scope_result=scope,
        policy=policy,
    )

    assert verdict.verdict == VerdictOutcome.BLOCK
    assert any("Exceeded maximum allowed changed files" in r for r in verdict.reasons)


def test_evaluate_session_multiple_fresh_gates_preserves_evidence_ids():
    """When multiple mandatory gates pass, all evidence IDs are collected in the verdict."""
    session = make_test_session()
    task = make_test_task_revision(required_gates=("gate-1", "gate-2"))
    snapshot = make_test_snapshot(SAMPLE_SNAP_1)
    scope = make_clean_scope_result()
    policy = make_test_policy().model_copy(update={"gates": {}})

    ev1 = make_test_evidence(
        evidence_id="ev-01",
        gate_id="gate-1",
        status=EvidenceStatus.PASSED,
        snapshot_after=SAMPLE_SNAP_1_ID,
    )
    ev2 = make_test_evidence(
        evidence_id="ev-02",
        gate_id="gate-2",
        status=EvidenceStatus.PASSED,
        snapshot_after=SAMPLE_SNAP_1_ID,
    )

    verdict = evaluate_session(
        session=session,
        task_revision=task,
        current_snapshot=snapshot,
        evidence_records=[ev1, ev2],
        scope_result=scope,
        policy=policy,
    )

    assert verdict.verdict == VerdictOutcome.ALLOW
    assert verdict.evidence_ids == ("ev-01", "ev-02")


def test_generate_handoff_stale_gate_display():
    """State card correctly formats a passed but stale gate with actionable refresh step."""
    task = make_test_task_revision(required_gates=("test-gate",))
    scope = make_clean_scope_result()
    ev = make_test_evidence(
        evidence_id="ev-01",
        gate_id="test-gate",
        status=EvidenceStatus.PASSED,
        snapshot_after="snap-older",
    )
    verdict = VerdictRecord(
        verdict_id="verd-stale123",
        session_id="sess-01",
        contract_revision=1,
        snapshot_id=SAMPLE_SNAP_1_ID,
        verdict=VerdictOutcome.BLOCK,
        enforcement_level=EnforcementLevel.ENFORCED,
        reasons=(
            f"Evidence for gate 'test-gate' is stale (snapshot snap-older != current {SAMPLE_SNAP_1_ID})",
        ),
        evidence_ids=(),
        evaluated_at=datetime.now(timezone.utc),
    )

    card = generate_handoff(task, verdict, scope, [ev])

    assert "Gate `test-gate`: ⚠️ **PASSED BUT STALE** (STALE (snapshot: `snap-older`))" in card
    assert "re-run gate on latest snapshot to refresh evidence" in card


def test_generate_handoff_no_required_gates():
    """State card displays clean status when task revision has no required gates."""
    task = make_test_task_revision(required_gates=())
    scope = make_clean_scope_result()
    verdict = VerdictRecord(
        verdict_id="verd-nogates123",
        session_id="sess-01",
        contract_revision=1,
        snapshot_id=SAMPLE_SNAP_1_ID,
        verdict=VerdictOutcome.ALLOW,
        enforcement_level=EnforcementLevel.ENFORCED,
        reasons=("All mandatory gates passed with fresh evidence and clean scope",),
        evidence_ids=(),
        evaluated_at=datetime.now(timezone.utc),
    )

    card = generate_handoff(task, verdict, scope, [])

    assert "No verification gates required for this task revision." in card
    assert "- **Verdict**: ✅ ALLOW" in card

