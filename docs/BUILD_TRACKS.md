# Devin Hacks Kochi — Build Tracks Reference & Alignment

This document outlines how ProofMesh aligns with the official hackathon tracks defined for **Devin Hacks Kochi** (see original specification in [`docs/BUILD_TRACKS.pdf`](BUILD_TRACKS.pdf)).

---

## 1. Hackathon Tracks Overview

The hackathon defines four distinct directions for projects:

| # | Track Name | Theme & Challenge |
|---|---|---|
| **1** | **KILL THE BUSYWORK** | Build something that takes an annoying, repetitive job off someone’s hands. Pick a real workflow and complete it, rather than just telling the user what to do. |
| **2** | **MAKE THE INVISIBLE VISIBLE** | Build something that helps people notice what they normally miss, and do something useful with that information. The interesting part is what happens *after* detection. |
| **3** | **WORKS ANYWAY** | Build for the conditions most products ignore: unreliable internet, constrained hardware, or strict environmental limitations. Choose one constraint and make your product work despite it. |
| **4** | **MAKE ROOM FOR PLAY** | Create a playful, interactive experience people want to engage with beyond routine work. |

---

## 2. ProofMesh Primary Track Alignment

ProofMesh directly addresses **Track 2 (Make the Invisible Visible)** as its primary submission track, while simultaneously satisfying the demanding offline constraints of **Track 3 (Works Anyway)** and the automation requirements of **Track 1 (Kill the Busywork)**.

### Track 2: MAKE THE INVISIBLE VISIBLE (Primary Alignment)

#### The Invisible Problem in AI Software Engineering
When AI coding agents implement tasks, critical failure modes remain completely invisible to developers until long after code is written:
1. **Silent Scope Creep**: Agents silently modify configuration files, environment definitions, or unrelated modules outside the approved task.
2. **Unverified Assumptions**: Agents assume a library function or database schema behaves in a particular way, building extensive changes on top of an unverified premise.
3. **Stale Evidence**: Agents run tests early in a session, make subsequent file modifications, and report "tests passed" even though the tests never ran against the final code state.
4. **Compounding Failure Loops**: When encountering an error, models often alternate between two ineffective fixes, burning tokens and polluting history without making forward progress.

#### What ProofMesh Makes Visible
ProofMesh provides continuous visibility across the intent-to-code lifecycle:
- **Scope Findings Table**: Fingerprints every workspace file with SHA-256 and explicitly highlights unexpected or restricted modifications before any commit occurs.
- **Evidence Freshness Indicators**: Cryptographically binds test runs to exact code snapshot hashes, exposing when previously passing checks have become stale due to intermediate code edits.
- **Loop & Budget Tracking**: Detects repetitive error signatures and tracks attempt counts against configured budgets.
- **Real-Time Visual Panel (`proofmesh ui`)**: Surfaces live session state, scope diffs, verification tables, and the overall verdict badge in a clean, local dashboard.

#### What Happens After Detection (The Decisive Difference)
In the words of Track 2: *"The interesting part is what happens after detection."*
ProofMesh does not stop at detection:
1. **Fails Closed**: Evaluator halts task completion with a definitive `BLOCK` verdict.
2. **Generates Focused Handoff Cards**: Rather than leaving the agent lost, ProofMesh emits a compact Markdown handoff card identifying the exact out-of-scope files or stale gates and provides an ordered sequence of corrective actions.
3. **Guides Deterministic Recovery**: In the seeded demo, the system intercepts an out-of-scope edit (`config/security.toml`), blocks completion, provides handoff guidance, verifies the clean correction, and transitions to `ALLOW` with a canonical integrity receipt.

---

### Track 3: WORKS ANYWAY (Secondary / Architectural Alignment)

#### The Constraint: Zero Network, Zero External Models, Zero Cloud Infrastructure
Most modern AI agent tooling depends heavily on hosted cloud platforms: remote API endpoints, paid LLM inference subscriptions, heavy cloud databases, and complex web build chains. When internet connectivity drops, API rate limits are hit, or privacy regulations prohibit external transmission, these tools fail completely.

#### How ProofMesh "Works Anyway"
- **100% Local-First Execution**: ProofMesh operates completely offline on local developer machines.
- **Zero Hosted Model Dependency**: The core control loop, evaluator, scope analyzer, loop detector, and 10-phase recovery demo execute deterministically with zero model calls or external network requests.
- **Zero Frontend Build Pipeline**: The live status dashboard (`proofmesh ui`) is written in vanilla HTML/CSS/JS and served via Python's standard-library `http.server`, requiring no Node.js, npm, Webpack, or external CDN access.
- **Resilient Process Survival**: State is committed transactionally to local SQLite storage; sessions, loop attempts, and evidence records survive unexpected process crashes, reboots, and terminal disconnects.

---

### Track 1: KILL THE BUSYWORK (Workflow Automation)

#### The Busywork: Manual PR Auditing of Agent Diffs
Developers reviewing AI-generated pull requests are forced to perform tedious, repetitive checks:
- Did the agent touch files it wasn't supposed to?
- Are the tests that passed actually testing the final code state, or did the agent edit code after running pytest?
- Were all mandatory acceptance criteria and required verification gates executed?
- Did the agent get stuck in a repair loop and leave partial scaffolding behind?

#### ProofMesh Automates the Entire Verification Chain
ProofMesh eliminates this manual overhead:
1. Automatically enforces the approved TaskFile scope.
2. Automatically binds test evidence to code fingerprints.
3. Automatically evaluates mandatory gates against project policy.
4. Exports a ready-to-paste Markdown verification report and canonical JSON integrity receipt proving that all requirements were met.

---

## 3. Summary of Project Evidence

| Feature / Artifact | Demonstrating Track | Verifiable Command |
|---|---|---|
| **10-Phase Recovery Demo** | Track 2 & Track 3 | `./proofmesh demo --dir demo_target` |
| **Deterministic BLOCK on Scope Violation** | Track 2 (Make Invisible Visible) | Inspected in `demo_target/report-blocked.md` |
| **Zero-Dependency Web Panel** | Track 3 (Works Anyway) | `./proofmesh ui --port 8765` |
| **Offline Test Suite (265 tests)** | Track 3 (Works Anyway) | `.venv/bin/pytest tests/` |
| **Canonical Integrity Receipt** | Track 1 & Track 2 | `proofmesh report --json` |
