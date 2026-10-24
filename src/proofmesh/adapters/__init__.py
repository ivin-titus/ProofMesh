"""ProofMesh host adapters and protocol implementations.

Provides MCP server tools and lifecycle hook integration for Google Antigravity
and compatible host systems.
"""

from proofmesh.adapters.antigravity import AntigravityAdapter
from proofmesh.adapters.hook_protocol import (
    HookDecision,
    PreInvocationPayload,
    PreInvocationResponse,
    PreToolUseAllowResponse,
    PreToolUseDenyResponse,
    PreToolUsePayload,
    PreToolUseResponse,
    StopAllowResponse,
    StopContinueResponse,
    StopPayload,
    StopResponse,
    ToolCallInfo,
    check_command_scope,
    evaluate_pre_tool_use,
    evaluate_stop,
    extract_target_file,
    parse_hook_payload,
)


def __getattr__(name: str):
    if name in ("create_mcp_server", "run_stdio_server"):
        from proofmesh.adapters import mcp_server
        return getattr(mcp_server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AntigravityAdapter",
    "create_mcp_server",
    "run_stdio_server",
    "HookDecision",
    "PreInvocationPayload",
    "PreInvocationResponse",
    "PreToolUsePayload",
    "PreToolUseResponse",
    "PreToolUseDenyResponse",
    "PreToolUseAllowResponse",
    "StopPayload",
    "StopResponse",
    "StopContinueResponse",
    "StopAllowResponse",
    "ToolCallInfo",
    "parse_hook_payload",
    "extract_target_file",
    "check_command_scope",
    "evaluate_pre_tool_use",
    "evaluate_stop",
]
