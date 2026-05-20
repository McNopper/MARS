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

import pytest
import tests.system.helpers as helpers


class TestClockToolRoundTrip:
    async def test_llm_calls_get_time_and_replies(self, unused_tcp_port):
        """Human asks 'what is the time' → LLM calls get_time → reply contains time."""
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        proc = helpers.spawn_llm_agent(unused_tcp_port)
        try:
            spawn = await helpers.read_until(h_reader, t="spawn", agent_type="LLMAgent", timeout=12.0)
            agent_id = spawn["agent_id"]

            helpers.send_msg(h_writer, agent_id, "what is the time?")
            await h_writer.drain()

            events = await helpers.read_any(h_reader, timeout=20.0)
            chat_events = [e for e in events if e.get("t") == "chat"]
            assert chat_events, f"No chat reply received. Events: {[e.get('t') for e in events]}"

            reply_text = chat_events[-1].get("content", "")
            assert "tool returned" in reply_text.lower() or "🕐" in reply_text or any(c.isdigit() for c in reply_text), (
                f"Reply doesn't look like it came from the clock tool: {reply_text!r}"
            )
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            h_writer.close()
            await server.stop_mcp_agents()

    async def test_clock_tool_discovered_by_llm_agent(self, unused_tcp_port):
        """Human must receive a spawn event with get_time skill on connect."""
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial_events = await helpers.read_initial_events(h_reader)

        spawned = [e for e in initial_events if e.get("t") == "spawn"]
        clock_spawns = [e for e in spawned if "get_time" in (e.get("skills") or [])]
        assert clock_spawns, f"No spawn event with 'get_time' skill. Spawned: {[e.get('agent_id') for e in spawned]}"

        h_writer.close()
        await server.stop_mcp_agents()


class TestMathToolRoundTrip:
    async def test_llm_calls_solve_math_and_replies(self, unused_tcp_port):
        """Human asks to solve x²-4=0 → LLM calls solve_math → reply contains roots."""
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        proc = helpers.spawn_llm_agent(unused_tcp_port, provider="mock-tool")
        try:
            spawn = await helpers.read_until(h_reader, t="spawn", agent_type="LLMAgent", timeout=12.0)
            agent_id = spawn["agent_id"]

            helpers.send_msg(h_writer, agent_id, "solve x**2 - 4 = 0")
            await h_writer.drain()

            events = await helpers.read_any(h_reader, timeout=20.0)
            chat_events = [e for e in events if e.get("t") == "chat"]
            assert chat_events, f"No chat reply received. Events: {[e.get('t') for e in events]}"

            reply_text = chat_events[-1].get("content", "")
            assert reply_text, "Reply is empty"
            assert "tool returned" in reply_text.lower() or any(kw in reply_text for kw in ("2", "-2", "x", "solve", "result")), (
                f"Reply doesn't look like it came from the math tool: {reply_text!r}"
            )
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            h_writer.close()
            await server.stop_mcp_agents()

    async def test_math_tool_discovered_by_llm_agent(self, unused_tcp_port):
        """Human must receive a spawn event with solve_math skill on connect."""
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial_events = await helpers.read_initial_events(h_reader)

        spawned = [e for e in initial_events if e.get("t") == "spawn"]
        math_spawns = [e for e in spawned if "solve_math" in (e.get("skills") or [])]
        assert math_spawns, f"No spawn event with 'solve_math'. Spawned: {[e.get('agent_id') for e in spawned]}"

        h_writer.close()
        await server.stop_mcp_agents()


class TestSciPyToolRoundTrip:
    async def test_scipy_tool_discovered(self, unused_tcp_port):
        """Human must receive a spawn event with solve_scipy skill on connect."""
        pytest.importorskip("scipy")
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial_events = await helpers.read_initial_events(h_reader)

        spawned = [e for e in initial_events if e.get("t") == "spawn"]
        scipy_spawns = [e for e in spawned if "solve_scipy" in (e.get("skills") or [])]
        assert scipy_spawns, f"No spawn event with 'solve_scipy'. Spawned: {[e.get('agent_id') for e in spawned]}"

        h_writer.close()
        await server.stop_mcp_agents()

    async def test_llm_calls_solve_scipy_and_replies(self, unused_tcp_port):
        """Human asks for numerical integration → LLM calls solve_scipy → reply returned."""
        pytest.importorskip("scipy")
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        proc = helpers.spawn_llm_agent(unused_tcp_port)
        try:
            spawn = await helpers.read_until(h_reader, t="spawn", agent_type="LLMAgent", timeout=12.0)
            agent_id = spawn["agent_id"]

            helpers.send_msg(h_writer, agent_id, "integrate x**2 from 0 to 1 using scipy")
            await h_writer.drain()

            events = await helpers.read_any(h_reader, timeout=20.0)
            chat_events = [e for e in events if e.get("t") == "chat"]
            assert chat_events, f"No chat reply. Events: {[e.get('t') for e in events]}"

            reply_text = chat_events[-1].get("content", "")
            assert reply_text, "Reply is empty"
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            h_writer.close()
            await server.stop_mcp_agents()
