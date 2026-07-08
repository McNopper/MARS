"""Unit tests for mars.server.services.mcp_server.MCPServer.

MCPServer is now a thin wrapper around FastMCP (official mcp SDK).
Tests cover the public API: instantiation, @server.tool() decorator,
and that run() exists as a synchronous callable.
"""
from __future__ import annotations

from mars.server.services.mcp_server import MCPServer


class TestMCPServerInstantiation:
    def test_creates_with_name(self):
        server = MCPServer("svc.test")
        assert server is not None

    def test_creates_with_name_and_version(self):
        server = MCPServer("svc.test", "2.0.0")
        assert server is not None

    def test_run_is_callable(self):
        server = MCPServer("svc.test")
        assert callable(server.run)


class TestToolDecorator:
    def test_decorator_returns_original_function(self):
        server = MCPServer("test")

        @server.tool("my_tool", "A test tool.")
        def my_tool(request: str) -> str:
            return f"got: {request}"

        assert my_tool("hello") == "got: hello"

    def test_async_tool_remains_callable(self):
        import asyncio
        server = MCPServer("test")

        @server.tool("async_tool", "Async tool.")
        async def async_tool(request: str) -> str:
            return f"async:{request}"

        result = asyncio.run(async_tool("x"))
        assert result == "async:x"

    def test_schema_arg_accepted_without_error(self):
        server = MCPServer("test")
        custom = {"type": "object", "properties": {"q": {"type": "string"}}}

        @server.tool("t", "desc", custom)
        def t(q: str = "") -> str:
            return q

        assert t("hi") == "hi"

    def test_multiple_tools_registered(self):
        server = MCPServer("test")

        @server.tool("a", "Tool A")
        def a(request: str) -> str:
            return "a"

        @server.tool("b", "Tool B")
        def b(request: str) -> str:
            return "b"

        assert a("x") == "a"
        assert b("x") == "b"
