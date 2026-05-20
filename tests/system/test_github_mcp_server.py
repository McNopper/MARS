"""System tests: GitHub MCP server integration.

Two test classes:

  TestFakeGitHubMCPServer
    Offline — uses the embedded fake GitHub MCP server from
    test_external_mcp_tool_call.py to verify the full MARS integration:
    registration, tool schema propagation, tool call round-trip.
    Runs on every CI pass (no binary, no token required).

  TestRealGitHubMCPServer
    Requires the github-mcp-server binary in bin/ and a GitHub token
    (GITHUB_PERSONAL_ACCESS_TOKEN env var or gh auth login).
    Skipped automatically when either is missing.
    Exercises: server start, tool discovery, search_repositories call.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

import tests.system.helpers as helpers
from mars.constants import CATEGORY_EXTERNAL, COST_DEMAND, PROTOCOL_MCP
from mars.runtime.services.registry import AgentSpec

# ---------------------------------------------------------------------------
# Reusable fake GitHub MCP server (inline Python, no real GitHub API)
# ---------------------------------------------------------------------------

import base64
import sys

_FAKE_GITHUB_MCP = r"""
import json, sys

TOOLS = [
    {
        "name": "search_repositories",
        "description": "Search GitHub repositories",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":    {"type": "string"},
                "page":     {"type": "integer"},
                "per_page": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_file_contents",
        "description": "Get file contents from a repository",
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo":  {"type": "string"},
                "path":  {"type": "string"},
            },
            "required": ["owner", "repo", "path"],
        },
    },
]

def send(msg):
    sys.stdout.buffer.write((json.dumps(msg) + "\n").encode())
    sys.stdout.buffer.flush()

for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    try:
        req = json.loads(raw)
    except Exception:
        continue
    rid  = req.get("id")
    meth = req.get("method", "")
    if meth == "initialize":
        send({"jsonrpc":"2.0","id":rid,"result":{
            "protocolVersion":"2024-11-05",
            "capabilities":{"tools":{}},
            "serverInfo":{"name":"fake-github-mcp","version":"0.1"},
        }})
    elif meth == "notifications/initialized":
        pass
    elif meth == "tools/list":
        send({"jsonrpc":"2.0","id":rid,"result":{"tools": TOOLS}})
    elif meth == "tools/call":
        params = req.get("params", {})
        name   = params.get("name", "")
        args   = params.get("arguments", {})
        if name == "search_repositories":
            text = json.dumps({"total_count": 1, "items": [
                {"full_name": "mcnopper/mars", "description": "Multi-agent runtime",
                 "stargazers_count": 42, "language": "Python"}
            ]})
        elif name == "get_file_contents":
            text = json.dumps({"content": "# README\nThis is a test repo."})
        else:
            text = json.dumps({"error": f"unknown tool: {name}"})
        send({"jsonrpc":"2.0","id":rid,"result":{
            "content":[{"type":"text","text":text}],
            "isError": False,
        }})
    elif rid is not None:
        send({"jsonrpc":"2.0","id":rid,"error":{"code":-32601,"message":"unknown"}})
"""


def _python_inline_cmd(code: str) -> str:
    encoded = base64.b64encode(code.encode()).decode()
    exe = sys.executable.replace("\\", "/")
    return f'"{exe}" -c "import base64,sys; exec(base64.b64decode(b\'{encoded}\').decode())"'


def _fake_github_spec() -> AgentSpec:
    return AgentSpec(
        name="github",
        description="Fake GitHub MCP server for testing",
        command=_python_inline_cmd(_FAKE_GITHUB_MCP),
        skills=["search_repositories", "get_file_contents"],
        category=CATEGORY_EXTERNAL,
        cost=COST_DEMAND,
        protocol=PROTOCOL_MCP,
    )


def _real_github_spec(binary_path: str) -> AgentSpec:
    return AgentSpec(
        name="github",
        description="GitHub MCP server",
        command=f'"{binary_path}" stdio',
        skills=["search_repositories", "get_file_contents", "list_issues"],
        category=CATEGORY_EXTERNAL,
        cost=COST_DEMAND,
        protocol=PROTOCOL_MCP,
    )


# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------

def _github_token_available() -> bool:
    """True when any usable GitHub token is discoverable."""
    if os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        return True
    return helpers.copilot_available()


# ---------------------------------------------------------------------------
# Offline tests (fake binary — no token required)
# ---------------------------------------------------------------------------

class TestFakeGitHubMCPServer:
    """Full integration using the embedded fake GitHub MCP server."""

    async def test_github_server_registers_tools(self, unused_tcp_port):
        """Fake GitHub MCP server spawns and registers its tools."""
        server = await helpers.start_server(unused_tcp_port)
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_github_spec()), timeout=10.0)

        agent_ids = list(server._mcp_adapters.keys())
        assert len(agent_ids) == 1, f"Expected 1 MCP agent, got {len(agent_ids)}"

        tools = server._mcp_adapters[agent_ids[0]].tools
        names = [t.name for t in tools]
        assert "search_repositories" in names
        assert "get_file_contents" in names
        await server.stop_mcp_agents()

    async def test_github_tool_schemas_in_spawn_event(self, unused_tcp_port):
        """spawn event carries full tool schemas for connected agents."""
        server = await helpers.start_server(unused_tcp_port)
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_github_spec()), timeout=10.0)

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial = await helpers.read_initial_events(h_reader)

        spawn_events = [e for e in initial if e.get("t") == "spawn" and "github" in e.get("agent_id", "")]
        assert spawn_events, "No github spawn event in initial events"

        schemas = {s["name"]: s for s in spawn_events[0].get("tool_schemas", [])}
        assert "search_repositories" in schemas, f"search_repositories missing from schemas: {list(schemas)}"
        props = schemas["search_repositories"].get("input_schema", {}).get("properties", {})
        assert "query" in props

        h_writer.close()
        await server.stop_mcp_agents()

    async def test_search_repositories_tool_call(self, unused_tcp_port):
        """Direct structured envelope call to fake GitHub MCP returns items."""
        server = await helpers.start_server(unused_tcp_port)
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_github_spec()), timeout=10.0)
        agent_id = next(iter(server._mcp_adapters))

        reader, writer = await helpers.connect(unused_tcp_port, "llm-agent", role="agent")
        await helpers.read_until(reader, t="welcome")

        envelope = json.dumps({
            "__tool__": "search_repositories",
            "__args__": {"query": "mars python", "page": 1, "per_page": 5},
        })
        helpers.send_msg(writer, agent_id, envelope)
        await writer.drain()

        while True:
            raw = await asyncio.wait_for(reader.readline(), timeout=10.0)
            ev = json.loads(raw)
            if ev.get("t") == "msg":
                result = json.loads(ev["text"])
                assert result["total_count"] == 1
                assert result["items"][0]["full_name"] == "mcnopper/mars"
                break

        writer.close()
        await server.stop_mcp_agents()

    async def test_llm_agent_uses_github_tools(self, unused_tcp_port):
        """mock-tool LLM agent can call the fake GitHub search tool end-to-end."""
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_github_spec()), timeout=10.0)

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        proc = helpers.spawn_llm_agent(
            unused_tcp_port,
            provider="mock-tool",
            extra_args=["--mock-tool-name", "search_repositories",
                        "--mock-tool-request", "mars"],
        )
        try:
            spawn = await helpers.read_until(h_reader, t="spawn", agent_type="LLMAgent", timeout=8.0)
            agent_id = spawn["agent_id"]

            helpers.send_msg(h_writer, agent_id, "search GitHub for mars repos")
            await h_writer.drain()

            events = await helpers.read_any(h_reader, timeout=20.0)
            chat_events = [e for e in events if e.get("t") == "chat"]
            assert chat_events, f"No chat reply. Events: {[e.get('t') for e in events]}"
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            h_writer.close()
            await server.stop_mcp_agents()


# ---------------------------------------------------------------------------
# Real GitHub MCP server tests (skipped when binary / token missing)
# ---------------------------------------------------------------------------

_binary = helpers.github_mcp_binary()

@pytest.mark.skipif(
    _binary is None,
    reason="github-mcp-server binary not found in bin/ — download from github.com/github/github-mcp-server/releases",
)
@pytest.mark.skipif(
    not _github_token_available(),
    reason="No GitHub token — set GITHUB_PERSONAL_ACCESS_TOKEN or run 'gh auth login'",
)
class TestRealGitHubMCPServer:
    """Tests using the real github-mcp-server binary."""

    async def test_real_server_registers_tools(self, unused_tcp_port):
        """Real GitHub MCP server starts and advertises tools."""
        server = await helpers.start_server(unused_tcp_port)
        spec = _real_github_spec(str(_binary))
        await asyncio.wait_for(server._spawn_mcp_agent(spec), timeout=15.0)

        agent_ids = [aid for aid in server._mcp_adapters if "github" in aid]
        assert agent_ids, "No github MCP adapter registered"

        tools = server._mcp_adapters[agent_ids[0]].tools
        tool_names = [t.name for t in tools]
        assert "search_repositories" in tool_names, f"Expected search_repositories. Got: {tool_names[:10]}"
        await server.stop_mcp_agents()

    async def test_real_search_repositories(self, unused_tcp_port):
        """Real GitHub MCP server executes search_repositories and returns results."""
        server = await helpers.start_server(unused_tcp_port)
        spec = _real_github_spec(str(_binary))
        await asyncio.wait_for(server._spawn_mcp_agent(spec), timeout=15.0)
        agent_id = next(aid for aid in server._mcp_adapters if "github" in aid)

        reader, writer = await helpers.connect(unused_tcp_port, "llm-agent", role="agent")
        await helpers.read_until(reader, t="welcome")

        envelope = json.dumps({
            "__tool__": "search_repositories",
            "__args__": {"query": "mars multi-agent python", "per_page": 3},
        })
        helpers.send_msg(writer, agent_id, envelope)
        await writer.drain()

        while True:
            raw = await asyncio.wait_for(reader.readline(), timeout=20.0)
            ev = json.loads(raw)
            if ev.get("t") == "msg":
                # Response may be a JSON string or already decoded
                text = ev.get("text", "")
                assert text, "Empty response from real GitHub MCP server"
                break

        writer.close()
        await server.stop_mcp_agents()

    async def test_real_server_spawn_event_has_schemas(self, unused_tcp_port):
        """spawn event from real GitHub MCP server carries tool schemas."""
        server = await helpers.start_server(unused_tcp_port)
        spec = _real_github_spec(str(_binary))
        await asyncio.wait_for(server._spawn_mcp_agent(spec), timeout=15.0)

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial = await helpers.read_initial_events(h_reader)

        github_spawns = [e for e in initial if e.get("t") == "spawn" and "github" in e.get("agent_id", "")]
        assert github_spawns, "No github spawn event received"
        schemas = {s["name"]: s for s in github_spawns[0].get("tool_schemas", [])}
        assert "search_repositories" in schemas

        h_writer.close()
        await server.stop_mcp_agents()
