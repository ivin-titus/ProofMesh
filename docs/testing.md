# ProofMesh Testing & Verification Guide

This document details ProofMesh's testing architecture, test suite organization, integration testing methodology, and execution instructions.

---

## 1. Test Suite Overview

ProofMesh maintains an automated regression and integration test suite consisting of **265 tests across 24 test modules**:

| Environment | Python Version | Total Tests | Passed | Execution Time |
|---|---|---|---|---|
| Target Environment (`.venv314`) | CPython 3.14.9 | 265 | **265** | ~19.8s |
| Host Environment (`.venv`) | Python 3.12.3 | 265 | **265** | ~17.6s |

---

## 2. Testing Philosophy: Real Integration Over Mocks

ProofMesh enforces a strict testing standard: **verify actual operational behavior against real filesystems, databases, subprocesses, and protocol streams.**

### How ProofMesh Avoids Test Artifact False Positives
- **Real SQLite Databases**: Tests create real, temporary on-disk SQLite databases using pytest's `tmp_path`. They verify database schema initialization, atomic migrations, constraint enforcement, and cross-process persistence (`test_separate_process_persistence`).
- **Real Filesystem Snapshots**: Snapshots read real directories on disk, compute real SHA-256 digests, resolve symlinks, and verify that intermediate file modifications invalidate evidence.
- **Real Child Subprocesses**: The verification runner executes real Python child processes (`sys.executable`), capturing stdout/stderr streams, testing execution timeouts, and validating memory boundedness under high-volume log output.
- **Real MCP JSON-RPC Wire Frames**: The MCP test suite launches `mcp_server.py` as an independent subprocess, streams JSON-RPC protocol frames over standard input/output, and asserts strict stdio protocol separation (`stdout` JSON-RPC, `stderr` diagnostics).
- **Minimal Mocking**: `unittest.mock.patch` is imported in only a single test file (`test_snapshot_completeness.py`) solely to simulate unreadable directories during recursive directory walks (`os.walk`). Pytest's `monkeypatch` is used sparingly and solely for environment variable overrides (`PROOFMESH_DB`) and simulating operating-system-level `chmod` errors.

---

## 3. Test Suite Breakdown by Functional Area

```
tests/
├── test_cli.py                          (10 tests)  # CLI subcommands, error handling, session scoping
├── test_demo_flow.py                     (4 tests)  # 10-phase seeded recovery demo flow and repeatability
├── test_demo_recovery.py                 (2 tests)  # Transition from BLOCK to ALLOW with fresh evidence
├── test_demo_safety.py                  (14 tests)  # Protection against non-fixture workspaces and user file deletion
├── test_evaluator.py                    (19 tests)  # Deterministic evaluator, gate enforcement, loop detection
├── test_evaluator_correctness.py         (9 tests)  # Baseline completeness, policy digest matching, state transitions
├── test_honest_status.py                 (3 tests)  # Truthful reporting of UNGUARDED, PARTIAL, ENFORCED status
├── test_hook_security.py                (29 tests)  # Path normalization, traversal prevention, NUL byte rejection
├── test_integration_spike.py             (5 tests)  # Golden fixture validation for Antigravity hooks & MCP
├── test_mcp_entrypoint.py                (7 tests)  # Real subprocess stdio smoke tests and protocol integrity
├── test_mcp_integration.py              (11 tests)  # MCP tool execution, handoff generation, completion claiming
├── test_packaging_and_migrations.py      (6 tests)  # Wheel packaging, resource inclusion, atomic SQL rollbacks
├── test_policy_and_session_foundation.py (4 tests)  # Default policy loading, custom overrides, immutability
├── test_repo_snapshot.py                (15 tests)  # Workspace file fingerprinting, Git state, symlink safety
├── test_scope_analyzer.py               (15 tests)  # Allow/restricted path pattern matching, file limits
├── test_snapshot_completeness.py        (10 tests)  # Observation error tracking during directory traversal
├── test_sqlite_persistence.py           (11 tests)  # Multi-process persistence, permissions (0700/0600), WAL
├── test_strict_models.py                 (9 tests)  # FrozenModel immutability, extra attribute rejection
├── test_task_lifecycle_edges.py         (21 tests)  # Revisions (N+1), proposal supersession, parent linkage
├── test_taskfile.py                     (32 tests)  # TOML front matter parsing, 64KB cap, contract digests
├── test_ui.py                            (5 tests)  # Dashboard HTML rendering, endpoints, localhost binding
├── test_ui_readonly.py                   (7 tests)  # Read-only GET guarantees, 405 Method Not Allowed checks
├── test_verification.py                 (12 tests)  # Subprocess gate execution, timeout handling, buffer caps
└── test_verification_bounded.py          (5 tests)  # 64KB memory stream drainer, concurrent edit invalidation
```

---

## 4. Running the Tests

### Running Under Host Python 3.12
```bash
.venv/bin/pytest tests/
```

### Running Under Target CPython 3.14
```bash
.venv314/bin/pytest tests/
```

### Running with Verbose Output & Timing
```bash
pytest -v --durations=10 tests/
```

### Running Specific Test Modules
```bash
# Test evaluator invariants
pytest tests/test_evaluator.py tests/test_evaluator_correctness.py

# Test MCP stdio protocol
pytest tests/test_mcp_entrypoint.py tests/test_mcp_integration.py

# Test filesystem security & path traversal defenses
pytest tests/test_hook_security.py tests/test_demo_safety.py
```

---

## 5. Known Test Boundaries & Limitations

1. **Host Hook Delivery**: Hook tests in `test_hook_security.py` and `test_integration_spike.py` validate handler behavior and schema compliance against real JSON fixtures captured from Google Antigravity (`agy` 1.4.7). They do not spawn a live Google Antigravity host process during automated test runs.
2. **Process Group Termination**: `test_verification_bounded.py` verifies that direct child processes are terminated on timeout via `proc.kill()`. It does not test termination of grandchild processes detached from the direct child process.
3. **Console Script Entrypoint**: Tests invoke CLI commands via `cli.py` or `python -m proofmesh.cli`. Testing the console script executable directly in system `PATH` is handled via wheel installation tests.
