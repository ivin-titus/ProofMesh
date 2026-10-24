# ProofMesh — Product Requirements Document (PRD)

**Version:** 0.1  
**Status:** Hackathon MVP specification  
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

### 5.4 Team / repository maintainer (future)

**Needs:** apply consistent project-specific acceptance policies across developers, agents, and CI.

**Future value:** versioned policy packs, external merge gates, audit history, and team-wide integrations.

## 6. Goals and non-goals

### 6.1 Hackathon goals

- Demonstrate a working TaskFile contract and prevent silent edits to an approved revision.
- Compare repository changes against task scope and explain suspicious changes.
- Execute real, configured checks and connect results to acceptance criteria.
- Detect a repeated failing check and stop unproductive automatic continuation within a defined retry budget.
- Mark evidence stale when relevant code changes.
- Expose core operations through MCP and integrate one real lifecycle hook.
- Produce a clear, machine-readable verdict and human-readable report.
- Demonstrate a compact, structured handoff that preserves relevant context.
- Include a browser smoke test for a UI-affecting sample task if the end-to-end core is stable.

### 6.2 Non-goals for MVP

- Building or replacing a coding-agent harness, IDE, issue tracker, CI platform, or multi-agent orchestrator.
- Universal integrations with every coding agent or guarantees over uninstrumented subagents.
- Full cross-language static analysis or a complete semantic dependency graph.
- Proving program correctness in the formal-methods sense.
- Executing arbitrary commands proposed by an LLM.
- Broad autonomous root-cause analysis across production logs, databases, traces, and every framework.
- Fully autonomous edits to the task contract or repository policy.
- Cloud service, team accounts, remote telemetry, or hosted evidence storage.

## 7. Core product model

### 7.1 Intent

A TaskFile is the approved task contract. It captures:

- Task ID and revision.
- User objective and explicit non-goals.
- Acceptance criteria with stable IDs.
- Allowed/restricted paths or change categories, where useful.
- Required verification gates.
- Constraints, assumptions, risk level, and approval requirements.
- Approval metadata and contract digest.

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

## 9. Functional requirements

Priority definitions: **P0** = necessary for the hackathon end-to-end demo; **P1** = only after the P0 flow is stable; **Future** = architecture should not prevent it, but it is not promised in the demo.

| ID | Priority | Requirement | Acceptance condition |
|---|---|---|---|
| FR-01 | P0 | Create a TaskFile for a task | Contract contains objective, acceptance criteria, scope/risk fields, gates, revision and digest. |
| FR-02 | P0 | Preserve approved intent | An agent cannot silently modify an approved revision; amendments require a new revision and approval event. |
| FR-03 | P0 | Inspect changes | Compare the start baseline with current tracked and untracked files; report changed paths and scope findings. |
| FR-04 | P0 | Run configured checks | Only configured gate IDs can invoke checks; each produces a structured result, timeout status and evidence record. |
| FR-05 | P0 | Bind evidence to code state | Evidence identifies the contract revision and a code-state fingerprint; relevant changes invalidate or mark evidence stale. |
| FR-06 | P0 | Evaluate completion | Return a deterministic verdict from contract, evidence, policy, and integration health. |
| FR-07 | P0 | Detect repeated failure | Detect repeated normalized failures or no progress; stop automatic retries after a configurable budget. |
| FR-08 | P0 | Expose core through MCP | A compatible agent can read the contract, inspect changes, run configured verification, retrieve status and request a handoff. |
| FR-09 | P0 | Integrate one lifecycle hook | A supported hook records an event and checks completion status; continuation is bounded and documented. |
| FR-10 | P0 | Show enforcement coverage | Report `ENFORCED`, `PARTIAL`, or `UNGUARDED` based on adapter capabilities and health. |
| FR-11 | P0 | Generate a compact handoff | Include objective, contract revision, changed paths, current code state, failed checks, prior attempts, unresolved assumptions and required next action. |
| FR-12 | P1 | Trigger browser verification on UI changes | If a configured UI path changes, run a configured Playwright smoke test or explicitly report UI verification unavailable. |
| FR-13 | P1 | Guided/Flow/Strict profiles | Profile changes explanations and intervention behavior without bypassing mandatory gates. |
| FR-14 | Future | Multi-worktree/subagent tracking | Attribute events where available and verify the final integrated snapshot. |
| FR-15 | Future | Broad plugin ecosystem | Add typed adapters for more agents and verification providers without changing core policy logic. |

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

### Hackathon success criteria

- Demonstrate one real agent integration end-to-end.
- Catch a deliberate scope violation.
- Catch a deliberately failing or weak verification condition.
- Detect repeated failure and stop automatic continuation within the configured budget.
- Show evidence becoming stale after a relevant edit.
- Show a task transition from blocked to accepted only after required checks pass.
- Browser smoke test executes when configured and relevant, or the report explicitly shows that browser verification is unavailable.
- Complete the demo without network connectivity being required for the core verification path, except for the chosen agent/LLM itself.

### Future product metrics

- Rate of unintended scope changes caught before acceptance.
- Percentage of completion decisions supported by fresh evidence.
- Repeat-failure loops prevented and average retries avoided.
- Median verification overhead and context tokens saved in supported handoffs.
- False-positive rate of scope and loop findings.
- Percentage of sessions accurately classified by enforcement capability.

Do not claim quality improvement from these metrics until they are measured against a baseline.

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

Use a prepared repository with a small FastAPI service and a minimal frontend. Create a task with clear acceptance criteria and a UI-affecting behavior. Demonstrate:

1. Create and approve the TaskFile.
2. Let a real supported coding agent make changes.
3. Detect an unrelated change or a required test regression.
4. Show a focused intervention and bounded retry behavior.
5. Run backend/API checks and, if configured, a Playwright smoke test.
6. Correct the defect and re-run checks.
7. Show fresh evidence and `ACCEPTED`; show the integration coverage report.

Use deterministic seeded cases so the demonstration does not depend on an LLM making a specific mistake on demand. Label scripted or replayed multi-agent events as simulations; do not imply the system observed a real subagent if it did not.

## 16. Roadmap

- **MVP:** single local repository, TaskFile, scope analysis, configured checks, evidence freshness, repeated-failure detection, MCP, one lifecycle hook and completion report.
- **Next:** Playwright plugin, profiles, richer API/runtime diagnostics, better dependency mapping, improved task amendment workflow.
- **Later:** multi-worktree and subagent event attribution, additional coding-agent adapters, policy packs, CI/merge gates, plugin SDK, team policy management.
- **Long-term vision:** intent-and-evidence continuity across multi-agent implementation, testing, review, deployment and incident follow-up—without taking over agent orchestration.

## 17. Assumptions and open decisions

- MVP is local-first and focused on a prepared repository.
- Python is the primary implementation language for the prototype.
- One native lifecycle integration is required; broader agent coverage is not.
- The MVP does not provide formal correctness proofs.
- User approval can be represented by an explicit local CLI/UI action plus a contract digest; cryptographic identity is future work.
- A completion hook may request continuation but cannot guarantee that the agent will obey forever or prevent a separate chat message claiming completion.
- The exact first agent adapter should be selected based on which supported harness is available and testable at the event; Codex is a candidate because its official documentation describes `Stop` and `SubagentStop` hooks.

## 18. Reference links

- MCP specification and release notes: https://modelcontextprotocol.io/specification/
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Agent Client Protocol: https://agentclientprotocol.com/ and https://github.com/agentclientprotocol/agent-client-protocol
- Codex hooks: https://learn.chatgpt.com/docs/hooks
- Codex advanced configuration: https://learn.chatgpt.com/docs/config-file/config-advanced
- Playwright MCP: https://playwright.dev/mcp/introduction
- Chrome DevTools for agents: https://developer.chrome.com/docs/devtools/agents/get-started
- BeforeDone (adjacent project for competitive review): https://github.com/rrrrrredy/beforedone
