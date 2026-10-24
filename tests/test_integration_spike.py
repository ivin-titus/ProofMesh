import json
from pathlib import Path
import pytest
from mcp.server.mcpserver import MCPServer
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp import ClientSession

FIXTURES_DIR = Path(__file__).parent / "fixtures"
AGY_FIXTURES = FIXTURES_DIR / "host_payloads" / "antigravity"
MCP_FIXTURES = FIXTURES_DIR / "mcp"


def test_antigravity_pre_invocation_fixture():
    path = AGY_FIXTURES / "pre_invocation_payload.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert "conversationId" in data
    assert "workspacePaths" in data
    assert "transcriptPath" in data
    assert "artifactDirectoryPath" in data
    assert "invocationNum" in data
    assert "modelName" in data


def test_antigravity_pre_tool_use_fixture():
    path = AGY_FIXTURES / "pre_tool_use_payload.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["toolCall"]["name"] == "run_command"
    assert "CommandLine" in data["toolCall"]["args"]
    assert "conversationId" in data

    resp_path = AGY_FIXTURES / "pre_tool_use_deny_response.json"
    assert resp_path.exists()
    resp = json.loads(resp_path.read_text())
    assert resp["decision"] == "deny"
    assert "reason" in resp


def test_antigravity_stop_fixture():
    path = AGY_FIXTURES / "stop_payload.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["terminationReason"] == "NO_TOOL_CALL"
    assert data["executionNum"] == 0
    assert data["fullyIdle"] is True

    resp_path = AGY_FIXTURES / "stop_continue_response.json"
    assert resp_path.exists()
    resp = json.loads(resp_path.read_text())
    assert resp["decision"] == "continue"
    assert "reason" in resp


def test_mcp_fixtures():
    init_data = json.loads((MCP_FIXTURES / "mcp_initialize_response.json").read_text())
    assert "protocol_version" in init_data
    assert "capabilities" in init_data
    assert "tools" in init_data["capabilities"]

    tools_data = json.loads((MCP_FIXTURES / "mcp_tools_list_response.json").read_text())
    assert len(tools_data["tools"]) == 1
    assert tools_data["tools"][0]["name"] == "proofmesh_ping"

    call_data = json.loads((MCP_FIXTURES / "mcp_tools_call_response.json").read_text())
    assert call_data["is_error"] is False
    assert call_data["content"][0]["text"] == "pong: hello proofmesh"


@pytest.mark.anyio
async def test_mcp_server_roundtrip():
    """Verify live in-memory MCP server execution of tools."""
    server = MCPServer("spike-server")

    @server.tool()
    def proofmesh_ping(message: str) -> str:
        return f"pong: {message}"

    tools = await server.list_tools()
    assert any(t.name == "proofmesh_ping" for t in tools)

    call_result = await server.call_tool("proofmesh_ping", arguments={"message": "verify"})
    assert call_result.structured_content == {"result": "pong: verify"}
