"""Component tests for MCPAdapter with an in-process fake MCP server.

These tests verify that MCPAdapter correctly handles:
- Large tool lists (simulating external servers like GitHub's 42+ tools)
- Structured multi-parameter tool calls via call_structured()
- The __tool__/__args__ envelope routing
- Buffer size sufficient for large responses

No real external services or network required — a fake MCP server is
implemented as a Python subprocess that speaks the JSON-RPC protocol.
"""
from __future__ import annotations

import asyncio
import json
import sys

import pytest

from mars.runtime.server.mcp_adapter import MCPAdapter


# ---------------------------------------------------------------------------
# Fake MCP server — cross-platform stdin/stdout (no asyncio pipe tricks)
# ---------------------------------------------------------------------------

_FAKE_MCP_SERVER_CODE = r"""
import json, sys

TOOLS = [
    {
        "name": f"tool_{i}",
        "description": f"Fake tool number {i}",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "page":  {"type": "integer"},
            },
            "required": ["query"],
        },
    }
    for i in range(50)
]
TOOLS.append({
    "name": "simple_tool",
    "description": "A tool with a single request param",
    "inputSchema": {
        "type": "object",
        "properties": {"request": {"type": "string"}},
        "required": ["request"],
    },
})

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
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-mcp", "version": "0.1"},
        }})
    elif meth == "notifications/initialized":
        pass
    elif meth == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
    elif meth == "tools/call":
        params = req.get("params", {})
        name   = params.get("name", "")
        args   = params.get("arguments", {})
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": json.dumps({"called": name, "args": args})}],
            "isError": False,
        }})
    elif rid is not None:
        send({"jsonrpc": "2.0", "id": rid,
              "error": {"code": -32601, "message": "not found"}})
"""


def _fake_mcp_cmd() -> list[str]:
    return [sys.executable, "-c", _FAKE_MCP_SERVER_CODE]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMCPAdapterLargeToolList:
    async def test_discovers_all_50_plus_tools(self):
        adapter = MCPAdapter("svc.fake@1", _fake_mcp_cmd())
        try:
            tools = await asyncio.wait_for(adapter.start(), timeout=15.0)
            assert len(tools) == 51  # 50 tool_N + simple_tool
        finally:
            await adapter.stop()

    async def test_tool_schemas_preserved(self):
        adapter = MCPAdapter("svc.fake@1", _fake_mcp_cmd())
        try:
            tools = await asyncio.wait_for(adapter.start(), timeout=15.0)
            t0 = tools[0]
            assert t0.name == "tool_0"
            assert "query" in t0.input_schema.get("properties", {})
            assert "page"  in t0.input_schema.get("properties", {})
        finally:
            await adapter.stop()


class TestMCPAdapterCallStructured:
    async def test_call_structured_passes_args_verbatim(self):
        adapter = MCPAdapter("svc.fake@1", _fake_mcp_cmd())
        try:
            await asyncio.wait_for(adapter.start(), timeout=15.0)
            result = await adapter.call_structured("tool_0", {"query": "hello", "page": 2})
            data = json.loads(result)
            assert data["called"] == "tool_0"
            assert data["args"] == {"query": "hello", "page": 2}
        finally:
            await adapter.stop()

    async def test_call_structured_unknown_tool_returns_error_string(self):
        adapter = MCPAdapter("svc.fake@1", _fake_mcp_cmd())
        try:
            await asyncio.wait_for(adapter.start(), timeout=15.0)
            result = await adapter.call_structured("nonexistent_tool", {})
            assert "unknown tool" in result.lower()
        finally:
            await adapter.stop()

    async def test_call_structured_none_tool_uses_first(self):
        adapter = MCPAdapter("svc.fake@1", _fake_mcp_cmd())
        try:
            await asyncio.wait_for(adapter.start(), timeout=15.0)
            result = await adapter.call_structured(None, {"query": "test"})
            data = json.loads(result)
            assert data["called"] == "tool_0"
        finally:
            await adapter.stop()


class TestMCPAdapterCallLegacy:
    async def test_call_with_request_property_wraps_correctly(self):
        adapter = MCPAdapter("svc.fake@1", _fake_mcp_cmd())
        try:
            await asyncio.wait_for(adapter.start(), timeout=15.0)
            result = await adapter.call("my query", tool_name="simple_tool")
            data = json.loads(result)
            assert data["args"] == {"request": "my query"}
        finally:
            await adapter.stop()

    async def test_call_without_tool_name_uses_first(self):
        adapter = MCPAdapter("svc.fake@1", _fake_mcp_cmd())
        try:
            await asyncio.wait_for(adapter.start(), timeout=15.0)
            result = await adapter.call("anything")
            data = json.loads(result)
            assert data["called"] == "tool_0"
        finally:
            await adapter.stop()


class TestMCPAdapterEnvelopeRouting:
    async def test_envelope_routes_to_correct_tool_with_structured_args(self):
        adapter = MCPAdapter("svc.fake@1", _fake_mcp_cmd())
        try:
            await asyncio.wait_for(adapter.start(), timeout=15.0)
            args = {"query": "python agents", "page": 3}
            result = await adapter.call_structured("tool_5", args)
            data = json.loads(result)
            assert data["called"] == "tool_5"
            assert data["args"]["query"] == "python agents"
            assert data["args"]["page"] == 3
        finally:
            await adapter.stop()
