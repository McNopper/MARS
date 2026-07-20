"""End-to-end test: drive the MARS world MCP server as a real MCP client.

This is the proof of the whole thesis - an MCP client (like opencode) connects to
the world server over stdio and drives the verbs. Spawns a subprocess, so it is
marked ``slow`` and excluded from the default run.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

pytestmark = pytest.mark.slow


def _text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


def _wait_for_port(host: str, port: int, attempts: int = 80) -> bool:
    for _ in range(attempts):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


async def _drive(world_dir: Path) -> dict:
    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "mars.world.server", "--world-dir", str(world_dir)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            out: dict = {}
            out["tool_names"] = {t.name for t in (await session.list_tools()).tools}
            out["look_lobby"] = _text(await session.call_tool("look", {"avatar": "you"}))
            out["say"] = _text(await session.call_tool("say", {"avatar": "you", "text": "hello world"}))
            out["listen"] = _text(await session.call_tool("listen", {"avatar": "you"}))
            out["rooms_before"] = _text(await session.call_tool("rooms", {}))
            out["go_bad"] = _text(await session.call_tool("go", {"avatar": "you", "room": "cellar"}))
            out["create_room"] = _text(await session.call_tool(
                "create_room", {"avatar": "you", "name": "workshop",
                                "content": "The Workshop\nA room to build things in."}))
            out["go_workshop"] = _text(await session.call_tool("go", {"avatar": "you", "room": "workshop"}))
            out["write"] = _text(await session.call_tool("write", {"avatar": "you", "text": "the contract"}))
            out["append"] = _text(await session.call_tool("append", {"avatar": "you", "text": "rule two"}))
            out["read"] = _text(await session.call_tool("read", {"avatar": "you"}))
            return out


@pytest.mark.asyncio
async def test_mcp_client_drives_the_world(tmp_path: Path) -> None:
    world_dir = tmp_path / "world"
    result = await _drive(world_dir)

    expected_verbs = {"look", "listen", "say", "go", "rooms", "create_room", "read", "write", "append"}
    assert expected_verbs <= result["tool_names"], f"missing verbs: {expected_verbs - result['tool_names']}"

    assert "Lobby" in result["look_lobby"]
    assert "you: hello world" in result["listen"]
    assert "lobby" in result["rooms_before"]
    # only lobby is seeded; the rest is created dynamically
    assert "workshop" not in result["rooms_before"]
    assert "no room" in result["go_bad"].lower()
    assert "Built room" in result["create_room"]
    assert "Workshop" in result["go_workshop"]
    assert "Protocol written" in result["write"]
    assert "Protocol updated" in result["append"]
    assert "the contract" in result["read"]
    assert "rule two" in result["read"]

    lobby = (world_dir / "rooms" / "lobby.md").read_text(encoding="utf-8")
    assert "you: hello world" in lobby
    # the protocol was written in the dynamically created workshop room
    workshop = (world_dir / "rooms" / "workshop.md").read_text(encoding="utf-8")
    assert "the contract" in workshop
    assert "rule two" in workshop


@pytest.mark.asyncio
async def test_mcp_client_drives_the_world_over_sse(tmp_path: Path, unused_tcp_port: int) -> None:
    """A remote MCP client connects to a standalone MARS server over SSE (the network door)."""
    world_dir = tmp_path / "world"
    port = unused_tcp_port
    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.world.server", "--transport", "sse",
         "--port", str(port), "--world-dir", str(world_dir)],
        stderr=subprocess.PIPE,
    )
    try:
        assert _wait_for_port("127.0.0.1", port), "SSE server did not start"
        async with sse_client(f"http://127.0.0.1:{port}/sse") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert "look" in {t.name for t in (await session.list_tools()).tools}
                await session.call_tool("say", {"avatar": "remote", "text": "hi over the wire"})
                heard = _text(await session.call_tool("listen", {"avatar": "remote"}))
                assert "remote: hi over the wire" in heard
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
