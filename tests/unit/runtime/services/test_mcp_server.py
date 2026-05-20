"""Unit tests for mars.runtime.services.mcp_server.MCPServer."""
from __future__ import annotations

import json

import pytest

from mars.runtime.services.mcp_server import MCPServer, _to_content
from mars.constants import MCP_PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# _to_content
# ---------------------------------------------------------------------------

class TestToContent:
    def test_string_wrapped_in_text_entry(self):
        result = _to_content("hello")
        assert result == [{"type": "text", "text": "hello"}]

    def test_dict_serialised_as_json(self):
        result = _to_content({"key": "value"})
        assert result[0]["type"] == "text"
        assert '"key"' in result[0]["text"]

    def test_list_serialised_as_json(self):
        result = _to_content([1, 2, 3])
        assert result[0]["type"] == "text"
        assert "1" in result[0]["text"]

    def test_non_string_cast(self):
        result = _to_content(42)
        assert result == [{"type": "text", "text": "42"}]


# ---------------------------------------------------------------------------
# MCPServer.tool decorator
# ---------------------------------------------------------------------------

class TestToolDecorator:
    def test_tool_registered_by_name(self):
        server = MCPServer("test", "1.0")

        @server.tool("my_tool", "A test tool.")
        def my_tool(request: str) -> str:
            return f"got: {request}"

        assert "my_tool" in server._tools
        assert server._tools["my_tool"].description == "A test tool."

    def test_default_schema_has_request_property(self):
        server = MCPServer("test", "1.0")

        @server.tool("t", "desc")
        def t(request: str) -> str:
            return request

        schema = server._tools["t"].input_schema
        assert "request" in schema["properties"]

    def test_custom_schema_stored(self):
        server = MCPServer("test", "1.0")
        custom = {"type": "object", "properties": {"q": {"type": "string"}}}

        @server.tool("t", "desc", custom)
        def t(q: str = "") -> str:
            return q

        assert server._tools["t"].input_schema is custom

    def test_decorator_returns_original_function(self):
        server = MCPServer("test", "1.0")

        @server.tool("t", "desc")
        def my_fn(request: str) -> str:
            return "ok"

        assert my_fn("x") == "ok"


# ---------------------------------------------------------------------------
# MCPServer._dispatch — initialize
# ---------------------------------------------------------------------------

class TestDispatchInitialize:
    async def test_initialize_returns_protocol_version(self):
        server = MCPServer("svc.test", "2.0.0")
        req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        resp = await server._dispatch(req)
        assert resp["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION

    async def test_initialize_returns_server_info(self):
        server = MCPServer("svc.test", "2.0.0")
        req = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        resp = await server._dispatch(req)
        assert resp["result"]["serverInfo"]["name"] == "svc.test"
        assert resp["result"]["serverInfo"]["version"] == "2.0.0"

    async def test_notification_initialized_returns_none(self):
        server = MCPServer("svc.test", "1.0")
        req = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        resp = await server._dispatch(req)
        assert resp is None


# ---------------------------------------------------------------------------
# MCPServer._dispatch — tools/list
# ---------------------------------------------------------------------------

class TestDispatchToolsList:
    async def test_empty_tools_list(self):
        server = MCPServer("svc.test", "1.0")
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        resp = await server._dispatch(req)
        assert resp["result"]["tools"] == []

    async def test_registered_tool_appears_in_list(self):
        server = MCPServer("svc.test", "1.0")

        @server.tool("echo", "Echoes the request.")
        def echo(request: str) -> str:
            return request

        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        resp = await server._dispatch(req)
        tools = resp["result"]["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "echo"
        assert tools[0]["description"] == "Echoes the request."


# ---------------------------------------------------------------------------
# MCPServer._dispatch — tools/call
# ---------------------------------------------------------------------------

class TestDispatchToolsCall:
    async def test_sync_tool_called_and_result_returned(self):
        server = MCPServer("svc.test", "1.0")

        @server.tool("double", "Doubles a number.")
        def double(request: str) -> str:
            return str(int(request) * 2)

        req = {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "double", "arguments": {"request": "5"}},
        }
        resp = await server._dispatch(req)
        assert resp["result"]["isError"] is False
        assert resp["result"]["content"][0]["text"] == "10"

    async def test_async_tool_awaited(self):
        server = MCPServer("svc.test", "1.0")

        @server.tool("async_echo", "Async echo.")
        async def async_echo(request: str) -> str:
            return f"async:{request}"

        req = {
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "async_echo", "arguments": {"request": "hi"}},
        }
        resp = await server._dispatch(req)
        assert resp["result"]["content"][0]["text"] == "async:hi"

    async def test_unknown_tool_returns_error(self):
        server = MCPServer("svc.test", "1.0")
        req = {
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "no_such_tool", "arguments": {}},
        }
        resp = await server._dispatch(req)
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    async def test_tool_exception_wrapped_as_error_result(self):
        server = MCPServer("svc.test", "1.0")

        @server.tool("boom", "Raises.")
        def boom(request: str) -> str:
            raise ValueError("kaboom")

        req = {
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "boom", "arguments": {"request": "x"}},
        }
        resp = await server._dispatch(req)
        assert resp["result"]["isError"] is True
        assert "kaboom" in resp["result"]["content"][0]["text"]

    async def test_unknown_method_returns_error(self):
        server = MCPServer("svc.test", "1.0")
        req = {"jsonrpc": "2.0", "id": 7, "method": "no/such/method"}
        resp = await server._dispatch(req)
        assert "error" in resp
