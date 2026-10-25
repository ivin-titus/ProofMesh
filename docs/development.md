# ProofMesh Developer & Contributor Guide

This guide details environment setup, virtual environment management, packaging, CLI workflows, and development conventions for ProofMesh.

---

## 1. Prerequisites & Supported Runtimes

ProofMesh supports Python `>=3.12,<3.15`. The codebase and complete test suite are continuously verified across two environments:
- **Target Runtime**: CPython 3.14 (pinned via `uv.lock`, tested on CPython 3.14.9).
- **Host Runtime**: Python 3.12 (tested on Python 3.12.3).

### Required Tooling
- Python 3.12 or Python 3.14 installed on your system.
- `uv` (recommended package manager) or standard `pip`.
- Git for repository tracking.

---

## 2. Environment Setup

### Option A: Using the Repository Convenience Runner (`./proofmesh`)
The repository includes a self-contained executable shell script [`./proofmesh`](../proofmesh) at the root. It automatically detects and dispatches to the active virtual environment:

```bash
# Display help and verify environment
./proofmesh --help

# Run the 10-phase recovery demo
./proofmesh demo --dir demo_target
```

### Option B: Setting Up a Python 3.12 or 3.14 Virtual Environment with `uv`

```bash
# Clone repository
git clone https://github.com/ivin-titus/ProofMesh.git
cd ProofMesh

# Create virtual environment with Python 3.12
uv venv .venv --python 3.12
source .venv/bin/activate

# Install dependencies in editable mode
uv pip install -e ".[dev]"
```

Or for Python 3.14:

```bash
# Create virtual environment with Python 3.14
uv venv .venv314 --python 3.14
source .venv314/bin/activate

# Sync dependencies from uv.lock
uv sync
```

---

## 3. Building and Packaging Distribution Wheels

ProofMesh uses standard `setuptools` with `pyproject.toml`:

```bash
# Build standard wheel and source distribution
uv build --wheel

# Inspect built wheel
ls -la dist/
```

Package metadata guarantees that default trusted policies (`src/proofmesh/resources/default-policy.toml`) and database migrations (`src/proofmesh/storage/migrations/*.sql`) survive wheel packaging and installation.

---

## 4. CLI Command Reference

The `proofmesh` command provides a unified operator interface:

| Subcommand | Arguments | Description |
|---|---|---|
| `demo` | `--dir <path>` | Run the deterministic 10-phase recovery demo on a dedicated fixture directory. |
| `init` | `[--path <path>]` | Initialize ProofMesh for a project workspace. Creates storage outside target repository. |
| `task propose` | `<taskfile.md>` | Parse and propose a TaskFile contract revision (initial proposal or revision $N+1$). |
| `task approve` | `<task_id> <revision> --by <user> [--reason <msg>]` | Explicitly approve a proposed TaskRevision, activating the contract. |
| `status` | `[--session-id <id>]` | Display current active session state, contract metadata, snapshot hash, and verdict. |
| `verify` | `<gate_id> [--extra-args ...]` | Execute an allowlisted verification gate (e.g. `pytest`) and record snapshot-bound evidence. |
| `evaluate` | `[--session-id <id>]` | Run deterministic evaluator against active contract, scope rules, and evidence records. |
| `report` | `[--session-id <id>] [--json]` | Render human-readable Markdown verification report or export canonical JSON receipt. |
| `ui` | `[--host 127.0.0.1] [--port 8765]` | Launch zero-dependency read-only local web status panel. |
| `mcp` | `[--repo-root <path>] [--session-id <id>]` | Launch the official ProofMesh MCP server on stdio transport. |

---

## 5. Model Context Protocol (MCP) Integration

ProofMesh exposes its core control layer to any MCP-compatible coding agent over standard input/output.

### Launching the MCP Server
```bash
# Using CLI subcommand
./proofmesh mcp

# Or via Python module directly
python -m proofmesh.adapters.mcp_server
```

### Agent Configuration Examples

#### Claude Code / Cursor (`.agents/mcp.json` or equivalent)
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

#### Google Antigravity Configuration
Add ProofMesh to your workspace MCP tool definitions:
```json
{
  "mcpServers": {
    "proofmesh": {
      "command": "/media/ivintitus/Data/My Projects/Side/ProofMesh/proofmesh",
      "args": ["mcp"]
    }
  }
}
```

---

## 6. Host Lifecycle Hooks Integration

ProofMesh provides a lifecycle hook adapter for hosts that support event interception (such as Google Antigravity):

```bash
# Invoking the hook adapter manually over stdin/stdout:
python -m proofmesh.adapters.antigravity PreToolUse < pre_tool_use_payload.json
python -m proofmesh.adapters.antigravity Stop < stop_payload.json
```

- `PreInvocation`: Injects a concise contract reminder into context.
- `PreToolUse`: Inspects proposed tool arguments. Rejects writes outside approved scope or directory traversal attempts with `{"decision": "deny"}`.
- `Stop`: Evaluates session verification evidence before model exit. If evidence is missing or stale, issues `{"decision": "continue", "reason": "<handoff-card>"}`.

---

## 7. Development & Coding Conventions

1. **Immutable Models**: Domain models in `src/proofmesh/models/` must remain frozen and strictly validated. Never perform in-place mutation on model collections.
2. **Path Containment**: Always normalize paths using `normalize_and_validate_path()` in `src/proofmesh/adapters/hook_protocol.py` to prevent symlink and `..` traversal escapes.
3. **Subprocess Execution**: Never use `shell=True`. Always pass argument lists, enforce execution timeouts, and wrap output streams in `_BoundedStreamDrainer`.
4. **Isolated Storage**: Never write databases or logs into target workspace repositories. Always store persistent records under `~/.local/share/proofmesh/projects/<project-id>/` with `0700`/`0600` permissions.
5. **Preserve Documentation Integrity**: Update `CHANGELOG.md` and `AI_USAGE.md` when introducing meaningful features or bug fixes.
