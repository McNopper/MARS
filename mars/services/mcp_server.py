"""Minimal MCP stdio server for MARS service agents.

MCP (Model Context Protocol) uses JSON-RPC 2.0 over stdin/stdout.
Service agents instantiate MCPServer, register tools with the
``@server.tool()`` decorator, then call ``asyncio.run(server.run())``.

Only LLM agents ever call service agents — humans never talk to them
directly.  The MCP request/response cycle is therefore:

    LLM wire agent → MARS server → MCPAdapter → MCPServer subprocess
                                              ← single text result ←

No duplicate msgs, no artifacts — one ``tools/call`` yields one result.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import sys
from dataclasses import dataclass
from typing import Any, Callable

MCP_PROTOCOL_VERSION = "2024-11-05"


@dataclass
class _ToolDef:
    name: str
    description: str
    input_schema: dict
    handler: Callable


def _to_content(result: Any) -> list[dict]:
    """Convert a Python value to an MCP content list."""
    if isinstance(result, str):
        return [{"type": "text", "text": result}]
    if isinstance(result, (dict, list)):
        return [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]
    return [{"type": "text", "text": str(result)}]


class MCPServer:
    """Minimal MCP stdio server for MARS service agents."""

    def __init__(self, name: str, version: str = "1.0.0") -> None:
        self._name = name
        self._version = version
        self._tools: dict[str, _ToolDef] = {}

    def tool(
        self,
        name: str,
        description: str,
        input_schema: dict | None = None,
    ) -> Callable:
        """Decorator: register a tool handler with this MCP server.

        The decorated function receives keyword arguments matching the
        input_schema properties.  If no schema is provided, a single
        ``request: str`` parameter is assumed.
        """
        schema = input_schema or {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "The request text"},
            },
            "required": ["request"],
        }

        def decorator(fn: Callable) -> Callable:
            self._tools[name] = _ToolDef(
                name=name,
                description=description,
                input_schema=schema,
                handler=fn,
            )
            return fn

        return decorator

    async def _dispatch(self, req: dict) -> dict | None:
        rid = req.get("id")
        method = str(req.get("method") or "")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": self._name, "version": self._version},
                },
            }

        if method == "notifications/initialized":
            return None  # notification — no response

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "tools": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": t.input_schema,
                        }
                        for t in self._tools.values()
                    ]
                },
            }

        if method == "tools/call":
            params = req.get("params") or {}
            tool_name = str(params.get("name") or "")
            arguments = dict(params.get("arguments") or {})
            tool = self._tools.get(tool_name)
            if tool is None:
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {
                        "code": -32601,
                        "message": f"Unknown tool: {tool_name!r}",
                    },
                }
            try:
                if inspect.iscoroutinefunction(tool.handler):
                    result = await tool.handler(**arguments)
                else:
                    loop = asyncio.get_running_loop()
                    handler = tool.handler
                    result = await loop.run_in_executor(
                        None, lambda: handler(**arguments)
                    )
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {"content": _to_content(result), "isError": False},
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {exc}"}],
                        "isError": True,
                    },
                }

        # Unknown method
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": -32601, "message": f"Unknown method: {method!r}"},
        }

    def _write(self, msg: dict) -> None:
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        sys.stdout.write(line)
        sys.stdout.flush()

    async def run(self) -> None:
        """Main loop: read JSON-RPC 2.0 from stdin, dispatch, write responses."""
        # Ensure stdout is UTF-8 safe on Windows
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

        loop = asyncio.get_running_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
            except (EOFError, ValueError, OSError):
                break
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except Exception:
                continue
            resp = await self._dispatch(req)
            if resp is not None:
                self._write(resp)
