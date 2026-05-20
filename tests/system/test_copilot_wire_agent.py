"""System tests for the GitHub Copilot provider via the wire agent.

Skipped automatically when no GitHub OAuth token is available.
Requires ``gh auth login`` (once) — no extra env vars needed.

Run manually::

    python -m pytest tests/system/test_copilot_wire_agent.py -v -s
"""
from __future__ import annotations

import subprocess
import sys

import pytest
import tests.system.helpers as helpers


pytestmark = pytest.mark.skipif(
    not helpers.copilot_available(),
    reason="No GitHub token — run 'gh auth login' first",
)


async def test_copilot_wire_agent_registers(unused_tcp_port):
    """GitHub Copilot wire agent connects and appears as LLMAgent."""
    server = await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome", timeout=30.0)

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "copilot"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        spawn = await helpers.read_until(h_reader, t="spawn", timeout=30.0)
        assert spawn["agent_type"] == "LLMAgent"
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_copilot_wire_agent_chat(unused_tcp_port):
    """Human sends a message to GitHub Copilot; agent returns a non-empty reply."""
    server = await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome", timeout=30.0)

    proc = subprocess.Popen(
        [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
         "--server", f"127.0.0.1:{unused_tcp_port}",
         "--provider", "copilot",
         "--model", "gpt-4o-mini"],
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
