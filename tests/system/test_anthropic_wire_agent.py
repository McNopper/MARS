"""System tests for the Anthropic Claude provider via the wire agent.

Skipped automatically when the ``anthropic`` package is not installed or when
``ANTHROPIC_API_KEY`` is not set in the environment.

Run manually::

    ANTHROPIC_API_KEY=sk-ant-... python -m pytest tests/system/test_anthropic_wire_agent.py -v
"""
from __future__ import annotations

import subprocess
import sys

import pytest
import tests.system.helpers as helpers


pytestmark = pytest.mark.skipif(
    not helpers.anthropic_available(),
    reason="ANTHROPIC_API_KEY not set or anthropic package not installed",
)


async def test_anthropic_wire_agent_registers(unused_tcp_port):
    """Anthropic wire agent connects and appears as LLMAgent in the roster."""
    server = await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome", timeout=30.0)

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "anthropic"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await helpers.read_until(h_reader, t="spawn", timeout=30.0)
        assert spawn["agent_type"] == "LLMAgent"
        assert spawn.get("vendor") == "anthropic"
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_anthropic_wire_agent_chat(unused_tcp_port):
    """Human sends a message to Claude; agent returns a non-empty chat reply."""
    server = await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome", timeout=30.0)

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "anthropic",
         "--model", "claude-haiku-4-5"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await helpers.read_until(h_reader, t="spawn", timeout=30.0)
        agent_id = spawn["agent_id"]

        helpers.send_msg(h_writer, agent_id, "Reply with exactly one word: hello")
        await h_writer.drain()

        chat = await helpers.read_until(h_reader, t="chat", timeout=30.0)
        assert chat["agent_id"] == agent_id
        assert chat["direction"] == "in"
        assert len(chat["content"].strip()) > 0
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()
