# ProofMesh — Product Requirements Document (PRD)

**Version:** 0.3 (scope-locked hackathon build)  
**Status:** Scope-locked hackathon MVP specification — build may start; long-term vision is explicitly separated  
**Last updated:** 2026-10-24  
**Product type:** Agent-neutral intent, intervention, and evidence control layer for AI-assisted software development

## 1. Executive summary

ProofMesh is a lightweight control layer that helps developers keep AI-assisted implementation aligned with an approved task, detect unproductive or compounding failures, and require current evidence before work is accepted. It integrates with existing coding-agent harnesses through MCP, lifecycle hooks, and a CLI; it is **not** another coding-agent harness or orchestrator.

Its product model has three pillars:

1. **Intent** — preserve the task the developer approved and compare actual changes against it.
2. **Intervention** — detect scope drift, repeated failures, stalled progress, and risky assumptions; provide focused corrective context or escalate.
3. **Evidence** — run relevant checks, associate results with acceptance criteria and the exact code state, and make an explicit completion decision.

The hackathon prototype will prove one end-to-end flow with one real agent integration, a local repository, deterministic verification, and a compact report. Broad ecosystem support is a future direction, not an MVP promise.

## 2. Problem statement

AI coding agents can implement code quickly but can also:

- Misinterpret a user's request and solve the wrong problem.
- Modify unrelated files or expand task scope without justification.
- Build subsequent changes on an unverified assumption or earlier mistake.
- Repeat ineffective repair attempts and consume time/tokens without progress.
- Produce tests that pass without meaningfully testing the requested behavior.
- Report completion even when mandatory checks fail, are stale, or were never run.
- Lose critical constraints and debugging history as tasks pass between agents or context windows.

Testing, code review, agent governance, MCP tooling, and lifecycle hooks exist independently. ProofMesh's intended value is to connect **approved intent → observed change → intervention → current evidence → acceptance verdict** in one lightweight, agent-neutral workflow.

## 3. Product vision and positioning

**Vision:** Become the intent-to-evidence continuity layer for autonomous software development, allowing different agents and verification tools to work on a task without losing its constraints, failure history, or acceptance criteria.

**Positioning statement:** ProofMesh does not decide which coding agent should write the implementation. It provides a shared contract, observes available evidence, detects drift and unproductive work, and evaluates whether a task is eligible for acceptance.

**Role: project manager for task intent.** ProofMesh owns the task contract, scope and acceptance decisions. Agents can propose tasks and amendments; ProofMesh decides whether to reject, accept under policy, or escalate to the user. It does not write code, plan the implementation, or schedule agents.

**Rules files vs enforcement:** AGENTS.md and similar files are advice; agents, especially smaller models on large changes, ignore them. ProofMesh turns the same rules into deterministic checks, write-time hook decisions and acceptance verdicts.

**Long-term differentiators beyond skills and rule files:** evidence-cited completion, stepwise refactors with a change budget, task-state re-anchoring after context loss or an agent switch, focused failure digests with loop detection, and a verdict/receipt that travels with a PR. These describe the broader product direction; the MVP subset is limited by §6 and §9 and the TRD scope lock.

**Agent-neutral long-term goal:** one stable core exposed through MCP, with native hooks where supported and a CI acceptance gate for workflows that produce commits/PRs. The MVP validates one host integration; universal install, multiple native adapters, and CI enforcement are roadmap items.

**Differentiation to demonstrate:** continuity of task intent and verification evidence across code changes and agent handoffs—not merely a browser tester, generic code reviewer, agent router, or pass/fail test runner.

This is a product hypothesis, not a claim that the overall category or any individual capability is unprecedented.

## 4. Product principles

1. **Agent-neutral core:** business rules do not depend on a specific model, harness, editor, or vendor.
2. **Evidence over self-report:** an agent's statement that work is done is not evidence that it is correct.
3. **Honest enforcement:** distinguish advice, observed controls, lifecycle enforcement, and external merge gates. Never claim a session is guarded when the integration is unhealthy or incomplete.
4. **Deterministic decisions where possible:** checks, thresholds, evidence freshness, and hard gates are evaluated by code; use an LLM only for bounded interpretation and explanations.
5. **No harness creep:** ProofMesh does not own agent planning, model selection, task scheduling, or code generation.
6. **Local-first by default:** source, logs, task contracts, and evidence remain local unless the user explicitly configures sharing.
7. **Least privilege:** never execute arbitrary model-generated commands or repository code without explicit policy and isolation.
8. **Lower interaction noise, not lower quality:** modes may reduce interruptions and context size, but do not silently waive mandatory gates.
9. **Runtime data safety:** every input from agents, hooks, files, config or storage is validated against a strict schema before use; invalid data fails closed.
10. **Lightweight by default:** a small Python package with stdlib SQLite and minimal dependencies; no services, containers or accounts required.

## 5. Target users and jobs to be done

### 5.1 Junior developer / AI-assisted beginner

**Needs:** understand a vague task, establish acceptance criteria, learn why a test or policy failed, avoid shipping untested AI-generated code.

**ProofMesh value:** Guided profile explains failed gates, identifies unverified criteria, and provides a concise, actionable next step without silently taking over the entire task.

### 5.2 Experienced solo developer

**Needs:** delegate implementation, reduce repetitive manual checking, avoid irrelevant prompts, and receive an exception only when something meaningful goes wrong.

**ProofMesh value:** Flow profile runs routine checks automatically and interrupts on meaningful scope drift, regressions, repeated failures, or approval-required decisions.

### 5.3 Developer working with multiple agents

**Needs:** preserve the original task and known failures when a main agent delegates to subagents or a different agent resumes the task.

**ProofMesh value:** structured handoff containing contract revision, code-state identifier, changed paths, checks, previous failed attempts, unresolved assumptions, and required next actions.

### 5.4 Developer simplifying an AI-generated codebase (first real user)

**Needs:** refactor a vibe-coded, over-engineered app (the first case is a social media app) into something simple and boring with clear architectural separation, using coding agents, without silently breaking behaviour.

**ProofMesh value:** refactor TaskFiles with explicit invariants, baseline-relative evidence (any pass → fail is a regression), architecture-boundary gates, and simplification metrics in the report.

### 5.5 Team / repository maintainer (future)

**Needs:** apply consistent project-specific acceptance policies across developers, agents, and CI.

**Future value:** versioned policy packs, external merge gates, audit history, and team-wide integrations.

## 6. Goals and non-goals

### 6.1 Demo goal: prove one complete control loop

The demo must show a real, coherent workflow—not a collection of stubbed capabilities:

1. A developer approves a bounded TaskFile contract.
2. ProofMesh records the repository baseline and detects a deliberate scope violation or relevant change.
3. ProofMesh runs at least one real, configured check and binds its result to the approved contract revision and the code snapshot checked.
4. A failed mandatory gate or repeated failure keeps the task unaccepted and produces a focused, actionable handoff.
5. One real agent integration can access ProofMesh; one verified lifecycle hook is used if the initial integration spike confirms it works.
6. After the issue is corrected, fresh evidence changes the deterministic verdict from blocked to accepted.
7. A human-readable and JSON report explains what happened and the integration's actual enforcement level.

The core demonstration must be repeatable without relying on an LLM spontaneously making a specific mistake. Use a prepared fixture with seeded failures for the primary scripted scenario. Then show the same mechanism with the live host agent where feasible.

### 6.2 MVP non-goals

Do not make these prerequisites for the hackathon demo:

- A universal agent installer or support for several native hook formats.
- CI status checks or PR comments on GitHub.
- Full multi-agent scheduling, orchestration, worktree isolation or guaranteed attribution of subagent actions.
- A semantic dependency graph across arbitrary languages and frameworks.
- Comprehensive test-obligation enforcement, mutation testing or autonomous root-cause analysis.
- A new browser automation engine, a full dashboard, or an IDE.
- A bundled/hosted model, decision model, or required network call.
- Team accounts, cloud storage, remote telemetry, or a distributed service.
- Full cross-language architecture analysis or formal proof of program correctness.

### 6.3 Demo scope versus product vision

**Hackathon core (must ship):** TaskFile approval and revision integrity; Git snapshot/scope report; one allowlisted check runner; evidence freshness; deterministic verdict; bounded repeated-failure detection; compact handoff; MCP access; one real host integration; persistent local state; readable/JSON report.

**Stretch only after the end-to-end flow passes repeatedly:** one existing Playwright smoke test for a UI-affecting change OR one optional decision-advisor call for a narrowly typed question. Do not attempt both unless there is clear spare time. The decision advisor may only add a warning or request review; it must never approve work or override deterministic gates.

**Long-term vision:** additional host adapters, stronger write-time controls, CI/merge gates, decision-model integrations, richer API/database/log/browser verification, multi-agent handoffs, stepwise refactors, test-quality analysis, policy packs, and a verification-plugin ecosystem. The architecture should leave room for these without requiring them now.

The prototype is successful when the core control loop is real and understandable. Feature count and framework breadth are secondary.

### 6.4 Explicit scope-control rule

A proposed feature belongs in the MVP only if it is needed to demonstrate Intent, Intervention, or Evidence in the single end-to-end flow. If it adds another independent subsystem, host integration, remote service, or orchestration responsibility, defer it unless the core is already reliable.

## 7. Core product model

### 7.1 Intent

A TaskFile is the approved task contract, written as a **structured Markdown file** (small TOML front matter plus fixed sections) so it is easy for both people and LLMs to read and draft, while staying strictly machine-parseable. It captures:

- Task ID and revision.
- User objective and explicit non-goals.
- Acceptance criteria with stable IDs.
- Allowed/restricted paths or change categories, where useful.
- Required verification gates.
- Constraints, assumptions, risk level, and approval requirements.
- Approval metadata and contract digest (stored by ProofMesh, not trusted from the editable file).

TaskFiles are owned by ProofMesh and stored in its local database, not in the repository. Agents read them through ProofMesh and can only submit proposals; no TaskFile is created or changed without a ProofMesh decision (policy rule or user approval requested by ProofMesh).

For a precise request, ProofMesh can propose a contract directly. For a vague request (e.g., "notifications are broken"), the agent can perform bounded, read-only investigation and propose a likely cause, plan, scope, risks, and acceptance criteria. The user approves the implementation contract or clarifies consequential ambiguity before implementation proceeds. The user is authorizing the objective and constraints; the agent discovers the solution.

An approved contract revision is immutable. An agent may submit an amendment proposal but cannot silently alter the approved intent. Approval must create a new revision and digest. A hash detects change; it is not, by itself, a cryptographic identity or proof of user authorization.

### 7.2 Intervention

ProofMesh evaluates observable signals such as:

- Changes outside the declared scope.
- A policy or TaskFile changing after approval.
- Repeated failures with the same normalized signature.
- Consecutive attempts that make no measurable progress.
- Previously passing checks becoming failures.
- A proposed change depending on failed or unverified behavior.
- A completion request while mandatory evidence is missing, failed, or stale.

Actions are `CONTINUE`, `NUDGE`, `REQUIRE_APPROVAL`, `STOP_AUTOMATIC_RETRIES`, or `BLOCK_ACCEPTANCE`. These are policy outcomes, not promises that every host agent can be forcibly stopped. If a hook cannot enforce an action, ProofMesh records the limitation and exposes the acceptance state independently.

### 7.3 Evidence

Evidence records identify a check, what it covers, the source and configuration of the check, the relevant code-state fingerprint, the contract revision, timestamp, exit status, summary, and artifact references. Evidence status includes `PASSED`, `FAILED`, `NOT_RUN`, `UNKNOWN`, or `STALE`.

A test passing is evidence only for the behavior it actually asserts. ProofMesh must not claim universal correctness from a green test suite.

### 7.4 Completion state

Keep agent self-report separate from product state:

- `IMPLEMENTED` — the agent claims the task is done.
- `VERIFIED` — required evidence is current for the relevant code state.
- `ACCEPTED` — all mandatory gates pass and required approvals exist.
- `BLOCKED` — a mandatory gate fails or a policy blocks acceptance.
- `NEEDS_APPROVAL` — a consequential decision requires the user.
- `UNKNOWN` — required evidence or integration health is missing.

An agent may say "done" in its response. Only ProofMesh's evaluator can mark a task `ACCEPTED` under the configured policy.

## 8. Operating profiles

Profiles configure the same core; they must not be separate logic implementations.

- **Guided:** more explanations, visible intermediate findings, explicit help for missing acceptance criteria, and educational failure summaries.
- **Flow:** low interruption; run routine safe checks automatically and interrupt on meaningful drift, regressions, repeated failures, high-risk actions, or required approvals.
- **Strict:** require stronger gates and explicit approval for configured risky changes. Strict mode still cannot guarantee enforcement when the host integration is bypassed.
- **Custom:** repository-defined gate rules and thresholds.

Mandatory gate failures cannot be converted into success merely by changing profiles. A profile can change notification, escalation, and autonomy policy, not the truth of evidence.

Profiles also set the **human-in-the-loop line**: ProofMesh decides routine matters itself and asks the developer for critical ones (initial contract, weakening amendments, restricted paths, policy changes, waivers). Guided and Strict ask more often; Flow auto-accepts strengthening amendments and final acceptance when all gates pass. The full matrix is in TRD §6.1.

## 9. Functional requirements

Priority definitions: **P0 — build now**; **P1 — stretch after the end-to-end flow is reliable**; **Future — preserve as roadmap, do not implement for this demo**. This priority table is authoritative if other sections describe broader capabilities.

| ID | Priority | Requirement | Acceptance condition |
|---|---|---|---|
| FR-01 | P0 | Propose and approve a TaskFile | A structured Markdown task validates into objective, acceptance criteria, scope, required gates and constraints; the user can approve it through a simple CLI flow. |
| FR-02 | P0 | Preserve intent revisions | Approved contracts are immutable; an amendment proposal cannot silently change the approved revision. A new approval creates a new revision and digest. |
| FR-03 | P0 | Snapshot repository changes | Record a baseline and report tracked/untracked changes and suspicious paths relative to the task scope. Do not claim semantic certainty from path matching alone. |
| FR-04 | P0 | Run configured verification | Only trusted, preconfigured gate IDs can run. Each check has a timeout and bounded output and produces a structured result. |
| FR-05 | P0 | Preserve evidence integrity/freshness | Evidence records identify contract revision, check/config and code fingerprint. A relevant later change marks the evidence stale. |
| FR-06 | P0 | Evaluate acceptance deterministically | Mandatory failed, stale, missing or unknown evidence cannot produce `ACCEPTED`. Agent self-report remains distinct from ProofMesh's verdict. |
| FR-07 | P0 | Detect repeated failures | Repeated normalized failure or no progress triggers a bounded intervention and compact handoff; it cannot create an unbounded completion-hook loop. |
| FR-08 | P0 | Expose core actions through MCP | A connected agent can read the task, inspect status, request configured verification, retrieve the verdict and request a handoff. |
| FR-09 | P0 | Integrate one real lifecycle hook | Select one host only after a short compatibility spike. The hook records a real event and checks status/requests continuation where the host supports it. Never fake a host integration. |
| FR-10 | P0 | Declare enforcement coverage | Report `ENFORCED`, `PARTIAL`, or `UNGUARDED` according to the actual adapter capabilities and health. |
| FR-11 | P0 | Create a compact handoff | Include approved intent/revision, code state, changed paths, blockers, exact relevant failure, previous attempts, unresolved assumptions and next action. |
| FR-12 | P0 | Persist state safely | SQLite state lives outside the target workspace; revisions/events/evidence are committed transactionally and survive process restarts. ProofMesh itself does not mutate the project working tree. |
| FR-13 | P0 | Validate trust boundaries | Strict models validate TaskFile, policy, MCP and hook inputs. Only allowlisted commands/gates may run; timeout and output limits are enforced. |
| FR-14 | P0 | Provide repeatable demo/report | One command runs a prepared, network-independent core scenario and produces Markdown + JSON reports. Seeded/simulated events are labelled as such. |
| FR-15 | P1 | Browser smoke verification | Reuse an existing Playwright test/script for a UI-affecting task. If unavailable, explicitly report UI verification as unverified. No new browser automation framework. |
| FR-16 | P1 — stretch | Optional decision advisor | One optional, narrow typed question may return an advisory warning/request-review result. It is off by default, never accepts work, and failure/unavailability does not affect deterministic gates. |
| FR-17 | P1 — stretch | Guided/Flow/Strict profiles | Profiles alter explanation and interruption policy, not truth of evidence or mandatory gate outcomes. A minimal preset is enough. |
| FR-18 | Future | CI/PR verdict and receipt | Re-run trusted checks against the final PR snapshot and report verdict independent of agent hooks. |
| FR-19 | Future | More host adapters and universal installation | Add adapters only after their actual hook payloads and response semantics are verified with golden-file tests. |
| FR-20 | Future | Multi-worktree/subagent tracking | Attribute events where available and verify the integrated final snapshot; report unknown attribution honestly. |
| FR-21 | Future | Advanced test obligations and test-quality checks | Detect missing/weak tests, test deletion/skips and fail-on-baseline bugs with explicit handling for flaky or inconclusive results. |
| FR-22 | Future | Project auto-initialization and architecture rules | Detect stacks without executing repository code, propose a policy for approval, and add language-specific rule providers. |
| FR-23 | Future | Stepwise refactors and change budgets | Unlock ordered refactor steps only after verification; require approval when a configured change budget is exceeded. |
| FR-24 | Future | Team policy packs and verification plugin ecosystem | Add typed verification providers and reusable repository policies without changing the core evaluator.

## 10. Quality gates

A minimal policy format should support:

- Gate ID and type.
- Whether it is mandatory.
- Path/change conditions.
- Timeout and retry policy.
- Criteria covered.
- Failure severity and optional approval requirement.
- Trusted command reference or plugin ID.

Initial gate types: `scope-drift`, `configured-command`, `test-suite`, `api-contract` (if a prepared check exists), `browser-smoke` (P1), `evidence-freshness`, `task-contract-integrity`, and `repeated-failure`.

Repository configuration is untrusted if the agent can edit it. For the demo, load trusted policy from a user-controlled config or pin its digest at session start; any policy change during the task must be detected and treated as a blocker or approval request.

## 11. Context and I/O optimization

ProofMesh should minimize unnecessary context passed through its own tools and supported integrations. It must not claim universal interception of private model context or every token exchanged inside an agent harness.

The compact handoff format should contain:

1. Approved intent and constraints.
2. Relevant changed files/dependencies.
3. Current code-state fingerprint.
4. Exact failure signature and summarized relevant output.
5. Attempts already made and their outcomes.
6. Known facts versus unverified assumptions.
7. Required next action and hard constraints.

Never compress away information that changes the diagnosis. Preserve exact error lines, API response details, identifiers, and file locations when relevant. Avoid full transcript retention by default; redact secrets and retain artifact references instead of duplicating large logs.

## 12. UX and reporting requirements

The user should be able to answer quickly:

- What did I ask for, and which contract revision is active?
- What changed, and what is suspicious or outside scope?
- Which checks ran against which code state?
- What is failed, stale, unknown, or not run?
- Is the agent integration actually enforcing anything?
- Why is acceptance blocked, and what is the smallest useful next action?

The report should show a timeline, scope findings, gate outcomes, intervention count, evidence references and the final verdict. The hackathon UI may be a lightweight web page or a polished terminal output; correctness of the core takes priority over UI breadth.

## 13. Success metrics

### Hackathon exit criteria (must pass)

- The prepared demo runs end-to-end after installation without a required model/API call for the core path.
- An approved TaskFile cannot be silently amended by an agent.
- A deliberate scope finding is visible and tied to the task contract.
- A real configured check runs and its result is recorded against a code-state fingerprint.
- A mandatory failure, stale result, or unknown mandatory gate blocks acceptance.
- A relevant edit invalidates earlier evidence.
- Repeated failure reaches a configured retry limit and produces a useful handoff without looping indefinitely.
- One real host integration is demonstrated. A native hook counts only if its actual payload and response were verified; otherwise declare the integration partial and demonstrate the supported MCP/CLI path honestly.
- The final report explains the verdict, gate evidence, enforcement coverage, and remaining unknowns.

### Stretch indicators

- One existing Playwright smoke test captures a meaningful UI assertion.
- OR one optional decision-advisor call improves a narrowly scoped warning/question while deterministic policy remains authoritative.
- A compact handoff is reused by a second agent or fresh session without losing contract and failure context.

### Future product metrics (measure before making claims)

- Unintended scope changes caught before acceptance.
- Share of acceptance criteria backed by fresh, relevant evidence.
- Repeated-failure loops avoided and retries saved.
- Verification latency and context size reduced in supported handoffs.
- False-positive rates for scope and no-progress findings.
- Percentage of sessions with accurately reported enforcement coverage.

Do not claim productivity or quality improvements until measured against a baseline.

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Agent ignores MCP | Use supported lifecycle hooks and external Git/CI gates where available; report enforcement level honestly. |
| Hook unavailable, disabled or unhealthy | Mark session partial/unguarded; never imply a guarantee. |
| False-positive scope drift | Explain evidence; use warning/justification tiers instead of blocking every extra file. |
| Stale or mismatched test evidence | Bind results to contract revision and code-state fingerprint; recheck after changes. |
| Unobservable subagents | Report attribution as best-effort; inspect integrated final state. |
| Retry hook itself loops | Make calls idempotent, track continuation budget, and eventually stop continuation while keeping acceptance blocked. |
| Arbitrary code execution | Allowlisted gate IDs, command allowlists, timeouts and isolated test environment. |
| Policy altered by agent | Keep trusted policy outside writable scope where practical and verify digest. |
| Scope creep | Require each new feature to strengthen Intent, Intervention, Evidence, or an adapter required to expose those pillars. |

## 15. Demo narrative

### Primary demo: one visible, repeatable control loop

Use a prepared sample repository with an intentional scope/verification failure. The demo must work even if the live agent behaves perfectly or the network is unavailable.

1. **Intent:** propose and approve a refactor or bug-fix TaskFile with a small set of acceptance criteria and one scope restriction.
2. **Baseline:** record the starting code fingerprint and baseline check result.
3. **Intervention:** introduce or demonstrate a change outside declared scope, and show a scope finding tied to the task.
4. **Verification:** run a real configured test/check, retain its bounded output, and associate it with the criterion and code state.
5. **Failure:** make the required check fail; ProofMesh reports `BLOCKED`, not accepted.
6. **Loop protection:** repeat the same failure signature until the configured budget is reached; ProofMesh stops automatic retries and provides a focused handoff.
7. **Freshness:** change relevant code after a passing check and show the prior evidence becomes `STALE`.
8. **Recovery:** fix the issue, rerun verification and show fresh evidence changing the verdict to `ACCEPTED`.
9. **Integration:** show a real agent asking ProofMesh for status/verification and one real hook event if verified. The report displays the actual enforcement level.

### Optional live extension

If the core is stable, run one of the same checks against the developer's real social-media project through the host selected and verified in the integration spike. Antigravity is a candidate, not a prerequisite. Then choose **one** stretch feature: a Playwright UI smoke test or a narrow decision-advisor call. Do not depend on the real repository or a live model making a particular mistake for the main story.

Keep a recorded run and exported reports as backup; label any seeded/replayed events. The decision model, if shown, is advisory only and must never replace the deterministic verdict.

## 16. Roadmap

### Hackathon demo — current scope

One local repository, one approved TaskFile, Git scope analysis, one allowlisted check runner, evidence freshness, deterministic verdict, bounded failure-loop detection, compact handoff, SQLite persistence, MCP interface, one validated host integration, and Markdown/JSON report.

### Next iteration

Existing Playwright smoke-check provider, simple operating profiles, optional advisory decision-model integration, richer check providers, project initialization, and improved architecture/test-obligation checks.

### Long-term vision

Additional hook and agent adapters; CI and merge gates; multi-worktree/subagent event attribution; policy packs and verification plugins; richer runtime diagnostics across APIs, databases, logs and traces; test-quality/mutation analysis; stepwise refactor budgets; team policy management.

The long-term ecosystem is an intent-to-evidence continuity layer across agent handoffs—not a new coding-agent harness or task orchestrator. The MVP must not attempt to implement the entire roadmap.

## 17. Assumptions and open decisions

- MVP is local-first and focused on a prepared repository.
- Python 3.14 is the implementation language; Pydantic v2 (strict) provides runtime validation.
- ProofMesh is a native Python package (no Docker in the runtime path).
- SQLite is the only store; scope is limited to what the hackathon demo needs.
- The event's judging and review format is set by its organizers; this product specification does not assume a particular review tool or judging process.
- Detailed decisions and open questions are tracked in TRD §23.
- One native lifecycle integration is the target; the first compatibility spike chooses the host. Antigravity may be tested first if already available, but it is not a requirement. If the hook contract cannot be verified quickly, use another host with a demonstrable integration or report the supported path as partial/unguarded.
- The MVP does not provide formal correctness proofs.
- User approval can be represented by an explicit local CLI/UI action plus a contract digest; cryptographic identity is future work.
- A completion hook may request continuation but cannot guarantee that the agent will obey forever or prevent a separate chat message claiming completion.
- The core is designed to be agent-neutral. The hackathon implementation validates one host only; Codex, Claude Code, Google Antigravity, OpenCode and Devin remain adapter targets, not implied MVP support.

- **Constraints:** zero budget; developer hardware is 8 GB RAM, i3 11th gen, no GPU. The MVP needs no paid service, GPU or bundled model. ProofMesh runs only when the host starts it (hook processes, stdio MCP server, CI job).
- A decision-model advisor (for example, via the optional SystemOne/Laya/Jev path described in the TRD) is a stretch feature only. It must not be required for the core demo, increase mandatory resource/network requirements, or override deterministic acceptance gates.

## 18. Reference links

- MCP specification and release notes: https://modelcontextprotocol.io/specification/
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Agent Client Protocol: https://agentclientprotocol.com/ and https://github.com/agentclientprotocol/agent-client-protocol
- Codex hooks: https://learn.chatgpt.com/docs/hooks
- Codex advanced configuration: https://learn.chatgpt.com/docs/config-file/config-advanced
- Playwright MCP: https://playwright.dev/mcp/introduction
- Chrome DevTools for agents: https://developer.chrome.com/docs/devtools/agents/get-started
- BeforeDone (adjacent project for competitive review): https://github.com/rrrrrredy/beforedone
