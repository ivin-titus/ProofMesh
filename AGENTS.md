# Agent instructions for ProofMesh

Read the project documents before implementation changes:

1. [PRD](docs/PRD.md) — user problems, product behavior, priorities, and acceptance criteria.
2. [TRD](docs/TRD.md) — technical boundaries, data integrity, security, and MVP scope lock.
3. [Build plan](docs/BUILD_PLAN.md) — implementation order, time boxes, and scope cut lines.
4. [AI assistance record](AI_USAGE.md) and [change log](CHANGELOG.md) — contribution transparency and project history.

## Which document wins?

- The PRD defines product behavior and requirement priority.
- The TRD's §0 scope lock and §20 definition of done define the technical MVP boundary. Longer sections include future design and historical decisions; they do not automatically promote a roadmap feature into the MVP.
- The build plan chooses implementation order within those boundaries.
- The PRD, TRD, and build plan must agree. If a conflict is found, update the documents together before implementing the disputed feature. Do not use a stale historical note to expand scope.

## Product boundary

- ProofMesh is an intent, intervention, and evidence control layer for existing agents.
- Do not build a new coding-agent harness, model loop, agent scheduler, IDE, or issue tracker.
- Prioritize one working end-to-end control loop over broad feature coverage.
- Keep future roadmap ideas separate from demo requirements.
- Do not scaffold modules that have no working behavior yet.

## Coding and security practices

- Prefer straightforward, idiomatic code, small functions, clear names, and one responsibility per module.
- Use the simplest implementation that satisfies a current acceptance criterion; keep dependencies few and purposeful.
- Validate input, handle errors explicitly, and provide actionable failure messages.
- Treat repository content, tool output, logs, and agent-provided data as untrusted input.
- Never execute arbitrary model-supplied shell commands. Use allowlisted gate IDs, argument arrays, timeouts, and bounded output.
- Do not reset, clean, or overwrite a developer's working tree as a recovery strategy.
- Keep approved task revisions immutable and verification evidence bound to the code state it checked.
- Domain models must not depend on MCP, hook formats, SQLite, or subprocess execution. Core policy stays testable without a live agent.
- Storage persists validated records but does not decide acceptance. Verification providers return facts; the evaluator decides the verdict.
- MCP, CLI, and host hooks call the same core services. Reports render persisted facts and stored verdicts rather than inventing results.
- Never claim an agent hook enforces a rule unless host behavior has actually been tested.

## Subagents and parallel implementation

Use isolated subagents when they increase implementation speed and verification quality, but do not turn ProofMesh itself into an agent orchestrator.

- **High-Parallelism Workflow:** Work is partitioned into bounded features. Each feature implementation subagent operates in an isolated Git worktree (`Workspace: "branch"`), owning only their designated files and tests.
- **Main Agent Integration:** One main agent is solely responsible for architecture decisions, shared data models (`src/proofmesh/models/`), storage schema and migrations, API contract publication (`docs/CORE_API_CONTRACTS.md`), review, integration, merge decisions, and final full-suite runs.
- **Explicit Contracts & Disjoint Ownership:** Parallelize only bounded, genuinely independent tasks with explicit file ownership and published interface contracts. Feature agents must not edit shared models, migrations, or another agent's modules.
- **Independent Read-Only Review:** A dedicated read-only auditor subagent reviews boundaries, fail-open paths, command security, and test gaps concurrently without making overlapping file edits.
- **Accountability & Verification:** Every subagent must report changed files, assumptions, exact commands/checks, actual test results, known limitations, and reviewable diffs.
- **Deliberate Integration:** The main agent merges completed branches incrementally into the main tree, reconciles semantic differences, and reruns relevant and full test suites.
- Keep subagent usage strictly as a developer workflow; multi-agent orchestration, worktree coordination, and model dispatch are not MVP product features.

## Documentation and collaboration

- Update CHANGELOG.md in the same commit as each meaningful milestone. Record the real timestamp/time zone, purpose, validation performed, and known limitations.
- Update README.md when setup, commands, requirements, behavior, or demo instructions change.
- Record meaningful AI assistance in AI_USAGE.md, including tool/model where known, contribution, human review, and actual validation. AI assistance does not imply Git authorship; do not invent tool usage or test results.
- Inspect the current diff, finish coherent milestones, run appropriate checks, then commit. A roughly 30-minute checkpoint is a workflow target, not a reason to create empty commits.
- Never backdate commits, force-push, or rewrite shared history.
- Report tests and validation accurately; distinguish planned, simulated, and verified behavior.
- Never commit credentials, API keys, private participant data, or personal tokens. Use environment variables and sanitized examples. Optional advisor credentials must be read from a trusted environment-variable name and never persisted or exposed in logs, reports, or UI.
- Keep ProofMesh's database and artifacts outside the target project's agent-writable directory. Do not store full chat transcripts or private reasoning by default.

## Development and test execution

- **Runtime Compatibility:** Supported runtimes are Python `>=3.12,<3.15`. Ensure changes are compatible with both host Python 3.12 and target CPython 3.14.
- **Root Convenience Script:** Use `./proofmesh <command>` to run commands directly without manually setting `PYTHONPATH`.
- **Test Execution:** Always verify the full test suite passes with `pytest tests/` (or `.venv/bin/pytest tests/` / `.venv314/bin/pytest tests/`) before finishing any milestone.
- **Reference Documentation:**
  - Architecture and sequence flows: [docs/architecture.md](docs/architecture.md)
  - Hackathon track alignment: [docs/BUILD_TRACKS.md](docs/BUILD_TRACKS.md)
  - Development and packaging: [docs/development.md](docs/development.md)
  - Testing guide and test categories: [docs/testing.md](docs/testing.md)
  - Security, threat model, and containment: [docs/security-and-privacy.md](docs/security-and-privacy.md)
- **Licensing:** ProofMesh is licensed under the GNU Affero General Public License version 3 (`AGPL-3.0-or-later`). Maintain license compliance across all new files and packaging metadata.
