# ProofMesh — Technical Requirements Document (TRD)

**Version:** 0.2 (ideation draft)  
**Status:** Hackathon implementation specification — under active ideation on branch `devin/ideation`  
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
7. expose the same core through a CLI, MCP tools, and one native hook adapter;
8. validate every piece of data that crosses a trust boundary at runtime (Pydantic, strict mode) and fail closed;
9. ship as a lean native Python package (stdlib SQLite, minimal third-party dependencies, no services or containers required) with persistent state stored outside the agent-writable workspace.

The core must not implement its own model loop, choose which agent writes code, orchestrate agents, or require a web UI to function.

## 2. Recommended implementation stack

Guiding rule: **minimal dependencies**. Every third-party package must earn its place; prefer the standard library.

- **Language:** Python 3.14 (pinned via `requires-python = ">=3.14,<3.15"`). Planned third-party dependencies (Pydantic, MCP SDK, PyYAML) publish Python 3.14 classifiers on PyPI.
- **Runtime dependencies (target):** `pydantic` (v2), `mcp` (official SDK), `pyyaml` (TaskFile front matter — or zero if TOML front matter is chosen, §23). Everything else from the standard library.
- **Models/validation:** Pydantic v2 in strict mode for all domain models and every trust boundary (see §5.6). Configuration is a strict Pydantic model loaded from a user-level TOML file (`tomllib`) and environment variables — no `pydantic-settings` dependency needed.
- **TaskFile format:** structured Markdown with a small front-matter block (see §6). Front matter parsed with `yaml.safe_load` only; Markdown body parsed by a strict, line-based section parser (no Markdown library).
- **Persistence:** SQLite only, via the standard-library `sqlite3` module with hand-written, parameterized SQL. No ORM, no query builder, no migration framework. Database file lives in a protected per-user data directory outside the workspace (see §14).
- **MCP:** official MCP Python SDK; pin the SDK version in the lock file and use stable, commonly supported tool primitives.
- **CLI:** `argparse` (standard library).
- **Repository observation:** Git CLI plus filesystem fingerprints for untracked files.
- **Checks:** subprocess runner invoking allowlisted commands such as `pytest`, `ruff`, type checks, or a project-specific test script.
- **Packaging/runtime:** a normal Python package managed with `uv` (`uv.lock` committed); installed with `uv tool install proofmesh` or run with `uvx proofmesh`. No Docker in the runtime path (decision and rationale in §3.1).
- **Dev tooling (not shipped):** pytest, ruff, pyright (strict) — enforced in CI.
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

### 3.1 Runtime and distribution

**Decision (D-3, revised): no Docker in the runtime path.** ProofMesh runs as a native Python 3.14 process launched by the agent harness (MCP stdio server, hook command) or the user (CLI).

Rationale:

1. **Checks need the project's own toolchain.** ProofMesh's job is to run the target repo's tests/linters. Natively, it uses the toolchain already on the developer's machine. In a container, every project would need a derived image with its toolchain installed — the largest source of complexity in the container design.
2. **Hook/MCP latency and moving parts.** Measured on the Linux dev VM (warm cache, `python:3.14-slim` = 180 MB uncompressed): bare Python start ≈ 0.01 s, `docker exec` into a running container ≈ 0.05 s, `docker run --rm` ≈ 0.27 s per call. Linux overhead is tolerable, but it adds a daemon dependency, and Docker Desktop on macOS/Windows (not measured) adds a VM layer, file-sharing quirks and SQLite-WAL-over-file-sharing risk.
3. **Friction for users and reviewers.** Containers add path mapping (host paths in hook payloads → `/workspace`), UID/ownership problems (`git` "dubious ownership"), and require Docker to be installed and running.
4. **Dependencies are now tiny.** With stdlib `sqlite3` and `argparse`, a native install is three direct dependencies (the MCP SDK brings its own transitive ones); a container no longer buys much portability.
5. **The real container benefit — sandboxing untrusted test code — is out of MVP scope** (the demo runs only a prepared, trusted repository).

What is kept from the container design: state stored outside the repo, ProofMesh never writes to the workspace, least-privilege subprocess execution (§8.1).

**Install and run**

```text
uv tool install proofmesh          # or: uvx proofmesh <command>
proofmesh init                     # registers the repo, creates the data dir + DB
proofmesh mcp                      # MCP stdio server (configured in the agent harness)
proofmesh hook stop < payload.json # lifecycle hook entry point
```

**Revisit Docker later** only as an *optional sandbox for check execution* (running gates for untrusted repositories in a throwaway container), not as the way ProofMesh itself runs.

## 4. Proposed repository layout

```text
proofmesh/
  pyproject.toml
  uv.lock
  README.md
  config/
    default-policy.yaml
  src/proofmesh/
    __init__.py
    cli.py
    config.py                 # strict Pydantic config from TOML + env
    models/
      base.py                 # strict base models + shared constrained types
      task.py
      events.py
      evidence.py
      verdict.py
    core/
      task_service.py
      taskfile_md.py          # Markdown TaskFile parser + canonical renderer
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
      db.py                   # sqlite3 connection, PRAGMAs, integrity check, backup
      store.py                # hand-written parameterized queries -> Pydantic models
      hashchain.py            # tamper-evident append-only records
      migrations/             # 001_init.sql, 002_*.sql (applied via PRAGMA user_version)
  tests/
    test_task_contract.py
    test_taskfile_md.py
    test_model_validation.py
    test_storage.py
    test_scope_analyzer.py
    test_evidence_freshness.py
    test_loop_detector.py
    test_evaluator.py
  demo/
    sample-app/
    TASK.md                   # Markdown TaskFile
    policy.yaml
    run_demo.py               # one-command, offline, seeded demo
```

Keep the structure flexible; if time is tight, combine files rather than spending time scaffolding unused modules. Session data is never written into the target repo; it lives in the ProofMesh data directory (§14). `demo/TASK.md` is only the *input* used to seed the demo; the canonical TaskFile lives in ProofMesh's store (§6).

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

`approved_by`, `approved_at`, `approval_status` and `contract_digest` are stored by ProofMesh in the database, never trusted from the TaskFile on disk (the file is agent-writable).

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

### 5.6 Runtime data safety (Pydantic)

Runtime data safety is a hard requirement. Every value that enters the core from outside is parsed into a Pydantic model before use; invalid data is rejected, never coerced or partially used.

**Validated boundaries**

TaskFile front matter and body · trusted policy file · MCP tool arguments · hook stdin JSON · CLI arguments · environment/config · check-runner output summaries · rows read back from the database (re-validated on load, so a manually edited DB cannot inject invalid state).

**Base configuration**

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(
        strict=True,              # no implicit type coercion ("1" is not 1)
        extra="forbid",           # unknown fields are errors
        validate_default=True,
        revalidate_instances="always",
        str_max_length=10_000,    # global cap; tighter per field
    )

class FrozenModel(StrictModel):   # value objects, approved revisions, evidence, verdicts
    model_config = ConfigDict(frozen=True)
```

Mutable aggregates (e.g. `Session`) use `validate_assignment=True`; state changes go through explicit transition functions that check an allowed-transition table and return new validated instances.

**Shared constrained types**

- IDs: `Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]` (task, gate, criterion IDs use their own patterns, e.g. `^AC-\d{1,4}$`).
- Digests: `^sha256:[0-9a-f]{64}$`.
- `RepoRelPath`: POSIX, relative, normalized, no `..`, no NUL, no drive letters; resolved against the registered repository root with symlink-escape checks.
- Timestamps: `AwareDatetime`, normalized to UTC.
- Enums: `StrEnum` for statuses, verdicts, risk levels, enforcement levels.
- Secrets: `SecretStr` for any credential that may be configured later (none required in MVP); never included in `repr`, logs, reports or error messages.
- Collections: bounded (`max_length`) lists/dicts; event payloads use discriminated unions on `event_type` with a `schema_version` field.

**Parsing rules**

- Enforce a byte-size cap *before* parsing (defaults: hook stdin 1 MiB, TaskFile 64 KiB, MCP argument payload 256 KiB; configurable in trusted config only).
- Parse JSON with `model_validate_json` (strict JSON mode), not `json.loads` + dict access.
- Validation errors at a boundary return a structured error (field path + rule) and exit code `2`; inside the evaluator any missing/invalid input yields `UNKNOWN`, never `ALLOW`.
- Canonical JSON for digests: `model_dump(mode="json")` → `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` over NFC-normalized strings with LF line endings.
- Error messages and logs pass through the redactor; validation errors must not echo secret values.

## 6. TaskFile format and lifecycle

The TaskFile is a **structured Markdown document**. Markdown keeps it readable for humans and natural for LLMs to read and draft; a small YAML front-matter block plus a fixed set of headings keeps it deterministic to parse.

**Ownership: ProofMesh owns TaskFiles.** ProofMesh acts as the project manager for task intent. Agents can read the active TaskFile and *propose* a new task or an amendment, but no TaskFile is created, changed or superseded without a ProofMesh decision:

- The canonical TaskFile (raw Markdown + validated model + digest) is stored in ProofMesh's database (§14), not in the repository. There is no repo file whose edits ProofMesh would honour.
- Agents get the TaskFile through MCP (`get_task_contract`, returning Markdown + digest) or the CLI (`proofmesh task show`). Optionally ProofMesh can export a read-only copy for context; edits to that copy are ignored and reported as a `task-contract-integrity` finding.
- Agents submit drafts through MCP (`propose_task`, `propose_contract_amendment`). ProofMesh validates the draft (schema, grammar, known gates, policy) and decides:
  - **reject** — with structured reasons (invalid structure, unknown gates, scope expansion forbidden by policy);
  - **accept automatically** — only where trusted policy allows it (e.g. an amendment that narrows scope or adds acceptance criteria without changing risk);
  - **escalate** — `REQUIRE_APPROVAL` to the user for the initial contract and for any consequential change (scope expansion, risk increase, removed acceptance criteria, changed gates).
- Every decision is recorded as an approval/rejection event with actor (`proofmesh-policy:<rule-id>` or `user:<name>`) and reason.

Design rules:

- **Front matter** holds identity and machine-enforced policy: format version, task ID, revision link, risk level, scope globs, required gates.
- **Body** holds intent in prose, under a fixed set of `##` headings. Acceptance criteria use a strict list grammar so IDs and gate mappings are machine-readable.
- Approval metadata and the digest are **not** in the Markdown; they live in the database (§5.1) next to the canonical content in `task_revisions`.
- One document = one revision proposal.

Illustrative format (exact grammar to be finalized, semantics stable):

````markdown
---
proofmesh_taskfile: 1
task_id: task-1042
parent_revision: null
risk_level: medium
scope:
  allowed_paths: ["app/auth/reset/**", "tests/auth/**"]
  restricted_paths: ["database/migrations/**"]
  unexpected_change_policy: require_justification
required_gates: [regression-tests, auth-tests]
---

# Add password reset without changing login behavior

## Objective
Users who forget their password can request a reset link by email and set a new password.

## Non-goals
- No changes to the login form or session handling.

## Acceptance Criteria
- [AC-1] A user can request a reset.
  - gates: auth-tests
- [AC-2] Invalid or expired tokens are rejected.
  - gates: auth-regression
- [AC-3] Existing login behavior remains unchanged.
  - gates: regression-tests

## Constraints
- Reset tokens expire after 30 minutes.

## Assumptions
- [AS-1] Outbound email is mocked in tests. (unverified)

## Notes
Free-form context for the agent. Included in the digest.
````

**Parser contract**

- Size cap (64 KiB) before parsing; UTF-8 only; normalize line endings to LF and strings to NFC.
- Front matter: `yaml.safe_load`, reject YAML anchors/aliases and custom tags, then validate with the strict `TaskContract` model.
- Body: line-based parser that splits on `#`/`##` headings outside fenced code blocks. Allowed `##` headings: `Objective` (required), `Non-goals`, `Acceptance Criteria` (required, ≥1 item), `Constraints`, `Assumptions`, `Notes`. Unknown or duplicate headings are errors (prevents hidden instructions outside the digested structure).
- Acceptance-criterion grammar: `- [AC-<n>] <description>` followed by optional indented `- gates: <gate-id>[, <gate-id>...]`. Duplicate IDs, unknown gate IDs (not in trusted policy), or gates not listed in `required_gates`/policy are errors.
- `proofmesh task lint <file>` reports all errors with line numbers; `proofmesh task render` produces canonical Markdown from the model. Property test: `parse(render(m)) == m`.
- Digest = SHA-256 over canonical JSON of the validated model (§5.6), so cosmetic whitespace changes do not alter intent identity; the raw-file SHA-256 is stored alongside for audit.

Lifecycle:

1. `propose` — a user (CLI) or an agent (MCP) submits a draft from a precise prompt or bounded investigation; ProofMesh validates it.
2. `review` — ProofMesh shows objective, acceptance criteria, proposed scope, assumptions, risk and its own findings.
3. `decide` — ProofMesh rejects, auto-accepts under trusted policy, or requests user approval (initial contracts always require the user).
4. `approve` — canonicalize content, calculate digest, store the immutable approved revision.
5. `amend` / `supersede` — a new proposal goes through the same decision; the approved revision is never overwritten and older revisions remain auditable.

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

- `get_task_contract(task_id, revision?)` — read the approved contract (Markdown + structured model) and active digest.
- `propose_task(draft_markdown)` — submit a new TaskFile draft; returns ProofMesh's decision (`REJECTED` with reasons, or `PENDING_APPROVAL`).
- `propose_contract_amendment(task_id, draft_markdown, reason)` — submit an amendment; returns `REJECTED`, `ACCEPTED_BY_POLICY` or `PENDING_APPROVAL`. Never approves directly on the agent's say-so.
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

## 14. Storage (SQLite only)

**Decision (D-4, revised): SQLite only**, standard-library `sqlite3`, hand-written parameterized SQL. No Postgres/Neon, no ORM, no migration framework.

Why SQLite rather than plain JSON files: both cost zero dependencies, but the MCP server, hook processes and CLI can write at the same moment. JSON files would need hand-rolled locking and atomic-rename logic to avoid lost or corrupted writes, plus hand-written indexing for queries like "latest evidence for gate X at snapshot Y". SQLite provides transactions, WAL concurrency and integrity checks for free. JSON is still used for **exports** (`proofmesh report --format json`), which reviewers and other tools can read directly.

### 14.1 Logical schema

- `projects(project_id, root_path, created_at)`
- `tasks(task_id, project_id, created_at)`
- `task_revisions(task_id, revision, canonical_json, digest, raw_markdown, raw_digest, approval_status, decided_by, decided_at, decision_reason)`
- `task_proposals(proposal_id, task_id, base_revision, raw_markdown, submitted_by, submitted_at, decision, decision_reasons_json)`
- `sessions(session_id, task_id, revision, baseline_snapshot_id, policy_digest, profile, integration_status, state, started_at, ended_at)`
- `events(event_id, session_id, source, event_type, occurred_at, payload_json, snapshot_before, snapshot_after, prev_hash, row_hash)`
- `snapshots(snapshot_id, session_id, manifest_digest, manifest_json, captured_at)`
- `evidence(evidence_id, session_id, task_revision, gate_id, provider, status, snapshot_before, snapshot_after, started_at, ended_at, exit_code, summary_json, artifact_refs_json, prev_hash, row_hash)`
- `verdicts(verdict_id, session_id, evaluated_at, verdict, reasons_json, snapshot_id, contract_revision, enforcement_level, prev_hash, row_hash)`
- `approvals(approval_id, session_id, action, target_revision, actor, reason, created_at, prev_hash, row_hash)`

JSON columns are `TEXT` holding canonical JSON; timestamps are UTC ISO-8601 `TEXT`. Add indexes for `session_id`, timestamps, task/revision, and gate/status lookups. Every row is re-validated through its Pydantic model when read.

### 14.2 Query layer and migrations

- One module (`storage/store.py`) owns all SQL. Queries are hand-written and **always parameterized** (`?` placeholders); no string-formatted SQL. Each function returns validated Pydantic models, never raw rows.
- Migrations are ordered SQL files (`migrations/001_init.sql`, …). On start-up ProofMesh reads `PRAGMA user_version`, applies missing files inside a transaction, and bumps the version. A DB with a newer version than the code understands is refused (exit `3`).
- Writes use short explicit transactions (`BEGIN IMMEDIATE`) so concurrent processes serialize cleanly.

### 14.3 Keeping the `.db` file safe

- **Location:** `${PROOFMESH_HOME:-$XDG_DATA_HOME/proofmesh}` (default `~/.local/share/proofmesh/` on Linux, platform equivalent on macOS/Windows), one DB per registered project: `<data-dir>/projects/<project-id>/proofmesh.db`. Never inside the target repository, so the agent cannot accidentally edit, delete or commit it, and it never appears in diffs.
- **Permissions:** directory `0700`, files `0600` (process `umask 077`).
- **Connection PRAGMAs:** `journal_mode=WAL`, `synchronous=FULL` (durability of evidence/verdicts over raw write speed; revisit if slow), `foreign_keys=ON`, `busy_timeout=5000`, `trusted_schema=OFF`.
- **Start-up checks:** `PRAGMA quick_check` and schema-version check; refuse to run (exit `3`) on corruption instead of writing to a damaged DB.
- **Filesystem caveat:** SQLite WAL is not supported on network filesystems; refuse or warn if the data dir is on one.
- **Backups:** `proofmesh db backup` uses `sqlite3.Connection.backup()` to write a consistent timestamped copy under `<data-dir>/backups/`; never `cp` the live `.db` while `-wal`/`-shm` files exist. `proofmesh db restore` validates integrity and schema version first.
- **Tamper evidence:** append-only tables (`events`, `evidence`, `verdicts`, `approvals`) carry a hash chain: `row_hash = sha256(prev_hash || canonical_json(row))`. `proofmesh db verify` walks the chain and reports breaks.
- **Honest limitation:** an agent running as the same OS user *can* reach the data dir with its shell. Keeping the DB outside the repo prevents accidental/drive-by edits; the hash chain *detects* row edits unless the whole chain is rebuilt; it does not *prevent* a determined process with the same privileges. Stronger isolation (separate OS user, sandboxed agent) is future work and must not be claimed in the demo.
- **Encryption at rest:** not in MVP; rely on host disk encryption.
- **Artifacts:** bounded check output and screenshots under `<data-dir>/projects/<project-id>/artifacts/` with controlled file names and configured retention.

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
proofmesh task lint <file>
proofmesh task render <task-id> --revision <n>
proofmesh task show <task-id>
proofmesh mcp
proofmesh report <session-id> --format md|json
proofmesh demo
proofmesh db backup | restore <file> | verify
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
- ProofMesh never writes to the workspace; check subprocesses get a minimal environment, a controlled working directory and `/tmp`-redirected caches where the tool supports it.
- Database and artifacts live in the per-user data directory (`0700`/`0600`), outside the agent-writable workspace; all SQL is parameterized.
- Agents cannot create or change TaskFiles directly; only ProofMesh decisions (policy rule or user approval) produce revisions (§6).
- All external input is validated by strict Pydantic models with size caps before use (§5.6); the TaskFile parser rejects unknown sections, YAML aliases and custom tags.
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
- Markdown TaskFile: valid file parses; unknown/duplicate headings, malformed AC lines, duplicate AC IDs, unknown gate IDs, YAML aliases and oversized files are rejected with line numbers; `parse(render(m)) == m`; cosmetic whitespace edits keep the canonical digest stable.
- Strict models reject coercible-but-wrong types, extra fields, naive datetimes, path traversal (`../`, absolute, symlink escape) and oversized collections; secrets never appear in `repr`/errors.
- Storage: migrations apply in order and are idempotent; concurrent writers (two processes) do not lose writes; hash-chain verification detects a modified row; `quick_check` failure blocks start-up; backup/restore round-trips; no query uses string-formatted SQL (lint rule/grep test).
- TaskFile ownership: agent `propose_task`/`propose_contract_amendment` never produces an approved revision without a policy rule or user approval; scope expansion is escalated; rejected proposals return reasons.

### Integration tests (must-have)

- Start a session on a prepared repo, modify an out-of-scope file, and observe a scope finding.
- Run a real failing configured check and observe `BLOCKED`.
- Repeat the same failure to threshold and observe retry stop plus compact handoff.
- Fix the issue, rerun checks, and reach `ACCEPTED` only after fresh evidence exists.
- Modify source after a passing check and observe stale evidence.
- Invoke the chosen host hook using an actual sample payload and validate host-specific response semantics.
- Clean-install smoke test: `uvx proofmesh demo` on a fresh machine/CI runner with no network after install completes the seeded demo and writes `report.md` + `report.json`; the repo working tree is unchanged afterwards.

### End-to-end demo test

Use a prepared repository and a known task. The test must not require an LLM to make a specific mistake. Seed the initial conditions and validate the real agent integration separately from any scripted/simulated multi-agent events.

## 19. Hackathon implementation order

0. Project skeleton: `pyproject.toml` (Python 3.14, uv), strict base models/types, config, CI (ruff, pyright, pytest).
1. Markdown TaskFile parser/renderer, TaskFile model, canonical digest, ProofMesh-owned proposal/decision/revision store (SQLite).
2. Git baseline/snapshot plus scope report.
3. Configured command runner and evidence records.
4. Deterministic evaluator and evidence freshness.
5. Loop/retry detector and handoff packet.
6. CLI end-to-end flow.
7. MCP tools backed by the same core.
8. One lifecycle hook adapter and enforcement-health report.
9. Optional small UI and Playwright smoke check only if the end-to-end path is already reliable.

If time slips, cut dashboard breadth and optional browser automation before cutting contract integrity, evidence freshness, runtime validation, or the working hook.

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
- The full flow runs from a clean `uv` install with state persisted in the data directory and the repo working tree untouched by ProofMesh.
- Review-readiness checklist in §22 is complete.

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
- Python 3.14 release notes: https://docs.python.org/3.14/whatsnew/3.14.html
- Pydantic strict mode: https://docs.pydantic.dev/latest/concepts/strict_mode/
- SQLite WAL (incl. network filesystem limitation): https://www.sqlite.org/wal.html
- SQLite online backup API: https://www.sqlite.org/backup.html
- Python `sqlite3` module: https://docs.python.org/3.14/library/sqlite3.html
- Python `tomllib`: https://docs.python.org/3.14/library/tomllib.html
- uv tools (`uv tool install`, `uvx`): https://docs.astral.sh/uv/guides/tools/

## 22. Review readiness (jury + AI code reviewer)

The submission will be evaluated by human judges and an AI agent that reviews the code. Both reward the same things: a clear story, code that matches its claims, and evidence that it works.

- **One-command, offline demo:** `uvx proofmesh demo` (or `uv run proofmesh demo`) runs the seeded scenario end-to-end and writes `report.md` + `report.json`. No API keys or network needed for the core path.
- **README first screen:** problem → what ProofMesh does (Intent / Intervention / Evidence) → 30-second demo command → architecture diagram → honest limitations (enforcement levels, same-user DB access, heuristic loop detection).
- **Claims match code:** every capability in the README maps to a module and a test; no "coming soon" features presented as working; simulated events are labelled as simulated.
- **Small, readable codebase:** no unused scaffolding or empty modules; module docstrings explain each component's role; strict typing; consistent naming with the PRD/TRD vocabulary (TaskFile, Evidence, Verdict, Gate).
- **Green CI:** ruff, pyright (strict) and pytest run on every push; badge in README.
- **Tests as documentation:** test names read as requirements (`test_failed_mandatory_gate_blocks_acceptance`, `test_agent_cannot_approve_own_amendment`).
- **Traceability:** README links PRD requirement IDs (FR-xx) to tests; the decision log (§23) shows reasoning for reviewers.
- **Security hygiene visible in code:** parameterized SQL, no `shell=True`, allowlisted gates, strict Pydantic models at boundaries.

## 23. Ideation log and open questions

Decisions taken during ideation (branch `devin/ideation`):

- **D-1** TaskFile is structured Markdown (front matter + fixed headings), not pure YAML — LLM- and human-friendly, still deterministic to parse (§6).
- **D-2** Target runtime is Python 3.14 (§2).
- **D-3** *(revised)* No Docker in the runtime path; native Python package installed with `uv`. Docker may return later only as an optional sandbox for check execution (§3.1). Supersedes the earlier "run everything in one container" design (see git history of this branch).
- **D-4** *(revised)* SQLite only, stdlib `sqlite3`, hand-written parameterized SQL; no Postgres/Neon, no ORM/migration framework. JSON for exports only (§14).
- **D-5** Pydantic v2 strict models validate every trust boundary; invalid input fails closed (§5.6).
- **D-6** Scope is the hackathon demo; no team/cloud/multi-machine features.
- **D-7** ProofMesh owns the TaskFile lifecycle and acts as project manager for task intent: agents only propose; ProofMesh rejects, auto-accepts under trusted policy, or escalates to the user (§6). It still does not write code, plan implementations or schedule agents.
- **D-8** The deliverable is judged by a jury *and* an AI code reviewer; review readiness is a P0 requirement (§22).

Open questions:

1. **How autonomous is the "project manager"?** Which amendment types may ProofMesh auto-accept without the user (e.g. narrowing scope, adding ACs)? Should the initial contract ever be auto-approved?
2. **Front matter: YAML vs TOML.** TOML front matter (`+++`) parses with stdlib `tomllib` (drops PyYAML, avoids YAML aliases/implicit typing pitfalls) but needs a small hand-written renderer; YAML is more familiar to LLMs.
3. **TaskFile grammar details:** exact AC/assumption line syntax; whether scope/gates stay in front matter or move into body sections.
4. **Digest normalization:** which Markdown changes count as "cosmetic" (whitespace only?) vs. intent changes.
5. **Checks that write files:** redirect caches to `/tmp` per tool vs. run checks on a temporary copy/worktree of the repo.
6. **Which agent harness for the demo** (Codex hooks or another available harness) and its hook latency budget.
7. **Dogfooding:** should ProofMesh's own development be governed by ProofMesh TaskFiles, and shown to the jury as evidence?

