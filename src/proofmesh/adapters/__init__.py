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
from proofmesh.adapters.mcp_server import create_mcp_server, run_stdio_server

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
