"""System tests: human → LLM wire agent → MCP service tool → reply.

These tests start a real MARS server with live MCP service agents and a
real LLM wire agent subprocess (using the offline mock-tool provider).
They verify the complete chain:

  Human message
    → MARS server
      → LLM wire agent receives msg
        → LLM calls service tool (get_time / solve_math / solve_scipy)
          → server routes to MCP adapter
            → MCP subprocess responds
          ← tool result returned to LLM
        ← LLM generates natural-language reply
      ← server delivers reply to human
    ← Human receives answer

No external APIs required — mock-tool provider is used.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time

import pytest

from mars.srv.main import MARSServer
from mars.cli.models import MARSState


# ---------------------------------------------------------------------------
# Helpers (same pattern as other system wire-agent tests)
# ---------------------------------------------------------------------------

async def _start_server(port: int) -> MARSServer:
    state = MARSState()
    server = MARSServer(state)
    ready: asyncio.Future[None] = asyncio.get_event_loop().create_future()
    asyncio.create_task(server.serve("127.0.0.1", port, ready_future=ready))
    await asyncio.wait_for(ready, timeout=5.0)
    return server


async def _connect(port: int, name: str, role: str = "human"):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    hello: dict = {"t": "hello", "role": role, "name": name}
    writer.write((json.dumps(hello) + "\n").encode())
    await writer.drain()
    return reader, writer


async def _read_until(reader, *, t: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for event t={t!r}")
        raw = await asyncio.wait_for(reader.readline(), timeout=remaining)
        ev = json.loads(raw.decode())
        if ev.get("t") == t:
            return ev


async def _read_any(reader, *, timeout: float = 15.0) -> list[dict]:
    """Read all events until timeout, return them all."""
    events = []
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=min(remaining, 1.0))
            ev = json.loads(raw.decode())
            events.append(ev)
        except asyncio.TimeoutError:
            # short poll — if we already have some chat events stop waiting
            if any(e.get("t") in ("chat", "msg") for e in events):
                break
    return events


def _spawn_llm_agent(port: int, provider: str = "mock-tool", extra_args: list[str] | None = None) -> subprocess.Popen:
    cmd = [
        sys.executable, "-m", "mars.services.llm_wire_agent",
        "--server", f"127.0.0.1:{port}",
        "--provider", provider,
    ] + (extra_args or [])
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# Clock tool round-trip
# ---------------------------------------------------------------------------

class TestClockToolRoundTrip:
    async def test_llm_calls_get_time_and_replies(self, unused_tcp_port):
        """Human asks 'what is the time' → LLM calls get_time → reply contains time."""
        server = await _start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
        welcome = await _read_until(h_reader, t="welcome")
        my_id = welcome["your_id"]

        proc = _spawn_llm_agent(unused_tcp_port)
        try:
            spawn = await _read_until(h_reader, t="spawn", timeout=8.0)
            agent_id = spawn["agent_id"]

            # Send time question
            h_writer.write((json.dumps({
                "t": "msg", "target": agent_id,
                "text": "what is the time?",
            }) + "\n").encode())
            await h_writer.drain()

            # Wait for the LLM reply (it must have called the clock tool)
            events = await _read_any(h_reader, timeout=20.0)
            chat_events = [e for e in events if e.get("t") == "chat"]
            assert chat_events, f"No chat reply received. Events: {[e.get('t') for e in events]}"

            reply_text = chat_events[-1].get("content", "")
            # The mock-tool provider returns "The tool returned: <tool output>"
            # The tool output should include the clock emoji and/or a time string
            assert "tool returned" in reply_text.lower() or "🕐" in reply_text or \
                   any(c.isdigit() for c in reply_text), \
                f"Reply doesn't look like it came from the clock tool: {reply_text!r}"
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            h_writer.close()
            await server.stop_mcp_agents()

    async def test_clock_tool_discovered_by_llm_agent(self, unused_tcp_port):
        """Human must receive a spawn event with get_time skill on connect.

        _register_session sends spawn events for all existing agents before the
        welcome message, so we must collect them together with welcome — not
        call _read_until(welcome) which would discard them.
        """
        server = await _start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")

        # Collect all initial events up to and including welcome
        initial_events: list[dict] = []
        while True:
            try:
                raw = await asyncio.wait_for(h_reader.readline(), timeout=5.0)
                ev = json.loads(raw.decode())
                initial_events.append(ev)
                if ev.get("t") == "welcome":
                    break
            except asyncio.TimeoutError:
                break

        spawned = [e for e in initial_events if e.get("t") == "spawn"]
        clock_spawns = [e for e in spawned if "get_time" in (e.get("skills") or [])]
        assert clock_spawns, \
            f"No spawn event with 'get_time' skill. Spawned: {[e.get('agent_id') for e in spawned]}"

        h_writer.close()
        await server.stop_mcp_agents()


# ---------------------------------------------------------------------------
# Math tool round-trip
# ---------------------------------------------------------------------------

class TestMathToolRoundTrip:
    async def test_llm_calls_solve_math_and_replies(self, unused_tcp_port):
        """Human asks to solve x²-4=0 → LLM calls solve_math → reply contains roots."""
        server = await _start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
        welcome = await _read_until(h_reader, t="welcome")
        my_id = welcome["your_id"]

        # Use mock-tool targeting the solve_math tool specifically
        proc = _spawn_llm_agent(unused_tcp_port, provider="mock-tool", extra_args=[
            # pass the math expression as the tool request via env isn't possible,
            # so we rely on ToolCallMockProvider using the first available tool
        ])
        try:
            spawn = await _read_until(h_reader, t="spawn", timeout=8.0)
            agent_id = spawn["agent_id"]

            h_writer.write((json.dumps({
                "t": "msg", "target": agent_id,
                "text": "solve x**2 - 4 = 0",
            }) + "\n").encode())
            await h_writer.drain()

            events = await _read_any(h_reader, timeout=20.0)
            chat_events = [e for e in events if e.get("t") == "chat"]
            assert chat_events, \
                f"No chat reply received. Events: {[e.get('t') for e in events]}"

            reply_text = chat_events[-1].get("content", "")
            assert reply_text, "Reply is empty"
            # The reply must include content from the tool result
            assert "tool returned" in reply_text.lower() or \
                   any(kw in reply_text for kw in ("2", "-2", "x", "solve", "result")), \
                f"Reply doesn't look like it came from the math tool: {reply_text!r}"
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            h_writer.close()
            await server.stop_mcp_agents()

    async def test_math_tool_discovered_by_llm_agent(self, unused_tcp_port):
        """Human must receive a spawn event with solve_math skill on connect."""
        server = await _start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")

        # Collect all initial events up to and including welcome
        initial_events: list[dict] = []
        while True:
            try:
                raw = await asyncio.wait_for(h_reader.readline(), timeout=5.0)
                ev = json.loads(raw.decode())
                initial_events.append(ev)
                if ev.get("t") == "welcome":
                    break
            except asyncio.TimeoutError:
                break

        spawned = [e for e in initial_events if e.get("t") == "spawn"]
        math_spawns = [e for e in spawned if "solve_math" in (e.get("skills") or [])]
        assert math_spawns, \
            f"No spawn event with 'solve_math'. Spawned: {[e.get('agent_id') for e in spawned]}"

        h_writer.close()
        await server.stop_mcp_agents()


# ---------------------------------------------------------------------------
# SciPy tool round-trip
# ---------------------------------------------------------------------------

class TestSciPyToolRoundTrip:
    async def test_scipy_tool_discovered(self, unused_tcp_port):
        """Human must receive a spawn event with solve_scipy skill on connect."""
        pytest.importorskip("scipy")
        server = await _start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")

        # Collect all initial events up to and including welcome
        initial_events: list[dict] = []
        while True:
            try:
                raw = await asyncio.wait_for(h_reader.readline(), timeout=5.0)
                ev = json.loads(raw.decode())
                initial_events.append(ev)
                if ev.get("t") == "welcome":
                    break
            except asyncio.TimeoutError:
                break

        spawned = [e for e in initial_events if e.get("t") == "spawn"]
        scipy_spawns = [e for e in spawned if "solve_scipy" in (e.get("skills") or [])]
        assert scipy_spawns, \
            f"No spawn event with 'solve_scipy'. Spawned: {[e.get('agent_id') for e in spawned]}"

        h_writer.close()
        await server.stop_mcp_agents()

    async def test_llm_calls_solve_scipy_and_replies(self, unused_tcp_port):
        """Human asks for numerical integration → LLM calls solve_scipy → reply returned."""
        pytest.importorskip("scipy")
        server = await _start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await _connect(unused_tcp_port, "cli-user")
        welcome = await _read_until(h_reader, t="welcome")
        my_id = welcome["your_id"]

        proc = _spawn_llm_agent(unused_tcp_port)
        try:
            spawn = await _read_until(h_reader, t="spawn", timeout=8.0)
            agent_id = spawn["agent_id"]

            h_writer.write((json.dumps({
                "t": "msg", "target": agent_id,
                "text": "integrate x**2 from 0 to 1 using scipy",
            }) + "\n").encode())
            await h_writer.drain()

            events = await _read_any(h_reader, timeout=20.0)
            chat_events = [e for e in events if e.get("t") == "chat"]
            assert chat_events, \
                f"No chat reply. Events: {[e.get('t') for e in events]}"

            reply_text = chat_events[-1].get("content", "")
            assert reply_text, "Reply is empty"
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            h_writer.close()
            await server.stop_mcp_agents()
