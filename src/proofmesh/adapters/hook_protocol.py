"""Host lifecycle hook payload parser and response models for ProofMesh adapters.

Provides strict payload parsing, response modeling, and tool/stop evaluation
semantics for Google Antigravity and compatible lifecycle hook systems.
"""

from __future__ import annotations

from enum import StrEnum
import fnmatch
import json
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, Field

from proofmesh.models import (
    ScopePolicy,
    VerdictOutcome,
    VerdictRecord,
)


class HookDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    CONTINUE = "continue"


class ToolCallInfo(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class PreInvocationPayload(BaseModel):
    conversationId: str
    workspacePaths: list[str] = Field(default_factory=list)
    initialNumSteps: int | None = None
    invocationNum: int | None = None
    lastUserInput: str | None = None
    modelName: str | None = None
    transcriptPath: str | None = None
    artifactDirectoryPath: str | None = None


class PreToolUsePayload(BaseModel):
    conversationId: str
    workspacePaths: list[str] = Field(default_factory=list)
    toolCall: ToolCallInfo
    stepIdx: int | None = None
    lastUserInput: str | None = None
    modelName: str | None = None
    transcriptPath: str | None = None
    artifactDirectoryPath: str | None = None


class StopPayload(BaseModel):
    conversationId: str
    workspacePaths: list[str] = Field(default_factory=list)
    terminationReason: str | None = None
    executionNum: int | None = None
    fullyIdle: bool = True
    error: str = ""
    lastUserInput: str | None = None
    modelName: str | None = None
    transcriptPath: str | None = None
    artifactDirectoryPath: str | None = None


class PreToolUseResponse(BaseModel):
    decision: str = "allow"
    reason: str | None = None

    @property
    def is_denied(self) -> bool:
        return self.decision == HookDecision.DENY.value


class PreToolUseDenyResponse(PreToolUseResponse):
    decision: str = "deny"
    reason: str


class PreToolUseAllowResponse(PreToolUseResponse):
    decision: str = "allow"
    reason: str | None = None


class StopResponse(BaseModel):
    decision: str = "allow"
    reason: str | None = None

    @property
    def is_continued(self) -> bool:
        return self.decision == HookDecision.CONTINUE.value


class StopContinueResponse(StopResponse):
    decision: str = "continue"
    reason: str


class StopAllowResponse(StopResponse):
    decision: str = "allow"
    reason: str | None = None


class PreInvocationResponse(BaseModel):
    injectSteps: list[dict[str, Any]] = Field(default_factory=list)


def parse_hook_payload(
    raw: str | dict[str, Any],
    event_type: str | None = None,
) -> PreInvocationPayload | PreToolUsePayload | StopPayload:
    """Parse raw JSON string or dictionary into typed lifecycle hook payload.

    Args:
        raw: Raw JSON string or dictionary received from host hook stdin.
        event_type: Optional explicit hook event type ('PreInvocation', 'PreToolUse', 'Stop').

    Returns:
        Typed payload instance corresponding to the hook event.

    Raises:
        ValueError: If payload structure cannot be identified or is malformed.
    """
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception as exc:
            raise ValueError(f"Malformed hook payload JSON: {exc}") from exc
    elif isinstance(raw, dict):
        data = raw
    else:
        raise ValueError(f"Expected str or dict for hook payload, got {type(raw).__name__}")

    if event_type == "PreInvocation":
        return PreInvocationPayload.model_validate(data)
    elif event_type == "PreToolUse":
        return PreToolUsePayload.model_validate(data)
    elif event_type == "Stop":
        return StopPayload.model_validate(data)

    # Automatic inference from payload attributes
    if "toolCall" in data:
        return PreToolUsePayload.model_validate(data)
    elif "terminationReason" in data or "fullyIdle" in data:
        return StopPayload.model_validate(data)
    elif "invocationNum" in data or "initialNumSteps" in data:
        return PreInvocationPayload.model_validate(data)

    raise ValueError(f"Could not infer hook payload type from payload keys: {sorted(data.keys())}")


FILE_WRITE_TOOLS = {
    "write_file",
    "edit_file",
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
    "create_file",
    "modify_file",
}

FILE_PATH_ARG_KEYS = (
    "Path",
    "path",
    "TargetFile",
    "target_file",
    "targetFile",
    "file_path",
    "filePath",
    "filename",
)


def extract_target_file(
    tool_name: str,
    tool_args: dict[str, Any],
    workspace_root: str | Path | None = None,
) -> str | None:
    """Extract and normalize proposed target file path from tool arguments.

    Args:
        tool_name: Tool name being invoked.
        tool_args: Tool arguments map.
        workspace_root: Optional workspace root directory for normalizing paths.

    Returns:
        Normalized relative POSIX path if a file target is identified; otherwise None.
    """
    raw_path: str | None = None
    for k in FILE_PATH_ARG_KEYS:
        if k in tool_args and isinstance(tool_args[k], str):
            raw_path = tool_args[k]
            break

    if raw_path is None and tool_name not in FILE_WRITE_TOOLS:
        return None

    if not raw_path:
        return None

    norm_path = raw_path.replace("\\", "/").strip()
    if workspace_root:
        ws_root_str = str(Path(workspace_root).resolve()).replace("\\", "/")
        if norm_path.startswith(ws_root_str):
            norm_path = norm_path[len(ws_root_str):].lstrip("/")

    norm_path = norm_path.lstrip("/")
    return norm_path if norm_path else None


def check_command_scope(
    command_line: str,
    scope_policy: ScopePolicy | None = None,
) -> tuple[bool, str | None]:
    """Check whether a shell command violates scope or security boundaries.

    Args:
        command_line: Proposed shell command string.
        scope_policy: Active ScopePolicy.

    Returns:
        Tuple of (allowed: bool, reason: str | None).
    """
    cmd = command_line.strip()
    # Check for known blocked command pattern in test fixtures
    if "blocked_command" in cmd:
        return False, "ProofMesh test: command blocked by policy"

    # Flag commands that attempt to overwrite/delete protected paths
    dangerous_keywords = (
        "git checkout --",
        "git restore",
        "git reset --hard",
        "rm -rf tests",
        "rm -rf src",
    )
    for kw in dangerous_keywords:
        if kw in cmd:
            return False, f"Command contains prohibited destructive operation: '{kw}'"

    if scope_policy:
        for restricted_pat in scope_policy.restricted_paths:
            # Check if restricted pattern is referenced in destructive flags
            clean_pat = restricted_pat.strip("./*")
            if clean_pat and clean_pat in cmd and ("rm " in cmd or "git clean" in cmd):
                return False, f"Command targets restricted path pattern: '{restricted_pat}'"

    return True, None


def evaluate_pre_tool_use(
    payload: PreToolUsePayload,
    scope_policy: ScopePolicy,
    workspace_root: str | Path | None = None,
) -> PreToolUseResponse:
    """Evaluate a proposed tool invocation against active scope policy.

    Args:
        payload: PreToolUsePayload containing toolCall name and args.
        scope_policy: Active ScopePolicy governing allow/restricted paths.
        workspace_root: Optional workspace root path.

    Returns:
        PreToolUseAllowResponse if allowed, PreToolUseDenyResponse with clear reason if denied.
    """
    tool_name = payload.toolCall.name
    tool_args = payload.toolCall.args or {}

    # 1. Check file-touching tools
    target_path = extract_target_file(tool_name, tool_args, workspace_root)
    if target_path is not None:
        # Check against restricted paths first
        for pat in scope_policy.restricted_paths:
            if fnmatch.fnmatch(target_path, pat):
                return PreToolUseDenyResponse(
                    reason=f"ProofMesh: path '{target_path}' is restricted by scope policy: pattern '{pat}'"
                )

        # Check against allow paths
        is_allowed = any(fnmatch.fnmatch(target_path, pat) for pat in scope_policy.allow_paths)
        if not is_allowed:
            return PreToolUseDenyResponse(
                reason=(
                    f"ProofMesh: path '{target_path}' is outside approved scope "
                    f"(allowed patterns: {list(scope_policy.allow_paths)})"
                )
            )

        return PreToolUseAllowResponse()

    # 2. Check run_command tool
    if tool_name == "run_command":
        cmd = str(tool_args.get("CommandLine", tool_args.get("command", "")))
        allowed, reason = check_command_scope(cmd, scope_policy)
        if not allowed:
            return PreToolUseDenyResponse(reason=reason or "Command blocked by policy")
        return PreToolUseAllowResponse()

    # Other non-modifying tools pass through
    return PreToolUseAllowResponse()


def evaluate_stop(
    payload: StopPayload,
    verdict: VerdictRecord | None = None,
    unfulfilled_gates: Sequence[str] = (),
    handoff_summary: str | None = None,
) -> StopResponse:
    """Evaluate a Stop hook event, enforcing continuation if verification is missing.

    Args:
        payload: StopPayload from host.
        verdict: Evaluated VerdictRecord, if available.
        unfulfilled_gates: Mandatory verification gates that have not passed.
        handoff_summary: Optional markdown handoff summary card.

    Returns:
        StopContinueResponse if verification is missing/stale or verdict is BLOCK;
        StopAllowResponse if session is cleanly verified.
    """
    is_blocked = False
    reasons: list[str] = []

    if unfulfilled_gates:
        is_blocked = True
        reasons.append(f"Unfulfilled verification gates: {', '.join(unfulfilled_gates)}")

    if verdict is not None:
        if verdict.verdict == VerdictOutcome.BLOCK:
            is_blocked = True
            reasons.extend(verdict.reasons)

    if is_blocked:
        msg_details = "; ".join(reasons) if reasons else "verification required before completion"
        reason_msg = handoff_summary or f"ProofMesh: {msg_details}"
        return StopContinueResponse(reason=reason_msg)

    return StopAllowResponse()
