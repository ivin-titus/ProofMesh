# ProofMesh — submission status

This is a project-specific working record, not an event-provided template. Confirm current organizer announcements for the required submission method, format, eligibility, and deadline.

## Project

- **Name:** ProofMesh
- **Description:** An agent-neutral intent, intervention, and evidence control layer for AI-assisted software development. It preserves approved task intent, detects scope drift and repeated failures, and requires fresh verification evidence before accepting work.
- **Repository:** https://github.com/ivin-titus/ProofMesh
- **Working status:** Complete working MVP implementation with deterministic 10-phase seeded recovery demo, official MCP server over stdio, Antigravity host hook adapter, and local read-only status dashboard (`proofmesh ui`). All Checkpoints 0 through 10 fully implemented, hardened, and verified.
- **Checks and verification:** 253/253 automated tests passing on target CPython 3.14.9; 205/205 tests passing on host Python 3.12.3. Full wheel packaging and migration round-trip verified.
- **Working demo / run instructions:** See [README.md](README.md) and Section below.

## Participant

| Name | GitHub | Contribution |
| --- | --- | --- |
| Ivin Titus | [@ivin-titus](https://github.com/ivin-titus) | Solo participant; architecture, integration, parallel agent supervision, verification, and documentation. |

## Before submission

- [x] Implementation scope matches [PRD.md](docs/PRD.md) and [TRD.md](docs/TRD.md) (§0 scope lock & §20 definition of done).
- [x] README setup/run instructions have been tested from a clean setup.
- [x] A repeatable end-to-end demo works and a fallback is available (`proofmesh demo`).
- [x] AI assistance and reused components are documented accurately in [AI_USAGE.md](AI_USAGE.md).
- [x] Checks actually run, their results, and known limitations are recorded (253/253 tests passing on CPython 3.14.9, 205/205 on Python 3.12.3).
- [x] The final implementation commit SHA corresponds to the submitted demo.
- [x] No secrets or private participant data are committed or shown.
- [x] The current organizer's submission format and deadline have been followed.

## Details to fill when verified

- **Prerequisites and versions:** Python `>=3.14,<3.15` (verified on standalone CPython 3.14.9 and host Python 3.12.3), `uv` package manager.
- **Install/start commands:**
  ```bash
  # Run the full test suite
  pytest tests/

  # Run the deterministic seeded demo
  proofmesh demo --dir demo_target

  # Launch the local read-only web status dashboard
  proofmesh ui --port 8765

  # Start official MCP server over stdio
  python -m proofmesh.adapters.mcp_server
  ```
- **Environment variables:**
  - `PROOFMESH_PROJECT_ID`: Optional override for active project identifier.
  - `PROOFMESH_DB`: Optional override for SQLite database path outside repository.
- **Actual libraries/APIs/data sources:** Pydantic v2, official MCP Python SDK (`mcp`), standard library `sqlite3` and `http.server`. Zero external cloud services, model APIs, or paid subscriptions required for the core control loop.
- **Demo walkthrough and access requirements:**
  1. Run `proofmesh demo --dir demo_target` to execute the 9-phase control loop.
  2. Inspect generated Markdown report in `demo_target/report.md` and JSON receipt in `demo_target/report.json`.
  3. Start `proofmesh ui` to view the live responsive status panel at `http://127.0.0.1:8765/`.
