"""System test: say hello to a Copilot agent and an Ollama agent.

Starts a real MARS server, spawns one Copilot wire agent and one Ollama wire
agent, sends "hello" to each, and asserts both return a non-empty, non-error
reply — exactly what a user sees when they type hello in the MARS CLI.

Skip conditions
---------------
* Copilot:  no GitHub token — run ``gh auth login`` first.
* Ollama:   localhost:11434 is not reachable.

Run manually::

    python -m pytest tests/system/test_hello_copilot_ollama.py -v -s
"""
from __future__ import annotations

import subprocess
import sys

import pytest
import tests.system.helpers as helpers


# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def require_copilot():
    if not helpers.copilot_available():
        pytest.skip("Copilot unavailable — run 'gh auth login' first")


@pytest.fixture(autouse=True)
def require_ollama():
    if not helpers.ollama_reachable():
        pytest.skip("Ollama not running on localhost:11434")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_copilot_says_hello(unused_tcp_port):
    """Copilot wire agent replies with a non-empty message when greeted."""
    await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome", timeout=10.0)

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

        helpers.send_msg(h_writer, agent_id, "hello")
        await h_writer.drain()

        chat = await helpers.read_until(h_reader, t="chat", timeout=30.0)
        reply = chat["content"].strip()

        print(f"\n[copilot] -> {reply!r}")
        assert len(reply) > 0, "Copilot returned an empty reply"
        assert not reply.lower().startswith("error"), f"Copilot returned an error: {reply!r}"
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_ollama_says_hello(unused_tcp_port):
    """Ollama wire agent replies with a non-empty message when greeted."""
    model = helpers.first_ollama_model()
    await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome", timeout=10.0)

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

        helpers.send_msg(h_writer, agent_id, "hello")
        await h_writer.drain()

        chat = await helpers.read_until(h_reader, t="chat", timeout=60.0)
        reply = chat["content"].strip()

        print(f"\n[ollama/{model}] -> {reply!r}")
        assert len(reply) > 0, "Ollama returned an empty reply"
        assert not reply.lower().startswith("error"), f"Ollama returned an error: {reply!r}"
    finally:
        proc.terminate()
        proc.wait(timeout=3)
        h_writer.close()


async def test_both_reply_to_hello(unused_tcp_port):
    """Both Copilot and Ollama agents reply when greeted simultaneously."""
    model = helpers.first_ollama_model()
    await helpers.start_server(unused_tcp_port)

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome", timeout=10.0)

    procs = []
    try:
        for provider, extra in [
            ("copilot", ["--model", "gpt-4o-mini"]),
            ("ollama",  ["--model", model]),
        ]:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
                 "--server", f"127.0.0.1:{unused_tcp_port}",
                 "--provider", provider] + extra,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ))

        spawns = await helpers.collect_n(h_reader, t="spawn", n=2, timeout=30.0)
        vendor_to_id: dict[str, str] = {s.get("vendor", ""): s["agent_id"] for s in spawns}
        print(f"\n[agents online] {list(vendor_to_id)}")

        for agent_id in vendor_to_id.values():
            helpers.send_msg(h_writer, agent_id, "hello")
        await h_writer.drain()

        chats = await helpers.collect_n(h_reader, t="chat", n=2, timeout=90.0)
        replies: dict[str, str] = {}
        for chat in chats:
            if chat.get("direction") == "in":
                vendor = next(
                    (v for v, aid in vendor_to_id.items() if aid == chat["agent_id"]),
                    chat["agent_id"],
                )
                replies[vendor] = chat["content"].strip()
                print(f"[{vendor}] → {replies[vendor]!r}")

        assert "copilot" in replies, "No reply from Copilot"
        assert "ollama" in replies, "No reply from Ollama"
        for vendor, reply in replies.items():
            assert len(reply) > 0, f"{vendor} returned an empty reply"
            assert not reply.lower().startswith("error"), \
                f"{vendor} returned an error: {reply!r}"
    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=3)
        h_writer.close()
