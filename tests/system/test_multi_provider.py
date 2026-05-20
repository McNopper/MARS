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

import asyncio
import json
import os
import subprocess
import sys
import time

import pytest

from mars.runtime.server.main import MARSServer
from mars.client.cli.models import MARSState


# ---------------------------------------------------------------------------
# Session-cleanup fixture
# ---------------------------------------------------------------------------

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
        # WMIC gives us PID + CommandLine on Windows
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'",
             "get", "ProcessId,CommandLine", "/format:csv"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if not any(m in line for m in markers):
                continue
            parts = line.strip().split(",")
            # CSV columns: Node, CommandLine, ProcessId
            if len(parts) >= 3:
                pid_str = parts[-1].strip()
                if pid_str.isdigit() and int(pid_str) != current_pid:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", pid_str],
                        capture_output=True,
                    )
    except Exception:
        pass  # best-effort cleanup


# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------

def _copilot_available() -> bool:
    from mars.client.providers.copilot import _resolve_token
    try:
        return bool(_resolve_token(None))
    except Exception:
        return False


def _ollama_reachable() -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _first_ollama_model() -> str:
    try:
        import urllib.request, json as _j
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            data = _j.loads(r.read())
        models = data.get("models", [])
        if models:
            return models[0]["name"]
    except Exception:
        pass
    return "llama3.2"


@pytest.fixture(autouse=True)
def require_both_providers():
    """Skip the test if either Copilot or Ollama is unavailable."""
    if not _copilot_available():
        pytest.skip("Copilot unavailable: run 'gh auth login' to authenticate")
    if not _ollama_reachable():
        pytest.skip("Ollama not running on localhost:11434")


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
    """Read frames until one matching ``t`` arrives; return it."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for event t={t!r}")
        raw = await asyncio.wait_for(reader.readline(), timeout=remaining)
        ev = json.loads(raw.decode())
        if ev.get("t") == t:
            return ev


async def _collect_n(reader, *, t: str, n: int, timeout: float = 20.0) -> list[dict]:
    """Collect *n* events of type *t* from the stream."""
    deadline = time.monotonic() + timeout
    events: list[dict] = []
    while len(events) < n:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Only got {len(events)}/{n} events of type t={t!r} before timeout"
            )
        raw = await asyncio.wait_for(reader.readline(), timeout=remaining)
        ev = json.loads(raw.decode())
        if ev.get("t") == t:
            events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_both_providers_register(unused_tcp_port):
    """Both Copilot and Ollama wire agents connect and appear as LLMAgents."""
    model = _first_ollama_model()
    server = await _start_server(unused_tcp_port)  # noqa: F841

    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    await _read_until(h_reader, t="welcome", timeout=5.0)

    procs = []
    try:
        for provider, extra in [
            ("copilot", []),
            ("ollama",  ["--model", model]),
        ]:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "mars.runtime.services.llm_wire_agent",
                 "--server", f"127.0.0.1:{unused_tcp_port}",
                 "--provider", provider] + extra,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ))

        # Expect exactly 2 spawn events
        spawns = await _collect_n(h_reader, t="spawn", n=2, timeout=20.0)
        agent_ids   = [s["agent_id"]   for s in spawns]
        agent_types = [s["agent_type"] for s in spawns]
        vendors     = [s.get("vendor", "") for s in spawns]

        print(f"\n[CLI capture] spawn events received: {agent_ids}")
        for sp in spawns:
            print(f"  agent_id={sp['agent_id']}  type={sp['agent_type']}  vendor={sp.get('vendor','?')}")

        assert len(spawns) == 2, "Expected 2 agents to register"
        assert all(at == "LLMAgent" for at in agent_types), \
            f"All agents should be LLMAgent, got: {agent_types}"
        assert "copilot" in vendors, f"copilot vendor missing in {vendors}"
        assert "ollama"  in vendors, f"ollama vendor missing in {vendors}"

    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=3)
        h_writer.close()


async def test_both_providers_respond(unused_tcp_port):
    """Human sends a message to each agent; both return non-empty chat replies.

    This is the closest to a CLI capture: we assert that both providers
    produce visible output on the wire bus — exactly what would appear in
    the MARS TUI.
    """
    model = _first_ollama_model()
    server = await _start_server(unused_tcp_port)  # noqa: F841

    h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
    await _read_until(h_reader, t="welcome", timeout=5.0)

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
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ))

        spawns = await _collect_n(h_reader, t="spawn", n=2, timeout=20.0)
        # Map vendor → agent_id for targeted messaging
        vendor_to_id: dict[str, str] = {
            s.get("vendor", ""): s["agent_id"] for s in spawns
        }

        print(f"\n[CLI capture] agents online: {vendor_to_id}")

        replies: dict[str, str] = {}

        # Send to Copilot first, then Ollama — fire-and-forget both
        for vendor, agent_id in vendor_to_id.items():
            h_writer.write((json.dumps({
                "t": "msg",
                "target": agent_id,
                "text": "Reply with exactly one word: hello",
            }) + "\n").encode())
        await h_writer.drain()

        # Collect 2 chat replies (order may vary)
        chats = await _collect_n(h_reader, t="chat", n=2, timeout=60.0)
        for chat in chats:
            if chat.get("direction") == "in":
                sender = chat["agent_id"]
                vendor = next((v for v, aid in vendor_to_id.items() if aid == sender), sender)
                replies[vendor] = chat["content"]
                print(f"[CLI capture] {vendor} → {chat['content']!r}")

        assert "copilot" in replies, "No chat reply received from Copilot"
        assert "ollama"  in replies, "No chat reply received from Ollama"
        for vendor, reply in replies.items():
            text = reply.strip()
            assert len(text) > 0, f"{vendor} reply was empty"
            for prefix in ("🚫", "⚠️", "❌", "Error:", "error:"):
                assert not text.startswith(prefix), \
                    f"{vendor} returned an error instead of a chat reply: {text!r}"

    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=3)
        h_writer.close()
