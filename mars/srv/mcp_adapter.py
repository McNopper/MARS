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

MCP_PROTOCOL_VERSION = "2024-11-05"
_DEFAULT_TIMEOUT = 30.0


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
        )
        self._reader_task = asyncio.create_task(self._read_loop())

        # initialize handshake
        await self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mars-server", "version": "1.0"},
            },
        )
        # send initialized notification (fire-and-forget)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
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

        try:
            result = await asyncio.wait_for(
                self._request("tools/call", {"name": tool.name, "arguments": arguments}),
                timeout=_DEFAULT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return f"(service '{self.agent_id}' timed out after {_DEFAULT_TIMEOUT}s)"

        content = result.get("content", [])
        texts = [
            c["text"]
            for c in content
            if isinstance(c, dict) and c.get("type") == "text"
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
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except (asyncio.TimeoutError, Exception):
                try:
                    self._proc.kill()
                except Exception:
                    pass
