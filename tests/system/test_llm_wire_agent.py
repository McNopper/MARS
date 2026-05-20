"""Module tests for the LLM wire agent TCP round-trip.

These tests start a real in-process MARS server on a random port, spawn
the llm_wire_agent as a subprocess, exchange messages over loopback TCP,
and assert that the agent replies correctly.

No external services are required — the mock provider is used so the tests
are fast and fully offline.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time

import pytest

from mars.runtime.server.main import MARSServer
from mars.client.cli.models import MARSState


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


async def _connect(port: int, name: str, role: str = "human", agent_type: str | None = None):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    hello: dict = {"t": "hello", "role": role, "name": name}
    if agent_type:
        hello["agent_type"] = agent_type
    writer.write((json.dumps(hello) + "\n").encode())
    await writer.drain()
    return reader, writer


async def _read_until(reader, *, t: str, timeout: float = 5.0) -> dict:
    """Read lines until one with the expected 't' field arrives."""
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

async def test_wire_agent_registers_as_llm_agent(unused_tcp_port):
    """Wire agent connects with hello and server emits a spawn event."""
    server = await _start_server(unused_tcp_port)

    # Human connects first
    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    welcome = await _read_until(h_reader, t="welcome")
    my_id = welcome["your_id"]

    # Spawn wire agent subprocess with mock provider
    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "mock",
         "--name", "llm.mock"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Human receives spawn event for the new agent
        spawn = await _read_until(h_reader, t="spawn", timeout=8.0)
        assert spawn["agent_type"] == "LLMAgent"
        assert "llm.mock" in spawn["agent_id"]
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_wire_agent_replies_to_message(unused_tcp_port):
    """Human sends a message to the wire agent; agent replies via chat event."""
    server = await _start_server(unused_tcp_port)

    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    welcome = await _read_until(h_reader, t="welcome")
    my_id = welcome["your_id"]

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "mock",
         "--name", "llm.mock"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await _read_until(h_reader, t="spawn", timeout=8.0)
        agent_id = spawn["agent_id"]

        # Send a message to the agent
        h_writer.write((json.dumps({
            "t": "msg",
            "target": agent_id,
            "text": "Hello, agent!",
        }) + "\n").encode())
        await h_writer.drain()

        # Wait for the chat reply
        chat = await _read_until(h_reader, t="chat", timeout=10.0)
        assert chat["agent_id"] == agent_id
        assert chat["direction"] == "in"
        assert isinstance(chat["content"], str)
        assert len(chat["content"]) > 0
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_wire_agent_multi_turn(unused_tcp_port):
    """Wire agent maintains per-sender conversation history across turns."""
    server = await _start_server(unused_tcp_port)

    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    await _read_until(h_reader, t="welcome")

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "mock",
         "--name", "llm.mock"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await _read_until(h_reader, t="spawn", timeout=8.0)
        agent_id = spawn["agent_id"]

        for turn in range(3):
            h_writer.write((json.dumps({
                "t": "msg",
                "target": agent_id,
                "text": f"Turn {turn}",
            }) + "\n").encode())
            await h_writer.drain()
            chat = await _read_until(h_reader, t="chat", timeout=10.0)
            assert chat["agent_id"] == agent_id
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_despawn_on_wire_agent_exit(unused_tcp_port):
    """Server emits a despawn event when the wire agent process exits."""
    server = await _start_server(unused_tcp_port)

    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    await _read_until(h_reader, t="welcome")

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "mock",
         "--name", "llm.mock"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    spawn = await _read_until(h_reader, t="spawn", timeout=8.0)
    agent_id = spawn["agent_id"]

    proc.terminate()
    proc.wait(timeout=3)

    despawn = await _read_until(h_reader, t="despawn", timeout=5.0)
    assert despawn["agent_id"] == agent_id

    h_writer.close()

    """Wire agent connects with hello and server emits a spawn event."""
    server = await _start_server(unused_tcp_port)

    # Human connects first
    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    welcome = await _read_until(h_reader, t="welcome")
    my_id = welcome["your_id"]

    # Spawn wire agent subprocess with mock provider
    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "mock",
         "--name", "llm.mock"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Human receives spawn event for the new agent
        spawn = await _read_until(h_reader, t="spawn", timeout=8.0)
        assert spawn["agent_type"] == "LLMAgent"
        assert "llm.mock" in spawn["agent_id"]
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


@pytest.mark.asyncio
async def test_wire_agent_replies_to_message(unused_tcp_port):
    """Human sends a message to the wire agent; agent replies via chat event."""
    server = await _start_server(unused_tcp_port)

    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    welcome = await _read_until(h_reader, t="welcome")
    my_id = welcome["your_id"]

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "mock",
         "--name", "llm.mock"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await _read_until(h_reader, t="spawn", timeout=8.0)
        agent_id = spawn["agent_id"]

        # Send a message to the agent
        h_writer.write((json.dumps({
            "t": "msg",
            "target": agent_id,
            "text": "Hello, agent!",
        }) + "\n").encode())
        await h_writer.drain()

        # Wait for the chat reply
        chat = await _read_until(h_reader, t="chat", timeout=10.0)
        assert chat["agent_id"] == agent_id
        assert chat["direction"] == "in"
        assert isinstance(chat["content"], str)
        assert len(chat["content"]) > 0
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


@pytest.mark.asyncio
async def test_wire_agent_multi_turn(unused_tcp_port):
    """Wire agent maintains per-sender conversation history across turns."""
    server = await _start_server(unused_tcp_port)

    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    await _read_until(h_reader, t="welcome")

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "mock",
         "--name", "llm.mock"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await _read_until(h_reader, t="spawn", timeout=8.0)
        agent_id = spawn["agent_id"]

        for turn in range(3):
            h_writer.write((json.dumps({
                "t": "msg",
                "target": agent_id,
                "text": f"Turn {turn}",
            }) + "\n").encode())
            await h_writer.drain()
            chat = await _read_until(h_reader, t="chat", timeout=10.0)
            assert chat["agent_id"] == agent_id
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


@pytest.mark.asyncio
async def test_despawn_on_wire_agent_exit(unused_tcp_port):
    """Server emits a despawn event when the wire agent process exits."""
    server = await _start_server(unused_tcp_port)

    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    await _read_until(h_reader, t="welcome")

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "mock",
         "--name", "llm.mock"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    spawn = await _read_until(h_reader, t="spawn", timeout=8.0)
    agent_id = spawn["agent_id"]

    proc.terminate()
    proc.wait(timeout=3)

    despawn = await _read_until(h_reader, t="despawn", timeout=5.0)
    assert despawn["agent_id"] == agent_id

    h_writer.close()
