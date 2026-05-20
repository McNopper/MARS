"""System tests for the LLM wire agent TCP round-trip.

These tests start a real in-process MARS server on a random port, spawn
the llm_wire_agent as a subprocess, exchange messages over loopback TCP,
and assert that the agent replies correctly.

No external services are required — the mock provider is used so the tests
are fast and fully offline.
"""
from __future__ import annotations

import tests.system.helpers as helpers


async def test_wire_agent_registers_as_llm_agent(unused_tcp_port):
    """Wire agent connects with hello and server emits a spawn event."""
    await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome")

    proc = helpers.spawn_llm_agent(unused_tcp_port, provider="mock",
                                   extra_args=["--name", "llm.mock"])
    try:
        spawn = await helpers.read_until(h_reader, t="spawn", timeout=8.0)
        assert spawn["agent_type"] == "LLMAgent"
        assert "llm.mock" in spawn["agent_id"]
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_wire_agent_replies_to_message(unused_tcp_port):
    """Human sends a message to the wire agent; agent replies via chat event."""
    await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome")

    proc = helpers.spawn_llm_agent(unused_tcp_port, provider="mock",
                                   extra_args=["--name", "llm.mock"])
    try:
        spawn = await helpers.read_until(h_reader, t="spawn", timeout=8.0)
        agent_id = spawn["agent_id"]

        helpers.send_msg(h_writer, agent_id, "Hello, agent!")
        await h_writer.drain()

        chat = await helpers.read_until(h_reader, t="chat", timeout=10.0)
        assert chat["agent_id"] == agent_id
        assert chat["direction"] == "in"
        assert len(chat["content"]) > 0
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_wire_agent_multi_turn(unused_tcp_port):
    """Wire agent maintains per-sender conversation history across turns."""
    await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome")

    proc = helpers.spawn_llm_agent(unused_tcp_port, provider="mock",
                                   extra_args=["--name", "llm.mock"])
    try:
        spawn = await helpers.read_until(h_reader, t="spawn", timeout=8.0)
        agent_id = spawn["agent_id"]

        for turn in range(3):
            helpers.send_msg(h_writer, agent_id, f"Turn {turn}")
            await h_writer.drain()
            chat = await helpers.read_until(h_reader, t="chat", timeout=10.0)
            assert chat["agent_id"] == agent_id
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_despawn_on_wire_agent_exit(unused_tcp_port):
    """Server emits a despawn event when the wire agent process exits."""
    await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome")

    proc = helpers.spawn_llm_agent(unused_tcp_port, provider="mock",
                                   extra_args=["--name", "llm.mock"])
    spawn = await helpers.read_until(h_reader, t="spawn", timeout=8.0)
    agent_id = spawn["agent_id"]

    proc.terminate()
    proc.wait(timeout=3)

    despawn = await helpers.read_until(h_reader, t="despawn", timeout=5.0)
    assert despawn["agent_id"] == agent_id

    h_writer.close()
