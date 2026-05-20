"""Module tests: external MCP server spawn via _spawn_mcp_agent.

Tests that the server correctly:
- Starts an MCP server subprocess via MCPAdapter
- Publishes tool_schemas in the spawn event
- Registers tools by name in the wire agent's _service_tools dict
- Cleans up on despawn

A fake MCP server (Python subprocess) is used — no real external services.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import pytest


def _python_cmd(code: str) -> str:
    """Build a shlex-safe command string that runs inline Python code."""
    encoded = base64.b64encode(code.encode()).decode()
    exe = sys.executable.replace("\\", "/")
    return f'"{exe}" -c "import base64,sys; exec(base64.b64decode(b\'{encoded}\').decode())"'

from mars.runtime.server.main import MARSServer, _PROJECT_ROOT
from mars.client.cli.models import MARSState
from mars.runtime.services.registry import AgentSpec
from mars.constants import CATEGORY_EXTERNAL, COST_DEMAND, PROTOCOL_MCP


# ---------------------------------------------------------------------------
# Fake MCP server command (inline Python — no file needed)
# ---------------------------------------------------------------------------

_FAKE_SERVER = r"""
import json, sys

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
            "serverInfo":{"name":"fake","version":"0.1"},
        }})
    elif meth == "notifications/initialized":
        pass
    elif meth == "tools/list":
        send({"jsonrpc":"2.0","id":rid,"result":{"tools":[
            {"name":"search_repos","description":"Search repositories",
             "inputSchema":{"type":"object","properties":{"query":{"type":"string"},"page":{"type":"integer"}},"required":["query"]}},
            {"name":"get_file","description":"Get file contents",
             "inputSchema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},
        ]}})
    elif meth == "tools/call":
        params = req.get("params",{})
        name  = params.get("name","")
        args  = params.get("arguments",{})
        send({"jsonrpc":"2.0","id":rid,"result":{
            "content":[{"type":"text","text":json.dumps({"tool":name,"args":args})}],
            "isError":False,
        }})
    elif rid is not None:
        send({"jsonrpc":"2.0","id":rid,"error":{"code":-32601,"message":"unknown"}})
"""

def _fake_spec(name: str = "ext-fake") -> AgentSpec:
    cmd = _python_cmd(_FAKE_SERVER)
    return AgentSpec(
        name=name,
        description="Fake external MCP server for testing",
        command=cmd,
        skills=["search_repos", "get_file"],
        category=CATEGORY_EXTERNAL,
        cost=COST_DEMAND,
        protocol=PROTOCOL_MCP,
    )


async def _start_server(port: int) -> MARSServer:
    state = MARSState()
    server = MARSServer(state)
    ready: asyncio.Future[None] = asyncio.get_event_loop().create_future()
    asyncio.create_task(server.serve("127.0.0.1", port, ready_future=ready))
    await asyncio.wait_for(ready, timeout=5.0)
    return server


# ---------------------------------------------------------------------------
# _spawn_mcp_agent: discovery and spawn event
# ---------------------------------------------------------------------------

class TestSpawnMcpAgent:
    async def test_spawn_registers_agent_in_state(self, unused_tcp_port):
        server = await _start_server(unused_tcp_port)
        spec = _fake_spec()
        result = await asyncio.wait_for(server._spawn_mcp_agent(spec), timeout=10.0)
        assert "svc.ext-fake" in result or "ext-fake" in result
        assert any("ext-fake" in aid for aid in server._state.agents)
        await server.stop_mcp_agents()

    async def test_spawn_fires_event_with_tool_schemas(self, unused_tcp_port):
        fired: list[dict] = []
        state = MARSState()
        state._event_listeners.append(fired.append)
        server = MARSServer(state)
        ready: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        asyncio.create_task(server.serve("127.0.0.1", unused_tcp_port, ready_future=ready))
        await asyncio.wait_for(ready, timeout=5.0)

        spec = _fake_spec()
        await asyncio.wait_for(server._spawn_mcp_agent(spec), timeout=10.0)

        spawn_events = [e for e in fired if e.get("t") == "spawn" and "ext-fake" in e.get("agent_id", "")]
        assert spawn_events, f"No spawn event fired. Events: {[e.get('t') for e in fired]}"
        ev = spawn_events[0]
        schemas = ev.get("tool_schemas", [])
        assert len(schemas) == 2
        names = [s["name"] for s in schemas]
        assert "search_repos" in names
        assert "get_file" in names
        await server.stop_mcp_agents()

    async def test_spawn_event_schema_contains_input_schema(self, unused_tcp_port):
        fired: list[dict] = []
        state = MARSState()
        state._event_listeners.append(fired.append)
        server = MARSServer(state)
        ready: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        asyncio.create_task(server.serve("127.0.0.1", unused_tcp_port, ready_future=ready))
        await asyncio.wait_for(ready, timeout=5.0)

        await asyncio.wait_for(server._spawn_mcp_agent(_fake_spec()), timeout=10.0)
        spawn_ev = next(e for e in fired if e.get("t") == "spawn" and "ext-fake" in e.get("agent_id", ""))
        schema_map = {s["name"]: s for s in spawn_ev["tool_schemas"]}
        assert "query" in schema_map["search_repos"]["input_schema"].get("properties", {})
        await server.stop_mcp_agents()

    async def test_structured_tool_call_routed_correctly(self, unused_tcp_port):
        server = await _start_server(unused_tcp_port)
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_spec()), timeout=10.0)

        # Find the spawned agent id
        agent_id = next(aid for aid in server._mcp_adapters)

        # Simulate what the wire agent sends: a structured envelope
        envelope = json.dumps({"__tool__": "search_repos", "__args__": {"query": "test", "page": 1}})

        # Connect a fake client session to route through
        reader, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
        writer.write((json.dumps({"t": "hello", "role": "agent", "name": "llm-test", "agent_type": "LLMAgent"}) + "\n").encode())
        await writer.drain()

        # Read welcome
        while True:
            raw = await asyncio.wait_for(reader.readline(), timeout=5.0)
            ev = json.loads(raw)
            if ev.get("t") == "welcome":
                break

        # Send structured envelope to MCP agent
        writer.write((json.dumps({"t": "msg", "target": agent_id, "text": envelope}) + "\n").encode())
        await writer.drain()

        # Read response (server routes back as msg)
        while True:
            raw = await asyncio.wait_for(reader.readline(), timeout=10.0)
            ev = json.loads(raw)
            if ev.get("t") == "msg":
                payload = json.loads(ev["text"])
                assert payload["tool"] == "search_repos"
                assert payload["args"] == {"query": "test", "page": 1}
                break

        writer.close()
        await server.stop_mcp_agents()


# ---------------------------------------------------------------------------
# Wire agent tool registration from spawn event
# ---------------------------------------------------------------------------

class TestWireAgentToolRegistration:
    def test_from_spawn_with_schemas_creates_correct_tools(self):
        from mars.runtime.services.llm_wire_agent import _ServiceTool
        tool_schemas = [
            {"name": "search_repos", "description": "Search repos",
             "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
            {"name": "get_file", "description": "Get file",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        ]
        tools = _ServiceTool.from_spawn("svc.ext-fake@1", ["search_repos", "get_file"], tool_schemas)
        assert len(tools) == 2
        by_name = {t.name: t for t in tools}
        assert "search_repos" in by_name
        assert by_name["search_repos"].parameters["properties"]["query"]["type"] == "string"

    def test_deregister_removes_all_tools_for_agent(self):
        from mars.runtime.services.llm_wire_agent import _ServiceTool
        from collections import defaultdict

        service_tools: dict[str, _ServiceTool] = {}
        tools_by_agent: dict[str, set[str]] = defaultdict(set)

        def register(cid, skills, schemas):
            for t in _ServiceTool.from_spawn(cid, skills, schemas):
                service_tools[t.name] = t
                tools_by_agent[cid].add(t.name)

        def deregister(cid):
            for tname in tools_by_agent.pop(cid, set()):
                service_tools.pop(tname, None)

        schemas = [
            {"name": "tool_a", "description": "", "input_schema": {}},
            {"name": "tool_b", "description": "", "input_schema": {}},
        ]
        register("svc.ext@1", [], schemas)
        assert "tool_a" in service_tools
        assert "tool_b" in service_tools

        deregister("svc.ext@1")
        assert "tool_a" not in service_tools
        assert "tool_b" not in service_tools
        assert "svc.ext@1" not in tools_by_agent
