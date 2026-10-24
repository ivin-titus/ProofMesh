# ProofMesh — Technical Requirements Document (TRD)

**Version:** 0.1  
**Status:** Hackathon implementation specification  
**Last updated:** 2026-10-24  
**Target:** Lightweight, local-first prototype proving Intent → Intervention → Evidence with one real agent integration

## 1. Technical objectives

Build a small, agent-neutral core that can:

1. Store an approved task contract and immutable revisions.
2. observe repository changes and available agent lifecycle events;
3. run only trusted, configured verification gates;
4. bind verification results to the task revision and exact relevant code state;
5. detect scope drift, stale evidence, repeated failures, and no-progress loops;
6. produce deterministic completion verdicts;
7. expose the same core through a CLI, MCP tools, and one native hook adapter.

The core must not implement its own model loop, choose which agent writes code, orchestrate agents, or require a web UI to function.

## 2. Recommended implementation stack

- **Language:** Python 3.12+ (or the compatible Python version already available at the event).
- **Models/validation:** Pydantic v2.
- **Persistence:** SQLite; WAL mode for local concurrent reads/writes.
- **MCP:** official MCP Python SDK; pin the SDK version in the lock file and use stable, commonly supported tool primitives.
- **CLI:** Typer or argparse; choose one and avoid excess CLI framework work.
- **Repository observation:** Git CLI plus filesystem fingerprints for untracked files.
- **Checks:** subprocess runner invoking allowlisted commands such as `pytest`, `ruff`, type checks, or a project-specific test script.
- **Optional UI:** minimal local web dashboard only after the core end-to-end flow works. A terminal report is acceptable for MVP.
- **Optional UI verification:** existing Playwright test/script; do not build a browser automation engine.

### Protocol stance

MCP is the interoperable tool-access interface, not an enforcement guarantee. ACP is a potential future client/agent communication integration, not an MVP dependency. The implementation should pin and test a compatible MCP SDK release instead of relying on optional features from the newest protocol version. Start with local stdio transport for the demo; add remote transport and authentication only when needed.

## 3. Architecture

```text
Existing coding-agent harness
  ├── MCP client calls ──────────────┐
  ├── lifecycle hook command ────────┤
  └── optional CLI interaction ──────┤
                                     v
                         ProofMesh adapters
                      (MCP / hook / CLI)
                                     |
                                     v
                         ProofMesh core API
            ┌────────────────────────┼───────────────────────┐
            v                        v                       v
        Intent service          Event monitor          Evidence engine
        TaskFile/revisions      scope/loop/progress     configured checks
            └────────────────────────┼───────────────────────┘
                                     v
                            Policy evaluator
                                     |
                                     v
                          Verdict + handoff record
                                     |
                                     v
                         SQLite + artifacts directory
```

### Layer responsibilities

- **Adapters:** parse input formats native to the host, map events into common models and translate verdicts back to the host's hook response format. No business policy should live only in an adapter.
- **Core services:** task contracts, repo snapshots, policy evaluation, loop detection, check orchestration, context handoffs.
- **Storage:** structured event/evidence/task records in SQLite; large check output and screenshots as bounded artifacts on disk.
- **Check providers:** typed plugins that run a known check and return a structured result. Never accept an arbitrary shell command from model output.

## 4. Proposed repository layout

```text
proofmesh/
  pyproject.toml
  README.md
  config/
    default-policy.yaml
  src/proofmesh/
    __init__.py
    cli.py
    config.py
    models/
      task.py
      events.py
      evidence.py
      verdict.py
    core/
      task_service.py
      repo_snapshot.py
      scope_analyzer.py
      event_monitor.py
      loop_detector.py
      verification.py
      evaluator.py
      handoff.py
    adapters/
      mcp_server.py
      codex_hooks.py
    providers/
      command_check.py
      pytest_check.py
      playwright_check.py   # optional / P1
    storage/
      database.py
      repository.py
  tests/
    test_task_contract.py
    test_scope_analyzer.py
    test_evidence_freshness.py
    test_loop_detector.py
    test_evaluator.py
  demo/
    sample-app/
    taskfile.yaml
    policy.yaml
  .proofmesh/                 # generated local session data; gitignored
```

Keep the structure flexible; if time is tight, combine files rather than spending time scaffolding unused modules.

## 5. Core data model

### 5.1 TaskContract

Required fields:

- `task_id: str`
- `revision: int`
- `parent_revision: int | null`
- `summary: str`
- `acceptance_criteria: list[AcceptanceCriterion]`
- `scope: ScopePolicy`
- `required_gates: list[str]`
- `constraints: list[str]`
- `risk_level: low | medium | high`
- `approval_status: proposed | approved | superseded`
- `approved_by: str | null`
- `approved_at: datetime | null`
- `contract_digest: str`

Each acceptance criterion has stable `criterion_id`, description, and optional gate mappings. Canonicalize the validated model (excluding mutable presentation-only fields) before hashing. An approved revision is never updated in place; amendment creates a new revision. A digest detects content changes but is not a cryptographic user signature.

### 5.2 Session

- `session_id`
- `task_id` and active `contract_revision`
- repository root (resolved canonical path)
- baseline snapshot ID and current snapshot ID
- start/end timestamps
- adapter capability report
- profile and policy digest
- current state: `ACTIVE | IMPLEMENTED | VERIFIED | ACCEPTED | BLOCKED | NEEDS_APPROVAL | UNKNOWN | CLOSED`

### 5.3 EventRecord

- `event_id`, `session_id`, `source_adapter`, `event_type`, `timestamp`
- optional `agent_id`, `parent_agent_id`, host turn/tool ID
- optional command/check signature and exit status
- before/after snapshot IDs when available
- bounded summary and redacted artifact references
- event payload schema version

Do not persist private chain-of-thought. Store observable event metadata and necessary outputs, not a complete model transcript by default.

### 5.4 EvidenceRecord

- `evidence_id`, `session_id`, `contract_revision`
- gate ID and acceptance criteria covered
- check/provider name and version/config digest
- start/end timestamps and duration
- code snapshot ID before check and after check
- status: `PASSED | FAILED | NOT_RUN | UNKNOWN | STALE`
- exit code or structured assertion result
- bounded stdout/stderr summaries and artifact references
- invalidation reason, if stale

If the relevant snapshot changes while or after the check runs, mark the evidence `STALE` unless a provider can prove the changed files are irrelevant. For MVP, use the conservative approach: any source/config fingerprint change during a check invalidates its result.

### 5.5 Verdict

Allowed outcomes:

- `ALLOW` — no current mandatory blockers; action may proceed under policy.
- `WARN` — risks exist but do not block under this policy.
- `BLOCK` — policy requires preventing acceptance.
- `REQUIRE_APPROVAL` — a named human decision is required.
- `UNKNOWN` — required evidence or adapter health is insufficient.

Verdict output includes rule IDs, explanations, evidence IDs, contract revision, code snapshot ID, and enforcement capability. Do not make `UNKNOWN` equivalent to `ALLOW` for mandatory gates.

## 6. TaskFile format and lifecycle

Illustrative schema (the exact shape can be adjusted while keeping semantics stable):

```yaml
version: 1
task_id: "task-1042"
summary: "Add password reset without changing login behavior"
acceptance_criteria:
  - id: AC-1
    description: "A user can request a reset"
    gates: [auth-tests]
  - id: AC-2
    description: "Invalid or expired tokens are rejected"
    gates: [auth-regression]
  - id: AC-3
    description: "Existing login behavior remains unchanged"
    gates: [regression-tests]
scope:
  allowed_paths: ["app/auth/reset/**", "tests/auth/**"]
  restricted_paths: ["database/migrations/**"]
  unexpected_change_policy: "require_justification"
required_gates: ["regression-tests", "auth-tests"]
risk_level: "medium"
```

Lifecycle:

1. `propose` — create a draft from a precise prompt or bounded investigation.
2. `review` — show objective, acceptance criteria, proposed scope, assumptions and risk.
3. `approve` — canonicalize content, calculate digest, store immutable approved revision.
4. `amend` — create a proposed new revision; never overwrite the approved revision.
5. `supersede` — user approves the new revision; older revision remains auditable.

For vague tasks, read-only investigation may happen before approval. The implementation plan and write scope should be approved before implementation begins, except for explicitly authorized low-risk auto-approval policy. Keep user interviews and automatic clarification to consequential ambiguity; do not ask the user about every trivial implementation detail.

## 7. Repository snapshot and scope analysis

### 7.1 Snapshot strategy

At session start:

- Resolve and validate repository root.
- Capture current HEAD and working-tree status.
- Fingerprint tracked source/config files and all non-ignored untracked files relevant to the project.
- Record a baseline manifest without resetting, stashing, or modifying user files.

For the demo, a clean worktree is simplest. If the tree is dirty, preserve the baseline so pre-existing user changes are not misattributed to the agent. Never run `git reset --hard`, destructive checkout, or implicit rollback.

A snapshot ID can be SHA-256 over a canonical manifest of relative path, file mode where relevant, and content digest. Exclude `.git`, environments, caches, build output, dependency directories and generated `.proofmesh` artifacts via an explicit exclusion list. Exclusions must be visible/configurable; do not silently exclude relevant generated or config files.

### 7.2 Scope analysis

- Compare the baseline manifest with the current manifest.
- Identify added, changed, deleted, renamed, and untracked paths.
- Match against approved path patterns and restricted paths.
- Produce findings: `EXPECTED`, `JUSTIFICATION_REQUIRED`, `RESTRICTED`, or `UNKNOWN`.
- Path mismatch is evidence of potential drift, not proof of incorrectness.
- For an unexpected but plausibly related change, request a short justification; if high-risk or explicitly restricted, block or request approval according to policy.

For MVP, path-based rules plus change summaries are adequate. Semantic dependencies and cross-language impact graphs are future work.

## 8. Verification runner

### 8.1 Security contract

Never run arbitrary commands received from an LLM. A model may request a configured `gate_id`; trusted policy maps that ID to a known provider and fixed command/arguments.

Runner requirements:

- Use `subprocess` with argument arrays; avoid `shell=True`.
- Use repository-root containment checks and a controlled working directory.
- Enforce per-gate timeouts, output-size limits and cancellation.
- Capture exit status, duration, bounded output and artifact references.
- Redact likely secrets before persistence or display.
- Do not pass the full environment or credentials to tests unless explicitly required by a trusted configuration.
- Run only the prepared demo repository in the hackathon; later support sandbox/container isolation for untrusted repositories.

### 8.2 Check execution order

Use configured dependencies and cheap-to-expensive ordering:

1. Policy/TaskFile integrity.
2. Scope analysis.
3. Static or syntax checks when configured.
4. Existing unit/regression tests.
5. API/integration checks when configured.
6. Runtime/log checks when a managed test service exists.
7. Browser smoke test only if UI-related paths changed and a browser gate is configured.

A skipped or unavailable check produces `NOT_RUN` or `UNKNOWN`, not `PASSED`. The system must not invent a service URL or claim a runtime check happened if no test environment exists.

### 8.3 Browser verification

Reuse Playwright or an existing configured browser-test provider. Keep one workflow inside a single test run to avoid repeated model-driven browser interactions. Capture assertions, relevant failed requests, console errors and screenshot/trace references on failure.

Trigger browser verification when configured UI paths change. If browser tooling or the app is unavailable, report that UI behavior remains unverified; decide whether this blocks acceptance based on the project's explicit gate policy.

Use test credentials and a separate browser profile. Do not attach personal browser sessions or give untrusted agents unrestricted browser-side code execution.

## 9. Evidence freshness

At minimum, each check records a repository snapshot fingerprint before and after execution. If source files, relevant configuration, test definitions, or the contract change, evidence must be re-evaluated.

MVP conservative rule:

- Any change to a source/config/test path between check start and end => mark that check `STALE`.
- Any subsequent code-state change after a passing check => mark evidence stale at task level and rerun mandatory gates before acceptance.
- Any contract revision change => evidence tied to the prior revision cannot satisfy the new revision without explicit policy saying it remains applicable.

Future enhancement: per-gate dependency fingerprints can avoid rerunning completely unrelated checks. Do not spend hackathon time implementing sophisticated semantic invalidation.

## 10. Loop and compounding-error detector

Use deterministic event/result signals. Do not depend on private model reasoning.

### Inputs

- Consecutive results from the same gate.
- Normalized failure signature (exception class/message, assertion ID, error code, selected stable lines).
- Relevant changed-file and diff fingerprints.
- Number of outstanding failed mandatory gates.
- Whether the newest attempt resolves, introduces, or leaves failures unchanged.
- Hook continuation count and current `stop_hook_active`-style host signal when available.

### Initial policy

- Default repeated-failure threshold: 3 consecutive equivalent failures.
- Default maximum automatic continuation attempts for the same blocking state: 3 (configurable).
- Count progress only when an outstanding failure is resolved or a verifiable state improvement occurs; formatting or unrelated diffs alone are not progress.
- At threshold, stop automatic retries and emit a focused diagnosis/handoff. Keep the task `BLOCKED` or `NEEDS_APPROVAL` if required evidence remains missing.
- Do not keep requesting continuation forever. After budget exhaustion, permit the host turn to finish if required by its hook semantics while retaining a non-accepted verdict in ProofMesh.
- Make evaluation idempotent: the same event and snapshot should not consume retry budget repeatedly.

This is a heuristic, not proof that an agent is in an infinite loop. Provide the failure signature and reason so users can override a false positive.

## 11. Policy evaluator and completion logic

The policy evaluator is deterministic. Given the current contract revision, policy digest, relevant snapshot, evidence records, intervention state and adapter health, it returns a verdict plus reasons.

Baseline decision rules:

1. Unapproved/missing contract => `REQUIRE_APPROVAL` or `UNKNOWN`.
2. Task/policy integrity violation => `BLOCK` or `REQUIRE_APPROVAL` per policy.
3. Mandatory gate `FAILED` => `BLOCK`.
4. Mandatory gate `STALE`, `NOT_RUN`, or `UNKNOWN` => `BLOCK`/`UNKNOWN`; never silently pass.
5. Required integration unhealthy or absent => enforcement state `PARTIAL`/`UNGUARDED`; acceptance decision follows configured policy but must show the limitation.
6. Scope findings that require justification remain unresolved until justified or approved.
7. All mandatory gates current and passed, no unresolved blockers, required approvals complete => `ALLOW` for acceptance; product state may transition to `ACCEPTED`.
8. Agent says “done” without adequate evidence => state `IMPLEMENTED`, not `ACCEPTED`.

Keep two concepts separate: `completion_verdict` and `enforcement_capability`. A valid test result does not imply that the agent was prevented from bypassing the system.

## 12. MCP surface

Keep tool descriptions narrow and input schemas validated. Proposed tools:

- `get_task_contract(task_id, revision?)` — read the approved contract and active digest.
- `propose_contract_amendment(task_id, proposal)` — record a proposal; does not approve it.
- `inspect_changes(session_id)` — return changed paths and scope findings.
- `run_verification(session_id, gate_ids?)` — run configured checks by ID only.
- `get_completion_status(session_id)` — return state, blockers, evidence freshness, and enforcement capabilities.
- `get_evidence(session_id, evidence_ids?)` — return structured summaries and artifact references.
- `generate_handoff(session_id)` — produce the compact, schema-versioned context packet.
- `record_agent_event(session_id, event)` — only if an adapter needs a controlled event-ingestion tool; validate payload and size.

Do not expose `run_shell(command)`, arbitrary filesystem write, unrestricted browser execution, or a tool that lets the model edit approved policy. The MCP server should call the same Python core as the CLI and hooks.

The MCP server should use local stdio transport for the first demo. If remote HTTP transport is introduced later, add authentication, authorization, origin validation, request limits and explicit network exposure controls.

## 13. Agent adapter and hook design

### 13.1 Adapter contract

Each adapter declares capabilities such as:

- Can observe session start/end.
- Can observe tool execution before/after.
- Can observe subagent start/stop and identify subagents.
- Can provide command outputs/transcript references.
- Can request continuation or block a completion event.
- Can enforce command/file policies.

Capabilities are reported as facts, not inferred from MCP availability.

### 13.2 First adapter

Choose one harness that is available and testable at the event. Codex is a practical candidate because its current official documentation includes `Stop` and `SubagentStop` lifecycle hooks. A minimal adapter can:

- call `proofmesh hook <event>` with hook JSON on stdin;
- record an event and compute completion status;
- return the host-specific continuation response when mandatory evidence is missing and retry budget remains;
- prevent repeated hook continuation using host-provided loop flags plus ProofMesh's own attempt budget;
- keep the task non-accepted after the budget is exhausted.

Validate the exact event names, input/output schema and continuation semantics against the installed host version. Hook contracts are host-specific and may evolve. Don't assume all agent harnesses behave like Codex.

### 13.3 Enforcement caveat

MCP-only mode is advisory. A lifecycle hook can request continuation only to the extent the host supports and honors it. Git/CI gates can enforce merge policy independently. A local agent can still claim completion in chat; ProofMesh governs its own acceptance state, not arbitrary text in the host conversation.

## 14. SQLite schema (logical)

Tables to implement:

- `projects(project_id, root_path, created_at)`
- `tasks(task_id, project_id, created_at)`
- `task_revisions(task_id, revision, canonical_json, digest, approval_status, approved_by, approved_at)`
- `sessions(session_id, task_id, revision, baseline_snapshot_id, policy_digest, profile, integration_status, state, started_at, ended_at)`
- `events(event_id, session_id, source, event_type, occurred_at, payload_json, snapshot_before, snapshot_after)`
- `snapshots(snapshot_id, session_id, manifest_digest, manifest_json, captured_at)`
- `evidence(evidence_id, session_id, task_revision, gate_id, provider, status, snapshot_before, snapshot_after, started_at, ended_at, exit_code, summary_json, artifact_refs_json)`
- `verdicts(verdict_id, session_id, evaluated_at, verdict, reasons_json, snapshot_id, contract_revision, enforcement_level)`
- `approvals(approval_id, session_id, action, target_revision, actor, reason, created_at)`

Use schema migrations or a versioned initialization script. Add indexes for `session_id`, timestamps, task/revision, and gate/status lookups. Keep large logs out of SQLite; store bounded artifacts under `.proofmesh/artifacts/` with controlled file names and configured retention.

## 15. CLI commands

Minimum useful commands:

```text
proofmesh init
proofmesh task propose --file task.yaml
proofmesh task approve <task-id> --revision <n>
proofmesh session start <task-id>
proofmesh inspect <session-id>
proofmesh verify <session-id> [--gate <gate-id>]
proofmesh status <session-id>
proofmesh handoff <session-id>
proofmesh hook <event-name>
```

Exact syntax is implementation-flexible. Return meaningful exit codes: `0` accepted/check pass, `1` policy blocker or failed check, `2` invalid configuration/input, `3` unknown/unavailable enforcement or verification state. Document behavior and never collapse `UNKNOWN` into exit code `0`.

## 16. Security and privacy

- Treat repository files, README instructions, logs, test output, MCP tool arguments and agent summaries as untrusted input.
- Separate trusted policy from agent-writable files; record policy digest at session start.
- Validate repository path containment to prevent path traversal and symlink escapes where possible.
- Use allowlisted gates, command argument arrays, timeouts, capped output and minimal environment variables.
- Do not make destructive file changes or automatically roll back the worktree.
- Avoid capturing secrets from environment or logs; redact likely credentials and offer local-only retention.
- Protect artifacts from path traversal; do not allow a model-supplied artifact path to read arbitrary files.
- Local stdio transport avoids exposing a listening network server in MVP; remote transport requires additional controls.
- Test scripts remain potentially arbitrary code. Only run the prepared demo app for the event; future untrusted-repository support requires a sandbox or a clear opt-in security boundary.

## 17. Observability and performance

- Every operation has a session/event ID and bounded duration.
- Prefer incremental status reads and avoid repeated full transcript/diff uploads.
- Store a full repository fingerprint only when needed; later optimize with per-file/per-gate dependency fingerprints.
- Browser tests are opt-in based on changed paths and configured UI gates; do not start a browser for backend-only changes.
- Context handoffs should include exact relevant failure lines and references, not giant duplicated logs.
- Record gate execution time, timeout rate, retries prevented, stale-evidence count, and adapter health for future evaluation.

## 18. Testing plan

### Unit tests (must-have)

- Canonical TaskFile hashing and immutable revision behavior.
- User approval required for amendment; digest changes when required fields change.
- Scope classifier identifies expected, unexpected, and restricted paths.
- Evidence invalidates after contract or code fingerprint changes.
- Evaluator blocks failed/stale mandatory gates and preserves `UNKNOWN`.
- Loop detector catches repeated failure signatures and does not increment twice for the same event.
- Retry budget is respected; no infinite continuation.
- MCP schemas reject unknown gate IDs and oversized payloads.
- Runner times out and captures bounded output.

### Integration tests (must-have)

- Start a session on a prepared repo, modify an out-of-scope file, and observe a scope finding.
- Run a real failing configured check and observe `BLOCKED`.
- Repeat the same failure to threshold and observe retry stop plus compact handoff.
- Fix the issue, rerun checks, and reach `ACCEPTED` only after fresh evidence exists.
- Modify source after a passing check and observe stale evidence.
- Invoke the chosen host hook using an actual sample payload and validate host-specific response semantics.

### End-to-end demo test

Use a prepared repository and a known task. The test must not require an LLM to make a specific mistake. Seed the initial conditions and validate the real agent integration separately from any scripted/simulated multi-agent events.

## 19. Hackathon implementation order

1. TaskFile model, canonical digest, approval and revision store.
2. Git baseline/snapshot plus scope report.
3. Configured command runner and evidence records.
4. Deterministic evaluator and evidence freshness.
5. Loop/retry detector and handoff packet.
6. CLI end-to-end flow.
7. MCP tools backed by the same core.
8. One lifecycle hook adapter and enforcement-health report.
9. Optional small UI and Playwright smoke check only if the end-to-end path is already reliable.

If time slips, cut dashboard breadth and optional browser automation before cutting contract integrity, evidence freshness, or the working hook.

## 20. Definition of done for MVP

The MVP is done when, in the prepared sample repository:

- A user-approved TaskFile is created and later edits cannot silently overwrite its approved revision.
- ProofMesh detects one deliberate scope violation.
- It runs a real configured test/check and records a result tied to the code state.
- A failing mandatory gate keeps the task non-accepted.
- Repeated failure stops automatic retries within the configured budget without creating an infinite hook loop.
- A source change invalidates relevant evidence.
- A real supported agent can query ProofMesh and the chosen hook can request another attempt when the host supports it.
- After the fix, required checks produce fresh evidence and the evaluator accepts the task.
- Reports clearly label incomplete integration coverage and unverified behavior.

## 21. Official and adjacent references

- MCP specification: https://modelcontextprotocol.io/specification/
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- MCP specification release notes (2026-07-28): https://blog.modelcontextprotocol.io/posts/2026-07-28/
- Codex hooks: https://learn.chatgpt.com/docs/hooks
- Codex advanced configuration: https://learn.chatgpt.com/docs/config-file/config-advanced
- Agent Client Protocol: https://agentclientprotocol.com/ and https://github.com/agentclientprotocol/agent-client-protocol
- Playwright MCP: https://playwright.dev/mcp/introduction
- Chrome DevTools for agents: https://developer.chrome.com/docs/devtools/agents/get-started
- BeforeDone (adjacent project): https://github.com/rrrrrredy/beforedone
