"""Convenience adapter wiring Google Antigravity lifecycle hooks to ProofMesh core.

Provides lifecycle hook event handlers (PreInvocation, PreToolUse, Stop)
bound to ProofMesh core engine, scope analysis, and verification status.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from proofmesh.adapters.hook_protocol import (
    PreInvocationPayload,
    PreInvocationResponse,
    PreToolUseAllowResponse,
    PreToolUsePayload,
    PreToolUseResponse,
    StopAllowResponse,
    StopPayload,
    StopResponse,
    evaluate_pre_tool_use,
    evaluate_stop,
    parse_hook_payload,
)
from proofmesh.config import get_default_policy
from proofmesh.core.evaluator import evaluate_session
from proofmesh.core.handoff import generate_handoff
from proofmesh.core.repo_snapshot import capture_snapshot
from proofmesh.core.scope_analyzer import analyze_scope
from proofmesh.models import (
    IntegrationStatus,
    ScopePolicy,
    Session,
    TrustedPolicy,
)
from proofmesh.storage.paths import get_project_db_path
from proofmesh.storage.store import ProofMeshStore


class AntigravityAdapter:
    """Adapter binding Antigravity lifecycle hooks to ProofMesh core engine."""

    def __init__(
        self,
        store: ProofMeshStore | None = None,
        policy: TrustedPolicy | None = None,
        repo_root: Path | str | None = None,
        hooks_enabled: bool = True,
        mcp_enabled: bool = True,
    ) -> None:
        self.store = store or ProofMeshStore(get_project_db_path("default"))
        self.policy = policy or get_default_policy()
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd()
        self.hooks_enabled = hooks_enabled
        self.mcp_enabled = mcp_enabled

    def get_integration_status(self) -> IntegrationStatus:
        """Report verified integration status based on active capabilities.

        - ENFORCED: Both lifecycle hooks and MCP tool connection are active and verified.
        - PARTIAL: MCP or lifecycle hooks are partially active/advisory.
        - UNGUARDED: Neither hooks nor MCP are active.
        """
        if self.hooks_enabled and self.mcp_enabled:
            return IntegrationStatus.ENFORCED
        elif self.mcp_enabled or self.hooks_enabled:
            return IntegrationStatus.PARTIAL
        return IntegrationStatus.UNGUARDED

    def _resolve_session(self, conversation_id: str | None = None) -> Session | None:
        """Resolve session by conversation_id or fetch the latest active session."""
        if conversation_id:
            sess = self.store.get_session(conversation_id)
            if sess is not None:
                return sess

        conn = self.store.get_connection()
        try:
            row = conn.execute(
                "SELECT session_id FROM sessions ORDER BY started_at DESC LIMIT 1;"
            ).fetchone()
            if row and row["session_id"]:
                return self.store.get_session(str(row["session_id"]))
            return None
        finally:
            conn.close()

    def handle_pre_invocation(
        self,
        payload_or_raw: PreInvocationPayload | dict[str, Any] | str,
    ) -> PreInvocationResponse:
        """Handle PreInvocation hook, injecting a bounded reminder into context."""
        if isinstance(payload_or_raw, PreInvocationPayload):
            payload = payload_or_raw
        else:
            payload = parse_hook_payload(payload_or_raw, event_type="PreInvocation")  # type: ignore

        session = self._resolve_session(payload.conversationId)
        if session is None:
            return PreInvocationResponse(injectSteps=[])

        task_rev = self.store.get_task_revision(session.task_id, session.contract_revision)
        if task_rev is None:
            return PreInvocationResponse(injectSteps=[])

        # Construct concise ephemeral reminder (<= ~600 chars)
        gates_str = ", ".join(task_rev.required_gates) if task_rev.required_gates else "none"
        reminder = (
            f"[ProofMesh] Active Contract: {task_rev.task_id} (rev {task_rev.revision}). "
            f"Objective: {task_rev.summary}. "
            f"Required Gates: {gates_str}. "
            f"Allowed Paths: {list(task_rev.scope.allow_paths)}. "
            f"Do not edit files outside approved scope."
        )
        if len(reminder) > 600:
            reminder = reminder[:595] + "..."

        return PreInvocationResponse(injectSteps=[{"ephemeralMessage": reminder}])

    def handle_pre_tool_use(
        self,
        payload_or_raw: PreToolUsePayload | dict[str, Any] | str,
    ) -> PreToolUseResponse:
        """Handle PreToolUse hook, checking proposed file modifications against scope policy."""
        if isinstance(payload_or_raw, PreToolUsePayload):
            payload = payload_or_raw
        else:
            payload = parse_hook_payload(payload_or_raw, event_type="PreToolUse")  # type: ignore

        session = self._resolve_session(payload.conversationId)
        if session is not None:
            task_rev = self.store.get_task_revision(session.task_id, session.contract_revision)
            if task_rev is not None:
                scope_policy = task_rev.scope
            else:
                scope_policy = ScopePolicy(
                    allow_paths=self.policy.scope.default_allow_paths,
                    restricted_paths=self.policy.scope.default_restricted_paths,
                )
            root = Path(session.repo_root)
        else:
            scope_policy = ScopePolicy(
                allow_paths=self.policy.scope.default_allow_paths,
                restricted_paths=self.policy.scope.default_restricted_paths,
            )
            root = self.repo_root

        return evaluate_pre_tool_use(payload, scope_policy, workspace_root=root)

    def handle_stop(
        self,
        payload_or_raw: StopPayload | dict[str, Any] | str,
    ) -> StopResponse:
        """Handle Stop hook, instructing agent to continue if verification is unfulfilled."""
        if isinstance(payload_or_raw, StopPayload):
            payload = payload_or_raw
        else:
            payload = parse_hook_payload(payload_or_raw, event_type="Stop")  # type: ignore

        session = self._resolve_session(payload.conversationId)
        if session is None:
            return StopAllowResponse()

        task_rev = self.store.get_task_revision(session.task_id, session.contract_revision)
        if task_rev is None:
            return StopAllowResponse()

        root = Path(session.repo_root)
        current = capture_snapshot(root)
        baseline = self.store.get_snapshot(session.baseline_snapshot_id) or current
        scope_result = analyze_scope(baseline, current, task_rev.scope)
        evidence_records = self.store.list_evidence_for_session(session.session_id)

        verdict = evaluate_session(
            session=session,
            task_revision=task_rev,
            current_snapshot=current,
            evidence_records=evidence_records,
            scope_result=scope_result,
            policy=self.policy,
        )

        handoff = generate_handoff(task_rev, verdict, scope_result, evidence_records)
        return evaluate_stop(
            payload=payload,
            verdict=verdict,
            handoff_summary=handoff,
        )

    def handle_event(
        self,
        event_name: str,
        payload_data: dict[str, Any] | str,
    ) -> dict[str, Any]:
        """Dispatch a host hook event by name and return serializable JSON dictionary."""
        if event_name == "PreInvocation":
            return self.handle_pre_invocation(payload_data).model_dump(exclude_none=True)
        elif event_name == "PreToolUse":
            return self.handle_pre_tool_use(payload_data).model_dump(exclude_none=True)
        elif event_name == "Stop":
            return self.handle_stop(payload_data).model_dump(exclude_none=True)
        return {"decision": "allow"}


def main() -> None:
    """CLI entrypoint for host hooks calling ProofMesh via stdin/stdout."""
    event_name = sys.argv[1] if len(sys.argv) > 1 else "PreToolUse"
    raw_stdin = sys.stdin.read()
    adapter = AntigravityAdapter()
    result = adapter.handle_event(event_name, raw_stdin)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
