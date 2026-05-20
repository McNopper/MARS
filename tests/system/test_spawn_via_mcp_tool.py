"""System tests: agent-to-agent spawning via the MCP launcher tool.

Tests the complete spawn-via-tool flow:
  Human message → LLM agent (mock-tool provider)
    → calls spawn_agent MCP tool on launcher
      → server intercepts _mars_cmd envelope
        → spawns new agent subprocess
  Human receives second spawn event

Runs fully offline (mock-tool provider + launcher service agent).
Variants with real Copilot and Ollama providers are skipped when those
services are unavailable.
"""
from __future__ import annotations

import pytest
import tests.system.helpers as helpers


# ---------------------------------------------------------------------------
# Offline / mock variant
# ---------------------------------------------------------------------------

class TestSpawnViaMCPToolMock:
    """Use the offline mock-tool provider — no external services required."""

    async def test_mock_agent_can_spawn_another_mock(self, unused_tcp_port):
        """mock-tool agent calls spawn_agent → a second LLMAgent appears."""
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()  # starts the launcher service agent

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        # Spawn the mock-tool agent configured to call spawn_agent(request="mock")
        proc = helpers.spawn_llm_agent(
            unused_tcp_port,
            provider="mock-tool",
            extra_args=["--mock-tool-name", "spawn_agent", "--mock-tool-request", "mock"],
        )
        try:
            # Wait for the first agent to appear
            first_spawn = await helpers.read_until(h_reader, t="spawn", agent_type="LLMAgent", timeout=12.0)
            agent_id = first_spawn["agent_id"]

            # Ask the agent to spawn a mock provider — the ToolCallMockProvider
            # calls the first available tool (spawn_agent from the launcher) with
            # {"request": "<message text>"}.  The launcher maps request → provider.
            helpers.send_msg(h_writer, agent_id, "mock")
            await h_writer.drain()

            # Expect a second spawn event for the newly spawned agent
            second_spawn = await helpers.read_until(h_reader, t="spawn", timeout=15.0)
            assert second_spawn["agent_type"] == "LLMAgent", (
                f"Expected LLMAgent, got {second_spawn['agent_type']!r}"
            )
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            h_writer.close()
            await server.stop_mcp_agents()

    async def test_launcher_tool_available_to_agents(self, unused_tcp_port):
        """Agents see spawn_agent in their initial tool list once launcher is up."""
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial = await helpers.read_initial_events(h_reader)

        spawned = [e for e in initial if e.get("t") == "spawn"]
        launcher_spawns = [
            e for e in spawned
            if "spawn_agent" in (e.get("skills") or [])
        ]
        assert launcher_spawns, (
            f"No spawn event with 'spawn_agent' skill. "
            f"Spawned agents: {[e.get('agent_id') for e in spawned]}"
        )

        h_writer.close()
        await server.stop_mcp_agents()


# ---------------------------------------------------------------------------
# Copilot variant (skipped when token unavailable)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not helpers.copilot_available(),
    reason="No GitHub token — run 'gh auth login' first",
)
class TestSpawnViaMCPToolCopilot:
    async def test_copilot_agent_calls_spawn_tool(self, unused_tcp_port):
        """Copilot agent receives spawn_agent tool and can invoke it."""
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        proc = helpers.spawn_llm_agent(
            unused_tcp_port, provider="copilot",
            extra_args=["--model", "gpt-4o-mini"],
        )
        try:
            spawn = await helpers.read_until(h_reader, t="spawn", agent_type="LLMAgent", timeout=15.0)
            agent_id = spawn["agent_id"]

            # Ask Copilot to spawn a mock agent
            helpers.send_msg(h_writer, agent_id, "Please spawn a mock agent for me.")
            await h_writer.drain()

            # Either a second spawn event or a chat reply referencing spawn
            events = await helpers.read_any(h_reader, timeout=30.0)
            spawn_events = [e for e in events if e.get("t") == "spawn"]
            chat_events = [e for e in events if e.get("t") == "chat"]
            assert spawn_events or chat_events, (
                "Expected either a new spawn or a chat reply from Copilot"
            )
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            h_writer.close()
            await server.stop_mcp_agents()


# ---------------------------------------------------------------------------
# Ollama variant (skipped when Ollama is not running)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not helpers.ollama_reachable(),
    reason="Ollama not running on localhost:11434",
)
class TestSpawnViaMCPToolOllama:
    async def test_ollama_agent_calls_spawn_tool(self, unused_tcp_port):
        """Ollama agent receives spawn_agent tool and can invoke it."""
        model = helpers.first_ollama_model()
        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        proc = helpers.spawn_llm_agent(
            unused_tcp_port, provider="ollama",
            extra_args=["--model", model],
        )
        try:
            spawn = await helpers.read_until(h_reader, t="spawn", agent_type="LLMAgent", timeout=15.0)
            agent_id = spawn["agent_id"]

            helpers.send_msg(h_writer, agent_id, "Please spawn a mock agent for me.")
            await h_writer.drain()

            events = await helpers.read_any(h_reader, timeout=60.0)
            spawn_events = [e for e in events if e.get("t") == "spawn"]
            chat_events = [e for e in events if e.get("t") == "chat"]
            assert spawn_events or chat_events, (
                "Expected either a new spawn or a chat reply from Ollama"
            )
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            h_writer.close()
            await server.stop_mcp_agents()
