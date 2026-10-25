# ProofMesh Security, Threat Model & Privacy Architecture

This document provides a technical overview of ProofMesh's security controls, threat model, filesystem boundaries, subprocess isolation, and privacy guarantees.

---

## 1. Threat Model & Security Objectives

ProofMesh operates in environments where AI coding agents execute shell commands, create files, and modify existing codebases. In these environments, models can hallucinate commands, attempt directory traversals, modify sensitive configurations, or get stuck in compounding error loops.

### What ProofMesh Protects Against
1. **Scope Escape**: Agents modifying files outside the approved task scope (e.g., editing `.env`, modifying CI workflows, altering security configurations).
2. **Path Traversal & Symlink Escape**: Malicious or malformed tool call arguments attempting to escape workspace containment via `../`, NUL bytes, or resolving external symlinks.
3. **Stale Evidence Acceptance**: Agents claiming completion based on tests that were run prior to subsequent code modifications.
4. **Output Flooding Denial-of-Service**: Flawed agent code or runaway tests generating gigabytes of log output to exhaust system memory.
5. **Accidental Workspace Destruction**: Commands or recovery routines wiping out untracked files, user directories, or non-fixture databases.
6. **Compounding Failure Loops**: Agents repeating identical failing repair cycles and consuming excessive tokens.

### What ProofMesh Does Not Protect Against (Explicit Non-Goals)
1. **Kernel-Level OS Sandboxing**: ProofMesh evaluates policy and controls tool calls; it does not implement a Linux cgroup, seccomp, or container sandbox. If an agent has arbitrary, uninstrumented shell access outside of ProofMesh gates, ProofMesh cannot prevent operating-system-level actions.
2. **Asymmetric Non-Repudiation**: Exported receipts use unkeyed SHA-256 hashes for data integrity. They verify that facts have not been modified since the receipt was computed, but they do not provide cryptographic digital signatures backed by public/private key pairs.
3. **AST Semantic Correctness**: Scope analysis matches path patterns; it does not perform deep AST semantic analysis to prove that an allowed change does not introduce logical bugs.

---

## 2. Defensive Filesystem & Storage Security

### Database Isolation Outside Target Repositories
- **Storage Location**: Databases are stored in the user's local data directory (`~/.local/share/proofmesh/projects/<project-id>/proofmesh.db`), completely separated from the target workspace.
- **Strict File Permissions**:
  - Intermediate directories are created with `0700` permissions (readable, writable, and traversable only by the invoking user).
  - Database files, WAL files (`-wal`), and shared-memory files (`-shm`) are explicitly set to `0600` (readable and writable only by the invoking user).
- **Project Traversal Defense**: Project identifiers are strictly validated against pattern `^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$` and checked to ensure they cannot escape the `projects/` directory.

### Workspace Path Normalization & Containment
All proposed target file paths in tool calls and scope policies are validated using `normalize_and_validate_path()` (`src/proofmesh/adapters/hook_protocol.py`):
1. **NUL Byte Rejection**: Paths containing `\0` are immediately rejected.
2. **Drive & UNC Prefix Rejection**: Windows drive prefixes (`C:`) and UNC network paths (`\\`, `//`) are rejected.
3. **Backslash Normalization**: Windows-style backslashes are normalized to forward slashes before evaluation.
4. **Path Traversal Prevention**: Any path containing `..` components is rejected.
5. **Symlink Escape Protection**: If the target path exists or is a symlink, it is resolved via `.resolve(strict=True)` and verified against `.is_relative_to(workspace_root)`. If a nonexistent file is proposed, its existing parent directory chain is resolved and verified against the workspace root.

### Safe Demo Fixture Safeguards
The seeded demo runner (`src/proofmesh/demo.py`) implements non-destructive safeguards:
- **Fixture Marker Requirement**: The demo refuses to execute in non-empty directories unless a `.proofmesh-fixture` marker file is present.
- **Zero Recursive Deletions**: Never invokes `shutil.rmtree()` on arbitrary directories.
- **Foreign Database Protection**: Inspects database tables before running; refuses to reset or overwrite databases containing non-demo projects, tasks, or sessions.

---

## 3. Subprocess Execution & Memory Boundedness

When executing verification gates (e.g. `pytest`), ProofMesh enforces strict subprocess constraints:

### Safe Command Invocation
- **No Shell Execution**: Gates are invoked via `subprocess.Popen(cmd_list, shell=False, ...)`. Commands are represented as argument arrays, completely eliminating shell injection vulnerabilities (`&&`, `;`, `|`, `` ` ``).
- **Execution Timeouts**: Gates specify explicit timeout budgets (default 60s). If the timeout expires, the child process is terminated.
- **Pre-Gate & Post-Gate Snapshots**: ProofMesh captures a repository snapshot immediately before and after gate execution. If files are modified while a check is running, evidence is marked `FAILED` and invalidated.

### Output Stream Flooding Protection (`_BoundedStreamDrainer`)
Untrusted child processes may produce unbounded stdout/stderr output. ProofMesh intercepts process streams with dedicated background drainers (`src/proofmesh/core/verification.py`):
- **64KB Memory Buffer**: Peak stream memory capture is capped at 64KB per stream. Excess output is drained to `/dev/null` without buffering in RAM, preventing out-of-memory denial-of-service.
- **2,000-Character Formatted Summaries**: Output summaries persisted in `EvidenceRecord` are capped at 2,000 characters with truncation indicators.

---

## 4. Integrity Receipts vs. Digital Signatures

ProofMesh exports machine-readable JSON receipts (`report.json`) to record verification outcomes:

```json
{
  "schema_version": "1.0",
  "receipt_id": "rcpt-c8f921e4a7b0",
  "generated_at": "2026-10-25T00:45:00Z",
  "digest_type": "integrity_checksum",
  "digest_description": "Unkeyed SHA-256 integrity digest over canonical JSON fields. Not an identity digital signature.",
  "receipt_digest": "sha256:4a6f8b..."
}
```

### Technical Distinction
- **What it is**: An **unkeyed SHA-256 integrity checksum** computed over canonical, sorted, compact JSON representing the session, task contract, code snapshot, scope findings, evidence records, and verdict.
- **What it guarantees**: Detects accidental file corruption or subsequent tampering of the report file on disk. Any modification to the reported evidence causes the digest to mismatch.
- **What it does not guarantee**: Because it is not signed with an asymmetric private key (e.g. ed25519 or RSA) or an HMAC, an attacker with write access to the report can recompute the SHA-256 digest over modified data. Full cryptographic signing is a planned roadmap enhancement.

---

## 5. Privacy & Data Minimization

ProofMesh is strictly local-first:
- **Zero Cloud Transmission**: No code, git diffs, file contents, test logs, or agent prompts are transmitted to any external server.
- **Zero Telemetry**: ProofMesh contains no analytics, usage tracking, or phone-home telemetry.
- **Read-Only Local Dashboard**: The web panel (`proofmesh ui`) binds strictly to `127.0.0.1`. It rejects non-localhost bindings with a `ValueError`, accepts only `GET` requests, and does not expose endpoints to public network interfaces.
