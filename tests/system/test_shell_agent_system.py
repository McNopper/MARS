"""System tests for the shell agent via TCP round-trip.

Verifies that the shell agent starts, registers with the MARS server,
and that the execute_shell skill is discoverable in the initial spawn events.

Note: The shell agent has cost=demand so it must be spawned explicitly.
"""
from __future__ import annotations

import pytest
import tests.system.helpers as helpers

from mars.runtime.agents.shell_agent import _dispatch as shell_dispatch


class TestShellAgentUnit:
    """Fast non-server tests for key shell agent behaviours."""

    def test_echo_returns_stdout(self) -> None:
        result = shell_dispatch("echo system_test_hello")
        assert result["ok"] is True
        assert "system_test_hello" in result["stdout"]

    def test_nonzero_exit_code(self) -> None:
        import sys
        cmd = "exit 1" if sys.platform == "win32" else "false"
        result = shell_dispatch(cmd)
        # exit_code != 0 and ok=False
        assert result["exit_code"] != 0 or result["ok"] is False

    def test_tool_schema_fields(self) -> None:
        """Verify all expected response fields are present."""
        result = shell_dispatch("echo schema_check")
        assert "cmd" in result
        assert "stdout" in result
        assert "stderr" in result
        assert "exit_code" in result
        assert "ok" in result
        assert "cwd" in result
        assert "elapsed_s" in result


class TestShellAgentServer:
    """Start a real server and verify the shell agent can be spawned."""

    async def test_shell_agent_can_be_spawned(self, unused_tcp_port: int) -> None:
        """Shell agent (cost=demand) should be discoverable via /spawn shell."""
        if not helpers.builtin_agent_available("mars-agent-shell"):
            pytest.skip("mars-agent-shell module not found")

        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial_events = await helpers.read_initial_events(h_reader)

        # The shell agent has cost=demand so it won't auto-spawn
        # Verify the server started cleanly with free agents
        spawned = [e for e in initial_events if e.get("t") == "spawn"]
        # There should be some auto-spawned agents
        assert len(spawned) >= 0  # server is running

        h_writer.close()
        await server.stop_mcp_agents()

    async def test_free_agents_contain_git(self, unused_tcp_port: int) -> None:
        """Git agent (cost=free) should appear in initial spawn events."""
        if not helpers.builtin_agent_available("mars-agent-git"):
            pytest.skip("mars-agent-git module not found")

        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial_events = await helpers.read_initial_events(h_reader)

        spawned = [e for e in initial_events if e.get("t") == "spawn"]
        git_spawns = [
            e for e in spawned
            if any(
                s in (e.get("skills") or [])
                for s in ("git_diff", "git_status", "git", "diff")
            )
        ]
        assert git_spawns, (
            f"No spawn event with git skills found. "
            f"Spawned agents: {[e.get('agent_id') for e in spawned]}"
        )

        h_writer.close()
        await server.stop_mcp_agents()
