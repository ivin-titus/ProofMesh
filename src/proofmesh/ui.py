"""ProofMesh Local Read-Only Status Panel.

Provides a minimal, zero-dependency local web dashboard and JSON endpoint
using Python standard library http.server, binding exclusively to 127.0.0.1.
Renders the exact same validated data as the CLI and canonical receipts.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import html
import http.server
import json
import os
from pathlib import Path
import sys
import threading
from typing import Any, Sequence
import uuid

from proofmesh.core.scope_analyzer import analyze_scope
from proofmesh.models import (
    EvidenceStatus,
    VerdictOutcome,
)
from proofmesh.report import export_json_receipt
from proofmesh.storage.store import ProofMeshStore


def get_receipt_for_session(
    store: ProofMeshStore,
    session_id: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any] | None:
    """Retrieve the current canonical receipt for a session without modifying state.

    Never calculates or persists new verdicts, never executes live verification checks,
    and never modifies database tables.
    """
    effective_repo_root = repo_root or Path.cwd()

    # Resolve session
    if session_id:
        session = store.get_session(session_id)
    else:
        conn = store.get_connection()
        try:
            row = conn.execute(
                "SELECT session_id FROM sessions ORDER BY started_at DESC LIMIT 1;"
            ).fetchone()
            session = store.get_session(row["session_id"]) if row else None
        finally:
            conn.close()

    if session is None:
        return None

    task_revision = store.get_task_revision(session.task_id, session.contract_revision)
    if task_revision is None:
        return None

    baseline_snapshot = store.get_snapshot(session.baseline_snapshot_id)
    current_snapshot = store.get_snapshot(
        session.current_snapshot_id or session.baseline_snapshot_id
    )
    if baseline_snapshot is None or current_snapshot is None:
        return None

    scope_result = analyze_scope(baseline_snapshot, current_snapshot, task_revision.scope)
    evidence_records = store.list_evidence_for_session(session.session_id)
    verdicts = store.list_verdicts_for_session(session.session_id)

    if verdicts:
        verdict = verdicts[-1]
        return export_json_receipt(
            session=session,
            task=task_revision,
            snapshot=current_snapshot,
            scope_result=scope_result,
            evidence=evidence_records,
            verdict=verdict,
        )

    # If no verdict has been evaluated/saved yet, return unevaluated receipt representation
    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "receipt_id": f"rcpt-{uuid.uuid4().hex[:12]}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session": session.model_dump(mode="json"),
        "task": task_revision.model_dump(mode="json"),
        "snapshot": {
            "snapshot_id": current_snapshot.snapshot_id,
            "repo_root": current_snapshot.repo_root,
            "git_commit": current_snapshot.git_commit,
            "git_dirty": current_snapshot.git_dirty,
            "captured_at": current_snapshot.captured_at.isoformat(),
            "file_count": len(current_snapshot.files),
            "files": [f.model_dump(mode="json") for f in current_snapshot.files],
        },
        "scope": scope_result.model_dump(mode="json"),
        "evidence": [e.model_dump(mode="json") for e in evidence_records],
        "verdict": None,
    }
    canonical_repr = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    receipt["receipt_digest"] = f"sha256:{hashlib.sha256(canonical_repr.encode('utf-8')).hexdigest()}"
    return receipt


def render_dashboard_html(receipt: dict[str, Any] | None) -> str:
    """Render a clean, responsive HTML status dashboard with inline CSS."""
    if receipt is None:
        return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ProofMesh Control Panel</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem; }
    .card { background: #1e293b; border-radius: 8px; padding: 1.5rem; max-width: 600px; margin: 2rem auto; text-align: center; }
  </style>
</head>
<body>
  <div class="card">
    <h2>No Active ProofMesh Session</h2>
    <p>Run a task or execute the seeded demo to view verification status.</p>
  </div>
</body>
</html>"""

    session_data = receipt.get("session") or {}
    task_data = receipt.get("task") or {}
    scope_data = receipt.get("scope") or {}
    evidence_list = receipt.get("evidence") or []
    snapshot_data = receipt.get("snapshot") or {}
    verdict_data = receipt.get("verdict")

    snapshot_captured_at = html.escape(str(snapshot_data.get("captured_at") or "unknown"))

    if verdict_data is None:
        verdict_outcome = "UNEVALUATED"
        enforcement = "n/a"
        badge_class = "badge-neutral"
        badge_text = "⏳ Unevaluated"
        pill_class = "pill-neutral"
        verdict_display = "Unevaluated"
        evaluated_at_text = "Unevaluated (no evaluation recorded)"
        reasons_html = "<p>No evaluation recorded yet</p>"
    else:
        verdict_outcome = str(verdict_data.get("verdict", "UNKNOWN")).upper()
        enforcement = str(verdict_data.get("enforcement_level", "unknown"))
        evaluated_at_raw = verdict_data.get("evaluated_at")
        evaluated_at_text = (
            html.escape(str(evaluated_at_raw)) if evaluated_at_raw else "Unevaluated"
        )
        reasons = verdict_data.get("reasons") or []
        reason_items = [f"<li>{html.escape(str(r))}</li>" for r in reasons]
        reasons_html = "<ul>" + "".join(reason_items) + "</ul>" if reason_items else "<p>None</p>"

        if verdict_outcome == "ALLOW":
            badge_class = "badge-allow"
            badge_text = "✅ ALLOW"
            pill_class = "pill-allow"
            verdict_display = "ALLOW"
        elif verdict_outcome == "BLOCK":
            badge_class = "badge-block"
            badge_text = "❌ BLOCK"
            pill_class = "pill-block"
            verdict_display = "BLOCK"
        elif verdict_outcome == "REQUIRE_APPROVAL":
            badge_class = "badge-warn"
            badge_text = "⚠️ REQUIRE_APPROVAL"
            pill_class = "pill-warn"
            verdict_display = "REQUIRE_APPROVAL"
        elif verdict_outcome == "WARN":
            badge_class = "badge-warn"
            badge_text = "⚠️ WARN"
            pill_class = "pill-warn"
            verdict_display = "WARN"
        else:
            badge_class = "badge-neutral"
            badge_text = f"❓ {html.escape(verdict_outcome)}"
            pill_class = "pill-neutral"
            verdict_display = html.escape(verdict_outcome)

    # Build scope table rows
    scope_rows = []
    changes = scope_data.get("changes") or []
    findings_map = {f.get("path"): f for f in (scope_data.get("findings") or [])}
    for c in changes:
        c_path = html.escape(str(c.get("path") or ""))
        c_type = html.escape(str(c.get("change_type") or ""))
        finding = findings_map.get(c.get("path"))
        if finding is None:
            f_badge = '<span class="pill pill-neutral">Unknown</span>'
            f_reason = "No finding"
        elif finding.get("restricted"):
            f_badge = '<span class="pill pill-block">Restricted</span>'
            f_reason = html.escape(str(finding.get("reason") or "Restricted path"))
        elif not finding.get("allowed"):
            f_badge = '<span class="pill pill-block">Not Allowed</span>'
            f_reason = html.escape(str(finding.get("reason") or "Out of allow_paths"))
        else:
            f_badge = '<span class="pill pill-allow">Allowed</span>'
            f_reason = html.escape(str(finding.get("reason") or "Allowlisted"))
        scope_rows.append(
            f"<tr><td><code>{c_path}</code></td><td><code>{c_type}</code></td>"
            f"<td>{f_badge}</td><td>{f_reason}</td></tr>"
        )
    scope_table_body = (
        "".join(scope_rows)
        if scope_rows
        else "<tr><td colspan='4'>No file changes detected since baseline snapshot.</td></tr>"
    )

    # Build evidence table rows
    evidence_rows = []
    current_snap_id = snapshot_data.get("snapshot_id", "")
    for e in evidence_list:
        g_id = html.escape(str(e.get("gate_id") or ""))
        prov = html.escape(str(e.get("provider_name") or ""))
        status = str(e.get("status") or "").upper()
        if status == "PASSED":
            st_pill = '<span class="pill pill-allow">PASSED</span>'
        elif status == "FAILED":
            st_pill = '<span class="pill pill-block">FAILED</span>'
        else:
            st_pill = f'<span class="pill pill-warn">{html.escape(status)}</span>'

        is_fresh = bool(current_snap_id) and e.get("snapshot_after") == current_snap_id
        fr_pill = (
            '<span class="pill pill-allow">fresh</span>'
            if is_fresh
            else '<span class="pill pill-warn">stale</span>'
        )

        exit_c = html.escape(str(e.get("exit_code") if e.get("exit_code") is not None else 0))
        dur = html.escape(f"{e.get('duration_ms', 0)}ms")
        raw_summary = str(e.get("summary") or "")[:80]
        summary = html.escape(raw_summary)
        evidence_rows.append(
            f"<tr><td><code>{g_id}</code></td><td>{prov}</td><td>{st_pill}</td>"
            f"<td>{exit_c}</td><td>{dur}</td><td>{fr_pill}</td><td><code>{summary}</code></td></tr>"
        )
    evidence_table_body = (
        "".join(evidence_rows)
        if evidence_rows
        else "<tr><td colspan='7'>No verification evidence recorded for this session.</td></tr>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ProofMesh Control Panel</title>
  <style>
    :root {{
      --bg: #090d16;
      --card-bg: #131c2e;
      --border: #1e293b;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --allow-bg: rgba(16, 185, 129, 0.15);
      --allow-border: #10b981;
      --allow-text: #34d399;
      --block-bg: rgba(239, 68, 68, 0.15);
      --block-border: #ef4444;
      --block-text: #f87171;
      --warn-bg: rgba(245, 158, 11, 0.15);
      --warn-border: #f59e0b;
      --warn-text: #fbbf24;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 1.5rem;
      line-height: 1.5;
    }}
    .container {{ max-width: 1100px; margin: 0 auto; display: flex; flex-direction: column; gap: 1.5rem; }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 1.25rem;
    }}
    h1 {{ font-size: 1.5rem; font-weight: 700; color: #38bdf8; }}
    .subtitle {{ font-size: 0.875rem; color: var(--text-muted); }}
    .verdict-banner {{
      padding: 0.5rem 1.25rem;
      border-radius: 9999px;
      font-weight: 700;
      font-size: 1.125rem;
      border: 1px solid transparent;
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
    }}
    .badge-allow {{ background: var(--allow-bg); border-color: var(--allow-border); color: var(--allow-text); }}
    .badge-block {{ background: var(--block-bg); border-color: var(--block-border); color: var(--block-text); }}
    .badge-warn {{ background: var(--warn-bg); border-color: var(--warn-border); color: var(--warn-text); }}
    .badge-neutral {{ background: #334155; border-color: #64748b; color: #cbd5e1; }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1.25rem;
    }}
    .card h2 {{
      font-size: 1.1rem;
      font-weight: 600;
      margin-bottom: 1rem;
      color: #7dd3fc;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      padding-bottom: 0.5rem;
    }}
    .evaluation-notice {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 0.75rem 1rem;
      font-size: 0.85rem;
      color: #94a3b8;
    }}
    .evaluation-notice strong {{ color: #38bdf8; }}
    .grid-2 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.25rem; }}
    .meta-list {{ list-style: none; display: flex; flex-direction: column; gap: 0.5rem; font-size: 0.9rem; }}
    .meta-list li strong {{ color: #cbd5e1; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; text-align: left; }}
    th {{ background: #1e293b; color: #94a3b8; font-weight: 600; padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--border); }}
    td {{ padding: 0.6rem 0.75rem; border-bottom: 1px solid rgba(255, 255, 255, 0.05); vertical-align: middle; }}
    code {{ background: #0f172a; padding: 0.15rem 0.35rem; border-radius: 4px; font-family: ui-monospace, monospace; font-size: 0.825rem; color: #e2e8f0; }}
    .pill {{
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
    }}
    .pill-allow {{ background: var(--allow-bg); color: var(--allow-text); }}
    .pill-block {{ background: var(--block-bg); color: var(--block-text); }}
    .pill-warn {{ background: var(--warn-bg); color: var(--warn-text); }}
    .pill-neutral {{ background: #334155; color: #cbd5e1; }}
    .controls {{ display: flex; gap: 0.75rem; align-items: center; }}
    button {{
      background: #0284c7;
      color: white;
      border: none;
      padding: 0.4rem 0.8rem;
      border-radius: 6px;
      cursor: pointer;
      font-weight: 500;
      font-size: 0.85rem;
    }}
    button:hover {{ background: #0369a1; }}
    footer {{ text-align: center; font-size: 0.8rem; color: var(--text-muted); padding: 1rem 0; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>ProofMesh Control Layer</h1>
        <div class="subtitle"><strong>Last Persisted Evaluation</strong> &bull; Session: <code>{html.escape(str(session_data.get("session_id", "unknown")))}</code> &bull; Enforcement: <code>{html.escape(enforcement)}</code></div>
      </div>
      <div class="controls">
        <div class="verdict-banner {badge_class}">{badge_text}</div>
        <button onclick="location.reload()">Refresh</button>
      </div>
    </header>

    <div class="evaluation-notice">
      <strong>Last Persisted Evaluation:</strong> Displaying stored verification verdict evaluated at <code>{evaluated_at_text}</code> for snapshot captured at <code>{snapshot_captured_at}</code>. Auto-refresh checks for newly persisted records; it does not execute live checks.
    </div>

    <div class="grid-2">
      <!-- Task Contract -->
      <div class="card">
        <h2>Task Contract</h2>
        <ul class="meta-list">
          <li><strong>Task ID:</strong> <code>{html.escape(str(task_data.get("task_id", "")))}</code> (Rev {html.escape(str(task_data.get("revision", 1)))})</li>
          <li><strong>Summary:</strong> {html.escape(str(task_data.get("summary", "")))}</li>
          <li><strong>Risk Level:</strong> <code>{html.escape(str(task_data.get("risk_level", "")))}</code></li>
          <li><strong>Approval:</strong> <code>{html.escape(str(task_data.get("approval_status", "")))}</code> (by {html.escape(str(task_data.get("approved_by") or "n/a"))})</li>
          <li><strong>Contract Digest:</strong> <code>{html.escape(str(task_data.get("contract_digest", ""))[:28])}...</code></li>
          <li><strong>Snapshot ID:</strong> <code>{html.escape(str(snapshot_data.get("snapshot_id", ""))[:28])}...</code></li>
          <li><strong>Snapshot Captured At:</strong> {snapshot_captured_at}</li>
        </ul>
      </div>

      <!-- Verdict & Reasons -->
      <div class="card">
        <h2>Last Persisted Evaluation</h2>
        <ul class="meta-list">
          <li><strong>Status:</strong> <span class="pill {pill_class}">{html.escape(verdict_display)}</span></li>
          <li><strong>Verdict:</strong> <strong>{badge_text}</strong></li>
          <li><strong>Evaluated At:</strong> {evaluated_at_text}</li>
          <li><strong>Snapshot Captured At:</strong> {snapshot_captured_at}</li>
          <li><strong>Blockers:</strong>
            {reasons_html}
          </li>
        </ul>
      </div>
    </div>

    <!-- Scope Findings -->
    <div class="card">
      <h2>Scope Analysis (Changed Files: {scope_data.get("total_changed_files", 0)})</h2>
      <table>
        <thead>
          <tr>
            <th>Path</th>
            <th>Change</th>
            <th>Scope Finding</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {scope_table_body}
        </tbody>
      </table>
    </div>

    <!-- Verification Evidence -->
    <div class="card">
      <h2>Verification Evidence</h2>
      <table>
        <thead>
          <tr>
            <th>Gate ID</th>
            <th>Provider</th>
            <th>Status</th>
            <th>Exit Code</th>
            <th>Duration</th>
            <th>Freshness</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          {evidence_table_body}
        </tbody>
      </table>
    </div>

    <footer>
      ProofMesh Local Control Panel &bull; Read-only HTTP on 127.0.0.1 &bull; Last Persisted Evaluation &bull; Zero external network dependencies
    </footer>
  </div>
  <script>
    // Auto-refresh every 5 seconds if not paused (loads last persisted state, no live check)
    let autoRefresh = true;
    setInterval(() => {{
      if (autoRefresh) location.reload();
    }}, 5000);
  </script>
</body>
</html>"""


class ProofMeshUIHandler(http.server.BaseHTTPRequestHandler):
    """Read-only HTTP request handler for ProofMesh status panel."""

    store: ProofMeshStore
    session_id: str | None = None
    repo_root: Path | None = None

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard HTTP server access logging to keep terminal clean."""
        pass

    def do_GET(self) -> None:
        """Handle read-only GET requests."""
        path = self.path.split("?")[0].rstrip("/")
        if path == "" or path == "/index.html":
            receipt = get_receipt_for_session(self.store, self.session_id, self.repo_root)
            body = render_dashboard_html(receipt).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/status" or path == "/api/receipt":
            receipt = get_receipt_for_session(self.store, self.session_id, self.repo_root)
            if receipt is None:
                body = json.dumps({"error": "No active session found"}).encode("utf-8")
                self.send_response(404)
            else:
                body = json.dumps(receipt, indent=2).encode("utf-8")
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        """Reject non-GET requests as read-only."""
        self.send_response(405)
        self.end_headers()

    def do_PUT(self) -> None:
        """Reject non-GET requests as read-only."""
        self.send_response(405)
        self.end_headers()

    def do_DELETE(self) -> None:
        """Reject non-GET requests as read-only."""
        self.send_response(405)
        self.end_headers()

    def do_PATCH(self) -> None:
        """Reject non-GET requests as read-only."""
        self.send_response(405)
        self.end_headers()


def create_ui_server(
    store: ProofMeshStore,
    session_id: str | None = None,
    repo_root: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> http.server.HTTPServer:
    """Create a configured read-only HTTP server bound to 127.0.0.1 or localhost."""
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError(f"ProofMesh UI must only bind to 127.0.0.1 or localhost, got: {host}")

    class CustomHandler(ProofMeshUIHandler):
        pass

    CustomHandler.store = store
    CustomHandler.session_id = session_id
    CustomHandler.repo_root = repo_root

    return http.server.HTTPServer((host, port), CustomHandler)
