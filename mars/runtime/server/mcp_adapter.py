"""MARS server-side MCP client adapter.

Spawns an MCP stdio service-agent subprocess, performs the MCP
``initialize`` + ``tools/list`` handshake, then exposes a single
``call()`` coroutine for routing service requests.

Only the MARS TCP server uses this adapter — it is transparent to
LLM agents and to humans.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from mars.constants import (
    MCP_BUFFER_SIZE,
    MCP_CLIENT_NAME,
    MCP_CLIENT_VERSION,
    MCP_CONTENT_TYPE_TEXT,
    MCP_NOTIFICATION_INITIALIZED,
    MCP_PROTOCOL_VERSION,
    MCP_TIMEOUT,
    PROCESS_TERM_TIMEOUT,
)


@dataclass
class MCPToolInfo:
    name: str
    description: str
    input_schema: dict


class MCPAdapter:
    """Client-side MCP adapter: spawns an MCP subprocess and calls its tools."""

    def __init__(self, agent_id: str, command: list[str]) -> None:
        self.agent_id = agent_id
        self._command = command
        self._proc: asyncio.subprocess.Process | None = None
        self._tools: list[MCPToolInfo] = []
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._next_id = 1
        self._reader_task: asyncio.Task | None = None

    @property
    def skills(self) -> list[str]:
        return [t.name for t in self._tools]

    @property
    def tools(self) -> list[MCPToolInfo]:
        return list(self._tools)

    async def start(self) -> list[MCPToolInfo]:
        """Spawn subprocess, complete MCP handshake, return tool list."""
        self._proc = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=MCP_BUFFER_SIZE,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        # Yield to the event loop so the reader task starts before we send anything.
        await asyncio.sleep(0)

        # initialize handshake
        await self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": MCP_CLIENT_NAME, "version": MCP_CLIENT_VERSION},
            },
        )
        # send initialized notification (fire-and-forget)
        self._send({"jsonrpc": "2.0", "method": MCP_NOTIFICATION_INITIALIZED, "params": {}})
        await self._drain()

        # list available tools
        result = await self._request("tools/list", {})
        self._tools = [
            MCPToolInfo(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in result.get("tools", [])
        ]
        return self._tools

    async def call(self, request: str, tool_name: str | None = None) -> str:
        """Send a plain-text request to the service.  Returns a text result.

        Uses the first available tool unless *tool_name* is specified.
        The tool's input_schema is inspected: if it has a ``request``
        property the request is passed as ``{"request": text}``; otherwise
        the first required parameter name is used.
        """
        if not self._tools:
            return "(no tools available)"

        tool = (
            next((t for t in self._tools if t.name == tool_name), None)
            if tool_name
            else self._tools[0]
        )
        if tool is None:
            return f"(unknown tool: {tool_name!r})"

        props = tool.input_schema.get("properties", {})
        if "request" in props:
            arguments: dict[str, Any] = {"request": request}
        else:
            required = tool.input_schema.get("required", list(props.keys()))
            arguments = {required[0]: request} if required else {"request": request}

        return await self._invoke(tool.name, arguments)

    async def call_structured(self, tool_name: str | None, arguments: dict[str, Any]) -> str:
        """Call a specific tool with a pre-built arguments dict.

        Used when the wire agent has already parsed the LLM's structured
        tool-call arguments and wants to pass them through verbatim.
        """
        if not self._tools:
            return "(no tools available)"
        tool = (
            next((t for t in self._tools if t.name == tool_name), None)
            if tool_name
            else self._tools[0]
        )
        if tool is None:
            return f"(unknown tool: {tool_name!r})"
        return await self._invoke(tool.name, arguments)

    async def _invoke(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tools/call RPC and return the text result."""
        try:
            result = await asyncio.wait_for(
                self._request("tools/call", {"name": tool_name, "arguments": arguments}),
                timeout=MCP_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return f"(service '{self.agent_id}' timed out after {MCP_TIMEOUT}s)"

        content = result.get("content", [])
        texts = [
            c["text"]
            for c in content
            if isinstance(c, dict) and c.get("type") == MCP_CONTENT_TYPE_TEXT
        ]
        is_error = result.get("isError", False)
        text = "\n".join(texts) if texts else str(result)
        return f"Error: {text}" if is_error else text

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _send(self, msg: dict) -> None:
        if self._proc and self._proc.stdin and not self._proc.stdin.is_closing():
            self._proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))

    async def _drain(self) -> None:
        if self._proc and self._proc.stdin:
            try:
                await self._proc.stdin.drain()
            except Exception:
                pass

    async def _request(self, method: str, params: dict) -> dict:
        rid = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict] = loop.create_future()
        self._pending[rid] = fut
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        await self._drain()
        try:
            return await fut
        finally:
            self._pending.pop(rid, None)

    async def _read_loop(self) -> None:
        if not self._proc or not self._proc.stdout:
            return
        while True:
            try:
                line = await self._proc.stdout.readline()
            except Exception:
                break
            if not line:
                break
            try:
                msg = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            rid = msg.get("id")
            if rid is not None:
                fut = self._pending.pop(rid, None)
                if fut is not None and not fut.done():
                    if "result" in msg:
                        fut.set_result(msg["result"])
                    elif "error" in msg:
                        fut.set_exception(RuntimeError(str(msg["error"])))
                    else:
                        fut.set_result({})
        # Subprocess exited — cancel any pending requests so callers don't hang.
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def stop(self) -> None:
        """Terminate the subprocess and clean up."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._proc:
            if self._proc.stdin:
                try:
                    self._proc.stdin.close()
                except Exception:
                    pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=PROCESS_TERM_TIMEOUT)
            except (asyncio.TimeoutError, Exception):
                try:
                    self._proc.kill()
                except Exception:
                    pass
