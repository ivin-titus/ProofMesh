# ProofMesh

**An intent-to-evidence control layer for AI-assisted software development.**

ProofMesh is an agent-neutral assistant tool that helps keep coding agents aligned with an approved task, detects scope drift and unproductive failure loops, and requires current verification evidence before a task is accepted. It works alongside existing agent harnesses; it is not another coding agent or orchestrator.

## Project overview

- **Project name:** ProofMesh
- **Short description:** Preserve developer intent across AI-assisted implementation, intervene when agents drift or repeat failures, and evaluate completion using fresh, attributable evidence.
- **Team:** Solo project; see [SUBMISSION.md](SUBMISSION.md).
- **Working demo:** Not available yet. The runtime implementation has not started; see [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md).
- **Technology stack:** Planned — Python 3.14, Pydantic v2, SQLite, MCP Python SDK, and uv. These are design choices, not yet verified implementation dependencies.

## Current status

**Documentation and scope planning only. No working application code is available yet.**

The repository currently contains the product and technical specifications, the hackathon build plan, and the event-track reference PDF. Do not assume the architecture or CLI commands described in those documents are implemented until a working implementation is committed.

### Key documents

- [Product Requirements Document](ProofMesh_PRD.md) — product goals, user needs, demo scope, non-goals, acceptance criteria, and roadmap.
- [Technical Requirements Document](ProofMesh_TRD.md) — architecture, domain model, storage, adapters, security, and technical acceptance criteria.
- [Overnight Build Plan](docs/BUILD_PLAN.md) — implementation checkpoints, scope cut lines, demo script, and end-of-night checklist.
- [Repository working rules](RULES.md) and [AI-agent guidance](AGENTS.md).
- [AI usage record](AI_USAGE.md), [change log](CHANGELOG.md), and [submission checklist](SUBMISSION.md).

## Run the project

The project is **not runnable yet** because the implementation is not present. Do not run speculative install/start/test commands or treat planned commands as working.

Once a first vertical slice exists, update this section in the same commit as the corresponding implementation so it contains actual prerequisites, dependency installation, environment setup, start, and test/demo commands.

## Intended demo

The first demo should prove one repeatable control loop:

**Approved task intent → scope/change finding → real configured check → code-bound evidence → blocked verdict/intervention → correction → fresh evidence → accepted verdict.**

The primary demo must not depend on a live model making a specific mistake. Seeded/replayed events must be clearly labelled. One real agent integration is targeted; enforcement guarantees must be described only when the host's actual behavior has been verified.

## Current limitations

- No runtime implementation or runnable demo yet.
- Agent/hook integration compatibility is not yet validated by code.
- Planned stack and architecture remain subject to the implementation and tests.
- The project does not claim to prove program correctness or forcibly control every uninstrumented agent.

## Libraries, APIs, and references

Planned references, not a claim of integrated usage:

- [Model Context Protocol](https://modelcontextprotocol.io/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Pydantic](https://docs.pydantic.dev/)
- [uv](https://docs.astral.sh/uv/)
- [Playwright](https://playwright.dev/) — optional future verification provider.

## Event-template note

The repository adopts general workflow practices from the [DevDay Kochi hackathon template](https://github.com/anima-regem/devday-kochi-hackathon-template), but that template names a different event (DevDay Exchange Community Hackathon, 10–11 October 2026). The project context here is Devin Hacks Kochi, 24–25 October 2026. Do not treat the template's event-specific dates, venue, credit terms, or Codex requirement as rules for Devin Hacks unless the current organizers confirm them. See [RULES.md](RULES.md).
