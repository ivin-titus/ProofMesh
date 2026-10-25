# Dogfooding ProofMesh: Step-by-Step Field Guide

This guide describes how to dogfood ProofMesh safely against a real project (such as Hori-Z or another backend/frontend repository) without risking production branches or dirtying working trees.

---

## 1. Safety Principles

1. **Always use an isolated Git worktree**: Never run agent experiments directly on your main development branch or dirty working trees.
2. **External database location**: ProofMesh automatically stores its SQLite database outside the repository (by default under `~/.local/share/proofmesh/projects/<project-id>/` or specified via `PROOFMESH_DB`).
3. **Fail-closed verification**: Only allowlisted gates execute (`shell=False`, argument arrays, timeouts).
4. **No destructive recovery**: ProofMesh reports scope violations and blocks completion; it never wipes or cleans your working tree.

---

## 2. Setting Up an Isolated Worktree

In your target project's repository (e.g. `Hori-Z`):

```bash
# 1. Create a disposable branch in an isolated worktree
git worktree add ../horiz-dogfood -b proofmesh-test-dogfood

# 2. Change into the disposable worktree
cd ../horiz-dogfood
```

---

## 3. Initializing ProofMesh

Ensure ProofMesh is accessible in your environment:

```bash
# Option A: Create a shell alias pointing to the repository convenience runner
alias proofmesh="/media/ivintitus/Data/My Projects/Side/ProofMesh/proofmesh"

# Option B: Install in editable mode inside your active virtual environment
uv pip install -e "/media/ivintitus/Data/My Projects/Side/ProofMesh[dev]"
```

In the target project worktree (`../horiz-dogfood`):

```bash
# Initialize ProofMesh for this directory
proofmesh init --path .
```

---

## 4. Establishing Approved Intent (`task.md`)

Create a structured TaskFile defining the task contract and security perimeter:

```markdown
+++
task_id = "task-feature-auth-refactor"
version = 1
summary = "Refactor token validation helper in backend"
risk_level = "medium"
allow_paths = ["backend/src/**", "backend/tests/**"]
restricted_paths = ["backend/config/**", "docker-compose.yml", ".env*"]
required_gates = ["pytest"]
constraints = ["Zero database migration", "Preserve existing API response schema"]
max_changed_files = 8
+++

# task-feature-auth-refactor: Refactor token validation helper

## Objective
Clean up token expiration logic in the backend auth service and add unit tests.

## Acceptance criteria
- [AC-1] Refactor token expiration check in backend/src/auth.py (gates: pytest)
- [AC-2] Ensure all unit tests pass (gates: pytest)
```

Propose and approve the contract:

```bash
# 1. Propose contract revision 1
proofmesh task propose task.md

# 2. Human explicitly approves the task revision
proofmesh task approve task-feature-auth-refactor 1 --by $(whoami) --reason "Ready for agent implementation"
```

---

## 5. Live Dashboard & Agent Interception

Open a separate terminal window to run the read-only live web status panel:

```bash
# Starts local read-only dashboard on 127.0.0.1:8765
proofmesh ui --port 8765
```

Open `http://127.0.0.1:8765/` in your browser. The dashboard displays the active contract, snapshot fingerprint, scope findings table, verification evidence table, and verdict badge.

### Connecting Your Coding Agent

**Option A: Model Context Protocol (MCP)**  
In your agent configuration (e.g. `.agents/mcp.json` or Antigravity MCP settings):

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

**Option B: Antigravity Lifecycle Hooks**  
Copy or reference the ProofMesh hook adapter in `.agents/hooks.json` to enforce `PreToolUse` denial for restricted files and `Stop` continuation when evidence is missing.

---

## 6. The Control Loop Walkthrough

### Step A: Inspect Baseline Snapshot
Check current status:
```bash
proofmesh status
```

### Step B: In-Scope Changes
Make an allowed modification in `backend/src/`:
```bash
echo "# token helper comment" >> backend/src/auth.py
proofmesh status
```
Notice scope status reports `✅ Clean (all changes within allowed scope)`.

### Step C: Execute Verification Gate
Run allowlisted pytest:
```bash
proofmesh verify test
```
ProofMesh captures exit code, execution duration, and binds the SHA-256 code snapshot fingerprint to the evidence record.

### Step D: Scope Drift & Tamper Detection
Simulate an agent making an out-of-scope or unauthorized configuration change:
```bash
echo "BYPASS_AUTH=true" >> backend/config/settings.env
proofmesh evaluate
```

**Result:**
- Evaluator halts with `❌ VERDICT: BLOCK`.
- Scope violation reported: `backend/config/settings.env` matches `restricted_paths`.
- Existing `test` evidence is automatically flagged as `stale` because code state changed after the check ran!
- Handoff card displays exact blockers and corrective actions.
- Dashboard at `http://127.0.0.1:8765/` updates to red `❌ BLOCK` badge.

### Step E: Correction and Acceptance
Revert the unauthorized file and re-verify:
```bash
rm backend/config/settings.env
proofmesh verify test
proofmesh evaluate
```

**Result:**
- Evaluator emits `✅ VERDICT: ALLOW`.
- All required gates passed with fresh evidence.
- Scope clean.

---

## 7. Exporting Tamper-Evident Receipts

When the task is complete, export the canonical cryptographic receipt:

```bash
# Export Markdown report for pull request description
proofmesh report > pr-verification-report.md

# Export machine-readable JSON receipt with SHA-256 digest
proofmesh report --json > proofmesh-receipt.json
```

The `receipt_digest` provides a tamper-evident audit record proving exactly which code snapshot, gate executions, and human approvals produced the acceptance verdict.

---

## 8. Cleaning Up

Once dogfooding is finished, tear down the temporary worktree cleanly:

```bash
cd /media/ivintitus/Data/My\ Projects/Side/ProofMesh
git worktree remove ../horiz-dogfood
git branch -D proofmesh-test-dogfood
```
