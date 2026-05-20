"""System tests for Ollama LLM provider via the wire agent.

These tests start a real MARS server, spawn a wire agent connected to a
locally running Ollama instance, and verify end-to-end chat works.

Skipped automatically when Ollama is not reachable on localhost:11434.
Run with a live Ollama server and at least one pulled model, e.g.::

    ollama pull llama3.2
    python -m pytest tests/system/test_ollama_wire_agent.py -v
"""
from __future__ import annotations

import subprocess
import sys

import pytest
import tests.system.helpers as helpers


pytestmark = pytest.mark.skipif(
    not helpers.ollama_reachable(),
    reason="Ollama not running on localhost:11434",
)


async def test_ollama_wire_agent_registers(unused_tcp_port):
    """Ollama wire agent connects and appears as LLMAgent in the roster."""
    model = helpers.first_ollama_model()
    server = await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome", timeout=30.0)

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "ollama",
         "--model", model],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await helpers.read_until(h_reader, t="spawn", timeout=30.0)
        assert spawn["agent_type"] == "LLMAgent"
        assert spawn.get("vendor") == "ollama"
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_ollama_wire_agent_chat(unused_tcp_port):
    """Human sends a message to Ollama; agent returns a non-empty chat reply."""
    model = helpers.first_ollama_model()
    server = await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome", timeout=30.0)

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "ollama",
         "--model", model],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await helpers.read_until(h_reader, t="spawn", timeout=30.0)
        agent_id = spawn["agent_id"]

        helpers.send_msg(h_writer, agent_id, "Reply with exactly one word: hello")
        await h_writer.drain()

        chat = await helpers.read_until(h_reader, t="chat", timeout=60.0)
        assert chat["agent_id"] == agent_id
        assert chat["direction"] == "in"
        assert len(chat["content"].strip()) > 0
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_ollama_wire_agent_multi_turn(unused_tcp_port):
    """Ollama wire agent maintains conversation history across two turns."""
    model = helpers.first_ollama_model()
    server = await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome", timeout=30.0)

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "ollama",
         "--model", model],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await helpers.read_until(h_reader, t="spawn", timeout=30.0)
        agent_id = spawn["agent_id"]

        for msg in ("Say 'one'.", "Say 'two'."):
            helpers.send_msg(h_writer, agent_id, msg)
            await h_writer.drain()
            chat = await helpers.read_until(h_reader, t="chat", timeout=60.0)
            assert len(chat["content"].strip()) > 0
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()
