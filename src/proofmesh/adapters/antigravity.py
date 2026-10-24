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
from proofmesh.core.loop_detector import LoopDetector
from proofmesh.core.repo_snapshot import capture_snapshot
from proofmesh.core.scope_analyzer import analyze_scope
from proofmesh.models import (
    IntegrationStatus,
    ScopePolicy,
    Session,
    TrustedPolicy,
    VerdictOutcome,
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
        project_id: str | None = None,
        hooks_enabled: bool = False,
        mcp_enabled: bool = False,
        loop_detector: LoopDetector | None = None,
    ) -> None:
        self.store = store or ProofMeshStore(get_project_db_path("default"))
        self.policy = policy or get_default_policy()
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
        self.project_id = project_id or "default"
        self.hooks_enabled = hooks_enabled
        self.mcp_enabled = mcp_enabled
        self.loop_detector = loop_detector or LoopDetector()

    def get_integration_status(self, session: Session | None = None) -> IntegrationStatus:
        """Report verified integration status based on active capabilities.

        - ENFORCED: Both lifecycle hooks and MCP tool connection are active and verified.
        - PARTIAL: MCP or lifecycle hooks are partially active/advisory.
        - UNGUARDED: Neither hooks nor MCP are active.
        """
        hooks_active = self.hooks_enabled
        mcp_active = self.mcp_enabled

        if session is not None:
            if session.integration_status == IntegrationStatus.ENFORCED:
                hooks_active = True
                mcp_active = True
            elif session.integration_status == IntegrationStatus.PARTIAL:
                mcp_active = True

        if hooks_active and mcp_active:
            return IntegrationStatus.ENFORCED
        elif hooks_active or mcp_active:
            return IntegrationStatus.PARTIAL
        return IntegrationStatus.UNGUARDED

    def _resolve_session(self, conversation_id: str | None = None) -> Session | None:
        """Resolve session by conversation_id or fetch active session for project and repository."""
        if conversation_id:
            sess = self.store.get_session(conversation_id, repo_root=self.repo_root)
            if sess is not None:
                return sess

        # Query active session for project and repository root
        active_sess = self.store.get_active_session_for_project(
            self.project_id, repo_root=self.repo_root
        )
        if active_sess is not None:
            return active_sess

        # If project_id was default or not found, search registered projects matching repo_root
        conn = self.store.get_connection()
        try:
            rows = conn.execute(
                "SELECT project_id FROM projects WHERE root_path = ?;",
                (str(self.repo_root),),
            ).fetchall()
            for r in rows:
                p_id = str(r["project_id"])
                p_sess = self.store.get_active_session_for_project(p_id, repo_root=self.repo_root)
                if p_sess is not None:
                    return p_sess
            return None
        finally:
            conn.close()

    def handle_pre_invocation(
        self,
        payload_or_raw: PreInvocationPayload | dict[str, Any] | str,
    ) -> PreInvocationResponse:
        """Handle PreInvocation hook, injecting a bounded reminder into context."""
        self.hooks_enabled = True
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
        self.hooks_enabled = True
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
            root = Path(session.repo_root).resolve()
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
        self.hooks_enabled = True
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

        root = Path(session.repo_root).resolve()
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

        budget_exhausted = False
        if verdict.verdict == VerdictOutcome.BLOCK:
            for r in verdict.reasons:
                self.loop_detector.record_attempt(session.session_id, "evaluation", r)
                if self.loop_detector.is_budget_exhausted(session.session_id, "evaluation", r, self.policy.budget):
                    budget_exhausted = True
            for g in task_rev.required_gates:
                ev = next((e for e in evidence_records if e.gate_id == g), None)
                if ev is None or ev.status != "passed":
                    sig = ev.summary if ev else "missing"
                    self.loop_detector.record_attempt(session.session_id, g, sig)
                    if self.loop_detector.is_budget_exhausted(session.session_id, g, sig, self.policy.budget):
                        budget_exhausted = True

        handoff = generate_handoff(task_rev, verdict, scope_result, evidence_records)
        return evaluate_stop(
            payload=payload,
            verdict=verdict,
            handoff_summary=handoff,
            loop_detector=self.loop_detector,
            budget=self.policy.budget,
            session_id=session.session_id,
            budget_exhausted=budget_exhausted,
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
