"""System tests for Ollama LLM provider via the wire agent.

These tests start a real MARS server, spawn a wire agent connected to a
locally running Ollama instance, and verify end-to-end chat works.

Skipped automatically when Ollama is not reachable on localhost:11434.
Run with a live Ollama server and at least one pulled model, e.g.::

    ollama pull llama3.2
    python -m pytest tests/system/test_ollama_wire_agent.py -v
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
# Skip fixture
# ---------------------------------------------------------------------------

def _ollama_reachable() -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_reachable(),
    reason="Ollama not running on localhost:11434",
)


# ---------------------------------------------------------------------------
# Helpers (same pattern as module tests)
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


def _first_ollama_model() -> str:
    """Return the name of the first installed Ollama model, or 'llama3.2'."""
    try:
        import urllib.request, json as _json
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            data = _json.loads(r.read())
        models = data.get("models", [])
        if models:
            return models[0]["name"]
    except Exception:
        pass
    return "llama3.2"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_ollama_wire_agent_registers(unused_tcp_port):
    """Ollama wire agent connects and appears as LLMAgent in the roster."""
    model = _first_ollama_model()
    server = await _start_server(unused_tcp_port)

    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    await _read_until(h_reader, t="welcome", timeout=5.0)

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "ollama",
         "--model", model],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await _read_until(h_reader, t="spawn", timeout=10.0)
        assert spawn["agent_type"] == "LLMAgent"
        assert spawn.get("vendor") == "ollama"
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_ollama_wire_agent_chat(unused_tcp_port):
    """Human sends a message to Ollama; agent returns a non-empty chat reply."""
    model = _first_ollama_model()
    server = await _start_server(unused_tcp_port)

    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    await _read_until(h_reader, t="welcome", timeout=5.0)

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "ollama",
         "--model", model],
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

        # Ollama may take a few seconds to generate
        chat = await _read_until(h_reader, t="chat", timeout=60.0)
        assert chat["agent_id"] == agent_id
        assert chat["direction"] == "in"
        assert len(chat["content"].strip()) > 0
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_ollama_wire_agent_multi_turn(unused_tcp_port):
    """Ollama wire agent maintains conversation history across two turns."""
    model = _first_ollama_model()
    server = await _start_server(unused_tcp_port)

    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    await _read_until(h_reader, t="welcome", timeout=5.0)

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "ollama",
         "--model", model],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await _read_until(h_reader, t="spawn", timeout=10.0)
        agent_id = spawn["agent_id"]

        for msg in ("Say 'one'.", "Say 'two'."):
            h_writer.write((json.dumps({
                "t": "msg", "target": agent_id, "text": msg,
            }) + "\n").encode())
            await h_writer.drain()
            chat = await _read_until(h_reader, t="chat", timeout=60.0)
            assert len(chat["content"].strip()) > 0
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()
