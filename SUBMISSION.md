# ProofMesh — Hackathon Submission Status

This is a project-specific working record for **Devin Hacks Kochi**, documenting working status, verified capabilities, test results, and demo instructions.

---

## Project Overview

- **Project Name:** ProofMesh
- **Description:** An agent-neutral intent, intervention, and evidence control layer for AI-assisted software development. It preserves approved task intent, detects scope drift and repeated failure loops, and requires fresh, code-bound verification evidence before accepting work.
- **Repository:** https://github.com/ivin-titus/ProofMesh
- **License:** GNU Affero General Public License v3 ([AGPL-3.0-or-later](LICENSE))
- **Working Status:** Complete, fully functional MVP implementation with a deterministic 10-phase seeded recovery demo, official Model Context Protocol (MCP) server over stdio, Antigravity host lifecycle hook adapter, and zero-dependency local read-only web status dashboard (`proofmesh ui`).
- **Automated Verification:** **265/265 automated tests passing** across 24 test suites under both target CPython 3.14.9 (`.venv314`) and host Python 3.12.3 (`.venv`). Full wheel packaging and transactional SQLite migration round-trip verified.

---

## Hackathon Track Alignment (Devin Hacks Kochi)

ProofMesh targets the following hackathon tracks:

1. **Track 2: Make the Invisible Visible** *(Primary Track)*
   - Surfaces invisible AI failure modes: silent scope drift, unverified test claims, stale evidence, and loop failure cycles.
   - Provides live visibility via structured Markdown handoff cards, machine-verifiable canonical integrity receipts, and an interactive local web dashboard (`proofmesh ui`).
2. **Track 3: Works Anyway**
   - 100% local-first architecture with zero external network, cloud model, or paid subscription dependencies.
   - Robust fail-closed design with bounded 64KB memory stream drainers, subprocess sandboxing, symlink traversal guards, and atomic SQLite persistence.
3. **Track 1: Kill the Busywork**
   - Eliminates repetitive manual PR review busywork and verification chores by automating scope containment checks, binding test evidence to exact git snapshots, and generating self-contained audit receipts.

*For complete track mappings and evidence citations, see [docs/BUILD_TRACKS.md](docs/BUILD_TRACKS.md).*

---

## Participant

| Name | GitHub | Contribution |
| :--- | :--- | :--- |
| Ivin Titus | [@ivin-titus](https://github.com/ivin-titus) | Solo participant; architecture, integration, parallel agent supervision, verification, and documentation. |

---

## Pre-Submission Verification Checklist

- [x] Implementation scope matches [docs/PRD.md](docs/PRD.md) and [docs/TRD.md](docs/TRD.md) (§0 scope lock & §20 definition of done).
- [x] README setup and run instructions have been tested and verified from clean checkouts.
- [x] Repeatable 10-phase end-to-end demo works without network or live LLM dependencies (`./proofmesh demo`).
- [x] AI assistance and development methodology are fully documented in [AI_USAGE.md](AI_USAGE.md).
- [x] Checks run and test counts verified: **265/265 tests passing** on both CPython 3.14.9 and Python 3.12.3.
- [x] No secrets, private credentials, or personal tokens are committed or exposed.
- [x] Documentation includes complete guides: [Architecture](docs/architecture.md), [Build Tracks](docs/BUILD_TRACKS.md), [Development](docs/development.md), [Testing](docs/testing.md), [Security & Privacy](docs/security-and-privacy.md), and [Dogfooding](docs/DOGFOODING.md).

---

## Technical Specifications & Environment

- **Prerequisites & Supported Runtimes:**
  - Python `>=3.12,<3.15` (verified on host Python 3.12.3 and CPython 3.14.9).
  - Git version control.
  - Package manager: `uv` (recommended) or standard `pip`.
- **Primary Dependencies:**
  - `pydantic` v2 (strict immutable domain models)
  - `mcp` official Python SDK (stdio protocol adapter)
  - Standard library `sqlite3` (transactional local persistence with WAL mode)
  - Standard library `http.server` (local read-only web panel)
  - Zero cloud dependencies, zero external model APIs, zero telemetry.
- **Convenience Runner:**
  - Root script `./proofmesh` auto-detects virtual environments and sets `PYTHONPATH=src`.

---

## Key Verification & Demo Commands

```bash
# 1. Run the full automated test suite (265 tests)
pytest tests/
# Or using the root runner:
./proofmesh test  # or pytest tests/

# 2. Run the deterministic 10-phase seeded recovery demo
./proofmesh demo --dir demo_target

# 3. Launch the local read-only web status panel
./proofmesh ui --port 8765

# 4. Start the official Model Context Protocol (MCP) server over stdio
./proofmesh mcp

# 5. Build distribution wheel
uv build --wheel
```

---

## Deterministic Demo Walkthrough

1. Execute `./proofmesh demo --dir demo_target`.
2. Inspect the terminal output showing the 10-phase recovery loop:
   - Contract proposal → human approval → baseline snapshot → clean code changes → verification gate PASS → ALLOW evaluation → scope violation injection (restricted config edit) → BLOCK evaluation with structured handoff card → correction → fresh verification → ALLOW evaluation → canonical integrity receipt export.
3. Review the generated audit reports in `demo_target/`:
   - `demo_target/report.md` (human-readable Markdown audit report)
   - `demo_target/report.json` (machine-verifiable canonical JSON receipt with `receipt_digest`)
   - `demo_target/report-blocked.md` (preserved audit record of the blocked intervention)
4. Start the web dashboard: `./proofmesh ui --port 8765`.
5. Open `http://127.0.0.1:8765/` in a browser to inspect live session contracts, verdict badge, scope analysis, and evidence freshness.
