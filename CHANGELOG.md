# Change log

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


Record meaningful project changes newest first. Use the actual timestamp with timezone. Keep this file updated in the same commit as the change being recorded.

## 2026-10-24T22:09:29+05:30 — Adopt template-aligned repository workflow

- **Changed:** Added the project README, agent guidance, project working rules, AI usage record, submission checklist, Git ignore rules, and pull-request template; updated the build plan to use this branch and the current remaining-time window.
- **Why:** Adopt the reusable documentation, review, AI-usage, and commit-cadence practices from the linked participant template while keeping the two different hackathon events distinct.
- **Validation:** Read the reference template README, AGENTS.md, RULES.md, AI_USAGE.md, CHANGELOG.md, SUBMISSION.md, .gitignore, and pull-request template; inspected the current ProofMesh branch and existing PRD/TRD/build plan.
- **Test result:** Documentation-only change; no application tests were run because no runtime implementation exists yet.
- **Limitations:** The linked template describes DevDay Exchange Community Hackathon on 10–11 October 2026, not the Devin Hacks Kochi event described for this project. Current event-specific rules must be confirmed with its organizers.
