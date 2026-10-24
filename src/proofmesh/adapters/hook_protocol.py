"""Host lifecycle hook payload parser and response models for ProofMesh adapters.

Provides strict payload parsing, response modeling, and tool/stop evaluation
semantics for Google Antigravity and compatible lifecycle hook systems.
"""

from __future__ import annotations

from enum import StrEnum
import fnmatch
import json
from pathlib import Path
import re
from typing import Any, Sequence

from pydantic import BaseModel, Field

from proofmesh.core.loop_detector import LoopDetector
from proofmesh.models import (
    BudgetPolicy,
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
    "file",
    "filepath",
)


def normalize_and_validate_path(
    raw_path: str,
    workspace_root: str | Path | None = None,
) -> str:
    """Safely normalize and validate target path within canonical workspace root.

    Args:
        raw_path: Proposed target path string.
        workspace_root: Optional workspace root directory. Defaults to Path.cwd().

    Returns:
        Normalized relative POSIX path within the workspace root.

    Raises:
        ValueError: If path contains NUL bytes, traversal components ('..'),
            drive-qualified paths ('C:\\'), UNC paths ('\\\\'), or attempts to escape
            canonical workspace containment (including symlink escapes or nonexistent
            file parent directory escapes).
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Target file path cannot be empty")

    if "\0" in raw_path:
        raise ValueError("Path contains prohibited NUL byte")

    raw_clean = raw_path.strip()

    # Reject drive-qualified (e.g. C:\ or C:/) or UNC network paths
    if re.match(r"^[a-zA-Z]:", raw_clean):
        raise ValueError(f"Drive-qualified paths are not permitted: '{raw_path}'")
    if raw_clean.startswith(("\\\\", "//")):
        raise ValueError(f"UNC network paths are not permitted: '{raw_path}'")

    # Normalize Windows backslashes to forward slashes safely
    norm = raw_clean.replace("\\", "/")

    # Check for drive-qualified paths after backslash replacement
    if re.match(r"^[a-zA-Z]:", norm):
        raise ValueError(f"Drive-qualified paths are not permitted: '{raw_path}'")

    # Reject traversal components ('..')
    parts = [p for p in norm.split("/") if p and p != "."]
    if ".." in parts:
        raise ValueError(f"Path traversal component ('..') detected: '{raw_path}'")

    ws_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()

    if norm.startswith("/"):
        target_path = Path(norm)
    else:
        target_path = ws_root / norm

    # Validate workspace containment
    if target_path.exists() or target_path.is_symlink():
        resolved_target = target_path.resolve()
        if not resolved_target.is_relative_to(ws_root):
            raise ValueError(
                f"Path '{raw_path}' resolves to '{resolved_target}', escaping workspace root '{ws_root}'"
            )
        rel_path = resolved_target.relative_to(ws_root).as_posix()
    else:
        # Nonexistent target file
        resolved_theoretical = target_path.resolve()
        if not resolved_theoretical.is_relative_to(ws_root):
            raise ValueError(
                f"Target path '{raw_path}' resolves to '{resolved_theoretical}', escaping workspace root '{ws_root}'"
            )

        # For nonexistent target files, validate their existing parent directory path
        parent = target_path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent

        if parent.exists():
            resolved_parent = parent.resolve()
            if not resolved_parent.is_relative_to(ws_root):
                raise ValueError(
                    f"Target path parent directory '{parent}' resolves to '{resolved_parent}', escaping workspace root '{ws_root}'"
                )

        rel_path = resolved_theoretical.relative_to(ws_root).as_posix()

    if rel_path == ".":
        return ""
    return rel_path


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

    Raises:
        ValueError: If path contains NUL bytes, traversal components, drive prefixes,
            UNC prefixes, or escapes the workspace root.
    """
    raw_path: str | None = None
    for k in FILE_PATH_ARG_KEYS:
        if k in tool_args:
            val = tool_args[k]
            if isinstance(val, str):
                raw_path = val
                break

    if raw_path is None:
        return None

    if not raw_path.strip():
        if tool_name in FILE_WRITE_TOOLS:
            raise ValueError("Target file path cannot be empty")
        return None

    return normalize_and_validate_path(raw_path, workspace_root=workspace_root)


def check_command_scope(
    command_line: str,
    scope_policy: ScopePolicy | None = None,
) -> tuple[bool, str | None]:
    """Check whether a shell command violates scope or security boundaries.

    Note: Substring checks intercept known destructive operations and restricted
    path patterns, but do not claim to provide complete command isolation.

    Args:
        command_line: Proposed shell command string.
        scope_policy: Active ScopePolicy.

    Returns:
        Tuple of (allowed: bool, reason: str | None).
    """
    cmd = command_line.strip()

    # Intercept known destructive operations on repository state
    destructive_patterns = (
        "git checkout --",
        "git checkout .",
        "git restore",
        "git reset --hard",
        "git reset HEAD",
        "git clean -",
        "rm -rf tests",
        "rm -rf src",
        "rm -rf .git",
        "rm -rf docs",
        "rm -rf .",
        "rm -rf *",
        "rm -r tests",
        "rm -r src",
    )
    for pat in destructive_patterns:
        if pat in cmd:
            return False, f"Command contains prohibited destructive operation: '{pat}'"

    if scope_policy:
        for restricted_pat in scope_policy.restricted_paths:
            # Check if restricted pattern is targeted by file removal or clean commands
            clean_pat = restricted_pat.strip("./*")
            if clean_pat and clean_pat in cmd and any(
                op in cmd for op in ("rm ", "git clean", "shred ", "truncate ", "dd ", "mv ")
            ):
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

    ws_root = (
        workspace_root
        or (payload.workspacePaths[0] if payload.workspacePaths else None)
        or Path.cwd()
    )

    # 1. Check file-write tools
    if tool_name in FILE_WRITE_TOOLS:
        try:
            target_path = extract_target_file(tool_name, tool_args, ws_root)
        except ValueError as exc:
            return PreToolUseDenyResponse(
                reason=f"ProofMesh path security: {exc}"
            )

        if not target_path:
            return PreToolUseDenyResponse(
                reason=f"File modification tool '{tool_name}' missing, empty, or unrecognized target path argument"
            )

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

    # 2. Check other tools with potential path arguments (e.g. read_file)
    try:
        read_target = extract_target_file(tool_name, tool_args, ws_root)
    except ValueError as exc:
        return PreToolUseDenyResponse(
            reason=f"ProofMesh path security: {exc}"
        )

    # 3. Check run_command tool
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
    loop_detector: LoopDetector | None = None,
    budget: BudgetPolicy | None = None,
    session_id: str | None = None,
    budget_exhausted: bool = False,
) -> StopResponse:
    """Evaluate a Stop hook event, enforcing continuation if verification is missing.

    Respects LoopDetector retry budget: if retries are exhausted, allows the host
    to stop to prevent infinite loops, but keeps verdict as BLOCK and explains
    budget exhaustion in the response reason.

    Args:
        payload: StopPayload from host.
        verdict: Evaluated VerdictRecord, if available.
        unfulfilled_gates: Mandatory verification gates that have not passed.
        handoff_summary: Optional markdown handoff summary card.
        loop_detector: Optional LoopDetector tracking failure attempts.
        budget: Optional BudgetPolicy defining max retries.
        session_id: Session identifier for loop detection lookup.
        budget_exhausted: Explicit flag if budget has already been determined exhausted.

    Returns:
        StopContinueResponse if verification is missing/stale or verdict is BLOCK;
        StopAllowResponse if session is cleanly verified or retry budget is exhausted.
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

    # Check budget exhaustion
    exhausted = budget_exhausted
    if not exhausted and loop_detector is not None and session_id is not None:
        effective_budget = budget or BudgetPolicy()
        for g in unfulfilled_gates:
            if loop_detector.is_budget_exhausted(session_id, g, effective_budget):
                exhausted = True
                break
        if not exhausted and verdict is not None:
            for (s, _, _), count in loop_detector._failures.items():
                if s == session_id and count >= effective_budget.max_retries:
                    exhausted = True
                    break

    if is_blocked:
        msg_details = "; ".join(reasons) if reasons else "verification required before completion"
        if exhausted:
            # Allow host to stop to prevent infinite loops, keeping verdict as BLOCK
            reason_msg = (
                f"ProofMesh: Retry budget exhausted. Halting continuation with verdict BLOCK. "
                f"Unresolved blockers: {msg_details}"
            )
            return StopAllowResponse(reason=reason_msg)

        reason_msg = handoff_summary or f"ProofMesh: {msg_details}"
        return StopContinueResponse(reason=reason_msg)

    return StopAllowResponse()
