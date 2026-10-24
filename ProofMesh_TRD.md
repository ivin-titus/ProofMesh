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
9. ship as a single lightweight, portable container image with persistent state stored outside the agent-writable workspace.

The core must not implement its own model loop, choose which agent writes code, orchestrate agents, or require a web UI to function.

## 2. Recommended implementation stack

- **Language:** Python 3.14 (pinned via `requires-python = ">=3.14,<3.15"`). All planned core dependencies (Pydantic, pydantic-core, pydantic-settings, MCP SDK, SQLAlchemy, Alembic, psycopg, PyYAML, Typer) publish Python 3.14 classifiers on PyPI; re-verify wheels for both `linux/amd64` and `linux/arm64` when locking.
- **Models/validation:** Pydantic v2 in strict mode for all domain models and every trust boundary (see §5.6). `pydantic-settings` for configuration.
- **TaskFile format:** structured Markdown with a small YAML front-matter block (see §6). YAML parsed with `yaml.safe_load` only; Markdown body parsed by a strict, line-based section parser (no general-purpose Markdown renderer required).
- **Persistence:** storage abstraction with SQLite as the default backend (WAL mode, file kept in a protected data directory outside the workspace) and PostgreSQL (e.g. Neon) as an opt-in backend selected by a database URL (see §14).
- **DB access layer (proposed):** SQLAlchemy 2.x **Core** (no ORM) + Alembic migrations so one schema definition serves both SQLite and Postgres; `psycopg` (v3) as the Postgres driver. Alternative: hand-written SQL over `sqlite3`/`psycopg` with fewer dependencies but duplicated dialect logic — open decision (§22).
- **MCP:** official MCP Python SDK; pin the SDK version in the lock file and use stable, commonly supported tool primitives.
- **CLI:** Typer or argparse; choose one and avoid excess CLI framework work.
- **Repository observation:** Git CLI plus filesystem fingerprints for untracked files.
- **Checks:** subprocess runner invoking allowlisted commands such as `pytest`, `ruff`, type checks, or a project-specific test script.
- **Packaging/runtime:** one OCI image built with a multi-stage Dockerfile on `python:3.14-slim`, dependencies installed with `uv` from a frozen lock file, run as non-root with a read-only root filesystem (see §3.1).
- **Static typing/lint:** pyright or mypy in strict mode (with the Pydantic plugin for mypy) and ruff, enforced in CI.
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

### 3.1 Container runtime

The whole tool runs inside one container. Goals: small image, same behaviour on Linux/macOS/Windows hosts, no host Python required, and no write access to anything except ProofMesh's own data directory.

**Image**

- Multi-stage build: builder stage copies the `uv` binary, runs `uv sync --frozen --no-dev` into `/app/.venv`; runtime stage is `python:3.14-slim` + `git` (needed for repository observation) + the venv. No compilers, no package caches, no shell tooling beyond what slim ships.
- Multi-arch (`linux/amd64`, `linux/arm64`) via `docker buildx`.
- Non-root default user; `ENTRYPOINT ["proofmesh"]`; `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`.
- System gitconfig sets `safe.directory=/workspace` so a bind-mounted repo owned by a different UID does not trigger Git's "dubious ownership" error.
- `alpine` (musl) and distroless bases are candidates only if measured size/compatibility wins justify them; `slim` is the default because all dependencies ship glibc wheels. Measure the final image size and record a target once the first build exists.

**Mounts and filesystem**

| Container path | Source | Mode | Purpose |
|---|---|---|---|
| `/workspace` | the target repository (bind mount) | read-only by default | observed code; ProofMesh never writes here |
| `/data` | named volume `proofmesh-data` (default) or a host dir | read-write, `0700` | SQLite DB, artifacts, backups, pinned policy |
| `/tmp` | tmpfs | read-write | scratch for check runs (caches, temp files) |
| `/run/secrets/*` | Docker secrets / read-only file mounts | read-only | e.g. Postgres URL file |

Mounting the workspace read-only is a deliberate least-privilege choice: generated session data no longer lives in `<repo>/.proofmesh/`, so an agent cannot edit or delete ProofMesh's records by editing the repo. Checks that need to write (pytest cache, coverage files) are pointed at `/tmp` (`-p no:cacheprovider`, `COVERAGE_FILE=/tmp/...`) or get a per-run copy/overlay — open question (§22).

**Run flags (baseline)**

```text
docker run --rm -i --init \
  --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --network none \
  -v "$PWD":/workspace:ro \
  -v proofmesh-data:/data \
  ghcr.io/<owner>/proofmesh:<version> <command>
```

`--network none` applies to local SQLite mode; omit it when a remote Postgres/Neon backend is configured. A `compose.yaml` provides the same settings for a long-lived instance.

**Integration modes**

- **MCP (stdio):** agent config launches `docker run -i --rm ... proofmesh mcp`; stdio works through `-i` without exposing a port.
- **Lifecycle hooks:** hooks are invoked per event and are latency-sensitive. Options: (a) `docker run --rm -i ... proofmesh hook <event>` per call (simplest, pays container start-up each time); (b) a long-lived container from `compose.yaml` plus `docker exec -i proofmesh proofmesh hook <event>` (faster). Measure both before choosing (§22).
- **Host path mapping:** hook payloads and agent events contain host absolute paths; the adapter maps the configured host repo root to `/workspace` and rejects paths outside it.

**Check execution inside the container**

The ProofMesh image only contains Python 3.14 + ProofMesh. Checks need the *target project's* toolchain. MVP: the demo uses a derived image (`proofmesh-demo`) that adds the sample app's dependencies in a separate venv. Not planned for MVP: mounting the Docker socket to launch sibling check containers (equivalent to host root access). Rootless/sandboxed per-gate runners are future work (§22).

## 4. Proposed repository layout

```text
proofmesh/
  pyproject.toml
  uv.lock
  Dockerfile
  compose.yaml
  .dockerignore
  README.md
  config/
    default-policy.yaml
  src/proofmesh/
    __init__.py
    cli.py
    config.py                 # pydantic-settings; DB URL as SecretStr
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
      ports.py                # storage interface used by core
      schema.py               # SQLAlchemy Core tables (shared by both backends)
      sqlite_backend.py       # PRAGMAs, integrity check, backup
      postgres_backend.py     # Neon / any Postgres (opt-in)
      migrations/             # Alembic
      hashchain.py            # tamper-evident append-only records
  tests/
    test_task_contract.py
    test_taskfile_md.py
    test_model_validation.py
    test_storage_backends.py
    test_scope_analyzer.py
    test_evidence_freshness.py
    test_loop_detector.py
    test_evaluator.py
  demo/
    sample-app/
    TASK.md                   # Markdown TaskFile
    policy.yaml
    Dockerfile                # proofmesh-demo image with sample-app deps
```

Keep the structure flexible; if time is tight, combine files rather than spending time scaffolding unused modules. Session data is no longer written into the target repo; it lives under `/data` in the container (§3.1, §14).

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
- `RepoRelPath`: POSIX, relative, normalized, no `..`, no NUL, no drive letters; resolved against `/workspace` with symlink-escape checks.
- Timestamps: `AwareDatetime`, normalized to UTC.
- Enums: `StrEnum` for statuses, verdicts, risk levels, enforcement levels.
- Secrets: `SecretStr` (DB URL, tokens); never included in `repr`, logs, reports or error messages.
- Collections: bounded (`max_length`) lists/dicts; event payloads use discriminated unions on `event_type` with a `schema_version` field.

**Parsing rules**

- Enforce a byte-size cap *before* parsing (defaults: hook stdin 1 MiB, TaskFile 64 KiB, MCP argument payload 256 KiB; configurable in trusted config only).
- Parse JSON with `model_validate_json` (strict JSON mode), not `json.loads` + dict access.
- Validation errors at a boundary return a structured error (field path + rule) and exit code `2`; inside the evaluator any missing/invalid input yields `UNKNOWN`, never `ALLOW`.
- Canonical JSON for digests: `model_dump(mode="json")` → `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` over NFC-normalized strings with LF line endings.
- Error messages and logs pass through the redactor; validation errors must not echo secret values.

## 6. TaskFile format and lifecycle

The TaskFile is a **structured Markdown file** (default name `TASK.md`, or `.proofmesh/tasks/<task-id>.md` in a user-controlled location). Markdown keeps it readable for humans and natural for LLMs to read and draft; a small YAML front-matter block plus a fixed set of headings keeps it deterministic to parse.

Design rules:

- **Front matter** holds identity and machine-enforced policy: format version, task ID, revision link, risk level, scope globs, required gates.
- **Body** holds intent in prose, under a fixed set of `##` headings. Acceptance criteria use a strict list grammar so IDs and gate mappings are machine-readable.
- Approval metadata and the digest are **not** in the file; they live in the database (§5.1). The on-disk file is a working copy; the approved canonical content is stored in `task_revisions`.
- One file = one revision proposal. Editing an approved TaskFile on disk does not change the approved revision; ProofMesh detects the mismatch (on-disk digest ≠ approved digest) and reports a `task-contract-integrity` finding, then offers `task propose` to create an amendment.

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

1. `propose` — create a draft from a precise prompt or bounded investigation (an LLM may draft the Markdown; ProofMesh validates it).
2. `review` — show objective, acceptance criteria, proposed scope, assumptions and risk.
3. `approve` — canonicalize content, calculate digest, store immutable approved revision in the database.
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

## 14. Storage: schema, placement, safety and backends

### 14.1 Logical schema

Tables to implement (shared by all backends):

- `projects(project_id, root_path, created_at)`
- `tasks(task_id, project_id, created_at)`
- `task_revisions(task_id, revision, canonical_json, digest, raw_markdown, raw_digest, approval_status, approved_by, approved_at)`
- `sessions(session_id, task_id, revision, baseline_snapshot_id, policy_digest, profile, integration_status, state, started_at, ended_at)`
- `events(event_id, session_id, source, event_type, occurred_at, payload_json, snapshot_before, snapshot_after, prev_hash, row_hash)`
- `snapshots(snapshot_id, session_id, manifest_digest, manifest_json, captured_at)`
- `evidence(evidence_id, session_id, task_revision, gate_id, provider, status, snapshot_before, snapshot_after, started_at, ended_at, exit_code, summary_json, artifact_refs_json, prev_hash, row_hash)`
- `verdicts(verdict_id, session_id, evaluated_at, verdict, reasons_json, snapshot_id, contract_revision, enforcement_level, prev_hash, row_hash)`
- `approvals(approval_id, session_id, action, target_revision, actor, reason, created_at, prev_hash, row_hash)`
- `schema_meta(version, applied_at)`

Use versioned migrations (Alembic). Add indexes for `session_id`, timestamps, task/revision, and gate/status lookups. JSON columns are `TEXT` in SQLite and `JSONB` in Postgres; timestamps are UTC (`TEXT` ISO-8601 in SQLite, `timestamptz` in Postgres). Every row is re-validated through its Pydantic model when read. Keep large logs out of the database; store bounded artifacts under `/data/artifacts/` with controlled file names and configured retention.

### 14.2 Storage interface

Core services depend only on a storage port (repository interface: `save_revision`, `append_event`, `append_evidence`, `latest_verdict`, …). Core never imports `sqlite3`, `psycopg` or SQLAlchemy directly. The backend is selected at start-up from configuration:

| Setting | Example | Notes |
|---|---|---|
| `PROOFMESH_DATABASE_URL` | `sqlite:////data/proofmesh.db` (default) | local, offline, zero setup |
| | `postgresql+psycopg://user@host/db?sslmode=require` | Neon or any Postgres; opt-in |
| `PROOFMESH_DATABASE_URL_FILE` | `/run/secrets/proofmesh_db_url` | preferred for credentials; overrides the plain env var |

The URL is a `SecretStr`, never written to logs, reports, handoffs or the repo. Config is loaded from trusted sources only (env, secret file, user-level config under `/data`), never from the workspace.

### 14.3 SQLite (default) — keeping the `.db` file safe

- **Location:** `/data/proofmesh.db` inside the container, backed by the named volume `proofmesh-data` (default) or a user-chosen host directory (e.g. `${XDG_DATA_HOME:-~/.local/share}/proofmesh`). Never inside the target repository, so the agent cannot edit, delete or commit it.
- **Permissions:** directory `0700`, files `0600` (process `umask 077`); owned by the container user.
- **Connection PRAGMAs:** `journal_mode=WAL`, `synchronous=FULL` (durability of evidence/verdicts over raw write speed; revisit if slow), `foreign_keys=ON`, `busy_timeout=5000`, `trusted_schema=OFF`.
- **Start-up checks:** `PRAGMA quick_check` and schema-version check; refuse to run (exit `3`) on corruption or unknown future schema instead of writing to a damaged DB.
- **Concurrency:** one writer process per DB (MCP server, hooks and CLI serialize writes through short transactions); WAL allows concurrent readers.
- **Filesystem caveat:** SQLite WAL is not supported on network filesystems. Docker Desktop (macOS/Windows) bind mounts go through a VM file-sharing layer, so the default is a named volume (stored inside the Docker VM's local filesystem). Host-directory mounts are supported but documented as "local disk only".
- **Backups:** `proofmesh db backup` uses the SQLite online backup API (or `VACUUM INTO`) to write a consistent timestamped copy under `/data/backups/`; never `cp` the live `.db` while `-wal`/`-shm` files exist. `proofmesh db restore` validates integrity and schema version first.
- **Tamper evidence:** append-only tables (`events`, `evidence`, `verdicts`, `approvals`) carry a hash chain: `row_hash = sha256(prev_hash || canonical_json(row))`. `proofmesh db verify` walks the chain and reports breaks. This *detects* edits by anything that did not rewrite the whole chain; it does not *prevent* a party with full DB write access from rebuilding it. Anchoring the chain head externally (in reports, a Git note, or a remote DB) is future work.
- **Encryption at rest:** not in MVP; rely on host disk encryption. SQLCipher or application-level encryption of sensitive columns are options (§22).

### 14.4 PostgreSQL / Neon (opt-in)

- Same schema and migrations via SQLAlchemy Core + Alembic; driver `psycopg` 3.
- TLS required (`sslmode=require` minimum; `verify-full` with CA bundle preferred). Reject non-TLS URLs unless an explicit `allow_insecure_db` flag is set in trusted config (local dev only).
- Connection timeout and bounded retries; a DB outage makes the evaluator return `UNKNOWN`, never `ALLOW`.
- Neon specifics to validate: pooled endpoints use PgBouncer in transaction mode (server-side prepared statements must be disabled, e.g. psycopg `prepare_threshold=None`, or use the direct endpoint); scale-to-zero adds cold-start latency on the first query — measure against hook latency budgets.
- Least-privilege DB role: application role can `INSERT`/`SELECT` on append-only tables but not `UPDATE`/`DELETE` them; migrations run with a separate role.
- **Privacy trade-off:** with a remote DB, task contracts, event metadata, evidence summaries and verdicts leave the machine. This must be an explicit user choice (PRD principle 6). Large artifacts stay in local `/data/artifacts/` unless artifact sharing is separately designed.
- **Offline:** the hackathon demo uses SQLite so the core verification path works without network access (PRD §13). Container runs with `--network none` in SQLite mode.

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
proofmesh mcp
proofmesh db migrate | backup | restore <file> | verify
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
- Container hardening: non-root user, read-only root filesystem, `--cap-drop ALL`, `no-new-privileges`, tmpfs `/tmp`, workspace mounted read-only, `--network none` unless a remote DB is configured. Never mount the Docker socket into the ProofMesh container.
- Database files live in the protected `/data` volume (`0700`/`0600`), outside the agent-writable workspace; remote DB credentials come from secret files/env as `SecretStr` and require TLS.
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
- Storage contract tests run the same suite against SQLite and Postgres (Postgres via a local container in CI; Neon optional/manual); hash-chain verification detects a modified row; `quick_check` failure blocks start-up; backup/restore round-trips.

### Integration tests (must-have)

- Start a session on a prepared repo, modify an out-of-scope file, and observe a scope finding.
- Run a real failing configured check and observe `BLOCKED`.
- Repeat the same failure to threshold and observe retry stop plus compact handoff.
- Fix the issue, rerun checks, and reach `ACCEPTED` only after fresh evidence exists.
- Modify source after a passing check and observe stale evidence.
- Invoke the chosen host hook using an actual sample payload and validate host-specific response semantics.
- Container smoke test: build the image, run `proofmesh init/verify/status` against the demo repo with the workspace mounted read-only, `--read-only` root FS and `--network none`; data persists across container restarts via the named volume.

### End-to-end demo test

Use a prepared repository and a known task. The test must not require an LLM to make a specific mistake. Seed the initial conditions and validate the real agent integration separately from any scripted/simulated multi-agent events.

## 19. Hackathon implementation order

0. Project skeleton: `pyproject.toml` (Python 3.14), strict base models/types, settings, Dockerfile + compose that run `proofmesh --version`.
1. Markdown TaskFile parser/renderer, TaskFile model, canonical digest, approval and revision store (SQLite backend behind the storage port).
2. Git baseline/snapshot plus scope report.
3. Configured command runner and evidence records.
4. Deterministic evaluator and evidence freshness.
5. Loop/retry detector and handoff packet.
6. CLI end-to-end flow.
7. MCP tools backed by the same core.
8. One lifecycle hook adapter and enforcement-health report.
9. Optional small UI and Playwright smoke check only if the end-to-end path is already reliable.

If time slips, cut dashboard breadth, optional browser automation and the Postgres/Neon backend (keep the storage port) before cutting contract integrity, evidence freshness, runtime validation, or the working hook.

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
- The full flow runs from the published container image with the workspace mounted read-only and state persisted in the `/data` volume.

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
- pydantic-settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- SQLite WAL (incl. network filesystem limitation): https://www.sqlite.org/wal.html
- SQLite online backup API: https://www.sqlite.org/backup.html
- SQLAlchemy 2.x Core: https://docs.sqlalchemy.org/en/20/core/
- Alembic: https://alembic.sqlalchemy.org/
- Neon connection pooling: https://neon.tech/docs/connect/connection-pooling
- uv in Docker: https://docs.astral.sh/uv/guides/integration/docker/
- Docker official Python image: https://hub.docker.com/_/python

## 22. Ideation log and open questions

Decisions taken during ideation (branch `devin/ideation`):

- **D-1** TaskFile is structured Markdown (YAML front matter + fixed headings), not pure YAML — LLM- and human-friendly, still deterministic to parse (§6).
- **D-2** Target runtime is Python 3.14 (§2).
- **D-3** ProofMesh ships and runs as a single lightweight, portable container image (§3.1).
- **D-4** SQLite is the default store, kept in a protected data volume outside the workspace; Postgres (e.g. Neon) is an opt-in backend behind the same storage interface (§14).
- **D-5** Pydantic v2 strict models validate every trust boundary; invalid input fails closed (§5.6).

Open questions:

1. **TaskFile grammar details:** exact AC/assumption line syntax; whether scope/gates stay in front matter or move into body sections; where TaskFiles live (repo vs. user-controlled dir) given the repo is agent-writable.
2. **Digest normalization:** which Markdown changes count as "cosmetic" (whitespace only?) vs. intent changes.
3. **Hook latency in Docker:** `docker run` per hook vs. long-lived container + `docker exec`; acceptable latency budget per host hook.
4. **Checks needing writes / project toolchains:** tmpfs redirection vs. per-run overlay copy of the workspace; derived per-project images vs. a sandboxed sibling runner (without exposing the Docker socket).
5. **DB access layer:** SQLAlchemy Core + Alembic vs. hand-written SQL per backend (dependency weight vs. duplication).
6. **Remote DB scope:** is Neon for multi-machine/team history (future) or also a hackathon demo item? How are artifacts shared when the DB is remote?
7. **Encryption at rest** for the SQLite file (SQLCipher, column-level, or host disk encryption only).
8. **Hash-chain anchoring:** where to publish the chain head so DB rewrites become detectable.
9. **Base image:** `python:3.14-slim` vs. alpine/distroless after measuring size and start-up time.
10. **Docker Desktop on macOS/Windows:** confirm WAL behaviour and performance with named volumes vs. bind mounts.
