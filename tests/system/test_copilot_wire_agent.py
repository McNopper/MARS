"""System tests for the GitHub Copilot provider via the wire agent.

Skipped automatically when ``GITHUB_TOKEN`` (or ``GH_TOKEN``) is not set.

Run manually::

    GITHUB_TOKEN=ghp_... python -m pytest tests/system/test_copilot_wire_agent.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time

import pytest

from mars.srv.main import MARSServer
from mars.cli.models import MARSState


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

def _copilot_available() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))


pytestmark = pytest.mark.skipif(
    not _copilot_available(),
    reason="GITHUB_TOKEN or GH_TOKEN not set",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _start_server(port: int) -> MARSServer:
    state = MARSState()
    server = MARSServer(state)
    ready: asyncio.Future[None] = asyncio.get_event_loop().create_future()
    asyncio.create_task(server.serve("127.0.0.1", port, ready_future=ready))
    await asyncio.wait_for(ready, timeout=5.0)
    return server


async def _connect(port: int, name: str):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write((json.dumps({"t": "hello", "role": "human", "name": name}) + "\n").encode())
    await writer.drain()
    return reader, writer


async def _read_until(reader, *, t: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for event t={t!r}")
        raw = await asyncio.wait_for(reader.readline(), timeout=remaining)
        ev = json.loads(raw.decode())
        if ev.get("t") == t:
            return ev


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_copilot_wire_agent_registers(unused_tcp_port):
    """GitHub Copilot wire agent connects and appears as LLMAgent."""
    server = await _start_server(unused_tcp_port)

    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    await _read_until(h_reader, t="welcome", timeout=5.0)

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "copilot"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await _read_until(h_reader, t="spawn", timeout=10.0)
        assert spawn["agent_type"] == "LLMAgent"
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_copilot_wire_agent_chat(unused_tcp_port):
    """Human sends a message to GitHub Copilot; agent returns a non-empty reply."""
    server = await _start_server(unused_tcp_port)

    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    await _read_until(h_reader, t="welcome", timeout=5.0)

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "copilot",
         "--model", "gpt-4o-mini"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await _read_until(h_reader, t="spawn", timeout=10.0)
        agent_id = spawn["agent_id"]

        h_writer.write((json.dumps({
            "t": "msg",
            "target": agent_id,
            "text": "Reply with exactly one word: hello",
        }) + "\n").encode())
        await h_writer.drain()

        chat = await _read_until(h_reader, t="chat", timeout=30.0)
        assert chat["agent_id"] == agent_id
        assert chat["direction"] == "in"
        assert len(chat["content"].strip()) > 0
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()
