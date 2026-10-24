# ProofMesh

**An agent-neutral intent, intervention, and evidence layer for AI-assisted software development.**

ProofMesh is designed to keep coding agents aligned with an approved task, detect scope drift and repeated failures, and require current verification evidence before a task can be accepted. It works alongside existing coding-agent tools; it is not another agent harness or orchestrator.

## Project status

**Full MVP Control Loop Implemented & Verified (Checkpoints 0 through 7).**

- **Checkpoint 0 (Integration spike):** Verified Google Antigravity CLI (`agy` 1.4.7) lifecycle hooks (`PreInvocation`, `PreToolUse`, `Stop`) with denial and continuation semantics, plus live stdio MCP client/server round-trip.
- **Checkpoint 1, 1.1 & 1.2 (Package, policy packaging, migrations, and persistent state):**
  - Package configured via `pyproject.toml` (`requires-python = ">=3.14,<3.15"`, locked via `uv.lock` for CPython 3.14, and verified on host Python 3.12).
  - Canonical default trusted policy packaged in `proofmesh.resources` (`src/proofmesh/resources/default-policy.toml`), guaranteed to survive wheel installation.
  - Strict Pydantic v2 models with UTC-normalized timestamps, bounded fields, and deeply immutable nested containers (`tuple`, `MappingProxyType`) preventing in-place mutations.
  - Transactional SQLite migrations with atomic schema upgrades and rollback on failure.
  - Parameterized SQLite store with secure directory permissions (`0700`) and file permissions (`0600`) outside target repositories.
- **Checkpoint 2 (Intent / TaskFile):** Markdown TaskFiles with TOML front matter, immutable TaskRevisions, deterministic SHA-256 contract digests, and proposal/human approval workflow.
- **Checkpoint 3 (Repository Snapshot & Scope):** SHA-256 file fingerprinting, git state capture, symlink escape protection, and fail-closed pattern-based scope analysis (`allow_paths`, `restricted_paths`, file limit).
- **Checkpoint 4 (Verification & Evidence Freshness):** Safe allowlisted subprocess gate execution (`shell=False`, argument arrays, bounded 2000-char summaries, execution timeouts) and snapshot-based evidence freshness tracking.
- **Checkpoint 5 (Intervention & Verdict):** Deterministic evaluator returning `ALLOW`, `BLOCK`, or `REQUIRE_APPROVAL`, policy mandatory gate enforcement, repeated failure loop detector with budget exhaustion, and Markdown handoff cards.
- **Checkpoint 6 (Seeded CLI Demo & Receipts):** Unified `proofmesh` CLI, 9-phase deterministic seeded scenario (zero model/network dependency), human-readable Markdown reports, and canonical JSON receipts with SHA-256 digest.
- **Checkpoint 7 (MCP Server & Host Hook Adapter):** Official Python MCP server exposing tools (`get_task_contract`, `inspect_changes`, `run_verification`, `get_status`, `claim_completion`, `get_handoff`) and Antigravity lifecycle hook adapter.

## Quick Start & Usage

### 1. Run the Deterministic Seeded Demo

Run the self-contained 9-phase control loop demo:

```bash
# Using Python 3.14 venv or python directly:
proofmesh demo --dir demo_target

# Or via python module:
python -m proofmesh.cli demo --dir demo_target
```

The demo executes without any external network or model dependency and outputs:
- Phase-by-phase progress directly in the terminal
- Formatted verification report in `demo_target/report.md`
- Tamper-evident receipt in `demo_target/report.json`

### 2. ProofMesh CLI Commands

```bash
# Initialize ProofMesh for a project workspace
proofmesh init --path .

# Propose a TaskFile contract
proofmesh task propose task.md

# Approve a proposed revision (explicit human approval)
proofmesh task approve <task-id> 1 --by alice --reason "Approved for implementation"

# Check active session and contract status
proofmesh status

# Run an allowlisted verification gate (e.g. pytest)
proofmesh verify pytest

# Evaluate session against scope, evidence, and policy
proofmesh evaluate

# Render Markdown report or export canonical JSON receipt
proofmesh report
proofmesh report --json

# Launch local read-only web status dashboard
proofmesh ui --port 8765
```

### 3. Connect Model Context Protocol (MCP) Server

To run the official ProofMesh MCP server over stdio for an agent:

```bash
python -m proofmesh.adapters.mcp_server
```

Or connect it programmatically in your agent config (e.g., in `.agents/mcp.json` or Antigravity settings):

```json
{
  "mcpServers": {
    "proofmesh": {
      "command": "python",
      "args": ["-m", "proofmesh.adapters.mcp_server"]
    }
  }
}
```

## Documentation

- [Product Requirements Document](docs/PRD.md) — product goals, MVP scope, acceptance criteria, and roadmap.
- [Technical Requirements Document](docs/TRD.md) — architecture, data model, security, verification, and technical acceptance criteria.
- [Build plan](docs/BUILD_PLAN.md) — implementation checkpoints, time boxes, demo sequence, and cut lines.
- [Hackathon tracks reference](docs/BUILD_TRACKS.pdf) — supporting event context; current organizer instructions remain authoritative.
- [Agent instructions](AGENTS.md) — development practices, security boundaries, and document ownership.
- [AI assistance record](AI_USAGE.md) — documented AI contributions, separate from Git authorship.
- [Change log](CHANGELOG.md) — significant project changes and validation.
- [Dogfooding Guide](docs/DOGFOODING.md) — step-by-step instructions for testing ProofMesh in isolated worktrees.
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
