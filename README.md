# ProofMesh

**An agent-neutral intent, intervention, and evidence layer for AI-assisted software development.**

ProofMesh is designed to keep coding agents aligned with an approved task, detect scope drift and repeated failures, and require current verification evidence before a task can be accepted. It works alongside existing coding-agent tools; it is not another agent harness or orchestrator.

## Project status

**Planning/specification only on this branch. Runtime implementation has not started.** The commands and architecture described in the specifications are design targets, not working features. There is no runnable app or demo yet.

## Documentation

- [Product Requirements Document](docs/PRD.md) — product goals, MVP scope, acceptance criteria, and roadmap.
- [Technical Requirements Document](docs/TRD.md) — architecture, data model, security, verification, and technical acceptance criteria.
- [Build plan](docs/BUILD_PLAN.md) — implementation checkpoints, time boxes, demo sequence, and cut lines.
- [Hackathon tracks reference](docs/BUILD_TRACKS.pdf) — supporting event context; current organizer instructions remain authoritative.
- [Agent instructions](AGENTS.md) — development practices, security boundaries, and document ownership.
- [AI assistance record](AI_USAGE.md) — documented AI contributions, separate from Git authorship.
- [Change log](CHANGELOG.md) — significant project changes and validation.
- [Submission status](SUBMISSION.md) — project details and outstanding demo/submission checklist.

## Planned implementation

The current design targets Python 3.14, Pydantic v2, SQLite, the MCP Python SDK, and `uv`. These are planned choices, not verified installed dependencies. The implementation should stay local-first, use minimal dependencies, and avoid a required hosted model, paid service, Docker runtime, or network dependency for the core demo.

## Intended demo

**Approved task → repository scope finding → real configured check → code-bound evidence → blocked verdict and focused handoff → correction → fresh evidence → accepted verdict.**

The core demo should be deterministic and repeatable without requiring a live model to make a particular mistake. Seeded or replayed events must be labelled. A real agent/hook integration is only described as working after its actual request/response behavior has been verified.

## Scope and limitations

The [PRD priority table](docs/PRD.md#9-functional-requirements) and [TRD scope lock](docs/TRD.md#0-scope-lock-for-the-hackathon-build) define the MVP boundary. Broader host support, CI/PR gating, multi-agent orchestration, stepwise refactoring, and decision-model integration are not assumed to be MVP features unless those specifications explicitly promote them.

ProofMesh does not prove universal program correctness or forcibly control every uninstrumented agent. MCP access alone is advisory; the actual enforcement level depends on the verified host integration and any independent gate that is configured.
