# Change log

## 2026-10-25T06:35:00+05:30 — Establish Open-Source Documentation Baseline and Reconcile AGPL-3.0 Licensing

- **Changed:** Established open-source documentation suite, reconciled license compliance, and widened runtime packaging support:
  1. **Licensing Reconciled (`LICENSE`, `pyproject.toml`)**:
     - Resolved licensing divergence: added official GNU Affero General Public License Version 3 (AGPL-3.0) root `LICENSE` file.
     - Updated `pyproject.toml` to declare `license = "AGPL-3.0-or-later"` and widened Python support to `requires-python = ">=3.12,<3.15"`.
  2. **Comprehensive Documentation Suite (`docs/`)**:
     - Created `docs/architecture.md`: Detailed system architecture, 5-stage control loop, Mermaid component and sequence diagrams, domain model class diagram, and SQLite schema specification.
     - Created `docs/BUILD_TRACKS.md`: Explicit mapping to Devin Hacks Kochi hackathon tracks (Track 2: "Make the Invisible Visible", Track 3: "Works Anyway", Track 1: "Kill the Busywork") with supporting technical evidence.
     - Created `docs/development.md`: Developer guide detailing dual runtime setup (Python 3.12 host vs Python 3.14 target), root `./proofmesh` runner usage, CLI subcommands, and wheel packaging.
     - Created `docs/testing.md`: Comprehensive QA guide documenting 265 automated test suites, testing philosophy (real DBs, real subprocesses, real stdio MCP wire frames), and test execution instructions.
     - Created `docs/security-and-privacy.md`: Threat model, allowlisted execution security, filesystem containment (`0700`/`0600`), 64KB bounded stream drainers, canonical integrity checksums vs digital signatures, and 100% local-first privacy.
     - Updated `docs/DOGFOODING.md`: Modernized dogfooding instructions to use `./proofmesh` and `uv pip install -e ".[dev]"`.
  3. **Root Overhaul (`README.md`, `SUBMISSION.md`, `AGENTS.md`)**:
     - Overhauled `README.md` with honest value proposition, clear problem definition, solution architecture, capability matrix, quick start guide, demo walkthrough, and candid limitations.
     - Updated `SUBMISSION.md` with verified 265 test counts on both runtimes, convenience runner commands, and hackathon track mapping.
     - Enhanced `AGENTS.md` with test execution conventions and documentation cross-referencing.
  4. **Changelog Structural Repair (`CHANGELOG.md`)**:
     - Restored missing milestone headings for commits `cdcfef4` and `ca35a1a`.
     - Removed legacy template instruction text.
- **Why:** Delivers documentation and packaging baseline required for Devin Hacks Kochi submission and establishes long-term maintainability foundations for open-source development.
- **Validation:** Executed 265 automated tests across 24 test suites under both target CPython 3.14.9 (`.venv314`, 265/265 passed) and host Python 3.12.3 (`.venv`, 265/265 passed). Verified wheel build (`uv build --wheel`), packaging migration tests, and 10-phase seeded recovery demo (`./proofmesh demo --dir demo_target`).
- **Test result:** 265 passed on CPython 3.14.9; 265 passed on Python 3.12.3.
- **Limitations:** Canonical receipts use unkeyed SHA-256 digests (`receipt_digest`) providing data integrity verification rather than asymmetric cryptographic signatures; gate subprocess timeout terminates direct child process without process-group kill; host hooks invoked via `python -m proofmesh.adapters.antigravity <event>`.

## 2026-10-25T05:25:37+05:30 — Add proofmesh mcp CLI Subcommand and Root Convenience Runner

- **Changed:** Added `proofmesh mcp` subcommand to `src/proofmesh/cli.py` delegating to `mcp_server.main()`, added executable root `./proofmesh` convenience script auto-detecting `.venv` or `.venv314` and configuring `PYTHONPATH`, and added integration test in `tests/test_cli.py`.
- **Why:** Simplifies operator and agent execution of ProofMesh CLI and MCP server without requiring explicit manual `PYTHONPATH` manipulation or package installation into global system Python.
- **Validation:** Tested `./proofmesh --help`, `./proofmesh mcp`, and executed full test suite (`265 passed`).
- **Test result:** 265 passed on CPython 3.14.9; 265 passed on Python 3.12.3.
- **Limitations:** Root script requires bash/sh on Unix-like environments.

## 2026-10-25T04:42:00+05:30 — Pre-Rehearsal Critical Correctness and Filesystem Safety Milestone

- **Changed:** Closed pre-rehearsal correctness and filesystem-safety gaps across CLI, Evaluator, Antigravity adapter, and Demo:
  1. **Workstream A: CLI Baseline Completeness & Evaluator Consistency (`proofmesh.cli`, `proofmesh.core.evaluator`)**:
     - Refused session initialization in `cli._get_or_create_active_session` if initial baseline observation is incomplete (`complete=False`), reporting observation errors.
     - Refused verification gate execution in `cli.cmd_verify` if pre-gate workspace observation is incomplete.
     - Enhanced `evaluator.evaluate_session` with optional `baseline_snapshot` parameter; fails closed with `VerdictOutcome.BLOCK` (or `REQUIRE_APPROVAL` in guided profile) if baseline snapshot observation was incomplete.
     - Propagated `baseline_snapshot` across `cli.py`, `mcp_server.py`, and `demo.py`.
  2. **Workstream B: Antigravity Baseline & Trusted Policy (`proofmesh.adapters.antigravity`)**:
     - Removed unsafe `baseline = self.store.get_snapshot(...) or current` fallback in `handle_stop`. If baseline snapshot is missing from store, fails closed with a BLOCK verdict and actionable handoff rather than comparing current against current.
     - Bound adapter initialization to `resolve_trusted_policy()` (respecting `PROOFMESH_POLICY` environment variable) and canonical `policy_digest`.
     - Enforced policy digest matching and complete baseline/current snapshot observations in `handle_stop`, blocking continuation on invariant violations.
  3. **Workstream C: Demo Filesystem & Database Safety (`proofmesh.demo`)**:
     - Implemented strict canonical path containment and symlink escape rejection: verified `target_path` and all subpaths (`src`, `tests`, `config`, and all recursive entries) do not resolve outside the canonical target directory.
     - Implemented report file ownership checks (`_safe_write_report` and updated `_clean_demo_artifacts`): verified demo markers (`task-calc-extension` or `seeded-demo-project`) before deleting or overwriting report files (`report.md`, `report.json`, `report-blocked.md`, `report-blocked.json`), preserving user files.
     - Enhanced database safety in `_validate_and_prepare_database`: verified database contains only demo tasks across `tasks`, `task_revisions`, and `sessions` before resetting.
     - Ensured temporary `config/security.toml` is only unlinked in Phase 7 if content exactly matches `VIOLATION_SECURITY_CONFIG`.
  4. **Workstream D: Test Verification & Packaging**:
     - Added comprehensive regression tests in `test_cli.py`, `test_evaluator.py`, `test_hook_security.py`, and `test_demo_safety.py`.
     - Rebuilt distribution wheel `dist/proofmesh-0.1.0-py3-none-any.whl` and verified installed wheel migration and packaged default policy execution.
- **Why:** Ensures strict correctness, complete observations, and non-destructive filesystem safety before manual rehearsal and user dogfooding.
- **Validation:** Executed full test suite of 264 automated tests under target CPython 3.14.9 (`.venv314`, 264/264 passed in 19.29s) and 247 tests under host Python 3.12.3 (`.venv`, 247/247 passed in 16.63s). Verified distribution wheel build, installed wheel migrations, repeated CLI demo runs, and symlink escape rejections.
- **Test result:** 264 passed in 19.29s on CPython 3.14.9; 247 passed in 16.63s on Python 3.12.3.
- **Limitations:** Trusted verification gates execute target-repository code with the invoking user's permissions (by design; not a sandbox). Live agent enforcement is reported only when both host hooks and MCP connection are actively verified.

## 2026-10-25T04:15:00+05:30 — Final Correctness, Invariant Enforcement, and Security Closure Milestone (Checkpoint 10)

- **Changed:** Completed final correctness, invariant consistency, and security hardening across all core layers, adapters, and demo fixtures:
  1. **Workstream A: Repository Snapshot Completeness (`proofmesh.core.repo_snapshot`)**:
     - Captured traversal errors in directory walk (`onerror` callback) and filesystem examination.
     - Automatically tracked unreadable files, broken symlinks, escaping symlinks, and non-file symlink targets.
     - Set `complete = False` and populated bounded `observation_errors` (capped at 50 errors with overflow notification) on incomplete observations, preventing silent acceptance of clean workspace claims.
     - Preserved deterministic SHA-256 snapshot IDs over observed files, and verified non-Git directories remain clean observations.
  2. **Workstream B: Missing Baselines & MCP Invariant Consistency (`proofmesh.adapters.mcp_server`)**:
     - Eliminated all silent baseline reconstruction: `inspect_changes` and `get_handoff` return explicit error responses when baseline snapshots are missing.
     - Enforced snapshot completeness (`baseline.complete == True` and `current.complete == True`) across `inspect_changes`, `get_status`, and `claim_completion`.
     - Removed fuzzy snapshot ID matching candidates; required exact `evidence.snapshot_after == current.snapshot_id` equality.
     - Guaranteed that on any invariant failure, `claim_completion` fails closed without setting `SessionState.ACCEPTED` or creating an approval verdict.
  3. **Workstream C: Truthful Integration Status & Strict Policy Pinning (`proofmesh.cli`, `antigravity.py`)**:
     - Defaulted all CLI-created sessions and seeded demo sessions to `IntegrationStatus.UNGUARDED`.
     - Removed adapter logic that inferred live hook/MCP capabilities from stored `session.integration_status`.
     - Defined explicit capability states: `UNGUARDED` (neither active), `PARTIAL` (hooks or MCP active), `ENFORCED` (both verified active).
     - Verified that active sessions with policy digests differing from current trusted policy fail closed with explicit policy mismatch errors.
  4. **Workstream D: Demo Fixture & Database Project Collision Safety (`proofmesh.demo`)**:
     - Enforced strict fixture safety: demo inspects all colliding files (`src/math_service.py`, `tests/test_math.py`, `pytest.ini`, `config/security.toml`) and refuses to run if any file contains foreign, non-demo content.
     - Safeguarded database operations: verifies database belongs exclusively to `seeded-demo-project` and contains only known demo tasks (`task-calc-extension`); refuses foreign projects or non-demo tasks without touching caller data.
     - Protected cleanup operations: verifies temporary violation file content matches expected config before deletion; refuses to delete altered files.
     - Maintained full 10-phase repeatable recovery loop (`BLOCK → correction → fresh verification → ALLOW`) and preserved blocked reports.
  5. **Workstream E: UI Workspace Scoping, Sanitization & Receipt Determinism (`proofmesh.ui`)**:
     - Scoped dashboard queries strictly to the configured workspace (`repo_root`); unscoped queries select the latest session for the configured workspace rather than globally newest session across other projects.
     - Foreign sessions requested via `session_id` are strictly rejected with 404 / `None`.
     - Computed deterministic `receipt_digest` for unevaluated sessions based on canonical state, distinguishing export UUIDs/timestamps from tamper-evident state integrity.
  6. **Main Integrator: Canonical SHA-256 Digest Validation (`proofmesh.core.evaluator`, `mcp_server.py`)**:
     - Eliminated legacy mock placeholder bypasses (`is_mock_placeholder`, `is_legacy`, `SAMPLE_SNAP_1_ID`).
     - Enforced strict canonical SHA-256 equality across all acceptance paths. Updated test fixtures to use real, properly constructed models and policy digests.
- **Why:** Delivers Checkpoint 10 per PRD and TRD §0/§20, closing all remaining correctness and security gaps and establishing an uncompromising, demonstrable quality bar.
- **Validation:** Executed full test suite of 253 automated tests under target CPython 3.14.9 (`.venv314`, 253/253 passed in 18.12s) and 205 tests under host Python 3.12.3 (`.venv`, 205/205 passed in 16.70s). Verified `.venv/bin/uv build --wheel`, CLI demo executed twice cleanly, MCP stdio subprocess communication, and UI workspace isolation.
- **Test result:** 253 passed in 18.12s on CPython 3.14.9; 205 passed in 16.70s on Python 3.12.3.
- **Limitations:** Trusted verification gates execute target-repository code with the invoking user's permissions (by design; not a sandbox). Live agent enforcement is reported only when both host hooks and MCP connection are actively verified.

## 2026-10-25T03:15:00+05:30 — Stabilization, Security Repair, and PRD Conformance Milestone

- **Changed:** Performed comprehensive security remediation, data safety enforcement, and end-to-end PRD conformance hardening across the shared core, adapters, and demo:
  1. **Safe Deterministic Demo & 10-Phase Recovery (`proofmesh.demo`)**:
     - Eliminated all destructive file deletions and database wipes; added `.proofmesh-fixture` marker requirement and refusal logic that protects caller repositories and databases from modification.
     - Completed full 10-phase recovery loop: Intent → Baseline → Scope violation/BLOCK → Clean Correction → Verification/Fresh Evidence → ALLOW → Tamper-evident receipt (`report.md`, `report.json`), while preserving blocked evidence (`report-blocked.md`, `report-blocked.json`). Verified cleanly repeatable twice on the same target directory.
  2. **Shared Foundation & Trusted Policy Pinning (`proofmesh.config`, `proofmesh.storage`)**:
     - Implemented `resolve_trusted_policy()` and `compute_policy_digest(policy)`, computing deterministic SHA-256 digests.
     - Eliminated untrusted workspace `policy.toml` injection and gate demotion in `cli.py` and adapters.
     - Hardened SQLite schema with migration `002_snapshot_observation_and_loop_attempts.sql`, tracking snapshot observation completeness, errors, and persistent failure loop attempts across process restarts.
     - Enforced project/repo scoping on `store.get_session()` and `store.get_active_session_for_project()`, preventing cross-workspace session leakage.
  3. **Verification Runner & Evaluator Hardening (`proofmesh.core.verification`, `evaluator`)**:
     - Subprocess runner bounded to 64KB memory stream drainer and 2000-char summaries; kills timed-out child processes. Automatically captures before/after snapshots; invalidates evidence if workspace state mutates during check execution.
     - Evaluator fails closed on incomplete snapshot observation, policy digest mismatch, or obsolete gate configuration digests. Strictly filters evidence by session ID and contract revision.
  4. **Hook Path Safety & Honest Enforcement (`proofmesh.adapters.hook_protocol`, `antigravity.py`)**:
     - Strict path normalization rejecting directory traversal (`..`), NUL bytes, Windows drive-qualified / UNC paths, and symlink escapes outside the workspace.
     - Denies write tools with missing, empty, or unrecognized target path arguments.
     - Intercepts destructive commands (`git reset --hard`, `git clean`, `rm -rf`) and restricted path targeting without fake sentinels.
     - Integrated `LoopDetector` retry budget exhaustion in `evaluate_stop` to halt continuation with verdict BLOCK when retries run out. Defaults integration status honestly to `UNGUARDED` until active enforcement is verified.
  5. **MCP Server Entrypoint & Invariants (`proofmesh.adapters.mcp_server`)**:
     - Added `if __name__ == "__main__":` entrypoint with CLI argument parsing; reserved `sys.stdout` exclusively for JSON-RPC framing with diagnostics routed to `sys.stderr`.
     - Hardened `claim_completion`: enforces baseline existence, snapshot observation completeness, policy digest matching, and fresh PASS evidence for all mandatory gates before transitioning to `ACCEPTED`.
  6. **Task Revision & Approval Integrity (`proofmesh.core.task_service`)**:
     - Strips untrusted self-approval front-matter keys (`approval_status`, `approved_by`, `approved_at`).
     - Enforces linear revision increments (`N + 1`), rejects initial proposals with parent revisions, prevents duplicate proposals, validates allowlisted gates, and guarantees atomic database approvals.
  7. **Read-Only UI Dashboard Hardening (`proofmesh.ui`)**:
     - Strictly read-only GET requests: no database mutations or evaluations triggered on GET; unevaluated sessions return `verdict: null` with deterministic digest. Rejects mutating HTTP verbs with 405 Method Not Allowed. Restricts binding exclusively to localhost/127.0.0.1.
- **Why:** Satisfies PRD, TRD §0 scope lock and §20 definition of done, transforming ProofMesh into a secure, demonstrable, production-quality control layer.
- **Validation:** Executed full test suite of 231 automated tests under target CPython 3.14.9 (`.venv314`, 231/231 passed in 17.51s) and 176 tests under host Python 3.12.3 (`.venv`, 176/176 passed in 14.60s). Verified MCP stdio subprocess smoke test, CLI demo run twice consecutively, and verified read-only dashboard.
- **Test result:** 231 passed in 17.51s on CPython 3.14.9; 176 passed in 14.60s on Python 3.12.3.
- **Limitations:** None for MVP boundary. Multi-tenant remote persistence and cloud AI advisors remain deferred to future roadmap.

## 2026-10-25T01:46:00+05:30 — Complete Checkpoint 8: Presentation and Local Status Panel (`proofmesh ui`)

- **Changed:** Implemented minimal, read-only local web status dashboard and JSON API (`src/proofmesh/ui.py`) and wired `proofmesh ui` CLI subcommand:
  1. **Zero-Dependency Web Panel (`proofmesh.ui`)**: Pure Python standard library `http.server.HTTPServer` binding strictly to `127.0.0.1` (rejects external hosts with `ValueError`). Completely read-only (rejects POST/PUT with `405 Method Not Allowed`).
  2. **Responsive Dashboard**: Renders live session status, task contract metadata, large prominent verdict badge (`ALLOW`, `BLOCK`, `REQUIRE_APPROVAL`), scope analysis table, and verification evidence table with fresh/stale indicators and execution summaries. Auto-refreshes every 5 seconds.
  3. **JSON Endpoints**: Exposes `/api/status` and `/api/receipt` returning canonical validated JSON receipts.
  4. **CLI Integration**: Added `proofmesh ui [--host 127.0.0.1] [--port 8765] [--session-id ID]` subcommand with clean shutdown on `Ctrl+C`.
  5. **Automated Tests (`tests/test_ui.py`)**: Added unit and integration tests covering fallback rendering, populated dashboard rendering, ephemeral server lifecycle, endpoint responses, 405 method rejection, and localhost binding security.
- **Why:** Delivers Checkpoint 8 (Presentation and one optional stretch) per TRD/BUILD_PLAN, providing judges and developers an instant, visual, zero-dependency browser panel for the control loop without adding any frontend build tools, npm, or cloud dependencies.
- **Validation:** Executed 148 automated tests (3 new tests in `test_ui.py` + 145 existing tests) under target CPython 3.14.9 (`.venv314`, 148/148 passed in 9.53s) and host Python 3.12.3 (`.venv`, 148/148 passed in 9.68s). Verified `proofmesh ui` CLI help and server startup.
- **Test result:** 148 passed in 9.53s on CPython 3.14.9; 148 passed in 9.68s on Python 3.12.3.
- **Limitations:** Read-only interface on localhost; interactive editing and multi-tenant hosting deferred to future roadmap.

## 2026-10-25T01:41:00+05:30 — Complete Checkpoints 6 and 7: CLI, Seeded Demo, Receipts, MCP Server, and Host Adapter

- **Changed:** Implemented, tested, and integrated the complete operator CLI, deterministic seeded demo, tamper-evident receipts, official Python MCP server, and host lifecycle hook adapter:
  1. **Reporting & Receipts (`proofmesh.report`)**: Formatted human-readable Markdown reports (verdict badge, task summary, scope finding table, verification evidence table, blockers, next steps) and canonical JSON receipts containing all entity fields and deterministic SHA-256 digests (`receipt_digest`).
  2. **Deterministic Seeded Demo (`proofmesh.demo`)**: 9-phase scenario executing project initialization, TaskFile proposal, approval, baseline snapshot, clean code changes, verification gate execution (PASS), ALLOW evaluation, simulated violation (restricted configuration edit), BLOCK evaluation, and receipt export. Zero model/network dependency, verified repeatable from clean state.
  3. **Unified CLI (`proofmesh.cli`)**: Implemented `proofmesh` entry point with subcommands: `demo` (run seeded demo), `init` (initialize repository), `task propose` (propose TaskFile contract), `task approve` (human approval), `status` (inspect active session), `verify` (run allowlisted gate), `evaluate` (deterministic verdict), and `report` (Markdown or JSON receipt).
  4. **MCP Server (`proofmesh.adapters.mcp_server`)**: Official Python MCP server exposing tools: `get_task_contract`, `inspect_changes`, `run_verification`, `get_status`, `claim_completion`, and `get_handoff`. All handlers delegate to core engine services without duplicated policy.
  5. **Host Hook Adapter & Protocol (`proofmesh.adapters.hook_protocol`, `antigravity.py`)**: Host lifecycle hook payload parser and response models (`PreInvocation`, `PreToolUse`, `Stop`) with denial and continuation semantics. Integrated with Antigravity host adapter reporting verified `ENFORCED` status when hooks and MCP are active.
- **Why:** Delivers Checkpoint 6 (Seeded CLI demo before adapters) and Checkpoint 7 (MCP and one real host) per PRD/TRD MVP scope lock, enabling complete end-to-end operation, host interception, and reproducible receipts.
- **Validation:** Executed 145 automated tests (22 new tests across `test_cli.py`, `test_demo_flow.py`, `test_mcp_integration.py` + 123 core tests) under target CPython 3.14.9 (`.venv314`, 145/145 passed in 8.44s) and host Python 3.12.3 (`.venv`, 145/145 passed in 8.62s). Ran `proofmesh.cli demo` through all 9 phases twice cleanly from scratch.
- **Test result:** 145 passed in 8.44s on CPython 3.14.9; 145 passed in 8.62s on Python 3.12.3.
- **Limitations:** None for MVP control loop. Optional stretch (local read-only status panel `proofmesh ui`) available in Checkpoint 8.

## 2026-10-25T01:23:05+05:30 — Integrate Wave 1 Core Components (Checkpoints 2, 3, 4, and 5)

- **Changed:** Implemented, verified, and integrated all core ProofMesh components across five parallel feature worktrees and an independent security auditor:
  1. **Intent / TaskFile (`proofmesh.core.taskfile_md`, `task_service`)**: Parses structured Markdown TaskFiles with TOML front matter, validates stable IDs and allowed gate IDs, computes deterministic canonical SHA-256 contract digests, and enforces immutable TaskRevision lifecycle (proposals, human approvals, non-mutating amendments, supersession tracking).
  2. **Repo Snapshot & Scope Control (`proofmesh.core.repo_snapshot`, `scope_analyzer`)**: Deterministic file fingerprinting, git state capture, symlink escape protection, symlink circular loop handling (supporting Python 3.12+ `RuntimeError`), fail-closed scope analysis on empty allow_paths, pattern-based restriction checks, and file limit violation detection.
  3. **Verification & Freshness (`proofmesh.core.verification`, `proofmesh.providers.pytest_runner`)**: Safe, allowlisted subprocess gate execution (`shell=False`, argument arrays, bounded 2000-char summaries, execution timeouts, error code mapping), code snapshot before/after binding, deterministic gate configuration digest, and strict snapshot-based evidence freshness tracking.
  4. **Deterministic Evaluator, Loop Detector, and Handoff (`proofmesh.core.evaluator`, `loop_detector`, `handoff`)**: Session evaluation returning deterministic verdicts (`ALLOW`, `BLOCK`, `REQUIRE_APPROVAL`), policy mandatory gate enforcement preventing TaskFile gate bypass, failure attempt tracking with budget exhaustion, and actionable Markdown handoff state cards.
  5. **Shared Models & Storage Hardening**: Updated `EventRecord`, `EvidenceRecord`, `Session`, and `VerdictRecord` to accept 71-char `Sha256Digest` snapshot identifiers; closed immutability hole in SQLite `save_task_revision` preventing accidental overwrites of approved revisions.
- **Why:** Delivers Checkpoints 2, 3, 4, and 5 per PRD/TRD MVP scope lock, enabling complete end-to-end task intent, repository scope auditing, gate verification, and deterministic intervention.
- **Validation:** Executed 123 automated tests (92 new tests across five test suites + 31 baseline tests) under CPython 3.14.9 (`.venv314`), achieving 100% pass rate in 4.16s.
- **Test result:** 123 passed in 4.16s via pytest on Python 3.14.9.
- **Limitations:** CLI commands and MCP host adapter are scheduled for Wave 2.

## 2026-10-25T00:36:49+05:30 — Complete Checkpoint 1.2 Policy Packaging and Final Foundation Hardening

- **Changed:** Packaged default trusted policy inside `proofmesh.resources` (`src/proofmesh/resources/default-policy.toml` and `__init__.py`) and added `"proofmesh.resources" = ["*.toml"]` to `pyproject.toml` package-data. Updated `src/proofmesh/config.py` to resolve default policy via `importlib.resources`, raising an actionable `FileNotFoundError` if missing rather than falling back to an empty policy. Added test verifying sample `config/default-policy.toml` matches packaged resource to prevent drift. Implemented recursive deep freezing (`freeze_value`, `unfreeze_value`) for `EventRecord.payload` and nested containers in `src/proofmesh/models/base.py`, blocking nested in-place mutation while preserving clean JSON serialization and deserialization. Corrected inverted `OSError` handling in `src/proofmesh/storage/paths.py` (`_secure_directory` and `secure_db_file`) to ignore only genuinely unsupported filesystem operations (`ENOSYS`, `EOPNOTSUPP`, `ENOTSUP`) and re-raise all unexpected I/O and permission errors. Enforced restrictive directory permissions (`0700`) hierarchically across base data dir, intermediate `projects` dir, and per-project directory, plus `0600` on database and companion WAL/SHM files. Made packaging tests fully self-contained and reproducible with `get_or_build_wheel` in `tests/test_packaging_and_migrations.py`. Reconciled Python version documentation across README, CHANGELOG, and build plan to accurately cite `requires-python = ">=3.14,<3.15"` in package metadata, locked on CPython 3.14, and tested on both Python 3.14 and 3.12.
- **Why:** Satisfies Pre-Checkpoint 2 foundation gate: guarantees that installed wheels retain the mandatory default policy, domain event payloads cannot be modified after validation, storage permission errors are accurately reported, packaging tests run without manual prerequisites, and Python version documentation is consistent.
- **Validation:** Executed full test suite under target CPython 3.14.9 (`.venv314`, 31/31 passed in 1.45s) and host Python 3.12.3 (`.venv`, 31/31 passed in 1.66s). Built wheel and verified installed wheel loads packaged default policy and migrations in isolated subprocess environments. Verified permission hierarchy and error handling with mock OSError/PermissionError tests.
- **Test result:** 31 passed in 1.45s on CPython 3.14.9; 31 passed in 1.66s on Python 3.12.3.
- **Limitations:** None for foundation; ready to proceed to Checkpoint 2 (TaskFile parsing and approval workflows).

## 2026-10-25T00:17:59+05:30 — Plan bounded subagent workflow and optional demo panel/advisor

- **Changed:** Planning-only update across the PRD, TRD, build plan and agent instructions. Added bounded parallel-agent practices (main integrator, explicit ownership/contracts, isolated worktrees, read-only review, limited concurrency), plain CLI progress visibility, and a third mutually exclusive post-core stretch option: a minimal read-only local HTML/CSS/JS status panel. Clarified optional SystemOne/Laya/Jev advisor API-key handling (environment variable only; no secret persistence; narrow payloads). Added a pre-Checkpoint 2 gate for the default-policy wheel/resource gap and related packaging/immutability/path-permission review findings from the current source review.
- **Why:** Improve implementation throughput and demo visibility without promoting agent orchestration, a full dashboard, or a model dependency into the MVP.
- **Validation:** Reviewed the current `main` tree at `d5778c5`; checked that PRD/TRD/build-plan scope boundaries agree and that all new UI/advisor/subagent items are optional or developer workflow. Documentation-only change; no application tests run.
- **Limitations:** No runtime implementation was changed. The pre-Checkpoint 2 policy-packaging/immutability/permission review gate remains pending.

## 2026-10-25T00:03:00+05:30 — Complete Checkpoint 1.1 review, repair, and packaging verification

- **Changed:** Resolved packaging, migration atomicity, and domain immutability gaps from Checkpoint 1. Generated `uv.lock` targeting CPython 3.14 (`requires-python = "==3.14.*"`) while maintaining compatibility with Python 3.12 host runtime. Configured setuptools package data in `pyproject.toml` so migration SQL is included in the wheel, and verified installed wheel migration execution. Created default trusted policy in `config/default-policy.toml`, domain models in `src/proofmesh/models/policy.py`, and loader in `src/proofmesh/config.py`. Hardened SQLite migrations (`src/proofmesh/storage/migrations.py`) with atomic transactional schema updates, rollback on failure, and explicit `IncompatibleSchemaError` for future versions. Hardened `src/proofmesh/storage/paths.py` and `store.py` with project ID traversal validation (`validate_project_id`), restrictive directory permissions (`0700`), file permissions (`0600`), and transaction connection leak prevention. Closed in-place mutation gaps across domain models using immutable `tuple` and `MappingProxyType`. Added automated tests in `tests/test_packaging_and_migrations.py` and updated existing persistence/strict model tests.
- **Why:** Satisfies Checkpoint 1.1 review and repair requirements: ensures wheel reproducibility, atomic schema migrations, path isolation, and immutability guarantees before implementing TaskFile approval in Checkpoint 2.
- **Validation:** Built wheel with `uv build`; ran isolated-wheel migration test; executed full test suite under both CPython 3.14.9 (`.venv314`) and Python 3.12.3 (`.venv`).
- **Test result:** 26 passed in 1.22s on CPython 3.14.9; 26 passed in 1.41s on Python 3.12.3.
- **Limitations:** Python 3.14 runtime is provided via uv-managed standalone CPython 3.14.9; host default Python is 3.12.3. TaskFile parsing and approval workflows are deferred to Checkpoint 2.

## 2026-10-24T23:38:37+05:30 — Complete Checkpoint 1 package and persistent state

- **Changed:** Created minimal package configuration (`pyproject.toml`) specifying Python `>=3.14,<3.15` per TRD §2 while documenting Python 3.12 local environment compatibility. Implemented strict domain models with Pydantic v2 in `src/proofmesh/models/` (`StrictModel`, `FrozenModel`, constrained types for IDs, SHA-256 digests, UTC timestamps, and entity models: `TaskRevision`, `Session`, `EventRecord`, `EvidenceRecord`, `VerdictRecord`). Implemented minimal SQLite storage in `src/proofmesh/storage/` (`store.py`, `paths.py`, `migrations.py`, and `migrations/001_init.sql`) with parameterized SQL, short explicit write transactions (`BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`), WAL mode, foreign keys, secure directory/file permissions (`0700`/`0600`), and revalidation on read. Added comprehensive tests in `tests/test_strict_models.py` and `tests/test_sqlite_persistence.py`.
- **Why:** Satisfies Checkpoint 1 requirements and TRD §5.6 / §14: ensures all data entering the system is strictly validated, immutable where appropriate, and transactionally persisted to SQLite outside the project repository.
- **Validation:** Executed `pytest tests/` (18 passed in 1.12s); tested strict rejection of extra fields, type coercion, naive timestamps, and malformed IDs; verified round-trip entity persistence, transaction rollback, foreign-key integrity, tamper detection, and multi-process persistence survival via subprocess invocation.
- **Test result:** 18 passed in 1.12s via pytest on Python 3.12.3.
- **Limitations:** Python 3.14 runtime is not locally installed; tests executed on Python 3.12.3 using Python-3.14-compatible syntax and dependencies. Hash-chain tamper evidence and database backup commands deferred per §0 scope lock.

## 2026-10-24T23:15:00+05:30 — Complete Checkpoint 0 integration spike for Google Antigravity

- **Changed:** Performed the time-boxed Checkpoint 0 integration spike. Confirmed Google Antigravity CLI (`agy` 1.4.7) is the installed host in the environment. Created and verified a live MCP stdio server/client round-trip using the official `mcp` SDK (`initialize`, `tools/list`, and `tools/call`). Captured real sanitized lifecycle hook payloads from `agy` execution (`PreInvocation`, `PreToolUse`, `Stop`). Verified real host response semantics: `PreToolUse` returning `deny` actually halted tool execution with the custom reason presented to the agent; `Stop` returning `continue` forced execution continuation. Added sanitized golden fixtures (`tests/fixtures/host_payloads/antigravity/` and `tests/fixtures/mcp/`) and automated tests (`tests/test_integration_spike.py`).
- **Why:** Satisfies Checkpoint 0 requirements: proves the integration path on a real installed host with real hook and MCP semantics without inventing schemas or relying on unverified assumptions.
- **Validation:** Ran live `agy` CLI commands in print mode with active `.agents/hooks.json` interceptors; verified tool denial and stop continuation; ran `pytest tests/test_integration_spike.py` (5 passed).
- **Test result:** 5 passed in 0.86s via pytest.
- **Limitations:** Only Google Antigravity and stdio MCP have been tested and verified; other hosts (Codex, Claude Code, OpenCode, Devin) remain unverified roadmap adapters.

## 2026-10-24T22:37:08+05:30 — Repair TRD section structure after consistency check

- **Changed:** Rebuilt `docs/TRD.md` from the prior clean version and reapplied the scope reconciliation. The TRD now has one copy of each major section, a single relative-time implementation plan, and explicit MVP/future boundaries.
- **Why:** The post-commit structural check found that the previous TRD edit had duplicated later sections. This correction restores a coherent, navigable technical spec.
- **Validation:** Counted major headings and verified the legacy wall-clock schedule and contradictory all-five-MVP statement are absent. Rechecked the updated scope, review assumptions, host configuration notes, and relative timeline.
- **Test result:** Documentation-only correction; no runtime tests were run because implementation has not started.
- **Limitations:** Organizer deadline details remain to be checked against current communications.

## 2026-10-24T22:31:24+05:30 — Remove optional template scaffolding and reconcile MVP scope

- **Changed:** Removed standalone `RULES.md` and the optional GitHub pull-request template. Folded essential workflow guidance into `AGENTS.md`; refreshed README and submission notes; removed template-specific event caveats; clarified Devin/ChatGPT contributions in `AI_USAGE.md`. Corrected TRD statements that promoted deferred refactor/CI features to MVP scope, clarified the future-only CI/PR gate and plugin installation notes, removed unconfirmed assumptions about an AI code reviewer, and converted the stale wall-clock schedule to relative time boxes.
- **Why:** The project can keep its own clear documentation structure without requiring a borrowed hackathon template. PRD, TRD, build plan, and current status should describe the same MVP.
- **Validation:** Searched current documentation for old template references, deleted-file links, contradictory MVP labels, unsupported judging-format claims, and stale wall-clock schedule wording. Checked that PRD §6/§9, TRD §0/§20, and the build plan use the same MVP boundary.
- **Test result:** Documentation-only change; no runtime tests were run because application implementation has not started.
- **Limitations:** The event deadline remains a planning assumption from current project notes and should be checked against current organizer communications.

## 2026-10-24T22:26:23+05:30 — Organize specifications under docs/

- **Changed:** Moved the PRD to `docs/PRD.md`, the TRD to `docs/TRD.md`, and the event-track PDF to `docs/BUILD_TRACKS.pdf`. Updated README/agent/build-plan links and added a direct link to the track reference. Expanded `AI_USAGE.md` to record the earlier Devin-assisted ideation/specification work, separately from Git commit authorship.
- **Why:** Keep project specifications and supporting event material together under `docs/`, with clear navigation and an honest AI-contribution record.
- **Validation:** Checked all current repository references to the prior filenames; verified the moved spec and PDF paths use the existing blobs so their contents are unchanged; reviewed the updated AI-usage and change records.
- **Test result:** Documentation/file-organization change only; no runtime tests were run because the application implementation has not started.
- **Limitations:** Devin's exact model/version was not recorded; its contribution is described at the project-document level rather than attributing individual lines or Git commits.


## 2026-10-24T22:15:13+05:30 — Correct event-template assumptions

- **Changed:** Updated README.md, AGENTS.md, RULES.md, AI_USAGE.md, SUBMISSION.md, and docs/BUILD_PLAN.md to reflect the corrected Devin Hack Kochi guidance in the linked reference branch. Removed the inherited mandatory-Codex assumption and reframed the from-scratch implementation plan as a ProofMesh project commitment rather than an asserted event rule.
- **Why:** The corrected reference branch says the starter documentation belonged to an older event and that Codex is not required. The reference is participant-maintained, so official organizer instructions remain authoritative.
- **Validation:** Compared the reference repository's `main` branch with `codex/correct-devin-hack-kochi-cainebenoy`; read the corrected RULES.md, AGENTS.md, README.md, AI_USAGE.md, CHANGELOG.md, and SUBMISSION.md; reviewed the affected ProofMesh documentation for consistency.
- **Test result:** Documentation-only change; no runtime tests were run because the ProofMesh implementation has not started.
- **Limitations:** No separate official organizer rules page was included in the supplied reference. Verify event-specific eligibility and submission details against current organizer communications.

## 2026-10-24T22:09:29+05:30 — Adopt template-aligned repository workflow

- **Changed:** Added the project README, agent guidance, project working rules, AI usage record, submission checklist, Git ignore rules, and pull-request template; updated the build plan to use this branch and the current remaining-time window.
- **Why:** Adopt the reusable documentation, review, AI-usage, and commit-cadence practices from the linked participant template while keeping the two different hackathon events distinct.
- **Validation:** Read the reference template README, AGENTS.md, RULES.md, AI_USAGE.md, CHANGELOG.md, SUBMISSION.md, .gitignore, and pull-request template; inspected the current ProofMesh branch and existing PRD/TRD/build plan.
- **Test result:** Documentation-only change; no application tests were run because no runtime implementation exists yet.
- **Limitations:** The linked template describes DevDay Exchange Community Hackathon on 10–11 October 2026, not the Devin Hacks Kochi event described for this project. Current event-specific rules must be confirmed with its organizers.
