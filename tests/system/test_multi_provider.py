"""System test: Copilot + Ollama both active on one MARS server.

Verifies that when the server is started with ``--provider copilot ollama``,
both wire agents register and both respond to a chat message.  Output is
captured from the TCP bus so we can assert what "shows up" in the CLI.

Skip conditions
---------------
* Copilot skipped when no GitHub OAuth token is available (requires
  ``gh auth login`` — no extra env vars needed).
* Ollama  skipped when localhost:11434 is unreachable.

Run manually::

    python -m pytest tests/system/test_multi_provider.py -v -s
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
import tests.system.helpers as helpers


@pytest.fixture(autouse=True)
def kill_stale_mars_processes():
    """Kill any leftover MARS server or wire-agent processes before each test."""
    _kill_mars_procs()
    yield
    _kill_mars_procs()


def _kill_mars_procs() -> None:
    """Terminate Python processes whose cmdline references mars server/wire-agent."""
    markers = ("mars.runtime.server.main", "mars.runtime.services.llm_wire_agent")
    current_pid = os.getpid()
    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'",
             "get", "ProcessId,CommandLine", "/format:csv"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if not any(m in line for m in markers):
                continue
            parts = line.strip().split(",")
            if len(parts) >= 3:
                pid_str = parts[-1].strip()
                if pid_str.isdigit() and int(pid_str) != current_pid:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", pid_str],
                        capture_output=True,
                    )
    except Exception:
        pass


@pytest.fixture(autouse=True)
def require_both_providers():
    """Skip the test if either Copilot or Ollama is unavailable."""
    if not helpers.copilot_available():
        pytest.skip("Copilot unavailable: run 'gh auth login' to authenticate")
    if not helpers.ollama_reachable():
        pytest.skip("Ollama not running on localhost:11434")


async def test_both_providers_register(unused_tcp_port):
    """Both Copilot and Ollama wire agents connect and appear as LLMAgents."""
    model = helpers.first_ollama_model()
    server = await helpers.start_server(unused_tcp_port)  # noqa: F841

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome", timeout=30.0)

    procs = []
    try:
        for provider, extra in [
            ("copilot", []),
            ("ollama", ["--model", model]),
        ]:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
                 "--server", f"127.0.0.1:{unused_tcp_port}",
                 "--provider", provider] + extra,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ))

        spawns = await helpers.collect_n(h_reader, t="spawn", n=2, timeout=20.0)
        agent_ids = [s["agent_id"] for s in spawns]
        agent_types = [s["agent_type"] for s in spawns]
        vendors = [s.get("vendor", "") for s in spawns]

        print(f"\n[CLI capture] spawn events received: {agent_ids}")
        for sp in spawns:
            print(f"  agent_id={sp['agent_id']}  type={sp['agent_type']}  vendor={sp.get('vendor','?')}")

        assert len(spawns) == 2, "Expected 2 agents to register"
        assert all(at == "LLMAgent" for at in agent_types), f"All agents should be LLMAgent, got: {agent_types}"
        assert "copilot" in vendors, f"copilot vendor missing in {vendors}"
        assert "ollama" in vendors, f"ollama vendor missing in {vendors}"
    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=3)
        h_writer.close()


@pytest.mark.llm
async def test_both_providers_respond(unused_tcp_port):
    """Human sends a message to each agent; both return non-empty chat replies.

    This is the closest to a CLI capture: we assert that both providers
    produce visible output on the wire bus — exactly what would appear in
    the MARS TUI.
    """
    model = helpers.first_ollama_model()
    server = await helpers.start_server(unused_tcp_port)  # noqa: F841

    h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
    await helpers.read_until(h_reader, t="welcome", timeout=30.0)

    procs = []
    try:
        for provider, extra in [
            ("copilot", ["--model", "gpt-4o-mini"]),
            ("ollama", ["--model", model]),
        ]:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
                 "--server", f"127.0.0.1:{unused_tcp_port}",
                 "--provider", provider] + extra,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ))

        spawns = await helpers.collect_n(h_reader, t="spawn", n=2, timeout=20.0)
        vendor_to_id: dict[str, str] = {s.get("vendor", ""): s["agent_id"] for s in spawns}

        print(f"\n[CLI capture] agents online: {vendor_to_id}")

        replies: dict[str, str] = {}
        for vendor, agent_id in vendor_to_id.items():
            helpers.send_msg(h_writer, agent_id, "Reply with exactly one word: hello")
        await h_writer.drain()

        chats = await helpers.collect_n(h_reader, t="chat", n=2, timeout=120.0)
        for chat in chats:
            if chat.get("direction") == "in":
                sender = chat["agent_id"]
                vendor = next((v for v, aid in vendor_to_id.items() if aid == sender), sender)
                replies[vendor] = chat["content"]
                print(f"[CLI capture] {vendor} → {chat['content']!r}")

        assert "copilot" in replies, "No chat reply received from Copilot"
        assert "ollama" in replies, "No chat reply received from Ollama"
        for vendor, reply in replies.items():
            text = reply.strip()
            assert len(text) > 0, f"{vendor} reply was empty"
            for prefix in ("🚫", "⚠️", "❌", "Error:", "error:"):
                assert not text.startswith(prefix), f"{vendor} returned an error instead of a chat reply: {text!r}"
    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=3)
        h_writer.close()
