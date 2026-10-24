# ProofMesh

**An agent-neutral intent, intervention, and evidence layer for AI-assisted software development.**

ProofMesh is designed to keep coding agents aligned with an approved task, detect scope drift and repeated failures, and require current verification evidence before a task can be accepted. It works alongside existing coding-agent tools; it is not another agent harness or orchestrator.

## Project status

**Core package, strict models, and persistent storage implemented.**
- **Checkpoint 0 (Integration spike):** Verified Google Antigravity CLI (`agy` 1.4.7) lifecycle hooks (`PreInvocation`, `PreToolUse`, `Stop`) with denial and continuation semantics, plus live stdio MCP client/server round-trip.
- **Checkpoint 1, 1.1 & 1.2 (Package, policy packaging, migrations, and persistent state):**
  - Package configured via `pyproject.toml` (`requires-python = ">=3.14,<3.15"`, locked via `uv.lock` for CPython 3.14, and source-level test suite verified on host Python 3.12).
  - Canonical default trusted policy packaged in `proofmesh.resources` (`src/proofmesh/resources/default-policy.toml`), guaranteed to survive wheel installation and verified against repository sample.
  - Strict Pydantic v2 models with UTC-normalized timestamps, bounded fields, and deeply immutable nested containers (`tuple`, `MappingProxyType`) preventing in-place mutations.
  - Transactional SQLite migrations with atomic schema upgrades, rollback on failure, and rejection of future schema versions. Built wheel package verified to package and execute migrations in isolated environments.
  - Parameterized SQLite store with secure directory permissions (`0700` across data, intermediate projects, and per-project directories), file permissions (`0600`), and path-traversal prevention with accurate OS error handling.
- **Remaining checkpoints (Checkpoints 2–8):** TaskFile parsing/approval, repository snapshots/scope, verification providers, evaluator/verdicts, and CLI/demo orchestration are active/upcoming milestones.

## Documentation

- [Product Requirements Document](docs/PRD.md) — product goals, MVP scope, acceptance criteria, and roadmap.
- [Technical Requirements Document](docs/TRD.md) — architecture, data model, security, verification, and technical acceptance criteria.
- [Build plan](docs/BUILD_PLAN.md) — implementation checkpoints, time boxes, demo sequence, and cut lines.
- [Hackathon tracks reference](docs/BUILD_TRACKS.pdf) — supporting event context; current organizer instructions remain authoritative.
- [Agent instructions](AGENTS.md) — development practices, security boundaries, and document ownership.
- [AI assistance record](AI_USAGE.md) — documented AI contributions, separate from Git authorship.
- [Change log](CHANGELOG.md) — significant project changes and validation.
- [Submission status](SUBMISSION.md) — project details and outstanding demo/submission checklist.

## Implementation and runtime

The runtime targets Python 3.14 (`requires-python = ">=3.14,<3.15"` in `pyproject.toml`, pinned via `uv.lock` for CPython 3.14). The full test suite and source implementation are verified under both target CPython 3.14.9 and host Python 3.12.3. The stack uses Pydantic v2, standard library SQLite, the official MCP Python SDK, and `uv`. The implementation is strictly local-first with zero external hosted model, paid service, Docker, or network dependencies for the core demo and testing.

### Canonical build and test

```bash
# Build wheel
uv build --wheel

# Run test suite under Python 3.14 or Python 3.12
pytest tests/
```

## Intended demo

**Approved task → repository scope finding → real configured check → code-bound evidence → blocked verdict and focused handoff → correction → fresh evidence → accepted verdict.**

The core demo should be deterministic and repeatable without requiring a live model to make a particular mistake. Seeded or replayed events must be labelled. A real agent/hook integration is only described as working after its actual request/response behavior has been verified.

## Scope and limitations

The [PRD priority table](docs/PRD.md#9-functional-requirements) and [TRD scope lock](docs/TRD.md#0-scope-lock-for-the-hackathon-build) define the MVP boundary. Broader host support, CI/PR gating, multi-agent orchestration, stepwise refactoring, and decision-model integration are not assumed to be MVP features unless those specifications explicitly promote them.

ProofMesh does not prove universal program correctness or forcibly control every uninstrumented agent. MCP access alone is advisory; the actual enforcement level depends on the verified host integration and any independent gate that is configured.
