"""System tests: external MCP server integration end-to-end.

Tests the complete pipeline:
  Human → LLM wire agent → structured tool call → external MCP server → reply

Uses:
- A fake external MCP server (Python subprocess, no real GitHub needed)
- The mock-tool LLM provider (offline, deterministic tool dispatch)
- A real MARS TCP server with _spawn_mcp_agent

Also verifies that existing internal agents (clock) still work correctly
after the structured-args refactor.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import sys

import tests.system.helpers as helpers

from mars.constants import CATEGORY_EXTERNAL, COST_DEMAND, PROTOCOL_MCP
from mars.client.cli.models import MARSState
from mars.runtime.server.main import MARSServer
from mars.runtime.services.registry import AgentSpec


def _python_cmd(code: str) -> str:
    """Build a shlex-safe command string that runs inline Python code."""
    encoded = base64.b64encode(code.encode()).decode()
    exe = sys.executable.replace("\\", "/")
    return f'"{exe}" -c "import base64,sys; exec(base64.b64decode(b\'{encoded}\').decode())"'


_FAKE_GITHUB_MCP = r"""
import json, sys

TOOLS = [
    {
        "name": "search_repositories",
        "description": "Search GitHub repositories",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":    {"type": "string",  "description": "Search query"},
                "page":     {"type": "integer", "description": "Page number"},
                "per_page": {"type": "integer", "description": "Results per page"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_file_contents",
        "description": "Get contents of a file from a repository",
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner":  {"type": "string"},
                "repo":   {"type": "string"},
                "path":   {"type": "string"},
                "branch": {"type": "string"},
            },
            "required": ["owner", "repo", "path"],
        },
    },
    {
        "name": "create_issue",
        "description": "Create a GitHub issue",
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo":  {"type": "string"},
                "title": {"type": "string"},
                "body":  {"type": "string"},
            },
            "required": ["owner", "repo", "title"],
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
                {"full_name": "example/mars", "description": "Multi-agent runtime",
                 "stargazers_count": 42, "language": "Python"}
            ]})
        elif name == "get_file_contents":
            text = json.dumps({"content": "# README\nThis is a test repo.", "path": args.get("path","")})
        elif name == "create_issue":
            text = json.dumps({"number": 99, "title": args.get("title",""), "html_url": "https://github.com/example/repo/issues/99"})
        else:
            text = json.dumps({"error": f"unknown tool: {name}"})
        send({"jsonrpc":"2.0","id":rid,"result":{
            "content":[{"type":"text","text":text}],
            "isError": False,
        }})
    elif rid is not None:
        send({"jsonrpc":"2.0","id":rid,"error":{"code":-32601,"message":"unknown"}})
"""


def _fake_github_spec() -> AgentSpec:
    cmd = _python_cmd(_FAKE_GITHUB_MCP)
    return AgentSpec(
        name="github",
        description="Fake GitHub MCP server",
        command=cmd,
        skills=["search_repositories", "get_file_contents", "create_issue"],
        category=CATEGORY_EXTERNAL,
        cost=COST_DEMAND,
        protocol=PROTOCOL_MCP,
    )


class TestExternalMCPDiscovery:
    async def test_spawn_registers_three_github_tools(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_github_spec()), timeout=10.0)
        agent_ids = list(server._mcp_adapters.keys())
        assert len(agent_ids) == 1
        tools = server._mcp_adapters[agent_ids[0]].tools
        names = [t.name for t in tools]
        assert "search_repositories" in names
        assert "get_file_contents" in names
        assert "create_issue" in names
        await server.stop_mcp_agents()

    async def test_spawn_event_carries_tool_schemas(self, unused_tcp_port):
        fired: list[dict] = []
        state = MARSState()
        state._event_listeners.append(fired.append)
        server = MARSServer(state)
        ready: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        asyncio.create_task(server.serve("127.0.0.1", unused_tcp_port, ready_future=ready))
        await asyncio.wait_for(ready, timeout=5.0)

        await asyncio.wait_for(server._spawn_mcp_agent(_fake_github_spec()), timeout=10.0)

        spawn_ev = next(e for e in fired if e.get("t") == "spawn" and "github" in e.get("agent_id", ""))
        schemas = {s["name"]: s for s in spawn_ev.get("tool_schemas", [])}
        assert "search_repositories" in schemas
        assert "query" in schemas["search_repositories"]["input_schema"]["properties"]
        await server.stop_mcp_agents()

    async def test_wire_agent_sees_github_tools_on_connect(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_github_spec()), timeout=10.0)

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial = await helpers.read_initial_events(h_reader)

        spawn_events = [e for e in initial if e.get("t") == "spawn"]
        github_spawns = [e for e in spawn_events if "github" in e.get("agent_id", "")]
        assert github_spawns, f"No github spawn event. Got: {[e.get('agent_id') for e in spawn_events]}"
        schemas = github_spawns[0].get("tool_schemas", [])
        assert any(s["name"] == "search_repositories" for s in schemas)

        h_writer.close()
        await server.stop_mcp_agents()


class TestStructuredToolCallEndToEnd:
    async def test_search_repositories_called_with_structured_args(self, unused_tcp_port):
        """Wire the mock-tool LLM agent to call search_repositories with real args."""
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_github_spec()), timeout=10.0)

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        proc = helpers.spawn_llm_agent(unused_tcp_port)
        try:
            spawn = await helpers.read_until(h_reader, t="spawn", agent_type="LLMAgent", timeout=8.0)
            agent_id = spawn["agent_id"]

            helpers.send_msg(h_writer, agent_id, "search GitHub for Python multi-agent repos")
            await h_writer.drain()

            events = await helpers.read_any(h_reader, timeout=20.0)
            chat_events = [e for e in events if e.get("t") == "chat"]
            assert chat_events, f"No chat reply. Events: {[e.get('t') for e in events]}"
            reply = chat_events[-1].get("content", "")
            assert reply, "Empty reply"
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            h_writer.close()
            await server.stop_mcp_agents()

    async def test_direct_structured_envelope_to_mcp_agent(self, unused_tcp_port):
        """Send a __tool__/__args__ envelope directly and verify the MCP call."""
        server = await helpers.start_server(unused_tcp_port)
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_github_spec()), timeout=10.0)
        agent_id = next(iter(server._mcp_adapters))

        reader, writer = await helpers.connect(unused_tcp_port, "llm-agent", role="agent")
        await helpers.read_until(reader, t="welcome")

        envelope = json.dumps({
            "__tool__": "search_repositories",
            "__args__": {"query": "mars", "page": 1, "per_page": 5},
        })
        helpers.send_msg(writer, agent_id, envelope)
        await writer.drain()

        while True:
            raw = await asyncio.wait_for(reader.readline(), timeout=10.0)
            ev = json.loads(raw)
            if ev.get("t") == "msg":
                result = json.loads(ev["text"])
                assert result["total_count"] == 1
                assert result["items"][0]["full_name"] == "example/mars"
                break

        writer.close()
        await server.stop_mcp_agents()


class TestInternalAgentsUnaffected:
    async def test_clock_agent_still_works(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        clock_id = next((aid for aid in server._mcp_adapters if "clock" in aid), None)
        assert clock_id is not None, "Clock agent not started"
        result = await server._mcp_adapters[clock_id].call("what time is it?")
        assert "🕐" in result or re.search(r"\d{2}:\d{2}", result), f"Clock result doesn't look like a time: {result!r}"
        await server.stop_mcp_agents()

    async def test_clock_tool_schema_in_spawn_event(self, unused_tcp_port):
        fired: list[dict] = []
        state = MARSState()
        state._event_listeners.append(fired.append)
        server = MARSServer(state)
        ready: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        asyncio.create_task(server.serve("127.0.0.1", unused_tcp_port, ready_future=ready))
        await asyncio.wait_for(ready, timeout=5.0)
        await server.start_mcp_agents()

        clock_spawn = next(
            (e for e in fired if e.get("t") == "spawn" and "clock" in e.get("agent_id", "")),
            None,
        )
        assert clock_spawn is not None, "No clock spawn event"
        schemas = clock_spawn.get("tool_schemas", [])
        assert any(s["name"] == "get_time" for s in schemas), f"get_time not in tool_schemas: {schemas}"
        await server.stop_mcp_agents()

    async def test_sympy_agent_solve_still_works(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        sympy_id = next((aid for aid in server._mcp_adapters if "sympy" in aid), None)
        assert sympy_id is not None, "SymPy agent not started"
        result = await server._mcp_adapters[sympy_id].call("x**2 - 4 = 0")
        assert "2" in result or "-2" in result, f"SymPy result unexpected: {result!r}"
        await server.stop_mcp_agents()
