# ProofMesh — Hackathon Build Plan

**Status:** Active build checklist  
**Working branch:** main  
**Updated at:** 2026-10-25T00:35:00+05:30  
**Deadline noted for planning:** October 25, 2026, 11:00 IST; confirm against current organizer communications. A live remaining-time countdown is intentionally omitted because it quickly becomes stale.  
**Authority:** [PRD](PRD.md) defines product behavior and priorities; [TRD](TRD.md) §0 and §20 define the technical MVP boundary; this plan defines implementation order and cut lines. Follow [AGENTS.md](../AGENTS.md) for workflow and safety practices. Roadmap and historical ideation notes must not expand the MVP beyond the explicit scope lock.

## 1. The only outcome that matters tonight

Deliver one repeatable demonstration of:

**Approved intent → observed scope change → real check → code-bound evidence → blocked verdict/intervention → correction → fresh evidence → accepted verdict.**

A judge should be able to see the approved contract, what changed, why the task is blocked, which evidence is missing or stale, and why the task becomes accepted. The main demo must not depend on an LLM making a mistake on cue.

## 2. Build sequence with stop/go checkpoints

### Checkpoint 0 — Integration spike (first 25–30 minutes)

- [x] Choose the preferred available host, trying Antigravity first if already installed.
- [x] Verify a real MCP request/response against a trivial core operation.
- [x] If using a hook, capture a real hook payload and verify the exact response semantics.
- [x] Save the real payload as a golden fixture.
- [x] Decide: continue with this host, switch to another available host, or honestly demonstrate MCP/CLI as partial enforcement.

**Stop rule:** Do not build a universal installer or second adapter before this checkpoint succeeds. Never invent or assume a host's hook schema.

### Checkpoint 1 — Package and persistent state

- [x] Minimal package configuration, strict Pydantic models and default trusted policy.
- [x] SQLite schema/store for task revisions, sessions, events, evidence and decisions.
- [x] Parameterized SQL, transaction boundaries, stable IDs and schema version.
- [x] Per-user data directory outside the target repository.
- [x] A test proves state survives a new process.

**Checkpoint 1.1 Review & Repair (Completed):**
- [x] Lockfile `uv.lock` generated for CPython 3.14 without relaxing `requires-python = "==3.14.*"`.
- [x] Package data configured in `pyproject.toml`; wheel build verified to package and execute migrations.
- [x] SQLite migrations hardened with atomic schema upgrade/rollback and rejection of future schema versions.
- [x] Restrictive directory (`0700`) and database file (`0600`) permissions with path traversal prevention.
- [x] In-place mutation gap closed using immutable tuples and MappingProxyType on domain models.
- [x] Default trusted policy TOML created and verified.

**Exit condition:** One task/event/evidence round-trip works. Do not build hash-chain audit, a daemon, ORM, remote database, or backup UX tonight.

### Checkpoint 1.2 — Policy packaging and foundation hardening (completed)

- [x] Package the default trusted policy as a reliable package resource (`proofmesh.resources/default-policy.toml`). Resolved via `importlib.resources`; raises actionable `FileNotFoundError` if missing, verified via installed wheel test.
- [x] Test recursive immutability of nested `EventRecord.payload` data via recursive freeze (`MappingProxyType` + `tuple`), preserving JSON serialization.
- [x] Review storage-path permission handling: accurately distinguish unsupported-filesystem errnos (`ENOSYS`, `EOPNOTSUPP`, `ENOTSUP`) from unexpected I/O and permission errors. Enforce `0700` hierarchy across data dir, intermediate `projects` dir, per-project dir, and `0600` on database file.
- [x] Make packaging tests reproducible from a clean checkout without depending on a stale prebuilt `dist/` artifact (`get_or_build_wheel` helper).
- [x] Reconcile Python-version documentation with `requires-python = ">=3.14,<3.15"`; distinguish the supported package range from source tests run under Python 3.12.

**Go/no-go:** Foundation hardening complete, tested, and green on both CPython 3.14.9 (31/31 passed) and Python 3.12.3 (31/31 passed). Ready for Checkpoint 2.

### Checkpoint 2 — Intent / TaskFile

- [ ] Parse one structured Markdown TaskFile format with TOML front matter.
- [ ] Validate required fields, stable task/criterion IDs, and known gate IDs.
- [ ] Store a proposed revision and approve it through explicit user action.
- [ ] Canonicalize and hash the approved contract; never mutate an approved revision in place.
- [ ] Agent amendment requests create proposals, not approved revisions.

**Exit condition:** A test proves a proposed amendment cannot silently change the active approved contract.

### Checkpoint 3 — Repository snapshot and scope

- [ ] Capture the baseline Git state and fingerprints for relevant tracked and untracked files.
- [ ] Compute changed paths since baseline.
- [ ] Apply a small allow/restricted path policy.
- [ ] Report suspicious files with reasons; do not claim path matching proves semantic wrongdoing.

**Exit condition:** One seeded out-of-scope change appears in the report.

### Checkpoint 4 — Verification and evidence freshness

- [ ] Implement one trusted, preconfigured test/check provider.
- [ ] Use argument arrays, not shell=True; enforce timeout and bounded stdout/stderr.
- [ ] Persist status, exit code, duration, criterion mapping, contract revision, gate/config identity and code fingerprint.
- [ ] If relevant code or configuration changes during or after a check, mark the evidence stale.
- [ ] Never run a command or gate supplied ad hoc by model output.

**Exit condition:** A real check produces PASS/FAIL, and a relevant source edit invalidates its earlier evidence.

### Checkpoint 5 — Intervention and verdict

- [ ] Implement a deterministic evaluator returning ACCEPTED, BLOCKED, NEEDS_APPROVAL or UNKNOWN with reasons/evidence IDs.
- [ ] Missing, failed, stale or unknown mandatory evidence cannot result in ACCEPTED.
- [ ] Normalize repeated failures by gate ID and a bounded error/failing-test signature.
- [ ] Deduplicate repeated event delivery so the same event is not counted multiple times.
- [ ] Enforce a small retry/continuation budget and generate a compact handoff once exhausted.

**Exit condition:** Repeating a known failure produces bounded intervention; the completion hook cannot loop forever.

### Checkpoint 6 — Seeded CLI demo before adapters

- [ ] Wire one CLI command to run the seeded scenario.
- [ ] Persist state and generate a Markdown report plus a JSON receipt.
- [ ] Restart ProofMesh and reload the same task, evidence and verdict.
- [ ] Label seeded/simulated events. Never present simulated agent behavior as a live integration.

**Exit condition:** The core scenario passes twice from a clean state without an LLM or network dependency.

### Checkpoint 7 — MCP and one real host

- [ ] Expose only the necessary operations: get task contract, inspect changes, run configured verification, get completion status, claim completion, and get handoff.
- [ ] MCP handlers call the same core services as the CLI; no duplicated policy logic in adapters.
- [ ] Connect one real agent and verify a request/response.
- [ ] If the host supports it, wire one actual lifecycle hook to request continuation when evidence is missing.
- [ ] Report ENFORCED, PARTIAL or UNGUARDED based on what was verified.

**Exit condition:** The integration is demonstrated honestly. If hook enforcement is unavailable or unreliable, do not claim it can force the agent; show the real MCP path and clearly state its limits.

### Checkpoint 8 — Presentation and one optional stretch

Only after the core demo passes at least twice from a clean state:

- [ ] Improve the Markdown/JSON receipt and **plain CLI progress output** so the demo shows concise phase changes, gate results, blockers and final verdict. Do not add a heavy TUI framework; terminal visibility is part of the core demo, not a stretch.
- [ ] Record a fallback run and preserve exported reports.
- [ ] Choose **at most one** optional stretch: (a) a minimal local progress panel, (b) an existing Playwright smoke test, or (c) one narrow SystemOne decision-advisor call. Do not implement two options just because parallel agents are available.
- [ ] If choosing the panel: use vanilla HTML/CSS/JS and Python's standard-library HTTP server; start it explicitly with `proofmesh ui`, keep it off by default, bind only to `127.0.0.1`, make it read-only, and render the same versioned status/report data as the CLI. No npm build, framework, CDN, or frontend dependency in the core runtime. Ctrl+C stops it; CLI/demo must work with the panel off.
- [ ] If choosing the advisor: configure a SystemOne-compatible endpoint for hosted Jev or a local Laya service; keep it disabled by default and expose credentials only via a named environment variable such as `PROOFMESH_ADVISOR_KEY`. Never persist or display the key. Send only the narrow, bounded data needed for the question. The answer may warn or request review, never accept work or override deterministic gates.
- [ ] If choosing Playwright: reuse an existing test; do not build a browser automation framework.
- [ ] Drop the stretch immediately if setup, networking, credentials or debugging threaten core stability.
- [ ] Run the core twice again after final changes and check that the panel (if selected) shows the same verdict/evidence as the CLI and receipt.

## 3. Separation of concerns

Keep these boundaries, but create modules only when there is working behavior behind them.

    src/proofmesh/
      models/       # validated domain records, no I/O dependencies
      core/         # TaskFile, snapshots, scope, verification, freshness,
                    # evaluator, loop detector, handoff
      storage/      # SQLite schema, transactions and parameterized queries
      providers/    # one configured check provider
      adapters/     # MCP plus one verified hook adapter
      cli.py        # argument parsing and orchestration only
      report.py     # render persisted facts; do not invent a verdict
      demo.py       # deterministic seeded end-to-end scenario

Rules:
- Domain models do not import SQLite, MCP, subprocess, or host SDKs.
- Core services own policy and are testable without an agent.
- Storage persists validated records but never decides acceptance.
- Providers run trusted gate IDs and return facts; the evaluator decides.
- MCP, hook and CLI layers translate inputs/outputs and invoke the same core.
- Reports render persisted events/evidence/verdicts rather than recomputing them.
- Browser testing and a decision advisor are extensions, not independent control loops.
- Do not scaffold empty future modules just to make the repository look larger.

### Parallel implementation strategy (developer workflow, not product scope)

Subagents are encouraged for isolated implementation and verification work, but ProofMesh itself must not become an agent orchestrator.

- Keep one main integrator responsible for shared interfaces, merges, final validation, and scope decisions.
- Parallelize only after module contracts and file ownership are written down. Good independent tasks include a read-only security/code audit, a pure TaskFile parser, or repository snapshot/scope reporting after their input/output contracts are agreed.
- Prefer one read-only reviewer plus one implementer in an isolated branch/worktree. Cap normal concurrency at two or three agents; additional agents are worthwhile only when their work and review are genuinely independent.
- Do not let parallel agents edit shared models, storage schema, or public interfaces simultaneously. The integrator resolves shared-interface changes before other work depends on them.
- Each agent must return changed paths, assumptions, exact checks run, test output/result, known gaps, and a reviewable diff/commit. Do not accept “tests pass” without the commands/results.
- Integrate deliberately and rerun the full suite on the merged tree. A subagent's isolated test result does not prove the merged system works.
- Record material AI-tool contributions accurately in `AI_USAGE.md`. Do not store private reasoning or transcripts as project artifacts.

## 4. Data integrity that must not be cut

- Approved TaskFile revisions are append-only; amendments create a new revision.
- Evidence identifies the task revision, check/config, code fingerprint, status, time and bounded artifact references.
- Write related event/evidence/verdict state transactionally.
- Use parameterized SQL and strict validation at trust boundaries.
- Store the DB and artifacts outside the agent-writable project directory with restrictive local permissions.
- Never automatically reset, clean or roll back the user's working tree.
- Bound command duration and output; run only configured gates.
- Treat hook retries as duplicate-prone; make event handling idempotent.
- Unknown integration or evidence state is not success.
- A hash detects content changes; it does not authenticate a user.
- Do not store chain-of-thought or full transcripts by default. Persist concise event summaries and relevant failure excerpts.

## 5. Decision-model integration: valuable, but not the foundation

A decision advisor could make the demo more interesting, but ProofMesh must remain trustworthy when no model is available.

- Deterministic code owns TaskFile integrity, gate execution, freshness, retry budgets and the final verdict.
- If time permits, ask one narrow typed question such as whether a completion claim omits a requirement or whether a change needs human review.
- The advisor may add WARN or REQUIRE_APPROVAL. It cannot produce ACCEPTED or override mandatory failures.
- Advisor timeout/error must not affect the deterministic result.
- No new paid service, account or large local model download.
- If it is not already easy to invoke, leave the advisor as roadmap and invest in verified host integration and evidence presentation.

## 6. Two-to-three-minute demo script

1. Show the approved TaskFile and acceptance criteria.
2. Show a deliberately out-of-scope change and the corresponding scope finding.
3. Run the configured check and show its evidence and blocking result.
4. Repeat the same failure to demonstrate the retry limit and compact handoff.
5. Change relevant code after a passing check to demonstrate stale evidence.
6. Fix the issue, rerun the check and show fresh evidence changing the verdict to ACCEPTED.
7. Show the real agent's MCP request and a real hook event if verified.
8. Show the report/receipt and the actual enforcement level.

Use the live app/agent only as an extra credibility moment after the prepared fixture works. The fixture is the reliable demo; a live agent is not a single point of failure.

## 7. Long-term roadmap (not tonight's scope)

1. More verified host adapters, universal plugin installation and diagnostics.
2. CI/PR verdict receipts and required-merge policies for hosts without reliable hooks.
3. Existing Playwright, API, database, log and performance verification providers.
4. Richer dependency impact, test obligations, test-quality and mutation analysis.
5. Stepwise refactors and change budgets.
6. Optional decision advisors and Guided/Flow/Strict/Custom profile presets.
7. Multi-worktree/subagent event attribution and cross-agent handoffs.
8. Policy packs, verification-provider SDK and team policy management.
9. Review, deployment and incident follow-up integration.

## 8. End-of-night checklist

- [ ] Core scenario passes twice from a clean state.
- [ ] One real MCP client/agent is connected.
- [ ] One real hook is demonstrated, or its limitation is clearly marked.
- [ ] Failed/stale/missing/unknown mandatory evidence cannot produce ACCEPTED.
- [ ] State survives process restart.
- [ ] Repeated failure terminates within budget.
- [ ] Markdown report and JSON receipt match persisted state.
- [ ] README quick start matches actual working commands.
- [ ] Live demo has a recorded fallback.
- [ ] No unsupported claims about universal enforcement or full multi-agent visibility.
