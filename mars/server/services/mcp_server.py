"""MARS MCP service agent server — wraps the official ``mcp`` SDK (FastMCP).

Service agents instantiate :class:`MCPServer`, register tools with the
``@server.tool()`` decorator, then call ``server.run()`` (synchronous).

The MCP request/response cycle is:

    LLM wire agent → MARS server → MCPAdapter → MCPServer subprocess
                                              ← single text result ←

This module wraps ``mcp.server.fastmcp.FastMCP`` so existing agent code
needs only a one-line change: ``asyncio.run(server.run())`` → ``server.run()``.
The explicit JSON schema passed to ``@server.tool()`` is accepted for
backward-compatibility but ignored; FastMCP infers the schema from the
decorated function's Python type annotations.
"""
from __future__ import annotations

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP


class MCPServer:
    """Thin wrapper around :class:`~mcp.server.fastmcp.FastMCP`.

    Provides the same decorator-based API used by all MARS service agents
    while delegating all MCP protocol handling to the official SDK.
    """

    def __init__(self, name: str, version: str = "1.0.0") -> None:
        # version is accepted for API compatibility but not forwarded —
        # FastMCP derives it from the package metadata automatically.
        self._mcp = FastMCP(name)

    def tool(
        self,
        name: str,
        description: str,
        input_schema: dict | None = None,  # noqa: ARG002 — inferred by FastMCP
    ) -> Callable:
        """Decorator: register a tool handler with this MCP server.

        ``input_schema`` is accepted for backward-compatibility but ignored;
        FastMCP infers the JSON Schema from the function's type annotations.
        """
        return self._mcp.tool(name=name, description=description)

    def run(self) -> None:
        """Start the MCP stdio server loop (synchronous, blocks until stdin closes)."""
        self._mcp.run(transport="stdio")
