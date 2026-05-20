"""System tests for the memory service agent via TCP round-trip.

Verifies that the memory agent (cost=free) auto-spawns, registers memory
skills, and that a remember→recall round-trip works correctly.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import tests.system.helpers as helpers

from mars.runtime.agents.memory_agent import _dispatch as mem_dispatch


class TestMemoryAgentUnit:
    """Fast non-server memory round-trip tests."""

    def test_remember_recall_roundtrip(self, tmp_path: Path) -> None:
        mem_dispatch(tmp_path, "remember syskey: sysvalue")
        result = mem_dispatch(tmp_path, "recall syskey")
        assert result["ok"] is True
        assert result["value"] == "sysvalue"

    def test_memory_persists_to_disk(self, tmp_path: Path) -> None:
        import json
        mem_dispatch(tmp_path, "remember persistent: yes")
        path = tmp_path / "memory.json"
        assert path.exists()
        data = json.loads(path.read_text("utf-8"))
        assert "persistent" in data
        assert data["persistent"]["value"] == "yes"


class TestMemoryAgentServer:
    async def test_memory_agent_is_auto_spawned(self, unused_tcp_port: int) -> None:
        """Memory agent (cost=free) should appear in the initial roster."""
        if not helpers.builtin_agent_available("mars-agent-memory"):
            pytest.skip("mars-agent-memory module not found")

        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial_events = await helpers.read_initial_events(h_reader)

        spawned = [e for e in initial_events if e.get("t") == "spawn"]
        mem_spawns = [
            e for e in spawned
            if any(
                s in (e.get("skills") or [])
                for s in ("remember", "recall", "memory", "store_fact")
            )
        ]
        assert mem_spawns, (
            "Expected at least one spawn event with a memory skill. "
            f"Got: {[e.get('agent_id') for e in spawned]}"
        )

        h_writer.close()
        await server.stop_mcp_agents()

    async def test_remember_skill_present(self, unused_tcp_port: int) -> None:
        """The memory agent should advertise 'remember' in its skill list."""
        if not helpers.builtin_agent_available("mars-agent-memory"):
            pytest.skip("mars-agent-memory module not found")

        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial_events = await helpers.read_initial_events(h_reader)

        all_skills: list[str] = []
        for e in initial_events:
            if e.get("t") == "spawn":
                all_skills.extend(e.get("skills") or [])

        assert "remember" in all_skills or "memory" in all_skills, (
            f"'remember' skill not found. All skills: {all_skills}"
        )

        h_writer.close()
        await server.stop_mcp_agents()
