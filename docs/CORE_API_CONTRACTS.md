# ProofMesh Core API Contracts

This document establishes the frozen runtime contracts, type signatures, and file ownership boundaries for parallel feature development across subagents.

---

## 1. File Ownership Boundaries

Each implementation subagent owns **only** their designated files and tests. No subagent may modify shared models (`src/proofmesh/models/`), shared storage (`src/proofmesh/storage/`), or another agent's modules.

| Agent | Module Responsibilities | Test Ownership |
|---|---|---|
| **Agent A** (TaskFile & Service) | `src/proofmesh/core/taskfile_md.py`<br>`src/proofmesh/core/task_service.py` | `tests/test_taskfile.py` |
| **Agent B** (Repo Snapshot) | `src/proofmesh/core/repo_snapshot.py` | `tests/test_repo_snapshot.py` |
| **Agent C** (Scope Analyzer) | `src/proofmesh/core/scope_analyzer.py` | `tests/test_scope_analyzer.py` |
| **Agent D** (Verification & Freshness) | `src/proofmesh/core/verification.py`<br>`src/proofmesh/providers/pytest_runner.py` | `tests/test_verification.py` |
| **Agent E** (Evaluator, Loop & Handoff) | `src/proofmesh/core/evaluator.py`<br>`src/proofmesh/core/loop_detector.py`<br>`src/proofmesh/core/handoff.py` | `tests/test_evaluator.py` |
| **Agent F** (Read-Only Auditor) | Independent audit, verification & security review | None (read-only) |
| **Main Agent** | `src/proofmesh/models/`<br>`src/proofmesh/storage/`<br>`src/proofmesh/cli.py`<br>`src/proofmesh/demo.py`<br>`src/proofmesh/adapters/` | Integration tests |

---

## 2. Shared Data Models (Import from `proofmesh.models`)

All models inherit from `FrozenModel` and enforce strict validation and immutability:

- **Task & Policy Models**:
  - `TaskRevision(task_id, revision, parent_revision, summary, acceptance_criteria, scope, required_gates, constraints, risk_level, approval_status, approved_by, approved_at, contract_digest, raw_markdown)`
  - `AcceptanceCriterion(criterion_id, description, required_gates)`
  - `ScopePolicy(allow_paths, restricted_paths, max_changed_files)`
  - `TrustedPolicy(schema_version, profile, budget, scope, gates, advisor)`
  - `GatePolicy(provider, command, timeout_seconds, mandatory)`
  - `BudgetPolicy(max_retries, max_continuation_steps, max_changed_files)`

- **Snapshot Models**:
  - `FileFingerprint(path: str, sha256: Sha256Digest, size_bytes: int, is_tracked: bool)`
  - `RepoSnapshot(snapshot_id: Sha256Digest, repo_root: str, git_commit: str | None, git_dirty: bool, files: tuple[FileFingerprint, ...], captured_at: datetime)`
  - Helper methods: `snapshot.get_file(path) -> FileFingerprint | None`, `snapshot.file_paths -> set[str]`

- **Scope Models**:
  - `ScopeChangeType`: `"added"`, `"modified"`, `"deleted"`
  - `PathChange(path: str, change_type: ScopeChangeType, old_sha256: str | None, new_sha256: str | None)`
  - `ScopeFinding(path: str, allowed: bool, restricted: bool, reason: str)`
  - `ScopeAnalysisResult(baseline_snapshot_id, current_snapshot_id, changes, findings, total_changed_files, exceeded_file_limit, has_violations)`

- **Evidence & Verdict Models**:
  - `EvidenceRecord(evidence_id, session_id, contract_revision, gate_id, acceptance_criteria, provider_name, provider_version, config_digest, started_at, ended_at, duration_ms, snapshot_before, snapshot_after, status, exit_code, summary, invalidation_reason)`
  - `EvidenceStatus`: `"passed"`, `"failed"`, `"not_run"`, `"unknown"`, `"stale"`
  - `VerdictRecord(verdict_id, session_id, contract_revision, snapshot_id, verdict, enforcement_level, reasons, evidence_ids, evaluated_at)`
  - `VerdictOutcome`: `"allow"`, `"warn"`, `"block"`, `"require_approval"`, `"unknown"`

---

## 3. Function Signatures & Semantics

### Agent A: `taskfile_md.py` & `task_service.py`
- `parse_taskfile(content: str, known_gates: set[str] | None = None) -> TaskRevision`:
  - Front matter TOML delimited by `+++ ... +++`.
  - Required fields: `task_id`, `version` (int), `summary`, `risk_level`, `allow_paths`, `restricted_paths`.
  - Markdown body: Section `## Acceptance criteria` with list format: `- [AC-1] description (gates: test, lint)`.
  - Computes `contract_digest` deterministically: `sha256:` + hex hash over canonical JSON of content fields.
  - Rejects unknown gate IDs if `known_gates` provided.
  - Rejects oversized content (> 64 KiB).
- `TaskService(store: ProofMeshStore)`:
  - `propose_task(task_id: str, content: str, project_id: str, known_gates: set[str] | None = None) -> TaskRevision`: parses, sets `approval_status=ApprovalStatus.PROPOSED`, saves to store.
  - `approve_task(task_id: str, revision: int, approved_by: str, reason: str | None = None) -> TaskRevision`: marks `ApprovalStatus.APPROVED`, records `approved_at` (UTC) and `approved_by`, updates in store.
  - `propose_amendment(task_id: str, content: str, project_id: str, known_gates: set[str] | None = None) -> TaskRevision`: loads active approved revision `N`, parses new content as revision `N+1`, sets `parent_revision=N`, `approval_status=ApprovalStatus.PROPOSED`, saves without mutating `N`.
  - `get_active_revision(task_id: str) -> TaskRevision | None`: returns highest revision with `ApprovalStatus.APPROVED`.

### Agent B: `repo_snapshot.py`
- `capture_snapshot(repo_root: Path | str, exclude_patterns: Sequence[str] | None = None) -> RepoSnapshot`:
  - Resolves `repo_root`. Ignores `.git/` directory and any subpaths matching `exclude_patterns`.
  - Runs `git rev-parse HEAD` and `git status --porcelain` to capture `git_commit` and `git_dirty` (handles non-git repo safely with `git_commit=None`, `git_dirty=False`).
  - Collects relative POSIX paths of all files. Reads content bytes and computes `sha256:<64-hex>`.
  - Computes `snapshot_id`: `sha256:` of concatenated, sorted `"path:sha256\n"` records.
  - Safe against symlinks escaping `repo_root` (skips or flags symlinks that resolve outside `repo_root`).

### Agent C: `scope_analyzer.py`
- `analyze_scope(baseline: RepoSnapshot, current: RepoSnapshot, policy: ScopePolicy) -> ScopeAnalysisResult`:
  - Compares file paths and hashes between `baseline` and `current`.
  - Classifies paths as `ADDED`, `MODIFIED`, `DELETED`.
  - For each changed path, checks `fnmatch` against `policy.allow_paths` and `policy.restricted_paths`.
  - If a path matches `restricted_paths` -> `restricted=True`, `allowed=False`, `reason="Matches restricted path pattern '...'"`
  - If a path does not match any `allow_paths` -> `allowed=False`, `reason="Not covered by allow_paths"`
  - Checks if `total_changed_files > policy.max_changed_files` (if configured) -> `exceeded_file_limit=True`.
  - Sets `has_violations = True` if any change is not allowed, or is restricted, or limit exceeded.

### Agent D: `verification.py`
- `run_gate(gate_id: str, gate_policy: GatePolicy, repo_root: Path | str, session_id: str, contract_revision: int, snapshot_before: RepoSnapshot, acceptance_criteria: tuple[str, ...] = ()) -> EvidenceRecord`:
  - Executes `gate_policy.command` as argument list using `subprocess.run(..., shell=False, timeout=gate_policy.timeout_seconds, cwd=repo_root, capture_output=True)`.
  - Takes `snapshot_after = capture_snapshot(repo_root)`.
  - Handles `TimeoutExpired` -> status=`FAILED`, exit_code=-1, summary="Timeout after X seconds".
  - Handles `FileNotFoundError` -> status=`FAILED`, exit_code=-2, summary="Executable not found: ...".
  - Caps stdout/stderr in summary to 2000 chars.
  - Generates stable `evidence_id = f"ev-{uuid.uuid4().hex[:12]}"`.
- `check_evidence_freshness(evidence: EvidenceRecord, current_snapshot: RepoSnapshot) -> bool`:
  - Returns `True` if `evidence.snapshot_after == current_snapshot.snapshot_id`.
  - Returns `False` if snapshot IDs differ (meaning code changed after verification).

### Agent E: `evaluator.py`, `loop_detector.py`, `handoff.py`
- `evaluate_session(session: Session, task_revision: TaskRevision, current_snapshot: RepoSnapshot, evidence_records: Sequence[EvidenceRecord], scope_result: ScopeAnalysisResult, policy: TrustedPolicy) -> VerdictRecord`:
  - Checks scope: if `scope_result.has_violations` -> verdict is `BLOCK` or `REQUIRE_APPROVAL` with reasons listing violations.
  - Checks gates: for each gate in `task_revision.required_gates`:
    - Finds latest evidence for `gate`.
    - If missing -> `BLOCK`, reason: `f"Missing mandatory evidence for gate '{gate}'"`
    - If status != `PASSED` -> `BLOCK`, reason: `f"Gate '{gate}' failed with exit code ..."`
    - If stale (`evidence.snapshot_after != current_snapshot.snapshot_id`) -> `BLOCK`, reason: `f"Evidence for gate '{gate}' is stale"`
  - If all mandatory gates are `PASSED` & fresh, and scope clean -> verdict is `ALLOW`.
- `LoopDetector`:
  - `record_attempt(session_id: str, gate_id: str, failure_signature: str) -> int`: increments count.
  - `is_budget_exhausted(session_id: str, gate_id: str, budget: BudgetPolicy) -> bool`: returns True if retries >= `budget.max_retries`.
- `generate_handoff(task_revision: TaskRevision, verdict: VerdictRecord, scope_result: ScopeAnalysisResult, evidence_records: Sequence[EvidenceRecord]) -> str`:
  - Returns clean Markdown card summarizing: Status (`BLOCKED` / `ALLOW`), Blockers, Gate Summary, and Next Action.

---

## 4. Wave 2 Component Contracts

### Subagent G: `report.py`, `demo.py`, `cli.py`
- `render_markdown_report(session: Session, task: TaskRevision, snapshot: RepoSnapshot, scope_result: ScopeAnalysisResult, evidence: Sequence[EvidenceRecord], verdict: VerdictRecord) -> str`:
  - Formats human-readable Markdown report: Header, task summary, revision, approval, verdict badge, scope table, verification table, reasons, handoff next steps.
- `export_json_receipt(session: Session, task: TaskRevision, snapshot: RepoSnapshot, scope_result: ScopeAnalysisResult, evidence: Sequence[EvidenceRecord], verdict: VerdictRecord) -> dict[str, Any]`:
  - Formats machine-readable canonical receipt dictionary containing all entity fields and digests.
- `run_seeded_demo(target_dir: Path | str, db_path: Path | str | None = None) -> dict[str, Any]`:
  - Runs deterministic end-to-end scenario: init -> propose -> approve -> snapshot -> allowed change -> verify PASS -> evaluate ALLOW -> restricted change -> evaluate BLOCK -> export receipt.
  - Zero external model or network dependency; runnable cleanly twice from scratch.
- `cli.py`:
  - CLI entry point `proofmesh`: `demo`, `init`, `task propose`, `task approve`, `status`, `verify`, `evaluate`, `report`.

### Subagent H: `hook_protocol.py`, `mcp_server.py`, `antigravity.py`
- `hook_protocol.py`:
  - Parses host lifecycle hook payloads (`PreInvocation`, `PreToolUse`, `Stop`).
  - PreToolUse: denies out-of-scope/restricted edits with actionable reason.
  - Stop: returns `continue` if session has unfulfilled gates or is `BLOCK`.
- `mcp_server.py`:
  - Exposes official MCP tools: `get_task_contract`, `inspect_changes`, `run_verification`, `get_status`, `claim_completion`, `get_handoff`.
  - Invokes core services (`proofmesh.core`); zero duplicated policy logic.
- `antigravity.py`:
  - Connects Antigravity host hook payloads to ProofMesh engine.

---

## 5. Stabilization & PRD Conformance Contracts (Pre-Parallel Work)

### 5.1 Trusted Policy Loading, Identification, and Session Pinning
- **Resolver**: Single authoritative resolver in `proofmesh.config`:
  `resolve_trusted_policy(policy_path_override: Path | str | None = None) -> tuple[TrustedPolicy, Sha256Digest]`
- **Resolution Order**:
  1. `policy_path_override` if explicitly passed by programmatic caller.
  2. `PROOFMESH_POLICY` environment variable if set (pointing to an external trusted TOML file strictly outside the target workspace).
  3. Packaged default policy from `proofmesh.resources/default-policy.toml`.
  - Target workspace-internal `policy.toml` is **not** trusted after agent execution starts.
- **Canonical Digest**:
  - `policy_digest = f"sha256:{hashlib.sha256(json.dumps(policy.model_dump(mode='json'), sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()}"`
  - All-zero placeholder digests are rejected.
  - `session.policy_digest` is pinned on session creation.
  - Every evaluation, verification, and completion claim verifies `current_policy_digest == session.policy_digest`. Mismatches trigger `UNKNOWN` or `BLOCK`.

### 5.2 Explicit Representation of Incomplete Repository Observation
- **`RepoSnapshot` Fields**:
  - `complete: bool = True`
  - `observation_errors: tuple[str, ...] = Field(default_factory=tuple)`
- **Observation Failure Semantics**:
  - Symlink escaping `repo_root`, cyclic symlink loops, unreadable files (`PermissionError`/`OSError`), or failed/timed-out Git subprocesses add an error entry to `observation_errors` and set `complete = False`.
  - External symlinks are never followed outside `repo_root`.
  - If `snapshot.complete` is `False`, the Evaluator fails closed (`BLOCK` or `UNKNOWN`) and cannot evaluate to `ALLOW`.

### 5.3 Evidence Eligibility for Evaluator
Evidence is only eligible for evaluation if:
1. `evidence.session_id == session.session_id`
2. `evidence.contract_revision == session.contract_revision`
3. `evidence.gate_id` exists in the union of `task_revision.required_gates` and `trusted_policy.gates` (mandatory gates).
4. `evidence.config_digest` matches the gate policy digest in `trusted_policy.gates`.
5. `evidence.snapshot_after == current_snapshot.snapshot_id` (code-bound snapshot freshness).
6. Incomplete snapshots (`current_snapshot.complete is False`) disqualify passing evaluations.
7. Only the latest eligible evidence record per gate (by `ended_at`) is evaluated.

### 5.4 Project and Workspace Session Resolution
- Every session lookup must be scoped by `(project_id, repo_root)`.
- `ProofMeshStore.get_session(session_id, project_id=None, repo_root=None)`:
  Validates that `session_id` belongs to `project_id` and `repo_root`. Mismatched project/directory returns `None` or raises `ValueError`.
- `ProofMeshStore.get_active_session_for_project(project_id, repo_root=None)`:
  Queries the latest active session explicitly filtered by `tasks.project_id = ?` and `sessions.repo_root = ?`.
- Picking the latest row from `sessions` without project and workspace validation is strictly forbidden.

### 5.5 Verdict Terminology & Presentation Mapping
- **Internal / Domain Model (`VerdictOutcome`)**:
  - `ALLOW = "allow"`
  - `BLOCK = "block"`
  - `REQUIRE_APPROVAL = "require_approval"`
  - `WARN = "warn"`
  - `UNKNOWN = "unknown"`
- **Presentation / Report Mapping**:
  - `ALLOW` -> `ACCEPTED` (Badge: `✅ ALLOW / ACCEPTED`)
  - `BLOCK` -> `BLOCKED` (Badge: `❌ BLOCK / BLOCKED`)
  - `REQUIRE_APPROVAL` -> `NEEDS_APPROVAL` (Badge: `⚠️ REQUIRE_APPROVAL / NEEDS_APPROVAL`)
  - `UNKNOWN` -> `UNKNOWN` (Badge: `❓ UNKNOWN`)

### 5.6 Continuation / Retry Budgets Surviving Invocations
- Loop failure attempts are tracked by `(session_id, gate_id, failure_signature)` and persisted in SQLite.
- Duplicate event deliveries (same host turn or identical evidence) do not consume budget.
- Once retries reach `budget.max_retries`:
  - `LoopDetector.is_budget_exhausted()` returns `True`.
  - Stop hook allows host termination (`allow`) to prevent infinite model loops, but ProofMesh retains `VerdictOutcome.BLOCK` with handoff explaining budget exhaustion.
